"""Isolated background tasks with pinned source/weights and private exports."""
import csv
import errno
import io
import json
import os
import random
import secrets
import subprocess
import sys
import threading
import time

from flask import jsonify, request, Response
from werkzeug.exceptions import BadRequest, Conflict, NotFound
from autochess_auth import PERM_CHARACTER_MANAGE
from ui_management import atomic_write, digest
from ui_simulation_queue import SimulationQueue
from combat_settings import value as setting, snapshot as settings_snapshot, valid_season


def lock_job(folder):
    """Hold a job's file open while its backend owns the worker."""
    handle = (folder / 'task.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno not in (errno.EACCES, errno.EAGAIN):
            raise
        return None
    return handle


class Tasks:
    def __init__(self, bp, context, management, store):
        self.c, self.management, self.store = context, management, store
        self.queue = context.get('simulation_queue') or SimulationQueue()
        self.lock, self.processes = threading.RLock(), {}
        self.queued_leases = {}
        self.recover()
        for path, name, method in [('/simulations', 'start', 'POST'), ('/simulations/<jid>', 'get', 'GET'),
                                   ('/simulations/<jid>/cancel', 'cancel', 'POST'),
                                   ('/simulations/<jid>/export', 'export', 'GET'),
                                   ('/training', 'train', 'POST'), ('/training', 'training_status', 'GET')]:
            bp.add_url_rule('/api/ui' + path, 'tasks_' + name, getattr(self, name), methods=[method])

    def recover(self):
        saved_jobs = sorted(reversed(self.store.list('task')), key=lambda job: job.get('created', 0))
        for saved in saved_jobs:
            if saved['status'] not in ('queued', 'running'):
                continue
            folder = self.management.runtime / 'jobs' / saved['id']
            exists = folder.is_dir()
            lease = lock_job(folder) if exists else None
            if exists and lease is None:
                continue
            job = self.store.get('task', saved['id'])
            resumable = job['status'] == 'running' and job.get('_resumable_prelim')
            if lease and (job['status'] == 'queued' or resumable):
                if resumable:
                    job.pop('progress', None)
                    job['message'] = '服务重启后继续预赛'
                self.enqueue(job, lease)
                continue
            try:
                if job['status'] in ('queued', 'running'):
                    message = ('服务重启，训练已中断，原权重未替换' if job['params']['mode'] == 'train'
                               else '服务重启，模拟已中断，可以重新运行')
                    job.update(status='failed', message=message)
                    self.store.put('task', job)
            finally:
                if lease:
                    lease.close()

    def enqueue(self, job, lease):
        jid = job['id']
        try:
            with self.lock:
                job['status'] = 'queued'
                self.store.put('task', job)
                self.queued_leases[jid] = lease
                self.queue.submit(('task', jid), self.run, jid)
        except BaseException:
            self.queued_leases.pop(jid, None)
            lease.close()
            raise

    @staticmethod
    def public(job):
        return {key: value for key, value in job.items() if not key.startswith('_')}

    def params(self, data):
        mode = data.get('mode', 'single')
        if mode not in ('single', 'verbose', 'table', 'prelim'):
            raise BadRequest('不支持的模拟模式')
        defaults = {'single': setting('SIM_SINGLE_COUNT'), 'verbose': 1, 'table': setting('SIM_TABLE_COUNT'), 'prelim': setting('SIM_PRELIM_COUNT')}
        n = data.get('n', defaults[mode])
        if type(n) is not int or not 1 <= n <= 1000:
            raise BadRequest('模拟次数必须为 1–1000')
        seed, season = data.get('seed', random.randrange(2**31)), data.get('season', setting('SEASON_AVG_STATUS'))
        if type(seed) is not int or not 0 <= seed < 2**31 or not valid_season(season):
            raise BadRequest('种子应为非负整数，赛季状态为 0–100 或随机')
        params = dict(mode=mode, n=1 if mode == 'verbose' else n, seed=seed, season=season, map_size=data.get('map_size', setting('DEFAULT_MAP_SIZE')))
        valid = {c['serial'] for c in self.management.module().ALL_CHARACTERS}
        if mode in ('single', 'verbose'):
            self.c['valid_teams'](data)
            params.update(team_a=data['team_a'], team_b=data['team_b'])
        else:
            fmt = data.get('format', setting('SIM_DEFAULT_FORMAT'))
            if fmt not in ('1v1', '2v2', '3v3'):
                raise BadRequest('请选择有效赛制')
            params['format'] = fmt
            if mode == 'table':
                from team_tables import TEAM_TABLES_2V2, TEAM_TABLES_3V3
                teams = data.get('teams') or ([[s] for s in sorted(valid)] if fmt == '1v1' else
                                             TEAM_TABLES_2V2 if fmt == '2v2' else TEAM_TABLES_3V3)
                if not data.get('teams'):
                    teams = [team for team in teams if all(s in valid for s in team)]
                if not isinstance(teams, list) or len(teams) < 2:
                    raise BadRequest('至少需要两个有效小队')
                for team in teams:
                    if not isinstance(team, list) or not team or len(set(team)) != len(team) or any(s not in valid for s in team):
                        raise BadRequest('小队含重复、已禁用或已删除角色，请检查预设')
                params['teams'] = teams
            else:
                formats = data.get('formats', [fmt])
                if not isinstance(formats, list) or not formats or any(f not in ('1v1', '2v2', '3v3') for f in formats):
                    raise BadRequest('请选择预赛赛制')
                from team_tables import TEAM_TABLES_2V2, TEAM_TABLES_3V3
                pools = {'1v1': [[s] for s in valid], '2v2': TEAM_TABLES_2V2, '3v3': TEAM_TABLES_3V3}
                for requested in formats:
                    if sum(all(s in valid for s in team) for team in pools[requested]) < 2:
                        raise BadRequest(f'{requested} 预赛至少需要两支由启用角色组成的有效小队')
                workers = data.get('workers', setting('PRELIM_WORKERS'))
                if type(workers) is not int or not 1 <= workers <= 32:
                    raise BadRequest('并发数应为 1–32')
                params.update(formats=formats, workers=workers)
        # Ignore the retired UI option sent by older browser pages.
        params['fast'] = False
        if mode == 'single':
            workers = data.get('workers', min(8, os.cpu_count() or 1))
            if type(workers) is not int or not 1 <= workers <= 32:
                raise BadRequest('并发数应为 1–32')
            params['workers'] = workers
        return params

    def _task_owner(self):
        sid = self.c['session_id']()
        if sid:
            return sid
        if hasattr(self.management, 'current_account'):
            acc = self.management.current_account()
            if isinstance(acc, dict) and acc.get('id'):
                return f"acc:{acc['id']}"
        return ''

    def start(self):
        if not self._task_owner():
            raise BadRequest('请先建立会话')
        return jsonify(self.public(self.launch(self.params(self.c['body']()))))

    def launch(self, params):
        with self.lock, self.management.lock:
            if params.get('mode') == 'train':
                from ai_trainer import normalize_training_targets
                enabled = [ch['serial'] for ch in self.management.module().ALL_CHARACTERS]
                try:
                    targets = normalize_training_targets(params.get('target_serials'), enabled)
                except ValueError as exc:
                    raise BadRequest(str(exc)) from exc
                if len(self.management.module().ALL_CHARACTERS) < 6:
                    raise BadRequest('默认训练包含 3 对 3 抽样，需要至少启用 6 名角色')
                params = {**params, 'enabled_serials': enabled, 'target_serials': targets}
            else:
                params = self.params(params)
            params = {**params, 'settings': settings_snapshot()}
            if 'workers' in params or params['mode'] == 'train':
                params['workers'] = min(params.get('workers', self.queue.workers), self.queue.workers)
            owner = self._task_owner()
            for active in self.store.list('task'):
                if active['status'] in ('queued', 'running'):
                    if active['owner'] == owner:
                        raise Conflict('此会话已有任务在排队或运行，请等待或取消模拟')
                    if params['mode'] == active['params']['mode'] == 'train':
                        raise Conflict('已有训练任务在排队或运行，请等待完成')
            jid = secrets.token_hex(8)
            folder = self.management.snapshot_task(jid)
            job = dict(id=jid, owner=owner, completed=0, params=params,
                       result=None, logs=[], created=time.time(), data_version=digest((folder/'characters_data.py').read_bytes()))
            if params['mode'] == 'prelim':
                job['_resumable_prelim'] = True
            lease = lock_job(folder)
            if lease is None:
                raise Conflict('无法取得任务目录的写入权限')
            self.enqueue(job, lease)
            return job

    def run(self, jid):
        folder = self.management.runtime / 'jobs' / jid
        error_path = folder / 'stderr.log'
        proc = None
        with self.lock:
            lease = self.queued_leases.pop(jid)
        try:
            with self.lock:
                job = self.store.get('task', jid)
                if job['status'] != 'queued':
                    return
                if 'workers' in job['params']:
                    job['params']['workers'] = min(job['params']['workers'], self.queue.workers)
                job['status'] = 'running'
                self.store.put('task', job)
            with error_path.open('w', encoding='utf-8') as err:
                proc = subprocess.Popen([sys.executable, '-u', str(folder/'ui_task_worker.py')], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=err, text=True, encoding='utf-8', cwd=folder,
                    start_new_session=os.name != 'nt', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    env={'PYTHONHASHSEED': '0', **os.environ, 'PYTHONIOENCODING': 'utf-8'})
                with self.lock:
                    self.processes[jid] = proc
                    if self.store.get('task', jid)['status'] == 'cancelled':
                        return
                params = job['params']
                if '_checkpoint' in job:
                    params = {**params, 'checkpoint': job['_checkpoint']}
                proc.stdin.write(json.dumps(params) + '\n')
                proc.stdin.close()
                last_save = time.monotonic() - 1
                for line in proc.stdout:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError('工作进程返回了无法解析的状态更新') from exc
                    if not isinstance(row, dict):
                        raise RuntimeError('工作进程返回了无法解析的状态更新')
                    with self.lock:
                        checkpoint = row.pop('checkpoint', None)
                        if 'log' in row or 'logs' in row:
                            job['logs'].extend(row.get('logs', [row['log']] if 'log' in row else []))
                            if job['params']['mode'] != 'verbose':
                                job['logs'] = job['logs'][-3000:]
                        else:
                            job.update(row)
                        if checkpoint is not None:
                            job['_checkpoint'] = checkpoint
                        if checkpoint is not None or time.monotonic() - last_save >= 1:
                            if self.store.get('task', jid)['status'] == 'cancelled':
                                self.stop_process(proc)
                                break
                            self.store.put('task', job)
                            last_save = time.monotonic()
                with self.lock:
                    if self.store.get('task', jid)['status'] != 'cancelled':
                        self.store.put('task', job)
                code = proc.wait()
            with self.lock:
                job = self.store.get('task', jid)
                if job['status'] == 'cancelled':
                    return
                if code or job['result'] is None:
                    message = f'工作进程异常退出（代码 {code}）' if code else '工作进程未返回结果'
                    detail = error_path.read_text(encoding='utf-8', errors='replace').strip().splitlines()
                    if detail:
                        message += '：' + detail[-1].strip()[:300]
                    raise RuntimeError(message)
                if job['params']['mode'] == 'train':
                    self.install_weights(folder, job)
                job['status'] = 'completed'
                job.pop('_checkpoint', None)
                job.pop('message', None)
                self.store.put('task', job)
        except Exception as exc:
            with self.lock:
                job = self.store.get('task', jid)
                if job['status'] != 'cancelled':
                    job.update(status='failed', message=str(exc) or type(exc).__name__)
                    self.store.put('task', job)
        finally:
            try:
                with self.lock:
                    self.processes.pop(jid, None)
                if proc is not None:
                    self.stop_process(proc)
                    proc.wait()
                    proc.stdin.close()
                    proc.stdout.close()
            finally:
                lease.close()

    @staticmethod
    def stop_process(proc):
        if proc.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                import signal
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def install_weights(self, folder, job):
        weights = (folder/'ai_weights.json').read_bytes()
        json.loads(weights)
        with self.management.lock, self.c['guard'], self.c['ns']['_lock']:
            self.management.make_backup('before training weights')
            atomic_write(self.management.root/'ai_weights.json', weights)
            if job['params'].get('target_serials') is None and job['data_version'] == digest((self.management.root/'characters_data.py').read_bytes()):
                self.management.runtime.joinpath('needs-training').unlink(missing_ok=True)
            # Engines already hold their pinned Q-table; new rooms reload it.
            for name in ('_Q_TABLE_PVP_CACHE',):
                if name in self.c['ns']:
                    self.c['ns'][name] = None

    def lookup(self, jid):
        job = self.store.get('task', jid)
        if not job or job['owner'] != self._task_owner():
            raise NotFound('任务不存在')
        return job

    def get(self, jid):
        return jsonify(self.public(self.lookup(jid)))

    def cancel(self, jid):
        self.c['body']()
        with self.lock:
            job = self.lookup(jid)
            if job['params']['mode'] == 'train':
                raise Conflict('训练正在独立执行，请等待完成')
            if job['status'] in ('queued', 'running'):
                job['status'] = 'cancelled'
                job.pop('message', None)
                job.pop('_checkpoint', None)
                self.store.put('task', job)
                if jid in self.queued_leases and self.queue.cancel(('task', jid)):
                    self.queued_leases.pop(jid).close()
                if jid in self.processes:
                    self.stop_process(self.processes[jid])
            return jsonify(self.public(job))

    def train(self):
        self.management.require_permission(PERM_CHARACTER_MANAGE)
        data = self.c['body']()
        if 'target_serials' in data and data['target_serials'] is None:
            raise BadRequest('训练名单必须为非空角色编号列表')
        return jsonify(self.launch({'mode': 'train', 'seed': 42, **({'target_serials': data['target_serials']} if 'target_serials' in data else {})}))

    def training_status(self):
        self.management.require_permission(PERM_CHARACTER_MANAGE)
        owner = self._task_owner()
        return jsonify(jobs=[j for j in self.store.list('task') if j['params']['mode'] == 'train' and j['owner'] == owner][:10])

    def export(self, jid):
        job = self.lookup(jid)
        if job['status'] != 'completed':
            raise Conflict('请等待任务完成')
        if request.args.get('format') == 'csv':
            buf = io.StringIO()
            writer = csv.writer(buf)
            result = job['result']
            if 'matrix' in result:
                average_rounds = result.get('average_rounds', [])
                writer.writerow(['行队伍战胜列队伍的概率；对角线为该队伍参与的所有对局平均回合数'] + result['teams'])
                for i, (name, row) in enumerate(zip(result['teams'], result['matrix'])):
                    cells = [f'{value:.4f}' if value is not None else '' for value in row]
                    if i < len(cells):
                        avg = average_rounds[i] if i < len(average_rounds) else None
                        cells[i] = f'{avg:.1f}回合' if avg is not None else ''
                    writer.writerow([name] + cells)
            else:
                writer.writerow(['field', 'value'])
                for k, v in result.items():
                    writer.writerow([k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v])
            return Response('\ufeff' + buf.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=simulation-{jid}.csv'})
        return Response(json.dumps(self.public(job), ensure_ascii=False, indent=2), mimetype='application/json',
                        headers={'Content-Disposition': f'attachment; filename=simulation-{jid}.json'})
