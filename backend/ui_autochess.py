"""Flask Auto-Chess blueprint (/api/ui/autochess/*): SQLite persistence, auth, tokens, PvE & PvP rooms."""

import json
import os
import secrets
import threading
import time

from flask import Response, has_request_context, jsonify, request
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound

from arena_presets import ARENA_PRESETS, TERRAIN_DESCRIPTIONS
from autochess_auth import AuthError, AutoChessAuthService, exchange_wechat_code
from autochess_catalog import catalog_summary
from autochess_match import AutoChessMatch

_STORE_KIND = 'autochess_match'
_ROOM_KIND = 'autochess_room'
_ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class AutoChessUI:
    """Manages Auto-Chess accounts, PvE saves, multiplayer rooms, and SSE updates."""

    def __init__(self, bp, context, store, auth=None):
        self.c = context
        self.store = store
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)

        # Single-player / PvE matches keyed by match id
        self.matches = {}
        self.versions = {}

        # Multiplayer rooms keyed by uppercase 6-char room code
        self.rooms = {}
        self.room_matches = {}
        self.room_versions = {}
        self._room_steppers = set()

        instance = str(context.get('instance') or '8889')
        auth_cookie = 'autochess_auth' + ('' if instance == '8889' else '_' + instance)
        self.auth = auth if auth is not None else AutoChessAuthService(store, cookie_name=auth_cookie)

        routes = [
            ('/catalog', 'catalog', 'GET'),
            ('/auth/me', 'auth_me', 'GET'),
            ('/auth/register', 'auth_register', 'POST'),
            ('/auth/login', 'auth_login', 'POST'),
            ('/auth/logout', 'auth_logout', 'POST'),
            ('/auth/profile', 'auth_profile', 'POST'),
            ('/auth/wechat', 'auth_wechat', 'POST'),
            ('/auth/wechat/bind', 'auth_wechat_bind', 'POST'),
            ('/tokens/<serial>', 'token_set', 'POST'),
            ('/tokens/<serial>', 'token_delete', 'DELETE'),
            ('/matches', 'match_list', 'GET'),
            ('/matches', 'match_create', 'POST'),
            ('/ranked/leaderboard', 'ranked_leaderboard', 'GET'),
            ('/ranked/matches', 'ranked_match_create', 'POST'),
            ('/matches/<mid>', 'match_get', 'GET'),
            ('/matches/<mid>', 'match_delete', 'DELETE'),
            ('/matches/<mid>/action', 'match_action', 'POST'),
            ('/matches/<mid>/events', 'match_events', 'GET'),
            ('/matches/<mid>/poll', 'match_poll', 'GET'),
            ('/rooms', 'room_list', 'GET'),
            ('/rooms', 'room_create', 'POST'),
            ('/rooms/<code>/join', 'room_join', 'POST'),
            ('/rooms/<code>', 'room_get', 'GET'),
            ('/rooms/<code>/control', 'room_control', 'POST'),
            ('/rooms/<code>/action', 'room_action', 'POST'),
            ('/rooms/<code>/events', 'room_events', 'GET'),
            ('/rooms/<code>/poll', 'room_poll', 'GET'),
        ]
        for route, name, method in routes:
            bp.add_url_rule('/api/ui/autochess' + route, 'autochess_' + name, getattr(self, name), methods=[method])

    # ── Helpers: Origin / Auth / Ownership ──────────────────────────────────

    @staticmethod
    def _auth_err(exc):
        return jsonify(error=True, message=str(exc)), exc.status

    @staticmethod
    def _check_origin():
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/') and not origin.startswith('https://servicewechat.com'):
            raise Forbidden('请从自走棋页面发起操作')

    def _auth_token(self):
        auth_header = (request.headers.get('Authorization') or '').strip()
        if auth_header.lower().startswith('bearer '):
            bearer = auth_header[7:].strip()
            if bearer:
                return bearer
        header_tok = (request.headers.get('X-AutoChess-Auth') or '').strip()
        if header_tok:
            return header_tok
        return request.cookies.get(self.auth.cookie_name, '')

    def _current_account(self):
        token = self._auth_token()
        return self.auth.authenticate(token)

    def _require_account(self, message='请先登录自走棋账号后再使用多人联机功能'):
        acc = self._current_account()
        if not acc:
            raise AuthError(message, 401)
        return acc

    def _owner(self):
        acc = self._current_account()
        if acc:
            return f"acc:{acc['id']}"
        sid = self.c['session_id']()
        if not sid:
            raise Forbidden('请先建立玩家会话')
        return sid

    def _sync_account_tokens_to_live_matches(self, account):
        acc_id = account['id']
        overrides = dict(account.get('token_overrides') or {})
        with self.lock:
            for mid, match in self.matches.items():
                changed = match.set_commander_tokens(acc_id, overrides)
                if not changed and match.commanders.get(match.player_id, {}).get('account_id') == acc_id:
                    match.commanders[match.player_id]['token_overrides'] = dict(overrides)
                    changed = True
                if changed:
                    self.versions[mid] = self.versions.get(mid, 0) + 1
            for code, match in self.room_matches.items():
                if match.set_commander_tokens(acc_id, overrides):
                    self.room_versions[code] = self.room_versions.get(code, 0) + 1
            for code, room in self.rooms.items():
                updated_room = False
                for member in room.get('members', []):
                    if member.get('account_id') == acc_id:
                        member['token_overrides'] = dict(overrides)
                        member['display_name'] = account['display_name']
                        updated_room = True
                if updated_room:
                    self.store.put(_ROOM_KIND, room)
                    self.room_versions[code] = self.room_versions.get(code, 0) + 1
            self.cond.notify_all()

    # ── Auth & Token Routes ─────────────────────────────────────────────────

    def auth_me(self):
        acc = self._current_account()
        return jsonify(authenticated=bool(acc), account=acc)

    def auth_register(self):
        payload = self.c['body']() or {}
        try:
            acc, token = self.auth.register(
                username=payload.get('username', ''),
                password=payload.get('password', ''),
                display_name=payload.get('display_name'),
            )
        except AuthError as exc:
            return self._auth_err(exc)
        resp = jsonify(authenticated=True, account=acc, auth_token=token)
        resp.set_cookie(self.auth.cookie_name, token, httponly=True, samesite='Strict', max_age=86400 * 30)
        return resp

    def auth_login(self):
        payload = self.c['body']() or {}
        try:
            acc, token = self.auth.login(
                username=payload.get('username', ''),
                password=payload.get('password', ''),
            )
        except AuthError as exc:
            return self._auth_err(exc)
        resp = jsonify(authenticated=True, account=acc, auth_token=token)
        resp.set_cookie(self.auth.cookie_name, token, httponly=True, samesite='Strict', max_age=86400 * 30)
        return resp

    def auth_logout(self):
        self._check_origin()
        token = self._auth_token()
        self.auth.logout(token)
        resp = jsonify(ok=True, authenticated=False, account=None)
        resp.delete_cookie(self.auth.cookie_name)
        return resp

    @staticmethod
    def _resolve_wechat_openid(payload):
        trust_cloud = os.environ.get('AUTOCOMBAT_TRUST_WX_CLOUD_HEADERS', '').strip().lower() in ('1', 'true', 'yes')
        if trust_cloud:
            cloud_openid = (request.headers.get('X-WX-OPENID') or '').strip()
            if cloud_openid:
                return cloud_openid
        code = str((payload or {}).get('code') or '').strip()
        if code:
            dev_login = os.environ.get('AUTOCOMBAT_WX_DEV_LOGIN', '').strip().lower() in ('1', 'true', 'yes')
            if dev_login and code.startswith('dev:') and len(code) > 4:
                return 'dev_' + code[4:68]
            return exchange_wechat_code(code)
        raise AuthError('缺少微信登录凭证（请在微信云托管环境调用或提供有效 wx.login code）', 400)

    def auth_wechat(self):
        payload = self.c['body']() or {}
        try:
            openid = self._resolve_wechat_openid(payload)
            acc, token, created = self.auth.login_or_register_wechat(
                openid,
                display_name=payload.get('display_name'),
            )
        except AuthError as exc:
            return self._auth_err(exc)
        resp = jsonify(authenticated=True, account=acc, auth_token=token, created=created)
        resp.set_cookie(self.auth.cookie_name, token, httponly=True, samesite='Strict', max_age=86400 * 30)
        return resp

    def auth_wechat_bind(self):
        payload = self.c['body']() or {}
        try:
            openid = self._resolve_wechat_openid(payload)
            acc, token = self.auth.bind_wechat(
                openid,
                username=payload.get('username', ''),
                password=payload.get('password', ''),
            )
        except AuthError as exc:
            return self._auth_err(exc)
        self._sync_account_tokens_to_live_matches(acc)
        resp = jsonify(authenticated=True, account=acc, auth_token=token)
        resp.set_cookie(self.auth.cookie_name, token, httponly=True, samesite='Strict', max_age=86400 * 30)
        return resp

    def auth_profile(self):
        try:
            acc = self._require_account()
            payload = self.c['body']() or {}
            updated = self.auth.update_profile(
                acc['id'],
                display_name=payload.get('display_name'),
                old_password=payload.get('old_password'),
                new_password=payload.get('new_password'),
            )
        except AuthError as exc:
            return self._auth_err(exc)
        self._sync_account_tokens_to_live_matches(updated)
        return jsonify(account=updated)

    def token_set(self, serial):
        try:
            acc = self._require_account()
            payload = self.c['body']() or {}
            updated = self.auth.set_token_override(acc['id'], serial, payload.get('token_url', ''))
        except AuthError as exc:
            return self._auth_err(exc)
        self._sync_account_tokens_to_live_matches(updated)
        return jsonify(account=updated)

    def token_delete(self, serial):
        self._check_origin()
        try:
            acc = self._require_account()
            updated = self.auth.clear_token_override(acc['id'], serial)
        except AuthError as exc:
            return self._auth_err(exc)
        self._sync_account_tokens_to_live_matches(updated)
        return jsonify(account=updated)

    # ── Catalog ─────────────────────────────────────────────────────────────

    def catalog(self):
        data = catalog_summary()
        data['arenas'] = list(ARENA_PRESETS.values())
        data['terrains'] = TERRAIN_DESCRIPTIONS
        return jsonify(data)

    # ── Single-player / PvE Match Persistence ───────────────────────────────

    def _load_match(self, mid, owner):
        with self.lock:
            rec = self.store.get(_STORE_KIND, mid)
            if not rec:
                raise NotFound(f'对局 {mid} 不存在')
            if rec.get('owner') and rec['owner'] != owner:
                raise Forbidden('无权访问其他玩家的对局')
            match = self.matches.get(mid)
            if match is None:
                match = AutoChessMatch.from_dict(rec['state'])
                self.matches[mid] = match
                self.versions.setdefault(mid, 1)
            return match, rec

    def _save_match(self, match, owner, created_at=None, stats_recorded=False):
        with self.lock:
            now = time.time()
            doc = {
                'id': match.id,
                'owner': owner,
                'mode': match.mode,
                'ranked_tier': getattr(match, 'ranked_tier', None) if match.mode == 'ranked' else None,
                'arena_preset': match.arena_preset,
                'round_num': match.round_num,
                'phase': match.phase,
                'hp': match.commanders[match.player_id]['hp'],
                'created_at': created_at or now,
                'updated_at': now,
                'stats_recorded': bool(stats_recorded),
                'state': match.to_dict(),
            }
            self.store.put(_STORE_KIND, doc)
            self.matches[match.id] = match
            self.versions[match.id] = self.versions.get(match.id, 0) + 1
            self.cond.notify_all()
            return doc

    def invalidate_matches(self, match_ids):
        """Drop in-memory match caches for records updated via peer database sync."""
        if not match_ids:
            return
        with self.lock:
            changed = False
            for mid in match_ids:
                if mid in self.matches:
                    self.matches.pop(mid, None)
                    changed = True
                if mid in self.versions:
                    self.versions[mid] = self.versions.get(mid, 0) + 1
                    changed = True
            if changed:
                self.cond.notify_all()

    def ranked_leaderboard(self):
        acc = self._current_account()
        tier_filter = request.args.get('tier', 'all')
        try:
            limit = max(1, min(500, int(request.args.get('limit', 100) or 100)))
        except (TypeError, ValueError):
            limit = 100
        board = self.auth.get_ranked_leaderboard(
            viewer_account_id=acc['id'] if acc else None,
            tier_filter=tier_filter,
            limit=limit,
        )
        return jsonify(board)

    def _create_or_resume_ranked_match(self, acc, payload):
        owner = f"acc:{acc['id']}"
        with self.lock:
            for rec in self.store.list(_STORE_KIND):
                if (
                    rec.get('owner') == owner
                    and rec.get('mode') == 'ranked'
                    and rec.get('phase') != 'finished'
                ):
                    match, _ = self._load_match(rec['id'], owner)
                    return match, True

            arena = payload.get('arena_preset', 'autochess_standard')
            seed = payload.get('seed')
            tier_id = ((acc.get('ranked') or {}).get('rank_info') or {}).get('tier_id', 'bronze')
            player_name = str(payload.get('player_name') or acc['display_name'])[:24]
            match = AutoChessMatch(
                mode='ranked',
                ranked_tier=tier_id,
                arena_preset=arena,
                seed=seed,
                player_name=player_name,
            )
            match.commanders[match.player_id]['account_id'] = acc['id']
            match.commanders[match.player_id]['token_overrides'] = dict(acc.get('token_overrides') or {})
            self._save_match(match, owner)
            return match, False

    def ranked_match_create(self):
        try:
            acc = self._require_account('请先登录自走棋账号后再参与排位模式')
        except AuthError as exc:
            return self._auth_err(exc)
        payload = self.c['body']() or {}
        match, resumed = self._create_or_resume_ranked_match(acc, payload)
        return jsonify(match=match.to_public_dict(), resumed=resumed)

    def match_list(self):
        acc = self._current_account()
        if acc:
            owner = f"acc:{acc['id']}"
        else:
            owner = self.c['session_id']()
            if not owner:
                return jsonify(matches=[])
        with self.lock:
            rows = [
                {
                    'id': rec['id'],
                    'mode': rec.get('mode', 'lobby4'),
                    'ranked_tier': rec.get('ranked_tier'),
                    'arena_preset': rec.get('arena_preset', 'autochess_standard'),
                    'round_num': rec.get('round_num', 1),
                    'phase': rec.get('phase', 'prep'),
                    'hp': rec.get('hp', 40),
                    'updated_at': rec.get('updated_at', 0),
                }
                for rec in self.store.list(_STORE_KIND)
                if rec.get('owner') == owner
            ]
        return jsonify(matches=rows)

    def match_create(self):
        acc = self._current_account()
        payload = self.c['body']() or {}
        mode = payload.get('mode', 'lobby4')
        if mode == 'pvp_room':
            raise BadRequest('多人联机对局请通过开房间接口创建')
        if mode == 'ranked':
            try:
                req_acc = self._require_account('请先登录自走棋账号后再参与排位模式')
            except AuthError as exc:
                return self._auth_err(exc)
            match, resumed = self._create_or_resume_ranked_match(req_acc, payload)
            return jsonify(match=match.to_public_dict(), resumed=resumed)
        owner = f"acc:{acc['id']}" if acc else self._owner()
        arena = payload.get('arena_preset', 'autochess_standard')
        default_name = acc['display_name'] if acc else '指挥官'
        player_name = str(payload.get('player_name') or default_name)[:24]
        seed = payload.get('seed')
        match = AutoChessMatch(mode=mode, arena_preset=arena, seed=seed, player_name=player_name)
        if acc:
            match.commanders[match.player_id]['account_id'] = acc['id']
            match.commanders[match.player_id]['token_overrides'] = dict(acc.get('token_overrides') or {})
        self._save_match(match, owner)
        return jsonify(match=match.to_public_dict())

    def match_get(self, mid):
        owner = self._owner()
        match, _ = self._load_match(mid, owner)
        return jsonify(match=match.to_public_dict())

    def match_delete(self, mid):
        owner = self._owner()
        match, rec = self._load_match(mid, owner)
        if (match.mode == 'ranked' or rec.get('mode') == 'ranked') and match.phase != 'finished':
            raise BadRequest('进行中的排位赛无法直接删除，请进入对局点击【投降结算】')
        with self.lock:
            self.matches.pop(mid, None)
            self.versions.pop(mid, None)
            self.store.delete(_STORE_KIND, mid)
            self.cond.notify_all()
        return jsonify(ok=True)

    def match_action(self, mid):
        acc = self._current_account()
        owner = f"acc:{acc['id']}" if acc else self._owner()
        payload = self.c['body']() or {}
        action = str(payload.get('action') or '').strip()
        if not action:
            raise BadRequest('缺少 action 参数')
        updated_acc = None
        with self.lock:
            match, rec = self._load_match(mid, owner)
            stats_recorded = bool(rec.get('stats_recorded', False))
            if action != 'surrender' and match.phase == 'prep' and time.time() >= match.prep_deadline:
                pending = match.commanders[match.player_id]['pending_augments']
                if pending:
                    match.pick_augment(match.player_id, pending[0]['id'])
                ok, msg = match.start_combat()
            else:
                ok, msg = match.handle_action(match.player_id, action, payload)
            if acc and match.phase == 'finished' and not stats_recorded:
                p1 = match.commanders.get(match.player_id, {})
                if match.mode == 'ranked':
                    placement = p1.get('placement') or (1 if match.winner_id == match.player_id else 8)
                    updated_acc, settlement = self.auth.record_ranked_result(
                        acc['id'], placement=placement, match_id=match.id
                    )
                    if settlement:
                        match.ranked_settlement = settlement
                else:
                    placement = p1.get('placement') or (1 if match.winner_id == match.player_id else 4)
                    updated_acc = self.auth.record_match_result(acc['id'], placement=placement, mode=match.mode)
                stats_recorded = True
            self._save_match(match, owner, created_at=rec.get('created_at'), stats_recorded=stats_recorded)
            pub = match.to_public_dict()
        resp = {'ok': bool(ok), 'message': str(msg), 'match': pub}
        if updated_acc is not None:
            resp['account'] = updated_acc
        if getattr(match, 'ranked_settlement', None) is not None:
            resp['ranked_settlement'] = match.ranked_settlement
        return jsonify(resp)

    def match_events(self, mid):
        owner = self._owner()
        self._load_match(mid, owner)

        def _stream():
            last_ver = -1
            deadline = time.time() + 180.0
            while time.time() < deadline:
                with self.cond:
                    ver = self.versions.get(mid, 0)
                    if ver == last_ver:
                        self.cond.wait(timeout=1.5)
                        ver = self.versions.get(mid, 0)
                    if mid not in self.matches:
                        break
                    if ver != last_ver:
                        last_ver = ver
                        pub = self.matches[mid].to_public_dict()
                    else:
                        pub = None
                if pub is not None:
                    yield f'event: state\ndata: {json.dumps(pub, ensure_ascii=False)}\n\n'
                else:
                    yield ': keepalive\n\n'

        return Response(_stream(), mimetype='text/event-stream')

    def match_poll(self, mid):
        owner = self._owner()
        self._load_match(mid, owner)
        try:
            since = int(request.args.get('since', '-1'))
        except (TypeError, ValueError):
            raise BadRequest('无效的版本号 since')
        try:
            timeout = max(0.0, min(10.0, float(request.args.get('timeout', '8.0'))))
        except (TypeError, ValueError):
            timeout = 8.0

        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                if mid not in self.matches:
                    rec = self.store.get(_STORE_KIND, mid)
                    if not rec:
                        raise NotFound(f'对局 {mid} 不存在')
                    self._load_match(mid, owner)
                ver = self.versions.get(mid, 0)
                if ver != since:
                    pub = self.matches[mid].to_public_dict()
                    return jsonify(changed=True, version=ver, match=pub)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return jsonify(changed=False, version=ver, match=None)
                self.cond.wait(timeout=min(remaining, 1.5))

    # ── Multiplayer Rooms (Login Required) ──────────────────────────────────

    def _new_room_code(self):
        existing = {rec['id'] for rec in self.store.list(_ROOM_KIND)}
        for _ in range(40):
            code = ''.join(secrets.choice(_ROOM_ALPHABET) for _ in range(6))
            if code not in existing and code not in self.rooms:
                return code
        return secrets.token_hex(3).upper()

    def _load_room_locked(self, code):
        norm = str(code or '').strip().upper()
        if not norm:
            return None, None
        room = self.rooms.get(norm)
        if room is None:
            rec = self.store.get(_ROOM_KIND, norm)
            if not rec:
                return None, None
            room = rec
            self.rooms[norm] = room
            self.room_versions.setdefault(norm, 1)
        match = self.room_matches.get(norm)
        if match is None and room.get('match_state'):
            match = AutoChessMatch.from_dict(room['match_state'])
            self.room_matches[norm] = match
        return room, match

    def _save_room_locked(self, room, match=None):
        code = room['code']
        room['id'] = code
        room['updated_at'] = time.time()
        if match is not None:
            room['match_state'] = match.to_dict()
            self.room_matches[code] = match
        self.rooms[code] = room
        self.store.put(_ROOM_KIND, room)
        self.room_versions[code] = self.room_versions.get(code, 0) + 1
        self.cond.notify_all()

    def _invite_urls(self, code, host_url=None, host=None):
        urls = []
        if host_url is None and has_request_context():
            host_url = request.host_url
        if host is None and has_request_context():
            host = request.host
        if host_url:
            base = str(host_url).rstrip('/')
            urls.append(f'{base}/ui/autochess?room={code}')
        host_parts = str(host or '').split(':')
        port = host_parts[1] if len(host_parts) > 1 else str(self.c.get('instance') or '8889')
        for ip in (self.c.get('lan_ips') or []):
            candidate = f'http://{ip}:{port}/ui/autochess?room={code}'
            if candidate not in urls:
                urls.append(candidate)
        return urls

    @staticmethod
    def _find_member(room, account_id):
        return next((m for m in room.get('members', []) if m.get('account_id') == account_id), None)

    def _record_room_stats_if_finished_locked(self, room, match):
        if match.phase != 'finished' or room.get('stats_recorded'):
            return
        for cid, cmd in match.commanders.items():
            acc_id = cmd.get('account_id')
            if not acc_id:
                continue
            placement = cmd.get('placement') or (1 if cid == match.winner_id else 4)
            self.auth.record_match_result(acc_id, placement=placement, mode='pvp')
        room['stats_recorded'] = True

    def _public_room(self, room, match, viewer_acc_id, spectate_cid=None, host_url=None, host=None):
        code = room['code']
        members = [
            {
                'account_id': m['account_id'],
                'username': m['username'],
                'display_name': m['display_name'],
                'ready': bool(m.get('ready', False)),
                'is_host': m['account_id'] == room['host_account_id'],
            }
            for m in room.get('members', [])
        ]
        my_cid = match.commander_id_for_account(viewer_acc_id) if match else None
        return {
            'code': code,
            'name': room.get('name', f'房间 {code}'),
            'status': room.get('status', 'waiting'),
            'arena_preset': room.get('arena_preset', 'autochess_standard'),
            'max_players': int(room.get('max_players', 4)),
            'fill_bots': bool(room.get('fill_bots', True)),
            'prep_duration': int(room.get('prep_duration', 30)),
            'auto_step': bool(room.get('auto_step', True)),
            'host_account_id': room['host_account_id'],
            'my_account_id': viewer_acc_id,
            'my_commander_id': my_cid,
            'is_host': viewer_acc_id == room['host_account_id'],
            'members': members,
            'invite_urls': self._invite_urls(code, host_url=host_url, host=host),
            'updated_at': room.get('updated_at', 0),
            'match': match.to_public_dict(viewer_cid=my_cid, spectate_cid=spectate_cid) if match else None,
        }

    def _ensure_room_stepper_locked(self, code):
        if code in self._room_steppers:
            return
        self._room_steppers.add(code)

        def _runner():
            try:
                while True:
                    time.sleep(0.55)
                    with self.lock:
                        room, match = self._load_room_locked(code)
                        if not room or not match or room.get('status') != 'playing' or match.phase != 'combat':
                            break
                        match.step_combat(1)
                        if match.phase != 'combat':
                            self._record_room_stats_if_finished_locked(room, match)
                            if match.phase == 'finished':
                                room['status'] = 'finished'
                            self._save_room_locked(room, match)
                            break
                        self.room_versions[code] = self.room_versions.get(code, 0) + 1
                        self.cond.notify_all()
            finally:
                with self.lock:
                    self._room_steppers.discard(code)

        threading.Thread(target=_runner, name=f'autochess-room-{code}', daemon=True).start()

    def _maybe_advance_prep_deadline_locked(self, room, match):
        if not match or room.get('status') != 'playing' or match.phase != 'prep':
            return False
        if time.time() < float(match.prep_deadline):
            return False
        for cid, cmd in match.commanders.items():
            if cmd.get('is_human') and not cmd.get('eliminated'):
                pending = cmd.get('pending_augments') or []
                if pending:
                    match.pick_augment(cid, pending[0]['id'])
                cmd['ready'] = True
        ok, _ = match.start_combat()
        if ok:
            self._save_room_locked(room, match)
            if room.get('auto_step', True):
                self._ensure_room_stepper_locked(room['code'])
        return ok

    def _maybe_advance_round_result_deadline_locked(self, room, match):
        if not match or room.get('status') != 'playing' or match.phase != 'round_result':
            return False
        deadline = float(getattr(match, 'round_result_deadline', 0.0) or 0.0)
        if deadline <= 0 or time.time() < deadline:
            return False
        ok, _ = match.next_round()
        if ok:
            self._save_room_locked(room, match)
        return ok

    def room_list(self):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        with self.lock:
            items = []
            for rec in self.store.list(_ROOM_KIND):
                code = rec.get('code') or rec.get('id')
                room = self.rooms.get(code) or rec
                is_member = any(m.get('account_id') == acc['id'] for m in room.get('members', []))
                if room.get('status') == 'waiting' or is_member:
                    host_member = self._find_member(room, room.get('host_account_id'))
                    items.append({
                        'code': code,
                        'name': room.get('name', f'房间 {code}'),
                        'status': room.get('status', 'waiting'),
                        'arena_preset': room.get('arena_preset', 'autochess_standard'),
                        'max_players': int(room.get('max_players', 4)),
                        'fill_bots': bool(room.get('fill_bots', True)),
                        'prep_duration': int(room.get('prep_duration', 30)),
                        'member_count': len(room.get('members', [])),
                        'host_name': host_member['display_name'] if host_member else '',
                        'is_member': is_member,
                        'updated_at': room.get('updated_at', 0),
                    })
            items.sort(key=lambda r: r['updated_at'], reverse=True)
        return jsonify(rooms=items)

    def room_create(self):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        payload = self.c['body']() or {}
        arena = str(payload.get('arena_preset') or 'autochess_standard')
        if arena not in ARENA_PRESETS:
            arena = 'autochess_standard'
        max_players = max(2, min(4, int(payload.get('max_players', 4) or 4)))
        fill_bots = bool(payload.get('fill_bots', True))
        prep_duration = max(15, min(90, int(payload.get('prep_duration', 30) or 30)))
        auto_step = bool(payload.get('auto_step', True))

        with self.lock:
            code = self._new_room_code()
            name = str(payload.get('name') or f"{acc['display_name']}的房间").strip()[:28] or f'房间 {code}'
            now = time.time()
            room = {
                'id': code,
                'code': code,
                'name': name,
                'host_account_id': acc['id'],
                'status': 'waiting',
                'arena_preset': arena,
                'max_players': max_players,
                'fill_bots': fill_bots,
                'prep_duration': prep_duration,
                'auto_step': auto_step,
                'members': [
                    {
                        'account_id': acc['id'],
                        'username': acc['username'],
                        'display_name': acc['display_name'],
                        'ready': True,
                        'token_overrides': dict(acc.get('token_overrides') or {}),
                        'joined_at': now,
                    }
                ],
                'match_state': None,
                'stats_recorded': False,
                'created_at': now,
                'updated_at': now,
            }
            self._save_room_locked(room)
            pub = self._public_room(room, None, acc['id'])
        return jsonify(room=pub)

    def room_join(self, code):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        self._check_origin()
        with self.lock:
            room, match = self._load_room_locked(code)
            if not room:
                raise NotFound('联机房间不存在或已解散')
            existing = self._find_member(room, acc['id'])
            if existing:
                existing['display_name'] = acc['display_name']
                existing['token_overrides'] = dict(acc.get('token_overrides') or {})
                if match:
                    match.set_commander_tokens(acc['id'], acc.get('token_overrides') or {})
                self._save_room_locked(room, match)
                return jsonify(room=self._public_room(room, match, acc['id']))
            if room.get('status') != 'waiting':
                raise Conflict('该房间已开局，无法中途加入')
            if len(room.get('members', [])) >= int(room.get('max_players', 4)):
                raise Conflict('该房间已满员')
            room['members'].append({
                'account_id': acc['id'],
                'username': acc['username'],
                'display_name': acc['display_name'],
                'ready': False,
                'token_overrides': dict(acc.get('token_overrides') or {}),
                'joined_at': time.time(),
            })
            self._save_room_locked(room)
            pub = self._public_room(room, None, acc['id'])
        return jsonify(room=pub)

    def room_get(self, code):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        spectate_cid = request.args.get('spectate') or None
        with self.lock:
            room, match = self._load_room_locked(code)
            if not room:
                raise NotFound('联机房间不存在')
            if not self._find_member(room, acc['id']):
                raise Forbidden('请先加入该联机房间')
            self._maybe_advance_prep_deadline_locked(room, match)
            self._maybe_advance_round_result_deadline_locked(room, match)
            pub = self._public_room(room, match, acc['id'], spectate_cid=spectate_cid)
        return jsonify(room=pub)

    def room_control(self, code):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        payload = self.c['body']() or {}
        op = str(payload.get('op') or '').strip()
        if not op:
            raise BadRequest('缺少控制指令 op')

        with self.lock:
            room, match = self._load_room_locked(code)
            if not room:
                if op == 'leave':
                    return jsonify(ok=True, disbanded=True, room=None)
                raise NotFound('联机房间不存在')
            member = self._find_member(room, acc['id'])
            if not member:
                if op == 'leave':
                    return jsonify(ok=True, disbanded=False, room=None)
                raise Forbidden('请先加入该联机房间')
            is_host = acc['id'] == room['host_account_id']

            if op == 'ready':
                if room['status'] != 'waiting':
                    raise BadRequest('对局已开始')
                desired = payload.get('ready')
                member['ready'] = (not member['ready']) if desired is None else bool(desired)
                self._save_room_locked(room)
                return jsonify(ok=True, message='已更新准备状态', room=self._public_room(room, None, acc['id']))

            if op == 'config':
                if not is_host:
                    raise Forbidden('仅房主可修改房间设置')
                if room['status'] != 'waiting':
                    raise BadRequest('开局后无法修改房间设置')
                if 'name' in payload:
                    cleaned_name = str(payload['name'] or '').strip()[:28]
                    if cleaned_name:
                        room['name'] = cleaned_name
                if 'arena_preset' in payload and payload['arena_preset'] in ARENA_PRESETS:
                    room['arena_preset'] = payload['arena_preset']
                if 'max_players' in payload:
                    mp = max(2, min(4, int(payload['max_players'] or 4)))
                    if mp < len(room['members']):
                        raise BadRequest('人数上限不能小于当前房间人数')
                    room['max_players'] = mp
                if 'fill_bots' in payload:
                    room['fill_bots'] = bool(payload['fill_bots'])
                if 'prep_duration' in payload:
                    room['prep_duration'] = max(15, min(90, int(payload['prep_duration'] or 30)))
                self._save_room_locked(room)
                return jsonify(ok=True, message='房间设置已更新', room=self._public_room(room, None, acc['id']))

            if op == 'leave':
                if room['status'] != 'waiting':
                    raise BadRequest('对局进行中，暂不支持在候战室退房')
                room['members'] = [m for m in room['members'] if m['account_id'] != acc['id']]
                norm = room['code']
                if not room['members']:
                    self.rooms.pop(norm, None)
                    self.room_matches.pop(norm, None)
                    self.room_versions.pop(norm, None)
                    self.store.delete(_ROOM_KIND, norm)
                    self.cond.notify_all()
                    return jsonify(ok=True, disbanded=True, room=None)
                if is_host:
                    room['host_account_id'] = room['members'][0]['account_id']
                self._save_room_locked(room)
                return jsonify(ok=True, disbanded=False, room=None)

            if op == 'start':
                if not is_host:
                    raise Forbidden('仅房主可开启多人对局')
                if room['status'] != 'waiting':
                    raise BadRequest('对局已经开始')
                members = room.get('members', [])
                if not room.get('fill_bots') and len(members) < 2:
                    raise BadRequest('未开启 AI 补位时至少需要 2 名玩家才可开局')
                unready = [
                    m['display_name']
                    for m in members
                    if m['account_id'] != room['host_account_id'] and not m.get('ready')
                ]
                if unready:
                    raise BadRequest(f"尚有玩家未准备：{'、'.join(unready)}")

                human_players = []
                for m in members:
                    latest = self.auth.get_account(m['account_id']) or m
                    human_players.append({
                        'account_id': m['account_id'],
                        'name': latest.get('display_name', m['display_name']),
                        'token_overrides': dict(latest.get('token_overrides') or {}),
                    })
                new_match = AutoChessMatch(
                    match_id=f"room_{room['code']}_{secrets.token_hex(2)}",
                    mode='pvp_room',
                    arena_preset=room.get('arena_preset', 'autochess_standard'),
                    seed=payload.get('seed'),
                    human_players=human_players,
                    fill_bots=bool(room.get('fill_bots', True)),
                    prep_duration=int(room.get('prep_duration', 30)),
                )
                room['status'] = 'playing'
                room['stats_recorded'] = False
                self._save_room_locked(room, new_match)
                return jsonify(ok=True, message='多人联机对局已开启！', room=self._public_room(room, new_match, acc['id']))

        raise BadRequest(f'未知房间指令: {op}')

    def room_action(self, code):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        payload = self.c['body']() or {}
        action = str(payload.get('action') or '').strip()
        if not action:
            raise BadRequest('缺少 action 参数')
        spectate_cid = payload.get('spectate_cid') or request.args.get('spectate') or None

        with self.lock:
            room, match = self._load_room_locked(code)
            if not room:
                raise NotFound('联机房间不存在')
            if not self._find_member(room, acc['id']):
                raise Forbidden('请先加入该联机房间')
            if room.get('status') == 'waiting' or not match:
                raise BadRequest('房间尚未开始对局')
            cid = match.commander_id_for_account(acc['id'])
            if not cid:
                raise Forbidden('未找到您的指挥官席位')

            if self._maybe_advance_prep_deadline_locked(room, match):
                ok, msg = True, '备战倒计时结束，自动进入战斗阶段'
            elif self._maybe_advance_round_result_deadline_locked(room, match):
                ok, msg = True, '结算倒计时结束，自动进入下一回合备战'
            else:
                ok, msg = match.handle_action(cid, action, payload)
                if ok and action == 'ready_combat' and match.phase == 'prep' and match.all_humans_ready():
                    for hcid, cmd in match.commanders.items():
                        if cmd.get('is_human') and not cmd.get('eliminated'):
                            pending = cmd.get('pending_augments') or []
                            if pending:
                                match.pick_augment(hcid, pending[0]['id'])
                    ok, msg = match.start_combat()
                elif ok and action == 'skip_combat' and match.phase == 'combat' and match.all_humans_skip_combat():
                    ok, msg = match.resolve_combat()
                elif ok and action == 'ready_next' and match.phase == 'round_result' and match.all_humans_next_ready():
                    ok, msg = match.next_round()

            if match.phase == 'combat' and room.get('auto_step', True):
                self._ensure_room_stepper_locked(room['code'])
            self._record_room_stats_if_finished_locked(room, match)
            if match.phase == 'finished':
                room['status'] = 'finished'
            self._save_room_locked(room, match)
            pub = self._public_room(room, match, acc['id'], spectate_cid=spectate_cid)

        return jsonify(ok=bool(ok), message=str(msg), room=pub)

    def room_events(self, code):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        norm = str(code or '').strip().upper()
        spectate_cid = request.args.get('spectate') or None
        req_host_url = request.host_url
        req_host = request.host
        with self.lock:
            room, _ = self._load_room_locked(norm)
            if not room:
                raise NotFound('联机房间不存在')
            if not self._find_member(room, acc['id']):
                raise Forbidden('请先加入该联机房间')

        def _stream():
            last_ver = -1
            deadline = time.time() + 180.0
            while time.time() < deadline:
                with self.cond:
                    room_cur, match_cur = self._load_room_locked(norm)
                    if not room_cur:
                        break
                    self._maybe_advance_prep_deadline_locked(room_cur, match_cur)
                    self._maybe_advance_round_result_deadline_locked(room_cur, match_cur)
                    ver = self.room_versions.get(norm, 0)
                    if ver == last_ver:
                        self.cond.wait(timeout=1.5)
                        room_cur, match_cur = self._load_room_locked(norm)
                        if not room_cur:
                            break
                        self._maybe_advance_prep_deadline_locked(room_cur, match_cur)
                        self._maybe_advance_round_result_deadline_locked(room_cur, match_cur)
                        ver = self.room_versions.get(norm, 0)
                    if ver != last_ver:
                        last_ver = ver
                        pub = self._public_room(
                            room_cur,
                            match_cur,
                            acc['id'],
                            spectate_cid=spectate_cid,
                            host_url=req_host_url,
                            host=req_host,
                        )
                    else:
                        pub = None
                if pub is not None:
                    yield f'event: room\ndata: {json.dumps(pub, ensure_ascii=False)}\n\n'
                else:
                    yield ': keepalive\n\n'

        return Response(_stream(), mimetype='text/event-stream')

    def room_poll(self, code):
        try:
            acc = self._require_account()
        except AuthError as exc:
            return self._auth_err(exc)
        norm = str(code or '').strip().upper()
        spectate_cid = request.args.get('spectate') or None
        try:
            since = int(request.args.get('since', '-1'))
        except (TypeError, ValueError):
            raise BadRequest('无效的版本号 since')
        try:
            timeout = max(0.0, min(10.0, float(request.args.get('timeout', '8.0'))))
        except (TypeError, ValueError):
            timeout = 8.0

        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                room_cur, match_cur = self._load_room_locked(norm)
                if not room_cur:
                    raise NotFound('联机房间不存在')
                if not self._find_member(room_cur, acc['id']):
                    raise Forbidden('请先加入该联机房间')
                self._maybe_advance_prep_deadline_locked(room_cur, match_cur)
                self._maybe_advance_round_result_deadline_locked(room_cur, match_cur)
                ver = self.room_versions.get(norm, 0)
                if ver != since:
                    pub = self._public_room(
                        room_cur,
                        match_cur,
                        acc['id'],
                        spectate_cid=spectate_cid,
                    )
                    return jsonify(changed=True, version=ver, room=pub)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return jsonify(changed=False, version=ver, room=None)
                self.cond.wait(timeout=min(remaining, 1.5))
