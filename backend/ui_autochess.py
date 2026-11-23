"""Flask Auto-Chess blueprint (/api/ui/autochess/*) with SQLite persistence & SSE updates."""

import json
import threading
import time

from flask import Response, jsonify
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from arena_presets import ARENA_PRESETS, TERRAIN_DESCRIPTIONS
from autochess_catalog import catalog_summary
from autochess_match import AutoChessMatch

_STORE_KIND = 'autochess_match'


class AutoChessUI:
    """Manages Auto-Chess matches stored in ui_store and live in-memory combat stepping."""

    def __init__(self, bp, context, store):
        self.c = context
        self.store = store
        self.lock = threading.RLock()
        self.matches = {}
        self.versions = {}
        self.cond = threading.Condition(self.lock)

        routes = [
            ('/catalog', 'catalog', 'GET'),
            ('/matches', 'match_list', 'GET'),
            ('/matches', 'match_create', 'POST'),
            ('/matches/<mid>', 'match_get', 'GET'),
            ('/matches/<mid>', 'match_delete', 'DELETE'),
            ('/matches/<mid>/action', 'match_action', 'POST'),
            ('/matches/<mid>/events', 'match_events', 'GET'),
        ]
        for route, name, method in routes:
            bp.add_url_rule('/api/ui/autochess' + route, 'autochess_' + name, getattr(self, name), methods=[method])

    def _owner(self):
        sid = self.c['session_id']()
        if not sid:
            raise Forbidden('请先建立玩家会话')
        return sid

    def _load_match(self, mid, owner):
        with self.lock:
            rec = self.store.get(_STORE_KIND, mid)
            if not rec:
                raise NotFound(f'对局 {mid} 不存在')
            if rec.get('owner') and rec['owner'] != owner:
                raise Forbidden('无权访问其他会话的对局')
            match = self.matches.get(mid)
            if match is None:
                match = AutoChessMatch.from_dict(rec['state'])
                self.matches[mid] = match
                self.versions.setdefault(mid, 1)
            return match, rec

    def _save_match(self, match, owner, created_at=None):
        with self.lock:
            now = time.time()
            doc = {
                'id': match.id,
                'owner': owner,
                'mode': match.mode,
                'arena_preset': match.arena_preset,
                'round_num': match.round_num,
                'phase': match.phase,
                'hp': match.commanders[match.player_id]['hp'],
                'created_at': created_at or now,
                'updated_at': now,
                'state': match.to_dict(),
            }
            self.store.put(_STORE_KIND, doc)
            self.matches[match.id] = match
            self.versions[match.id] = self.versions.get(match.id, 0) + 1
            self.cond.notify_all()
            return doc

    def catalog(self):
        data = catalog_summary()
        data['arenas'] = list(ARENA_PRESETS.values())
        data['terrains'] = TERRAIN_DESCRIPTIONS
        return jsonify(data)

    def match_list(self):
        owner = self._owner()
        rows = []
        for rec in self.store.list(_STORE_KIND):
            if rec.get('owner') == owner:
                rows.append({
                    'id': rec['id'],
                    'mode': rec.get('mode', 'lobby4'),
                    'arena_preset': rec.get('arena_preset', 'autochess_standard'),
                    'round_num': rec.get('round_num', 1),
                    'phase': rec.get('phase', 'prep'),
                    'hp': rec.get('hp', 40),
                    'updated_at': rec.get('updated_at', 0),
                })
        return jsonify(matches=rows)

    def match_create(self):
        owner = self._owner()
        payload = self.c['body']() or {}
        mode = payload.get('mode', 'lobby4')
        arena = payload.get('arena_preset', 'autochess_standard')
        player_name = str(payload.get('player_name') or '指挥官')[:24]
        seed = payload.get('seed')
        match = AutoChessMatch(mode=mode, arena_preset=arena, seed=seed, player_name=player_name)
        self._save_match(match, owner)
        return jsonify(match=match.to_public_dict())

    def match_get(self, mid):
        owner = self._owner()
        match, _ = self._load_match(mid, owner)
        return jsonify(match=match.to_public_dict())

    def match_delete(self, mid):
        owner = self._owner()
        self._load_match(mid, owner)
        with self.lock:
            self.matches.pop(mid, None)
            self.versions.pop(mid, None)
            self.store.delete(_STORE_KIND, mid)
            self.cond.notify_all()
        return jsonify(ok=True)

    def match_action(self, mid):
        owner = self._owner()
        payload = self.c['body']() or {}
        action = str(payload.get('action') or '').strip()
        if not action:
            raise BadRequest('缺少 action 参数')
        with self.lock:
            match, rec = self._load_match(mid, owner)
            if match.phase == 'prep' and time.time() >= match.prep_deadline:
                pending = match.commanders[match.player_id]['pending_augments']
                if pending:
                    match.pick_augment(match.player_id, pending[0]['id'])
                ok, msg = match.start_combat()
            else:
                ok, msg = match.handle_action(match.player_id, action, payload)
            self._save_match(match, owner, created_at=rec.get('created_at'))
            pub = match.to_public_dict()
        return jsonify(ok=bool(ok), message=str(msg), match=pub)

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
