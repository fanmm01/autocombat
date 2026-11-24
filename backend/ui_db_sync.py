"""Bidirectional token-authenticated SQLite Store synchronization between peer backends."""

import hmac
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request

from flask import jsonify, request
from werkzeug.exceptions import BadRequest

from autochess_auth import (
    PERM_SERVER_MANAGE,
    ROLE_SUPER_ADMIN,
    normalize_permissions,
    normalize_role,
)

DEFAULT_SYNC_KINDS = (
    'identity',
    'autochess_account',
    'autochess_auth_token',
    'autochess_wx_bind',
    'autochess_match',
    'story_profile',
    'story_project',
    'story_run',
    'story_workspace',
    'story_slot',
)


def _normalize_peer_url(raw):
    text = str(raw or '').strip().rstrip('/')
    if text.endswith('/api/ui'):
        text = text[:-len('/api/ui')].rstrip('/')
    return text


def _parse_kinds(raw):
    if raw is None:
        return list(DEFAULT_SYNC_KINDS)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return list(DEFAULT_SYNC_KINDS)
        if text == '*':
            return None
        return [item.strip() for item in text.split(',') if item.strip()]
    if isinstance(raw, (list, tuple, set)):
        items = [str(item).strip() for item in raw if str(item).strip()]
        if '*' in items:
            return None
        return items
    return list(DEFAULT_SYNC_KINDS)


def _parse_float(raw, default, min_val=0.0):
    if raw is None or raw == '':
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(val):
        return default
    return max(min_val, val)


def _record_key(item):
    return (
        item['kind'],
        item['id'],
        float(item['updated_at']),
        bool(item.get('deleted', False)),
        str(item.get('origin') or '')[:64],
    )


