import os
import secrets
import threading
import time
import unittest
from unittest import mock

import autocombat_backend as backend


class MiniGameBackendApiTests(unittest.TestCase):
    def setUp(self):
        self.app = backend.app
        self.store = self.app.extensions['combat_ui']['store']
        self.ac_ui = self.app.extensions['combat_ui']['autochess']
        self.rooms = self.app.extensions['combat_ui']['rooms']
        self.created_accounts = []
        self.created_wx_binds = []
        self.created_matches = []
        self.created_rooms = []
        self.created_classic_rooms = []

    def tearDown(self):
        for code in self.created_classic_rooms:
            self.rooms.pop(code, None)
        for code in self.created_rooms:
            self.ac_ui.rooms.pop(code, None)
            self.ac_ui.room_matches.pop(code, None)
            self.ac_ui.room_versions.pop(code, None)
            self.store.delete('autochess_room', code)
        for mid in self.created_matches:
            self.ac_ui.matches.pop(mid, None)
            self.ac_ui.versions.pop(mid, None)
            self.store.delete('autochess_match', mid)
        for openid in self.created_wx_binds:
            self.store.delete('autochess_wx_bind', openid)
        for acc_id in self.created_accounts:
            self.store.delete('autochess_account', acc_id)

    def test_header_session_and_origin_policy(self):
        c1 = self.app.test_client()
        # Third-party browser origin is still rejected
        bad = c1.post(
            '/api/ui/session',
            json={'name': '非法来源'},
            headers={'Origin': 'https://evil.example.com'},
        )
        self.assertEqual(bad.status_code, 403)

        # WeChat Mini Game/Program origin is accepted and returns session_token
        ok = c1.post(
            '/api/ui/session',
            json={'name': '微信棋手'},
            headers={'Origin': 'https://servicewechat.com/wxcf8c456e7ecdd0f7/devtools/page-frame.html'},
        )
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        token = ok.get_json()['session_token']
        self.assertTrue(token)

        # Separate cookie-less test client authenticates via X-Combat-Session header
        c2 = self.app.test_client()
        room_res = c2.post(
            '/api/ui/rooms',
            json={'team_a': ['Y4'], 'team_b': ['Y1'], 'map_size': '8x8', 'local': True},
            headers={'X-Combat-Session': token},
        )
        self.assertEqual(room_res.status_code, 200, room_res.get_data(as_text=True))
        code = room_res.get_json()['code']
        self.created_classic_rooms.append(code)

        # Timeout poll returns cleanly with reset=False and events=[]
        p0 = c2.get(
            f'/api/ui/rooms/{code}/poll?after=1&timeout=0.05',
            headers={'X-Combat-Session': token},
        )
        self.assertEqual(p0.status_code, 200)
        self.assertEqual(p0.get_json()['events'], [])
        self.assertFalse(p0.get_json()['reset'])

        # Poll wakes up immediately on room control mutation
        def trigger_control():
            time.sleep(0.08)
            c_bg = self.app.test_client()
            c_bg.post(
                f'/api/ui/rooms/{code}/control',
                json={'op': 'speed', 'speed': 2},
                headers={'X-Combat-Session': token},
            )

        t = threading.Thread(target=trigger_control)
        t.start()
        p1 = c2.get(
            f'/api/ui/rooms/{code}/poll?after=1&timeout=2.0',
            headers={'X-Combat-Session': token},
        )
        t.join(timeout=3)
        self.assertEqual(p1.status_code, 200)
        self.assertGreaterEqual(len(p1.get_json()['events']), 1)

    def test_cookieless_bearer_auth_and_match_poll(self):
        c_reg = self.app.test_client()
        uname = f'mg_{secrets.token_hex(3)}'
        reg = c_reg.post(
            '/api/ui/autochess/auth/register',
            json={'username': uname, 'password': 'pw_secret_123', 'display_name': '云棋手'},
        )
        self.assertEqual(reg.status_code, 200, reg.get_data(as_text=True))
        reg_data = reg.get_json()
        acc_id = reg_data['account']['id']
        tok = reg_data['auth_token']
        self.created_accounts.append(acc_id)
        self.assertTrue(tok)

        # Fresh client without cookies authenticates via Bearer token
        c_api = self.app.test_client()
        me = c_api.get('/api/ui/autochess/auth/me', headers={'Authorization': f'Bearer {tok}'})
        self.assertTrue(me.get_json()['authenticated'])
        self.assertEqual(me.get_json()['account']['id'], acc_id)

        # Create match & verify match_poll timeout + wake-up
        m_res = c_api.post(
            '/api/ui/autochess/matches',
            json={'mode': 'pve12', 'arena_preset': 'autochess_standard'},
            headers={'Authorization': f'Bearer {tok}'},
        )
        self.assertEqual(m_res.status_code, 200)
        mid = m_res.get_json()['match']['id']
        self.created_matches.append(mid)

        first = c_api.get(
            f'/api/ui/autochess/matches/{mid}/poll?since=-1&timeout=0.05',
            headers={'X-AutoChess-Auth': tok},
        )
        self.assertEqual(first.status_code, 200)
        v1 = first.get_json()['version']
        self.assertTrue(first.get_json()['changed'])

        idle = c_api.get(
            f'/api/ui/autochess/matches/{mid}/poll?since={v1}&timeout=0.05',
            headers={'X-AutoChess-Auth': tok},
        )
        self.assertFalse(idle.get_json()['changed'])
        self.assertIsNone(idle.get_json()['match'])

        def mutate_match():
            time.sleep(0.08)
            c_bg = self.app.test_client()
            c_bg.post(
                f'/api/ui/autochess/matches/{mid}/action',
                json={'action': 'reroll'},
                headers={'Authorization': f'Bearer {tok}'},
            )

        t = threading.Thread(target=mutate_match)
        t.start()
        woke = c_api.get(
            f'/api/ui/autochess/matches/{mid}/poll?since={v1}&timeout=2.0',
            headers={'Authorization': f'Bearer {tok}'},
        )
        t.join(timeout=3)
        self.assertTrue(woke.get_json()['changed'])
        self.assertGreater(woke.get_json()['version'], v1)

        # Logout via Bearer invalidates token
        self.assertEqual(
            c_api.post('/api/ui/autochess/auth/logout', json={}, headers={'Authorization': f'Bearer {tok}'}).status_code,
            200,
        )
        self.assertFalse(
            c_api.get('/api/ui/autochess/auth/me', headers={'Authorization': f'Bearer {tok}'}).get_json()['authenticated']
        )

    def test_wechat_cloud_login_bind_and_room_poll(self):
        openid = 'ox_cloud_' + secrets.token_hex(6)
        self.created_wx_binds.append(openid)

        c_wx = self.app.test_client()
        # Reject X-WX-OPENID spoofing when AUTOCOMBAT_TRUST_WX_CLOUD_HEADERS is unset
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AUTOCOMBAT_TRUST_WX_CLOUD_HEADERS', None)
            denied = c_wx.post(
                '/api/ui/autochess/auth/wechat',
                json={},
                headers={'X-WX-OPENID': openid},
            )
            self.assertEqual(denied.status_code, 400)

        # CloudRun trusted header creates auto-account on first call, reuses on second
        with mock.patch.dict(os.environ, {'AUTOCOMBAT_TRUST_WX_CLOUD_HEADERS': '1'}):
            r1 = c_wx.post(
                '/api/ui/autochess/auth/wechat',
                json={'display_name': '星月微信号'},
                headers={'X-WX-OPENID': openid},
            )
            self.assertEqual(r1.status_code, 200, r1.get_data(as_text=True))
            d1 = r1.get_json()
            self.assertTrue(d1['created'])
            self.assertTrue(d1['account']['wx_bound'])
            auto_id = d1['account']['id']
            self.created_accounts.append(auto_id)

            r2 = c_wx.post(
                '/api/ui/autochess/auth/wechat',
                json={},
                headers={'X-WX-OPENID': openid},
            )
            self.assertEqual(r2.status_code, 200)
            self.assertFalse(r2.get_json()['created'])
            self.assertEqual(r2.get_json()['account']['id'], auto_id)

            # Register a regular web account and bind the openid to it
            c_web = self.app.test_client()
            uname = f'web_{secrets.token_hex(3)}'
            reg = c_web.post(
                '/api/ui/autochess/auth/register',
                json={'username': uname, 'password': 'web_pw_123', 'display_name': '老玩家'},
            )
            self.assertEqual(reg.status_code, 200)
            web_id = reg.get_json()['account']['id']
            self.created_accounts.append(web_id)

            # Wrong password rejected
            bad_bind = c_wx.post(
                '/api/ui/autochess/auth/wechat/bind',
                json={'username': uname, 'password': 'wrong_password'},
                headers={'X-WX-OPENID': openid},
            )
            self.assertEqual(bad_bind.status_code, 401)

            # Valid password seamlessly rebinds 0-game auto account's openid to web_id
            ok_bind = c_wx.post(
                '/api/ui/autochess/auth/wechat/bind',
                json={'username': uname, 'password': 'web_pw_123'},
                headers={'X-WX-OPENID': openid},
            )
            self.assertEqual(ok_bind.status_code, 200, ok_bind.get_data(as_text=True))
            bind_data = ok_bind.get_json()
            self.assertEqual(bind_data['account']['id'], web_id)
            self.assertTrue(bind_data['account']['wx_bound'])
            wx_tok = bind_data['auth_token']

        # Create room with Bearer token and verify room_poll
        c_room = self.app.test_client()
        rm = c_room.post(
            '/api/ui/autochess/rooms',
            json={'arena_preset': 'autochess_standard', 'max_players': 4, 'fill_bots': True},
            headers={'Authorization': f'Bearer {wx_tok}'},
        )
        self.assertEqual(rm.status_code, 200, rm.get_data(as_text=True))
        code = rm.get_json()['room']['code']
        self.created_rooms.append(code)

        rp0 = c_room.get(
            f'/api/ui/autochess/rooms/{code}/poll?since=-1&timeout=0.05',
            headers={'Authorization': f'Bearer {wx_tok}'},
        )
        self.assertEqual(rp0.status_code, 200)
        v_room = rp0.get_json()['version']
        self.assertTrue(rp0.get_json()['changed'])

        def update_room():
            time.sleep(0.08)
            c_bg = self.app.test_client()
            c_bg.post(
                f'/api/ui/autochess/rooms/{code}/control',
                json={'op': 'config', 'prep_duration': 45},
                headers={'Authorization': f'Bearer {wx_tok}'},
            )

        t = threading.Thread(target=update_room)
        t.start()
        rp1 = c_room.get(
            f'/api/ui/autochess/rooms/{code}/poll?since={v_room}&timeout=2.0',
            headers={'Authorization': f'Bearer {wx_tok}'},
        )
        t.join(timeout=3)
        self.assertTrue(rp1.get_json()['changed'])
        self.assertEqual(rp1.get_json()['room']['prep_duration'], 45)
