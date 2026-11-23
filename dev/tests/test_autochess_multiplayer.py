import secrets
import unittest

import autocombat_backend as backend
from autochess_auth import AuthError, validate_token_url


class AutoChessMultiplayerTests(unittest.TestCase):
    def setUp(self):
        self.app = backend.app
        self.store = self.app.extensions['combat_ui']['store']
        self.ac_ui = self.app.extensions['combat_ui']['autochess']
        self.created_accounts = []
        self.created_matches = []
        self.created_rooms = []

    def tearDown(self):
        for code in self.created_rooms:
            self.ac_ui.rooms.pop(code, None)
            self.ac_ui.room_matches.pop(code, None)
            self.ac_ui.room_versions.pop(code, None)
            self.store.delete('autochess_room', code)
        for mid in self.created_matches:
            self.ac_ui.matches.pop(mid, None)
            self.ac_ui.versions.pop(mid, None)
            self.store.delete('autochess_match', mid)
        for acc_id in self.created_accounts:
            self.store.delete('autochess_account', acc_id)

    def _register(self, client, prefix, password='pw_secret_123', display_name=None):
        uname = f'{prefix}_{secrets.token_hex(3)}'
        payload = {'username': uname, 'password': password}
        if display_name:
            payload['display_name'] = display_name
        r = client.post('/api/ui/autochess/auth/register', json=payload)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.created_accounts.append(data['account']['id'])
        return uname, data['account']

    def test_account_security_and_token_url_validation(self):
        # URL whitelist checks
        self.assertEqual(validate_token_url('/ui/icons/flame.svg'), '/ui/icons/flame.svg')
        self.assertEqual(validate_token_url('https://example.com/avatar.png'), 'https://example.com/avatar.png')
        self.assertEqual(
            validate_token_url('data:image/png;base64,iVBORw0KGgo='),
            'data:image/png;base64,iVBORw0KGgo=',
        )
        for bad in (
            'javascript:alert(1)',
            'file:///etc/passwd',
            'ftp://example.com/a.png',
            'data:image/svg+xml;base64,PHN2Zz4=',
            'data:image/png;base64,' + ('A' * 250_000),
        ):
            with self.assertRaises(AuthError):
                validate_token_url(bad)

        c1 = self.app.test_client()
        # Reject invalid inputs cleanly
        self.assertEqual(
            c1.post('/api/ui/autochess/auth/register', json={'username': 'ab', 'password': '123456'}).status_code,
            400,
        )
        self.assertEqual(
            c1.post('/api/ui/autochess/auth/register', json={'username': 'validuser', 'password': '123'}).status_code,
            400,
        )

        uname, acc = self._register(c1, 'sec', 'initial_pw1', display_name='安全官')
        raw_text = repr(acc)
        self.assertNotIn('password_hash', raw_text)
        self.assertNotIn('salt', raw_text)

        # Stored DB row uses salted pbkdf2_sha256, never plaintext
        raw_doc = self.store.get('autochess_account', acc['id'])
        self.assertEqual(len(raw_doc.get('password_salt', '')), 32)
        self.assertEqual(len(raw_doc.get('password_hash', '')), 64)
        self.assertNotIn('initial_pw1', raw_doc['password_hash'])

        # Profile update + password change + wrong password rejection
        upd = c1.post(
            '/api/ui/autochess/auth/profile',
            json={'display_name': '新昵称', 'old_password': 'initial_pw1', 'new_password': 'new_pw_789'},
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.get_json()['account']['display_name'], '新昵称')

        self.assertEqual(c1.post('/api/ui/autochess/auth/logout', json={}).status_code, 200)
        self.assertFalse(c1.get('/api/ui/autochess/auth/me').get_json()['authenticated'])

        # Old password fails, new password succeeds
        self.assertEqual(
            c1.post('/api/ui/autochess/auth/login', json={'username': uname, 'password': 'initial_pw1'}).status_code,
            401,
        )
        self.assertEqual(
            c1.post('/api/ui/autochess/auth/login', json={'username': uname, 'password': 'new_pw_789'}).status_code,
            200,
        )

    def test_cross_client_account_sync_and_guest_permissions(self):
        guest = self.app.test_client()
        self.assertEqual(guest.post('/api/ui/session', json={'name': 'GuestTester'}).status_code, 200)

        # Guest PvE modes succeed
        for pve_mode in ('pve12', 'lobby4'):
            r = guest.post('/api/ui/autochess/matches', json={'mode': pve_mode})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            mid = r.get_json()['match']['id']
            self.created_matches.append(mid)
            act = guest.post(f'/api/ui/autochess/matches/{mid}/action', json={'action': 'buy', 'slot_index': 0})
            self.assertEqual(act.status_code, 200)

        # Guest PvP room actions are denied with 401
        self.assertEqual(guest.get('/api/ui/autochess/rooms').status_code, 401)
        self.assertEqual(guest.post('/api/ui/autochess/rooms', json={'name': 'NoAuth'}).status_code, 401)
        self.assertEqual(guest.post('/api/ui/autochess/rooms/ABCDEF/join').status_code, 401)

        # Cross-client sync on the same account
        client_a = self.app.test_client()
        client_b = self.app.test_client()
        uname, _ = self._register(client_a, 'sync', 'pw_sync_123', display_name='云同步号')

        tok = client_a.post('/api/ui/autochess/tokens/Y1', json={'token_url': '/ui/icons/star.svg'})
        self.assertEqual(tok.status_code, 200)
        self.assertEqual(tok.get_json()['account']['token_overrides']['Y1'], '/ui/icons/star.svg')

        m_resp = client_a.post('/api/ui/autochess/matches', json={'mode': 'pve12', 'arena_preset': 'autochess_compact'})
        self.assertEqual(m_resp.status_code, 200)
        mid_sync = m_resp.get_json()['match']['id']
        self.created_matches.append(mid_sync)

        # Separate client logs in and accesses identical token + PvE save in SQLite
        self.assertEqual(
            client_b.post('/api/ui/autochess/auth/login', json={'username': uname, 'password': 'pw_sync_123'}).status_code,
            200,
        )
        me_b = client_b.get('/api/ui/autochess/auth/me').get_json()['account']
        self.assertEqual(me_b['token_overrides'].get('Y1'), '/ui/icons/star.svg')

        b_matches = [m['id'] for m in client_b.get('/api/ui/autochess/matches').get_json()['matches']]
        self.assertIn(mid_sync, b_matches)
        b_load = client_b.get(f'/api/ui/autochess/matches/{mid_sync}')
        self.assertEqual(b_load.status_code, 200)
        self.assertEqual(b_load.get_json()['match']['id'], mid_sync)

    def test_multiplayer_pvp_room_lifecycle_mirroring_and_vfx(self):
        c1 = self.app.test_client()
        c2 = self.app.test_client()
        c3 = self.app.test_client()

        _, acc1 = self._register(c1, 'p1', 'pw_room_111', display_name='玩家一')
        u2, acc2 = self._register(c2, 'p2', 'pw_room_222', display_name='玩家二')

        # Customize distinct tokens per account
        self.assertEqual(c1.post('/api/ui/autochess/tokens/Y1', json={'token_url': '/ui/icons/star.svg'}).status_code, 200)
        self.assertEqual(c2.post('/api/ui/autochess/tokens/Y2', json={'token_url': '/ui/icons/snow.svg'}).status_code, 200)

        # Create 2-player PvP room (fill_bots=False, auto_step=False for deterministic stepping)
        r_create = c1.post(
            '/api/ui/autochess/rooms',
            json={
                'name': '联机测试桌',
                'arena_preset': 'autochess_standard',
                'max_players': 2,
                'fill_bots': False,
                'prep_duration': 45,
                'auto_step': False,
            },
        )
        self.assertEqual(r_create.status_code, 200, r_create.get_data(as_text=True))
        room = r_create.get_json()['room']
        code = room['code']
        self.created_rooms.append(code)
        self.assertEqual(len(code), 6)
        self.assertTrue(any(f'?room={code}' in url for url in room['invite_urls']))

        # c2 sees waiting room in list, joins, toggles ready, c1 starts
        listed = c2.get('/api/ui/autochess/rooms').get_json()['rooms']
        self.assertTrue(any(item['code'] == code for item in listed))
        r_join = c2.post(f'/api/ui/autochess/rooms/{code}/join')
        self.assertEqual(r_join.status_code, 200)
        self.assertEqual(len(r_join.get_json()['room']['members']), 2)

        self.assertEqual(c2.post(f'/api/ui/autochess/rooms/{code}/control', json={'op': 'ready', 'ready': True}).status_code, 200)
        r_start = c1.post(f'/api/ui/autochess/rooms/{code}/control', json={'op': 'start'})
        self.assertEqual(r_start.status_code, 200, r_start.get_data(as_text=True))
        started = r_start.get_json()['room']
        self.assertEqual(started['status'], 'playing')
        self.assertIsNotNone(started['match'])

        # Both players buy 1 affordable shop card & ready_combat
        for cli in (c1, c2):
            cur_rm = cli.get(f'/api/ui/autochess/rooms/{code}').get_json()['room']['match']
            affordable = next(
                i
                for i, sl in enumerate(cur_rm['player']['shop'])
                if sl and not sl['bought'] and sl['cost'] <= cur_rm['player']['gold']
            )
            r_buy = cli.post(f'/api/ui/autochess/rooms/{code}/action', json={'action': 'buy', 'slot_index': affordable})
            self.assertTrue(r_buy.get_json()['ok'], r_buy.get_json())
            r_ready = cli.post(f'/api/ui/autochess/rooms/{code}/action', json={'action': 'ready_combat', 'ready': True})
            self.assertTrue(r_ready.get_json()['ok'], r_ready.get_json())

        rm1 = c1.get(f'/api/ui/autochess/rooms/{code}').get_json()['room']['match']
        rm2 = c2.get(f'/api/ui/autochess/rooms/{code}').get_json()['room']['match']
        self.assertEqual(rm1['phase'], 'combat')
        self.assertEqual(rm2['phase'], 'combat')
        self.assertEqual(rm1['opponent_name'], '玩家二')
        self.assertEqual(rm2['opponent_name'], '玩家一')

        # Mirrored perspectives: friendly 'Y' is always left columns (<= E), enemy 'X' is right (>= E)
        for view in (rm1, rm2):
            snap = view['live_snapshot']
            y_cols = [u['coord'][0] for u in snap['units'] if u['team'] == 'Y' and u.get('coord')]
            x_cols = [u['coord'][0] for u in snap['units'] if u['team'] == 'X' and u.get('coord')]
            self.assertTrue(y_cols and all(col <= 'E' for col in y_cols), y_cols)
            self.assertTrue(x_cols and all(col >= 'E' for col in x_cols), x_cols)

        # Opponents' custom tokens propagate cleanly in bout_token_overrides
        self.assertEqual(rm1['bout_token_overrides']['Y'].get('Y1'), '/ui/icons/star.svg')
        self.assertEqual(rm1['bout_token_overrides']['X'].get('Y2'), '/ui/icons/snow.svg')
        self.assertEqual(rm2['bout_token_overrides']['Y'].get('Y2'), '/ui/icons/snow.svg')
        self.assertEqual(rm2['bout_token_overrides']['X'].get('Y1'), '/ui/icons/star.svg')

        # Step combat & verify vfx_events + resolve round + next round
        saw_vfx = False
        for _ in range(25):
            r_step = c1.post(f'/api/ui/autochess/rooms/{code}/action', json={'action': 'step_combat', 'steps': 2}).get_json()
            for fr in r_step['room']['match']['combat_frames']:
                if fr.get('vfx_events'):
                    saw_vfx = True
            if r_step['room']['match']['phase'] != 'combat':
                break
        self.assertTrue(saw_vfx, 'Expected non-empty vfx_events in combat frames')

        cur_phase = c1.get(f'/api/ui/autochess/rooms/{code}').get_json()['room']['match']['phase']
        if cur_phase == 'combat':
            r_res = c1.post(f'/api/ui/autochess/rooms/{code}/action', json={'action': 'resolve_combat'}).get_json()
            cur_phase = r_res['room']['match']['phase']
        self.assertIn(cur_phase, ('round_result', 'finished'))

        if cur_phase == 'round_result':
            self.assertTrue(
                c1.post(f'/api/ui/autochess/rooms/{code}/action', json={'action': 'ready_next', 'ready': True}).get_json()['ok']
            )
            r_n2 = c2.post(f'/api/ui/autochess/rooms/{code}/action', json={'action': 'ready_next', 'ready': True}).get_json()
            self.assertTrue(r_n2['ok'])
            self.assertEqual(r_n2['room']['match']['phase'], 'prep')
            self.assertEqual(r_n2['room']['match']['round_num'], 2)

        # Spectate param & cross-client reconnect for Player 2
        self.assertEqual(c3.post('/api/ui/autochess/auth/login', json={'username': u2, 'password': 'pw_room_222'}).status_code, 200)
        reconn = c3.post(f'/api/ui/autochess/rooms/{code}/join')
        self.assertEqual(reconn.status_code, 200)
        self.assertEqual(reconn.get_json()['room']['my_account_id'], acc2['id'])
        self.assertEqual(reconn.get_json()['room']['match']['round_num'], 2)
        p1_cid = rm1['player']['id']
        spec_view = c3.get(f'/api/ui/autochess/rooms/{code}?spectate={p1_cid}').get_json()['room']['match']
        self.assertEqual(spec_view['watching_cid'], p1_cid)
        self.assertNotEqual(p1_cid, acc1['id'])


if __name__ == '__main__':
    unittest.main()