class DatabaseSync:
    """Exposes /api/ui/sync/* and runs startup, write-debounced, and periodic peer sync."""

    def __init__(
        self,
        bp,
        store,
        auth=None,
        on_records_changed=None,
        token=None,
        peer_url=None,
        kinds=None,
        interval_sec=None,
        debounce_sec=None,
        timeout_sec=None,
        auto_start=True,
    ):
        self.store = store
        self.auth = auth
        self.on_records_changed = on_records_changed

        env_token = os.environ.get('AUTOCOMBAT_DB_SYNC_TOKEN', '')
        env_peer = os.environ.get('AUTOCOMBAT_DB_SYNC_PEER', '')
        env_kinds = os.environ.get('AUTOCOMBAT_DB_SYNC_KINDS')
        env_interval = os.environ.get('AUTOCOMBAT_DB_SYNC_INTERVAL')
        env_debounce = os.environ.get('AUTOCOMBAT_DB_SYNC_DEBOUNCE')
        env_timeout = os.environ.get('AUTOCOMBAT_DB_SYNC_TIMEOUT')

        self.token = str(env_token if token is None else token).strip()
        self.peer_url = _normalize_peer_url(env_peer if peer_url is None else peer_url)
        self.kinds = _parse_kinds(env_kinds if kinds is None else kinds)
        self.interval_sec = _parse_float(env_interval if interval_sec is None else interval_sec, 30.0, 0.0)
        self.debounce_sec = _parse_float(env_debounce if debounce_sec is None else debounce_sec, 1.5, 0.1)
        self.timeout_sec = _parse_float(env_timeout if timeout_sec is None else timeout_sec, 12.0, 2.0)
        self.enabled = bool(self.token)

        self._state_lock = threading.RLock()
        self._sync_lock = threading.RLock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._pending_push = False
        self._pending_deadline = 0.0
        self._has_synced = False
        self._force_full_next = False
        self._last_peer_node_id = None
        self._last_pushed_rev = 0
        self._last_remote_rev = 0
        self._last_sync_at = 0.0
        self._last_error = None
        self._last_result = None
        self._cycle_count = 0
        self._thread = None

        bp.add_url_rule('/api/ui/sync/exchange', 'db_sync_exchange', self.sync_exchange, methods=['POST'])
        bp.add_url_rule('/api/ui/sync/status', 'db_sync_status', self.sync_status, methods=['GET'])
        bp.add_url_rule('/api/ui/sync/trigger', 'db_sync_trigger', self.sync_trigger, methods=['POST'])

        if self.enabled and self.peer_url:
            self.store.add_change_listener(self._on_local_change)
            if auto_start:
                self._thread = threading.Thread(
                    target=self._worker_loop,
                    name='autocombat-db-sync',
                    daemon=True,
                )
                self._thread.start()

    # ── Auth & Kind Helpers ─────────────────────────────────────────────────

    def _provided_sync_token(self):
        hdr = (request.headers.get('X-Sync-Token') or '').strip()
        if hdr:
            return hdr
        auth_header = (request.headers.get('Authorization') or '').strip()
        if auth_header.lower().startswith('bearer '):
            return auth_header[7:].strip()
        return ''

    def _has_valid_token(self):
        if not self.enabled:
            return False
        provided = self._provided_sync_token()
        if not provided:
            return False
        return hmac.compare_digest(provided, self.token)

    def _is_authorized_admin(self):
        if self.auth is None:
            return False
        token = ''
        auth_header = (request.headers.get('Authorization') or '').strip()
        if auth_header.lower().startswith('bearer '):
            token = auth_header[7:].strip()
        if not token:
            token = (request.headers.get('X-AutoChess-Auth') or '').strip()
        if not token:
            token = request.cookies.get(self.auth.cookie_name, '')
        if not token:
            return False
        acc = self.auth.authenticate(token)
        if not acc:
            return False
        role = normalize_role(acc)
        if role == ROLE_SUPER_ADMIN:
            return True
        return PERM_SERVER_MANAGE in normalize_permissions(acc, role)

    def _require_sync_token(self):
        if not self.enabled:
            return jsonify(error=True, message='未配置 AUTOCOMBAT_DB_SYNC_TOKEN，数据库同步未启用'), 503
        if not self._has_valid_token():
            return jsonify(error=True, message='同步密钥无效'), 401
        return None

    def _require_admin_or_token(self):
        if self._has_valid_token() or self._is_authorized_admin():
            return None
        return jsonify(error=True, message='需要同步密钥或服务器管理权限'), 401

    def _compute_effective_kinds(self, requested_kinds):
        if requested_kinds is None:
            return list(self.kinds) if self.kinds is not None else None
        req_list = [str(k).strip() for k in requested_kinds if isinstance(k, str) and str(k).strip()]
        if self.kinds is None:
            return req_list
        allowed = set(req_list)
        return [k for k in self.kinds if k in allowed]

    # ── HTTP Endpoints ──────────────────────────────────────────────────────

    def sync_exchange(self):
        err = self._require_sync_token()
        if err is not None:
            return err
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise BadRequest('请求必须为 JSON 对象')
        req_kinds = payload.get('kinds')
        if req_kinds is not None and not isinstance(req_kinds, list):
            raise BadRequest('kinds 必须为列表')
        incoming = payload.get('records')
        if incoming is None:
            incoming = []
        if not isinstance(incoming, list):
            raise BadRequest('records 必须为列表')

        effective_kinds = self._compute_effective_kinds(req_kinds)
        result = self.store.merge_records(incoming, allowed_kinds=effective_kinds)
        if result['changed'] and self.on_records_changed:
            self.on_records_changed(result['changed'])

        incoming_versions = set()
        for item in incoming:
            if (
                isinstance(item, dict)
                and isinstance(item.get('kind'), str)
                and item.get('kind')
                and isinstance(item.get('id'), str)
                and item.get('id')
                and isinstance(item.get('updated_at'), (int, float))
                and not isinstance(item.get('updated_at'), bool)
                and math.isfinite(item.get('updated_at'))
            ):
                incoming_versions.add(_record_key(item))

        req_since_rev = payload.get('since_rev')
        if req_since_rev is not None:
            try:
                since_rev = max(0, int(req_since_rev))
            except (TypeError, ValueError):
                since_rev = 0
            raw_out, server_rev = self.store.export_records(
                kinds=effective_kinds,
                since_rev=since_rev,
                include_head=True,
            )
        else:
            since = _parse_float(payload.get('since'), 0.0, 0.0)
            raw_out, server_rev = self.store.export_records(
                kinds=effective_kinds,
                since=since,
                include_head=True,
            )
        outgoing = [rec for rec in raw_out if _record_key(rec) not in incoming_versions]
        return jsonify(
            ok=True,
            node_id=self.store.node_id,
            server_time=time.time(),
            server_rev=server_rev,
            applied={
                'upserted': result['upserted'],
                'deleted': result['deleted'],
                'skipped': result['skipped'],
            },
            records=outgoing,
        )

    def sync_status(self):
        err = self._require_admin_or_token()
        if err is not None:
            return err
        with self._state_lock:
            status = {
                'enabled': self.enabled,
                'peer_url': self.peer_url,
                'kinds': list(self.kinds) if self.kinds is not None else '*',
                'interval_sec': self.interval_sec,
                'debounce_sec': self.debounce_sec,
                'has_synced': self._has_synced,
                'last_sync_at': self._last_sync_at,
                'last_error': self._last_error,
                'last_result': self._last_result,
                'store': self.store.summary(self.kinds),
            }
        return jsonify(status)

    def sync_trigger(self):
        err = self._require_admin_or_token()
        if err is not None:
            return err
        if not self.enabled:
            return jsonify(error=True, message='未配置 AUTOCOMBAT_DB_SYNC_TOKEN，数据库同步未启用'), 503
        if not self.peer_url:
            return jsonify(error=True, message='未配置 AUTOCOMBAT_DB_SYNC_PEER，当前节点仅被动接受同步'), 400
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise BadRequest('请求必须为 JSON 对象')
        res = self.sync_once(full=bool(payload.get('full', False)))
        code = 200 if res.get('ok') else 502
        return jsonify(res), code

    # ── Sync Execution & Background Loop ────────────────────────────────────

    def _on_local_change(self, kinds):
        if not (self.enabled and self.peer_url):
            return
        if self.kinds is not None and not any(kind in self.kinds for kind in kinds):
            return
        with self._state_lock:
            self._pending_push = True
            self._pending_deadline = time.time() + self.debounce_sec
            self._wake_event.set()

    def sync_once(self, full=False, opener=None):
        if not self.enabled:
            return {'ok': False, 'error': '未配置 AUTOCOMBAT_DB_SYNC_TOKEN'}
        if not self.peer_url:
            return {'ok': False, 'error': '未配置 AUTOCOMBAT_DB_SYNC_PEER'}

        with self._sync_lock:
            with self._state_lock:
                use_full = bool(full or not self._has_synced or self._force_full_next)
                local_since_rev = 0 if use_full else self._last_pushed_rev
                remote_since_rev = 0 if use_full else self._last_remote_rev

            local_records, local_head_rev = self.store.export_records(
                kinds=self.kinds,
                since_rev=local_since_rev,
                include_head=True,
            )
            payload = {
                'node_id': self.store.node_id,
                'since': 0.0,
                'since_rev': remote_since_rev,
                'records': local_records,
            }
            if self.kinds is not None:
                payload['kinds'] = list(self.kinds)

            body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(
                f'{self.peer_url}/api/ui/sync/exchange',
                data=body_bytes,
                method='POST',
                headers={
                    'Content-Type': 'application/json',
                    'X-Sync-Token': self.token,
                },
            )
            try:
                open_fn = opener or urllib.request.urlopen
                with open_fn(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode('utf-8')
                resp_data = json.loads(raw)
                if not isinstance(resp_data, dict) or not resp_data.get('ok'):
                    raise RuntimeError((resp_data or {}).get('message') or '对端同步返回异常响应')

                peer_node_id = resp_data.get('node_id')
                remote_records = resp_data.get('records') or []
                merged = self.store.merge_records(remote_records, allowed_kinds=self.kinds)
                if merged['changed'] and self.on_records_changed:
                    self.on_records_changed(merged['changed'])

                peer_restarted = (
                    not use_full
                    and self._has_synced
                    and self._last_peer_node_id
                    and peer_node_id
                    and peer_node_id != self._last_peer_node_id
                )
                if peer_restarted:
                    with self._state_lock:
                        self._last_peer_node_id = peer_node_id
                        self._last_pushed_rev = 0
                        self._last_remote_rev = 0
                        self._force_full_next = True
                    return self.sync_once(full=True, opener=opener)

                result = {
                    'ok': True,
                    'full': use_full,
                    'pushed': len(local_records),
                    'remote_applied': resp_data.get('applied') or {},
                    'pulled': len(remote_records),
                    'local_applied': {
                        'upserted': merged['upserted'],
                        'deleted': merged['deleted'],
                        'skipped': merged['skipped'],
                    },
                    'peer_node_id': peer_node_id,
                }
                server_rev = resp_data.get('server_rev')
                next_remote_rev = int(server_rev) if server_rev is not None else self._last_remote_rev
                with self._state_lock:
                    self._has_synced = True
                    self._force_full_next = False
                    self._last_peer_node_id = peer_node_id
                    self._last_pushed_rev = max(self._last_pushed_rev if not use_full else 0, local_head_rev)
                    self._last_remote_rev = max(self._last_remote_rev if not use_full else 0, next_remote_rev)
                    self._last_sync_at = time.time()
                    self._last_error = None
                    self._last_result = result
                return result
            except urllib.error.HTTPError as exc:
                detail = ''
                try:
                    err_body = exc.read().decode('utf-8', errors='replace')
                    parsed = json.loads(err_body)
                    detail = parsed.get('message') or err_body
                except Exception:
                    detail = str(exc)
                err_msg = f'HTTP {exc.code}: {detail}'
            except Exception as exc:
                err_msg = str(exc)

            with self._state_lock:
                self._last_sync_at = time.time()
                self._last_error = err_msg
                self._last_result = {'ok': False, 'full': use_full, 'error': err_msg}
            print(f'[db_sync] sync failed ({self.peer_url}): {err_msg}', file=sys.stderr)
            return {'ok': False, 'error': err_msg}

    def _worker_loop(self):
        self.sync_once(full=True)
        while not self._stop_event.is_set():
            with self._state_lock:
                if self._stop_event.is_set():
                    break
                self._wake_event.clear()
                pending = self._pending_push
                deadline = self._pending_deadline
            now = time.time()
            if pending:
                wait_for = deadline - now
                if wait_for <= 0:
                    with self._state_lock:
                        self._pending_push = False
                    self._cycle_count += 1
                    self.sync_once(full=(self._cycle_count % 10 == 0))
                    continue
            else:
                wait_for = self.interval_sec if self.interval_sec > 0 else 3600.0
            signaled = self._wake_event.wait(timeout=wait_for)
            if self._stop_event.is_set():
                break
            if not signaled and not pending and self.interval_sec > 0:
                self._cycle_count += 1
                self.sync_once(full=(self._cycle_count % 10 == 0))

    def stop(self):
        with self._state_lock:
            self._stop_event.set()
            self._wake_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
