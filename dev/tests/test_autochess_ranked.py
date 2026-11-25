import random
import secrets
import unittest

import autocombat_backend as backend
from autochess_ai import RANKED_AI_ARCHETYPES, generate_ranked_bots
import autochess_catalog as ac_cat
from autochess_match import AutoChessMatch
import autochess_ranked as rk


class AutoChessRankedTests(unittest.TestCase):
    def setUp(self):
        self.app = backend.app
        self.store = self.app.extensions['combat_ui']['store']
        self.ac_ui = self.app.extensions['combat_ui']['autochess']
        self.created_accounts = []
        self.created_matches = []

    def tearDown(self):
        for mid in self.created_matches:
            self.ac_ui.matches.pop(mid, None)
            self.ac_ui.versions.pop(mid, None)
            self.store.delete('autochess_match', mid)
        for acc_id in self.created_accounts:
            self.store.delete('autochess_account', acc_id)

    def _register(self, client, prefix, password='pw_ranked_123', display_name=None):
        uname = f'{prefix}_{secrets.token_hex(3)}'
        payload = {'username': uname, 'password': password}
        if display_name:
            payload['display_name'] = display_name
        r = client.post('/api/ui/autochess/auth/register', json=payload)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        acc = r.get_json()['account']
        self.created_accounts.append(acc['id'])
        return uname, acc

    def test_half_hs_ranked_saves_and_settlement_are_independent(self):
        api = '/api/ui/autochess'
        client = self.app.test_client()
        _, account = self._register(client, 'rk_half')
        raw = self.store.get('autochess_account', account['id'])
        raw.pop('ranked_half_hs')
        raw['ranked'].update(total_lp=380, coins=25)
        self.store.put('autochess_account', raw)

        matches = {}
        for ruleset in ('standard', 'half_hs'):
            result = client.post(f'{api}/ranked/matches', json={'ruleset': ruleset, 'seed': 7})
            self.assertEqual(result.status_code, 200)
            body = result.get_json()
            self.assertFalse(body['resumed'])
            self.assertEqual(body['match']['ruleset'], ruleset)
            matches[ruleset] = body['match']['id']
            self.created_matches.append(matches[ruleset])
            self.assertEqual(body['match']['ranked_tier'], 'silver' if ruleset == 'standard' else 'bronze')
        self.assertNotEqual(matches['standard'], matches['half_hs'])

        listing = client.get(f'{api}/matches').get_json()['matches']
        self.assertEqual({row['ruleset']: row['id'] for row in listing}, matches)
        for ruleset, mid in matches.items():
            body = client.post(f'{api}/ranked/matches', json={'ruleset': ruleset}).get_json()
            self.assertTrue(body['resumed'])
            self.assertEqual(body['match']['id'], mid)

        half_id = matches['half_hs']
        result = client.post(f'{api}/matches/{half_id}/action', json={'action': 'surrender'})
        self.assertEqual(result.status_code, 200)
        body = result.get_json()
        self.assertEqual(body['account']['ranked']['total_lp'], 380)
        self.assertEqual(body['account']['ranked']['games'], 0)
        self.assertEqual(body['account']['ranked_half_hs']['games'], 1)

        auth = self.ac_ui.auth
        _, duplicate = auth.record_ranked_result(account['id'], 1, match_id=half_id, ruleset='half_hs')
        self.assertIsNone(duplicate)
        updated, settlement = auth.record_ranked_result(account['id'], 1, match_id='second-half', ruleset='half_hs')
        self.assertGreater(settlement['coins_earned'], 0)
        self.assertEqual(updated['ranked']['coins'], 25 + settlement['coins_earned'])
        self.assertEqual(updated['ranked']['coins'], updated['ranked_half_hs']['coins'])

        for ruleset in matches:
            data = client.get(f'{api}/ranked/leaderboard?ruleset={ruleset}').get_json()
            self.assertEqual(data['ruleset'], ruleset)
            field = 'ranked_half_hs' if ruleset == 'half_hs' else 'ranked'
            self.assertEqual(data['my_entry']['total_lp'], updated[field]['total_lp'])
            self.assertEqual(data['my_entry']['coins'], updated['ranked']['coins'])
        half_catalog = client.get(f'{api}/catalog?ruleset=half_hs').get_json()
        self.assertEqual(half_catalog['ruleset'], 'half_hs')
        self.assertEqual(half_catalog['wiki_units']['Y16']['cost'], 4)

    def test_rank_divisions_lp_tables_silver_floor_shields_and_coins(self):
        # Tier and 100-LP division boundaries across all 6 tiers (Bronze 3, Silver 4, Gold 5, Plat 5, Diamond 5, King inf)
        expected = [
            (0, 'bronze', '青铜 III', 0, None),
            (99, 'bronze', '青铜 III', 99, None),
            (100, 'bronze', '青铜 II', 0, None),
            (299, 'bronze', '青铜 I', 99, None),
            (300, 'silver', '白银 IV', 0, None),
            (699, 'silver', '白银 I', 99, None),
            (700, 'gold', '黄金 V', 0, None),
            (1199, 'gold', '黄金 I', 99, None),
            (1200, 'platinum', '铂金 V', 0, None),
            (1699, 'platinum', '铂金 I', 99, None),
            (1700, 'diamond', '钻石 V', 0, None),
            (2199, 'diamond', '钻石 I', 99, None),
            (2200, 'king', '王者 1', 0, 1),
            (2299, 'king', '王者 1', 99, 1),
            (2300, 'king', '王者 2', 0, 2),
            (2550, 'king', '王者 4', 50, 4),
        ]
        for lp, tid, full_label, div_lp, k_lv in expected:
            d = rk.describe_rank(lp)
            self.assertEqual(d['tier_id'], tid)
            self.assertEqual(d['full_label'], full_label)
            self.assertEqual(d['division_lp'], div_lp)
            self.assertEqual(d['king_level'], k_lv)

        # Exact #1 and #8 LP table extremes for every tier
        base_lp_samples = {
            'bronze': (0, 100, 0),
            'silver': (350, 75, -25),
            'gold': (750, 50, -40),
            'platinum': (1250, 50, -50),
            'diamond': (1750, 35, -55),
            'king': (2250, 20, -60),
        }
        for tid, (start_lp, first_delta, eighth_delta) in base_lp_samples.items():
            p1, s1 = rk.settle_ranked_match({'total_lp': start_lp}, 1, match_id=f'{tid}_1')
            self.assertEqual(s1['base_delta'], first_delta)
            self.assertGreater(s1['coins_earned'], 0)
            p8, s8 = rk.settle_ranked_match({'total_lp': start_lp}, 8, match_id=f'{tid}_8')
            self.assertEqual(s8['base_delta'], eighth_delta)
            self.assertEqual(s8['coins_earned'], 0)
            self.assertEqual(p8['win_streak'], 0)

        # Win streak bonus & guaranteed shield card on 3-win streak
        prof = rk.default_ranked_profile()
        prof, st1 = rk.settle_ranked_match(prof, 1, match_id='w1', rng=random.Random(1))
        self.assertEqual(st1['streak_bonus'], 0)
        self.assertEqual(prof['win_streak'], 1)
        prof, st2 = rk.settle_ranked_match(prof, 2, match_id='w2', rng=random.Random(2))
        self.assertEqual(st2['streak_bonus'], 5)
        self.assertEqual(prof['win_streak'], 2)
        prof, st3 = rk.settle_ranked_match(prof, 3, match_id='w3', rng=random.Random(3))
        self.assertEqual(st3['streak_bonus'], 10)
        self.assertEqual(st3['shield_card_earned'], 1)
        self.assertEqual(prof['shield_cards'], 1)
        self.assertGreater(prof['coins'], 0)

        # Silver永不降青铜: at 300 LP with 2 shield cards, 8th place stays at 300 LP and NEVER consumes a shield card
        silver_floor_prof = {
            'total_lp': 300,
            'silver_floor_unlocked': True,
            'shield_cards': 2,
            'coins': 100,
        }
        sf_after, sf_settle = rk.settle_ranked_match(silver_floor_prof, 8, match_id='sf_lose')
        self.assertEqual(sf_after['total_lp'], 300)
        self.assertEqual(sf_settle['new_rank']['tier_id'], 'silver')
        self.assertTrue(sf_settle['silver_floor_triggered'])
        self.assertFalse(sf_settle['shield_card_used'])
        self.assertEqual(sf_after['shield_cards'], 2)
        self.assertEqual(sf_after['coins'], 100)  # coins never reduced on defeat

        # Shield card blocks division demotion cleanly when dropping across a 100-LP threshold
        gold_edge = {'total_lp': 805, 'silver_floor_unlocked': True, 'shield_cards': 1}
        ge_after, ge_settle = rk.settle_ranked_match(gold_edge, 8, match_id='g_demote')
        self.assertTrue(ge_settle['shield_card_used'])
        self.assertEqual(ge_after['total_lp'], 805)
        self.assertEqual(ge_after['shield_cards'], 0)
        self.assertFalse(ge_settle['demoted'])

    def test_ranked_8p_match_pool_and_distinct_ai_strategies(self):
        self.assertGreater(len(RANKED_AI_ARCHETYPES), 10)
        for t in rk.RANK_TIERS:
            bots = generate_ranked_bots(t['id'], count=7, rng=random.Random(77 + len(t['id'])))
            self.assertEqual(len(bots), 7)
            self.assertEqual(len({b['ai_profile']['archetype_id'] for b in bots}), 7)
            self.assertEqual(len({b['name'] for b in bots}), 7)

        m = AutoChessMatch(mode='ranked', ranked_tier='gold', seed=4242, player_name='排位棋手')
        self.assertEqual(len(m.commanders), 8)
        ai_cmds = [c for cid, c in m.commanders.items() if cid != 'P1']
        self.assertEqual(len(ai_cmds), 7)
        self.assertEqual(len({c['ai_profile']['archetype_id'] for c in ai_cmds}), 7)
        self.assertEqual(len({c['name'] for c in ai_cmds}), 7)

        # 8-player shared pool conservation
        expected_total = sum(ac_cat.POOL_COUNTS_8P[meta['cost']] for meta in ac_cat.UNIT_CATALOG.values())
        owned_copies = sum(
            3 ** (u['star'] - 1)
            for c in m.commanders.values() if not c.get('eliminated')
            for u in c['units']
        )
        self.assertEqual(owned_copies + sum(m.pool.values()), expected_total)

        # Serialization preserves ranked_tier & 8P pool_counts even after JSON roundtrip
        restored = AutoChessMatch.from_dict(self._json_roundtrip(m.to_dict()))
        self.assertEqual(restored.mode, 'ranked')
        self.assertEqual(restored.ranked_tier, 'gold')
        self.assertEqual(restored.pool_counts[1], ac_cat.POOL_COUNTS_8P[1])

    @staticmethod
    def _json_roundtrip(obj):
        import json
        return json.loads(json.dumps(obj, ensure_ascii=False))

    def test_ranked_login_gate_api_surrender_idempotency_and_leaderboard(self):
        guest = self.app.test_client()
        self.assertEqual(guest.post('/api/ui/session', json={'name': 'GuestNoRanked'}).status_code, 200)
        # Guest cannot start ranked mode (401)
        self.assertEqual(
            guest.post('/api/ui/autochess/ranked/matches', json={'arena_preset': 'autochess_standard'}).status_code,
            401,
        )
        self.assertEqual(
            guest.post('/api/ui/autochess/matches', json={'mode': 'ranked'}).status_code,
            401,
        )
        # Guest can still view public leaderboard
        lb_guest = guest.get('/api/ui/autochess/ranked/leaderboard')
        self.assertEqual(lb_guest.status_code, 200)
        self.assertIsNone(lb_guest.get_json()['my_rank'])

        c1 = self.app.test_client()
        c2 = self.app.test_client()
        _, acc1 = self._register(c1, 'rk1', display_name='天梯一号')
        _, acc2 = self._register(c2, 'rk2', display_name='天梯二号')

        # Seed acc2 higher in DB to test leaderboard sorting
        raw2 = self.store.get('autochess_account', acc2['id'])
        raw2['ranked']['total_lp'] = 1280
        raw2['ranked']['silver_floor_unlocked'] = True
        raw2['ranked']['wins'] = 6
        raw2['ranked']['games'] = 8
        raw2['ranked']['coins'] = 420
        self.store.put('autochess_account', raw2)

        # Create ranked 8p match for c1
        r_cr = c1.post('/api/ui/autochess/ranked/matches', json={'arena_preset': 'autochess_standard'})
        self.assertEqual(r_cr.status_code, 200, r_cr.get_data(as_text=True))
        d_cr = r_cr.get_json()
        mid = d_cr['match']['id']
        self.created_matches.append(mid)
        self.assertFalse(d_cr['resumed'])
        self.assertEqual(d_cr['match']['mode'], 'ranked')
        self.assertEqual(len(d_cr['match']['commanders']), 8)

        # Creating again while unfinished resumes the active ranked match
        r_resume = c1.post('/api/ui/autochess/ranked/matches', json={'arena_preset': 'autochess_compact'})
        self.assertEqual(r_resume.status_code, 200)
        self.assertTrue(r_resume.get_json()['resumed'])
        self.assertEqual(r_resume.get_json()['match']['id'], mid)

        # Unfinished ranked match cannot be silently deleted
        self.assertEqual(c1.delete(f'/api/ui/autochess/matches/{mid}').status_code, 400)

        # Play 1 combat round to verify 8P round resolution works end-to-end
        act_st = c1.post(f'/api/ui/autochess/matches/{mid}/action', json={'action': 'resolve_combat'})
        self.assertEqual(act_st.status_code, 200)
        self.assertTrue(act_st.get_json()['ok'])

        # Surrender settles cleanly & idempotently
        sur = c1.post(f'/api/ui/autochess/matches/{mid}/action', json={'action': 'surrender'})
        self.assertEqual(sur.status_code, 200)
        sur_j = sur.get_json()
        self.assertTrue(sur_j['ok'])
        self.assertEqual(sur_j['match']['phase'], 'finished')
        self.assertIsNotNone(sur_j.get('ranked_settlement'))
        self.assertEqual(sur_j['account']['ranked']['games'], 1)

        # Repeating action on finished match never double-settles LP
        _, duplicate_settlement = self.ac_ui.auth.record_ranked_result(acc1['id'], 1, match_id=mid)
        self.assertIsNone(duplicate_settlement)

        # Finished ranked match can now be deleted if desired
        self.assertEqual(c1.delete(f'/api/ui/autochess/matches/{mid}').status_code, 200)

        # Global leaderboard includes both accounts in sorted LP order and tier filter works
        lb_all = c1.get('/api/ui/autochess/ranked/leaderboard').get_json()
        ids = [e['account_id'] for e in lb_all['entries']]
        self.assertIn(acc1['id'], ids)
        self.assertIn(acc2['id'], ids)
        self.assertLess(ids.index(acc2['id']), ids.index(acc1['id']))
        self.assertEqual(lb_all['my_entry']['account_id'], acc1['id'])

        lb_plat = c1.get('/api/ui/autochess/ranked/leaderboard?tier=platinum').get_json()
        self.assertIn(acc2['id'], [e['account_id'] for e in lb_plat['entries']])
        self.assertNotIn(acc1['id'], [e['account_id'] for e in lb_plat['entries']])


if __name__ == '__main__':
    unittest.main()
