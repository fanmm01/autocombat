import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

from flask import Blueprint, Flask, request
from werkzeug.serving import make_server

import autocombat_backend as backend
from autochess_auth import (
    AutoChessAuthService,
    KIND_ACCOUNT,
    KIND_TOKEN,
    KIND_WX_BIND,
    PRIMARY_ADMIN_DEFAULT_PASSWORD,
    PRIMARY_ADMIN_ID,
)
from ui_autochess import AutoChessUI
from ui_db_sync import DatabaseSync
from ui_store import Store


class _TestClientHttpResponse:
    def __init__(self, resp):
        self._data = resp.get_data()
        self.status = resp.status_code

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_flask_opener(flask_app):
    def _opener(req, timeout=10):
        client = flask_app.test_client()
        headers = {k: v for k, v in req.header_items()}
        resp = client.open(
            req.selector,
            method=req.get_method(),
            data=req.data,
            headers=headers,
        )
        if resp.status_code >= 400:
            import urllib.error
            raise urllib.error.HTTPError(
                req.full_url,
                resp.status_code,
                'HTTP Error',
                resp.headers,
                io.BytesIO(resp.get_data()),
            )
        return _TestClientHttpResponse(resp)

    return _opener


class _SyncNode:
    def __init__(self, db_path, node_id, token='', peer_url='', debounce_sec=0.15, interval_sec=0.0, auto_start=False):
        self.app = Flask(f'sync_node_{node_id}')
        bp = Blueprint(f'ui_{node_id}', __name__)
        self.store = Store(db_path, node_id=node_id)
        self.auth = AutoChessAuthService(self.store, cookie_name=f'autochess_auth_{node_id}')
        context = {
            'instance': node_id,
            'clean': lambda v: json.loads(json.dumps(v, ensure_ascii=False, default=lambda x: list(x) if isinstance(x, set) else str(x))),
            'body': lambda: request.get_json(silent=True),
            'session_id': lambda: (request.headers.get('X-Combat-Session') or '').strip(),
        }
        self.ac_ui = AutoChessUI(bp, context, self.store, auth=self.auth)
        self.db_sync = DatabaseSync(
            bp,
            self.store,
            auth=self.auth,
            on_records_changed=lambda changed: self.ac_ui.invalidate_matches(
                [rid for kind, rid in changed if kind == 'autochess_match']
            ),
            token=token,
            peer_url=peer_url,
            debounce_sec=debounce_sec,
            interval_sec=interval_sec,
            auto_start=auto_start,
        )
        self.app.register_blueprint(bp)

    def stop(self):
        self.db_sync.stop()


class DatabaseSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self._nodes = []

    def tearDown(self):
        for node in reversed(self._nodes):
            node.stop()
        self._tmp.cleanup()

    def _new_node(self, name, **kwargs):
        node = _SyncNode(self.tmp_dir / f'{name}.sqlite3', name, **kwargs)
        self._nodes.append(node)
        return node

    def test_live_app_sync_guards_and_token_auth(self):
        live_sync = backend.app.extensions['combat_ui']['db_sync']
        self.assertIsNotNone(live_sync)
        live_client = backend.app.test_client()
        if not live_sync.enabled:
            res = live_client.post('/api/ui/sync/exchange', json={'records': []})
            self.assertEqual(res.status_code, 503)
            st = live_client.get('/api/ui/sync/status')
            self.assertEqual(st.status_code, 401)

        node = self._new_node('guard_node', token='sync-secret-xyz')
        c = node.app.test_client()
        no_tok = c.post('/api/ui/sync/exchange', json={'records': []})
        self.assertEqual(no_tok.status_code, 401)
        bad_tok = c.post('/api/ui/sync/exchange', json={'records': []}, headers={'X-Sync-Token': 'wrong'})
        self.assertEqual(bad_tok.status_code, 401)

        ok_tok = c.post(
            '/api/ui/sync/exchange',
            json={'node_id': 'peer', 'since': 0, 'records': []},
            headers={'X-Sync-Token': 'sync-secret-xyz'},
        )
        self.assertEqual(ok_tok.status_code, 200)
        self.assertTrue(ok_tok.get_json()['ok'])

        # Normal logged-in player cannot inspect sync status, but sync token can
        reg = c.post('/api/ui/autochess/auth/register', json={'username': 'player_guard', 'password': 'pw_guard_123'})
        self.assertEqual(reg.status_code, 200)
        user_auth = reg.get_json()['auth_token']
        denied = c.get('/api/ui/sync/status', headers={'Authorization': f'Bearer {user_auth}'})
        self.assertEqual(denied.status_code, 401)

        status_ok = c.get('/api/ui/sync/status', headers={'X-Sync-Token': 'sync-secret-xyz'})
        self.assertEqual(status_ok.status_code, 200)
        self.assertTrue(status_ok.get_json()['enabled'])

        # Super admin bearer token can also inspect sync status
        admin_login = c.post(
            '/api/ui/autochess/auth/login',
            json={'username': PRIMARY_ADMIN_ID, 'password': PRIMARY_ADMIN_DEFAULT_PASSWORD},
        )
        self.assertEqual(admin_login.status_code, 200)
        admin_tok = admin_login.get_json()['auth_token']
        admin_st = c.get('/api/ui/sync/status', headers={'Authorization': f'Bearer {admin_tok}'})
        self.assertEqual(admin_st.status_code, 200)
        self.assertTrue(admin_st.get_json()['enabled'])

    def test_legacy_db_backfill_and_bootstrap_admin_protection(self):
        legacy_path = self.tmp_dir / 'legacy.sqlite3'
        # Create a legacy database containing ONLY `records` table (like 154.8.155.71:8889 before sync)
        db = sqlite3.connect(legacy_path)
        with db:
            db.execute('CREATE TABLE records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
            legacy_admin = {
                'id': PRIMARY_ADMIN_ID,
                'username': PRIMARY_ADMIN_ID,
                'display_name': '主服管理员',
                'role': 'super_admin',
                'password_salt': '00112233445566778899aabbccddeeff',
                'password_hash': backend.autochess_auth._hash_password('custom-prod-pw', '00112233445566778899aabbccddeeff')
                if hasattr(backend, 'autochess_auth') else '',
                'created_at': 1795460000.0,
                'token_overrides': {},
                'stats': {'games': 12, 'wins': 9, 'top2': 11, 'pve_clears': 2},
                'ranked': {
                    'lp': 1520,
                    'rank_info': {'tier_id': 'platinum', 'tier_name': '铂金', 'division': 'II', 'lp_in_division': 20},
                    'stars_currency': 88,
                },
            }
            if not legacy_admin['password_hash']:
                from autochess_auth import _hash_password
                legacy_admin['password_hash'] = _hash_password('custom-prod-pw', legacy_admin['password_salt'])
            legacy_match = {
                'id': 'ac_legacy_01',
                'owner': f'acc:{PRIMARY_ADMIN_ID}',
                'mode': 'ranked',
                'ranked_tier': 'platinum',
                'arena_preset': 'autochess_standard',
                'round_num': 14,
                'phase': 'finished',
                'hp': 18,
                'created_at': 1795460463.0,
                'state': {'id': 'ac_legacy_01', 'mode': 'ranked'},
            }
            db.execute('INSERT INTO records VALUES (?,?,?)', (KIND_ACCOUNT, PRIMARY_ADMIN_ID, json.dumps(legacy_admin)))
            db.execute('INSERT INTO records VALUES (?,?,?)', ('autochess_match', 'ac_legacy_01', json.dumps(legacy_match)))
        db.close()

        node_a = _SyncNode(legacy_path, 'prod_ip', token='tok-sync')
        self._nodes.append(node_a)
        node_b = self._new_node('cloud_new', token='tok-sync', peer_url='http://mock-a')

        # Before sync: node_b has auto-seeded default fanmm01 (0 LP, default pw), NOT legacy match
        self.assertIsNone(node_b.store.get('autochess_match', 'ac_legacy_01'))
        res = node_b.db_sync.sync_once(full=True, opener=_make_flask_opener(node_a.app))
        self.assertTrue(res['ok'], res)

        # After sync: node_b receives real fanmm01 and legacy match; node_a keeps its real fanmm01!
        synced_admin_b = node_b.store.get(KIND_ACCOUNT, PRIMARY_ADMIN_ID)
        synced_admin_a = node_a.store.get(KIND_ACCOUNT, PRIMARY_ADMIN_ID)
        self.assertEqual(synced_admin_b['ranked']['lp'], 1520)
        self.assertEqual(synced_admin_b['stats']['wins'], 9)
        self.assertEqual(synced_admin_a['ranked']['lp'], 1520)
        self.assertIsNotNone(node_b.store.get('autochess_match', 'ac_legacy_01'))

        # Confirm real password works on node_b
        cb = node_b.app.test_client()
        login_res = cb.post('/api/ui/autochess/auth/login', json={'username': PRIMARY_ADMIN_ID, 'password': 'custom-prod-pw'})
        self.assertEqual(login_res.status_code, 200, login_res.get_data(as_text=True))

    def test_bidirectional_accounts_wechat_bind_tokens_and_matches(self):
        node_a = self._new_node('node_a', token='tok-bi')
        node_b = self._new_node('node_b', token='tok-bi', peer_url='http://mock-a')
        opener_a = _make_flask_opener(node_a.app)

        self.assertTrue(node_b.db_sync.sync_once(full=True, opener=opener_a)['ok'])

        ca = node_a.app.test_client()
        cb = node_b.app.test_client()

        # 1) Register account & create match on Node A
        reg_a = ca.post('/api/ui/autochess/auth/register', json={'username': 'web_alice', 'password': 'pw_alice_123'})
        self.assertEqual(reg_a.status_code, 200, reg_a.get_data(as_text=True))
        tok_a = reg_a.get_json()['auth_token']
        m_a = ca.post(
            '/api/ui/autochess/matches',
            json={'mode': 'pve'},
            headers={'Authorization': f'Bearer {tok_a}'},
        )
        self.assertEqual(m_a.status_code, 200, m_a.get_data(as_text=True))
        mid_a = m_a.get_json()['match']['id']

        # 2) WeChat one-tap login & create match on Node B
        with mock.patch.dict(os.environ, {'AUTOCOMBAT_TRUST_WX_CLOUD_HEADERS': '1'}):
            wx_b = cb.post(
                '/api/ui/autochess/auth/wechat',
                json={'player_name': '微信星序玩家'},
                headers={'X-WX-OPENID': 'wx_openid_sync_01'},
            )
        self.assertEqual(wx_b.status_code, 200, wx_b.get_data(as_text=True))
        tok_b = wx_b.get_json()['auth_token']
        wx_acc_id = wx_b.get_json()['account']['id']
        m_b = cb.post(
            '/api/ui/autochess/matches',
            json={'mode': 'pve'},
            headers={'Authorization': f'Bearer {tok_b}'},
        )
        self.assertEqual(m_b.status_code, 200, m_b.get_data(as_text=True))
        mid_b = m_b.get_json()['match']['id']

        # Sync B <-> A
        res = node_b.db_sync.sync_once(opener=opener_a)
        self.assertTrue(res['ok'], res)

        # Node A now recognizes Node B's WeChat token, wx_bind, and match
        me_on_a = ca.get('/api/ui/autochess/auth/me', headers={'Authorization': f'Bearer {tok_b}'})
        self.assertEqual(me_on_a.status_code, 200)
        self.assertTrue(me_on_a.get_json()['authenticated'])
        self.assertEqual(me_on_a.get_json()['account']['id'], wx_acc_id)
        self.assertTrue(me_on_a.get_json()['account']['wx_bound'])
        self.assertIsNotNone(node_a.store.get(KIND_WX_BIND, 'wx_openid_sync_01'))
        get_mb_on_a = ca.get(f'/api/ui/autochess/matches/{mid_b}', headers={'Authorization': f'Bearer {tok_b}'})
        self.assertEqual(get_mb_on_a.status_code, 200)

        # Node B now recognizes Node A's Web token, password login, and match
        me_on_b = cb.get('/api/ui/autochess/auth/me', headers={'Authorization': f'Bearer {tok_a}'})
        self.assertEqual(me_on_b.status_code, 200)
        self.assertTrue(me_on_b.get_json()['authenticated'])
        self.assertEqual(me_on_b.get_json()['account']['id'], 'web_alice')
        get_ma_on_b = cb.get(f'/api/ui/autochess/matches/{mid_a}', headers={'Authorization': f'Bearer {tok_a}'})
        self.assertEqual(get_ma_on_b.status_code, 200)

    def test_conflict_tombstone_delete_and_cache_invalidation(self):
        node_a = self._new_node('node_ca', token='tok-c')
        node_b = self._new_node('node_cb', token='tok-c', peer_url='http://mock-a')
        opener_a = _make_flask_opener(node_a.app)

        ca = node_a.app.test_client()
        cb = node_b.app.test_client()

        reg_a = ca.post('/api/ui/autochess/auth/register', json={'username': 'bob_sync', 'password': 'pw_bob_123'})
        tok_a = reg_a.get_json()['auth_token']
        m_res = ca.post('/api/ui/autochess/matches', json={'mode': 'pve'}, headers={'Authorization': f'Bearer {tok_a}'})
        mid = m_res.get_json()['match']['id']

        self.assertTrue(node_b.db_sync.sync_once(full=True, opener=opener_a)['ok'])
        # Load match on Node B so node_b.ac_ui.matches[mid] is cached in memory
        load_b = cb.get(f'/api/ui/autochess/matches/{mid}', headers={'Authorization': f'Bearer {tok_a}'})
        self.assertEqual(load_b.status_code, 200)
        self.assertIn(mid, node_b.ac_ui.matches)
        old_ver = node_b.ac_ui.versions.get(mid, 1)

        # Mutate match directly on Node A with newer timestamp -> sync should invalidate B's cache
        rec_a = node_a.store.get('autochess_match', mid)
        rec_a['round_num'] = 6
        rec_a['state']['round_num'] = 6
        node_a.store.put('autochess_match', rec_a, updated_at=time.time() + 10.0)
        node_b.db_sync.sync_once(opener=opener_a)
        self.assertNotIn(mid, node_b.ac_ui.matches)
        self.assertGreater(node_b.ac_ui.versions.get(mid, 0), old_ver)
        load_b2 = cb.get(f'/api/ui/autochess/matches/{mid}', headers={'Authorization': f'Bearer {tok_a}'})
        self.assertEqual(load_b2.get_json()['match']['round_num'], 6)

        # Conflict LWW check: stale update on B vs newer update on A -> A wins; then newer B -> B wins
        node_a.store.put('identity', {'id': 'id_lww', 'player': 'from_a_200'}, updated_at=200.0)
        node_b.store.put('identity', {'id': 'id_lww', 'player': 'from_b_100'}, updated_at=100.0)
        node_b.db_sync.sync_once(full=True, opener=opener_a)
        self.assertEqual(node_a.store.get('identity', 'id_lww')['player'], 'from_a_200')
        self.assertEqual(node_b.store.get('identity', 'id_lww')['player'], 'from_a_200')

        node_b.store.put('identity', {'id': 'id_lww', 'player': 'from_b_300'}, updated_at=time.time() + 20.0)
        node_b.db_sync.sync_once(opener=opener_a)
        self.assertEqual(node_a.store.get('identity', 'id_lww')['player'], 'from_b_300')

        # Tombstone propagation: delete match and logout token on A -> B removes both without resurrecting
        del_m = ca.delete(f'/api/ui/autochess/matches/{mid}', headers={'Authorization': f'Bearer {tok_a}'})
        self.assertEqual(del_m.status_code, 200)
        out_res = ca.post('/api/ui/autochess/auth/logout', headers={'Authorization': f'Bearer {tok_a}'})
        self.assertEqual(out_res.status_code, 200)

        node_b.db_sync.sync_once(opener=opener_a)
        self.assertIsNone(node_b.store.get('autochess_match', mid))
        self.assertIsNone(node_b.store.get(KIND_TOKEN, tok_a))
        # Second sync must NOT resurrect deleted records
        node_b.db_sync.sync_once(opener=opener_a)
        self.assertIsNone(node_a.store.get('autochess_match', mid))
        self.assertIsNone(node_a.store.get(KIND_TOKEN, tok_a))

    def test_real_http_sync_and_debounced_local_write_push(self):
        node_a = self._new_node('http_a', token='tok-http')
        srv = make_server('127.0.0.1', 0, node_a.app, threaded=True)
        port = srv.server_port
        srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
        srv_thread.start()
        try:
            node_b = self._new_node(
                'http_b',
                token='tok-http',
                peer_url=f'http://127.0.0.1:{port}/api/ui',
                debounce_sec=0.15,
                interval_sec=0.0,
                auto_start=True,
            )
            cb = node_b.app.test_client()
            reg = cb.post(
                '/api/ui/autochess/auth/register',
                json={'username': 'http_push_user', 'password': 'pw_http_123'},
            )
            self.assertEqual(reg.status_code, 200, reg.get_data(as_text=True))

            deadline = time.time() + 4.0
            synced_acc = None
            while time.time() < deadline:
                synced_acc = node_a.store.get(KIND_ACCOUNT, 'http_push_user')
                if synced_acc is not None:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(synced_acc)

            # Manual trigger & status over real HTTP
            trig = cb.post('/api/ui/sync/trigger', json={'full': False}, headers={'X-Sync-Token': 'tok-http'})
            self.assertEqual(trig.status_code, 200, trig.get_data(as_text=True))
            self.assertTrue(trig.get_json()['ok'])

            st = cb.get('/api/ui/sync/status', headers={'X-Sync-Token': 'tok-http'})
            self.assertEqual(st.status_code, 200)
            data = st.get_json()
            self.assertTrue(data['has_synced'])
            self.assertIsNone(data['last_error'])
            self.assertEqual(data['peer_url'], f'http://127.0.0.1:{port}')
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == '__main__':
    unittest.main()
