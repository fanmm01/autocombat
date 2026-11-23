import copy
import unittest

import autochess_catalog as ac_cat
from autochess_match import AutoChessMatch
import battle_engine as be
import battle_http_server as backend
import characters_data as cd
import combat_defaults


class AutoChessModeTests(unittest.TestCase):
    def test_bench_capacity_by_level_and_augment(self):
        match = AutoChessMatch(seed=19)
        cid = match.player_id
        cmd = match.commanders[cid]
        for level, slots in enumerate((6, 6, 8, 8, 10, 10), start=1):
            cmd['level'] = level
            cmd['augments'] = []
            self.assertEqual(match.bench_capacity(cid), slots)
            cmd['pending_augments'] = [next(a for a in ac_cat.AUGMENTS if a['id'] == 'aug_reserves')]
            self.assertTrue(match.pick_augment(cid, 'aug_reserves')[0])
            restored = AutoChessMatch.from_dict(match.to_dict())
            self.assertEqual(restored.to_public_dict()['player']['bench_capacity'], slots + 2)
            match.round_num = 8
            match._offer_augments_if_due()
            self.assertNotIn('aug_reserves', [a['id'] for a in cmd['pending_augments']])

        cmd['level'] = 5
        cmd['gold'] = 4
        cmd['xp'] = ac_cat.LEVEL_TABLE[5]['xp_to_next'] - 4
        self.assertTrue(match.buy_xp(cid))
        self.assertEqual(cmd['level'], 6)
        self.assertEqual(match.max_pop(cid), 7)

    def test_round_twelve_offers_third_augment(self):
        match = AutoChessMatch(mode='pve12', seed=12)
        cid = match.player_id
        cmd = match.commanders[cid]
        for round_num in range(2, 13):
            match.phase = 'round_result'
            self.assertTrue(match.next_round()[0])
            choices = cmd['pending_augments']
            if round_num in (4, 8, 12):
                self.assertEqual(len(choices), 3)
                self.assertTrue(all(a['id'] not in cmd['augments'] for a in choices))
                self.assertTrue(match.pick_augment(cid, choices[0]['id'])[0])
            else:
                self.assertFalse(choices)
        self.assertEqual(len(cmd['augments']), 3)

    def test_classic_mode_invariants_and_main_action_formula_preserved(self):
        self.assertEqual(cd.GLOBAL_RANGE_OVERRIDE, 1)
        self.assertEqual(combat_defaults.DEFAULTS['DEFAULT_MAP_SIZE'], '10x10')
        self.assertNotIn('Y60', ac_cat.UNIT_CATALOG)
        self.assertEqual(len(ac_cat.UNIT_CATALOG), 17)

        for cls in (be.FullBattleEngine, be.FastBattleEngine):
            eng = cls()
            self.assertFalse(eng.autochess_mode)
            cd.load_character_to_engine(eng, copy.deepcopy(ac_cat.CHAR_DATA_BY_SERIAL['Y1']), 'u1')
            cd.load_character_to_engine(eng, copy.deepcopy(ac_cat.CHAR_DATA_BY_SERIAL['Y2']), 'u2')
            eng.setup_battle(['u1'], ['u2'])
            # Classic global range override still returns 99
            self.assertEqual(eng._get_attack_range(skill_name='斗殴', uid='u1'), 99)

            # Main action count formula remains untouched in both classic and autochess modes
            for mov in (0, 3, 8, 9, 13, 14, 18, 24):
                eng.get_char('u1').set_attr('行动力', mov)
                eng.autochess_mode = False
                classic_acts = eng._calc_main_actions('u1')
                classic_move = eng._get_move_power('u1')
                eng.autochess_mode = True
                ac_acts = eng._calc_main_actions('u1')
                ac_move = eng._get_move_power('u1')
                self.assertEqual(classic_acts, ac_acts)
                self.assertEqual(classic_move, mov)
                if mov <= 0:
                    self.assertEqual(ac_move, 0)
                else:
                    self.assertGreaterEqual(ac_move, 2)
                    self.assertLessEqual(ac_move, 8)

    def test_spatial_cover_leyline_flying_dive_and_anchor_retention(self):
        eng = be.FullBattleEngine()
        cd.load_character_to_engine(eng, copy.deepcopy(ac_cat.CHAR_DATA_BY_SERIAL['Y5']), 'Y_fly')
        cd.load_character_to_engine(eng, copy.deepcopy(ac_cat.CHAR_DATA_BY_SERIAL['Y4']), 'X_rng')
        eng.setup_battle(
            ['Y_fly'], ['X_rng'],
            arena_preset='autochess_citadel',
            autochess_mode=True,
            initial_coords={'Y_fly': 'F5', 'X_rng': 'G2'},  # Y_fly on leyline, X_rng on cover (dist=3)
        )
        # No anchor bounce back on turn end in autochess mode
        eng._unit_il_entry('Y_fly', eng._get_initiative())['_anchor_coord'] = 'B2'
        eng._return_to_anchor('Y_fly')
        self.assertEqual(eng._unit_il_entry('Y_fly', eng._get_initiative())['coord'], 'F5')

        # Cover reduces ranged dmg (>=3 tiles) by 15%
        self.assertEqual(eng._apply_autochess_damage_mods('Y_fly', 'X_rng', 20), 17)

        # Flying dive removes melee penalty die in autochess mode until cleared
        eng.get_char('Y_fly').hs_transformed = True
        self.assertEqual(eng._can_melee('X_rng', 'Y_fly'), (True, True))
        eng._mark_flying_dive('Y_fly', 1)
        self.assertEqual(eng._can_melee('X_rng', 'Y_fly'), (True, False))
        eng._clear_flying_dive('Y_fly')
        self.assertEqual(eng._can_melee('X_rng', 'Y_fly'), (True, True))

    def test_pool_conservation_recursive_star_up_augments_and_serialization(self):
        m = AutoChessMatch(mode='lobby4', arena_preset='autochess_standard', seed=31415, player_name='棋手')
        initial_total = sum(ac_cat.POOL_COUNTS[meta['cost']] for meta in ac_cat.UNIT_CATALOG.values())

        def _check_pool():
            owned = sum(
                3 ** (u['star'] - 1)
                for c in m.commanders.values() if not c.get('eliminated')
                for u in c['units']
            )
            self.assertEqual(owned + sum(m.pool.values()), initial_total)

        _check_pool()
        m.commanders['P1']['gold'] = 100
        s = m.commanders['P1']['shop'][0]['serial']
        # Buy 9 copies -> recursive 1★ -> 2★ -> 3★
        for _ in range(9):
            m.commanders['P1']['shop'][0] = {'serial': s, 'bought': False}
            ok, msg = m.buy_unit('P1', 0)
            self.assertTrue(ok, msg)
        stars = [u['star'] for u in m.commanders['P1']['units'] if u['serial'] == s]
        self.assertIn(3, stars)
        _check_pool()

        # Roundtrip serialization
        restored = AutoChessMatch.from_dict(m.to_dict())
        self.assertEqual(restored.round_num, 1)
        self.assertEqual(sum(restored.pool.values()), sum(m.pool.values()))

    def test_flask_autochess_api_lifecycle(self):
        client = backend.app.test_client()
        sresp = client.post('/api/ui/session', json={'name': 'ac-unit'})
        self.assertEqual(sresp.status_code, 200)
        cat = client.get('/api/ui/autochess/catalog').get_json()
        self.assertEqual(len(cat['units']), 17)
        self.assertEqual(len(cat['available_emblems']), 17)
        for u in cat['units']:
            self.assertTrue(u.get('emblem_url', '').startswith('/ui/icons/'), u)
            self.assertTrue(u.get('accent', '').startswith('#'), u)
        self.assertEqual(len(cat['synergies']), 8)
        self.assertEqual(len(cat['augments']), 15)
        self.assertEqual(len(cat['wiki_units']), 17)
        self.assertNotIn('Y60', cat['wiki_units'])
        self.assertIn('2', cat['wiki_units']['Y1']['star_stats'])
        self.assertEqual(cat['wiki_units']['Y14']['skills'][0]['cooldown'], 3)
        for serial, w in cat['wiki_units'].items():
            for sp in w['skills']:
                if sp['range'] is not None:
                    self.assertLess(sp['range'], 90, (serial, sp))

        cr = client.post('/api/ui/autochess/matches', json={'mode': 'pve12', 'arena_preset': 'autochess_citadel'})
        self.assertEqual(cr.status_code, 200)
        mid = cr.get_json()['match']['id']
        for action, payload in (
            ('buy', {'slot_index': 0}),
            ('auto_arrange', {}),
            ('start_combat', {}),
            ('step_combat', {'steps': 2}),
            ('resolve_combat', {}),
        ):
            r = client.post(f'/api/ui/autochess/matches/{mid}/action', json={'action': action, **payload})
            self.assertEqual(r.status_code, 200, (action, r.get_data(as_text=True)))
            self.assertTrue(r.get_json()['ok'], (action, r.get_json()))
        self.assertEqual(client.delete(f'/api/ui/autochess/matches/{mid}').status_code, 200)

    def test_autochess_cd_reduction_and_summon_skill_bonus_take_effect(self):
        # 1. Cooldown reduction: 4-星祈 (+1 for 星祈 units) + aug_zone (+1 for all units)
        eng_cd = be.FullBattleEngine()
        y_configs = [
            {'uid': 'y_s1', 'serial': 'Y2', 'star': 1},
            {'uid': 'y_s2', 'serial': 'Y4', 'star': 1},
            {'uid': 'y_s3', 'serial': 'Y7', 'star': 1},
            {'uid': 'y_s4', 'serial': 'Y8', 'star': 1},
            {'uid': 'y_14', 'serial': 'Y14', 'star': 1},
        ]
        x_configs = [{'uid': 'x_1', 'serial': 'Y1', 'star': 1}]
        y_syn = ac_cat.compute_active_synergies(y_configs)
        x_syn = ac_cat.compute_active_synergies(x_configs)
        self.assertEqual(y_syn['星祈']['active_tier']['count'], 4)

        y_uids, _ = ac_cat.apply_autochess_modifiers(eng_cd, 'Y', y_configs, y_syn, augments=['aug_zone'])
        x_uids, _ = ac_cat.apply_autochess_modifiers(eng_cd, 'X', x_configs, x_syn, augments=[])
        eng_cd.setup_battle(y_uids, x_uids, arena_preset='autochess_citadel', autochess_mode=True)

        self.assertEqual(eng_cd._autochess_cd_reduction('y_s1'), 2)
        self.assertEqual(eng_cd._autochess_effective_cd('y_s1', 3), 1)
        self.assertEqual(eng_cd._autochess_effective_cd('y_s1', 1), 1)

        base_cart_cd = int(eng_cd._passive_rules('y_14', 'cartridge')['cooldown'])
        self.assertGreater(base_cart_cd, 1)
        self.assertEqual(eng_cd._autochess_cd_reduction('y_14'), 1)
        self.assertEqual(eng_cd._autochess_effective_cd('y_14', base_cart_cd), base_cart_cd - 1)
        eng_cd._y14_start_cooldown('y_14')
        y14_cds = [
            e['remainingRounds'] for e in eng_cd._get_effects()
            if e.get('type') == 'cooldown' and e.get('sourceUserId') == 'y_14'
        ]
        self.assertEqual(y14_cds, [base_cart_cd - 1] * 3)

        # Classic mode bypasses CD reduction; team + legacy 'cd_reduce' fallback also stack in autochess mode
        eng_cd.autochess_mode = False
        self.assertEqual(eng_cd._autochess_cd_reduction('y_s1'), 0)
        self.assertEqual(eng_cd._autochess_effective_cd('y_s1', 3), 3)
        eng_cd.autochess_mode = True
        eng_cd._autochess_unit_mods['x_1'] = {'cd_reduce': 1}
        eng_cd._autochess_team_mods['X'] = {'cd_reduction': 1}
        self.assertEqual(eng_cd._autochess_cd_reduction('x_1'), 2)

        # 2. Summon attack skill bonus: 2★ (+8) + 2-灵召 (+8) + aug_summon (+12) = +28
        eng_sum = be.FullBattleEngine()
        sum_configs = [
            {'uid': 'y_sum1', 'serial': 'Y12', 'star': 2},
            {'uid': 'y_sum2', 'serial': 'Y10', 'star': 1},
        ]
        sum_syn = ac_cat.compute_active_synergies(sum_configs)
        self.assertEqual(sum_syn['灵召']['active_tier']['count'], 2)

        sy_uids, _ = ac_cat.apply_autochess_modifiers(eng_sum, 'Y', sum_configs, sum_syn, augments=['aug_summon'])
        sx_uids, _ = ac_cat.apply_autochess_modifiers(
            eng_sum, 'X', x_configs, ac_cat.compute_active_synergies(x_configs), augments=[]
        )
        eng_sum.setup_battle(sy_uids, sx_uids, arena_preset='autochess_citadel', autochess_mode=True)

        self.assertEqual(eng_sum._autochess_summon_skill_bonus('y_sum1'), 28)
        eng_sum.autochess_mode = False
        self.assertEqual(eng_sum._autochess_summon_skill_bonus('y_sum1'), 0)
        eng_sum.autochess_mode = True

        # Team-level summon_skill_bonus also stacks cleanly with unit_mods
        eng_sum._autochess_team_mods['Y']['summon_skill_bonus'] = 5
        self.assertEqual(eng_sum._autochess_summon_skill_bonus('y_sum1'), 33)
        eng_sum._autochess_team_mods['Y']['summon_skill_bonus'] = 0

        eng_classic = be.FullBattleEngine()
        cd.load_character_to_engine(eng_classic, copy.deepcopy(ac_cat.CHAR_DATA_BY_SERIAL['Y12']), 'c_y12')
        cd.load_character_to_engine(eng_classic, copy.deepcopy(ac_cat.CHAR_DATA_BY_SERIAL['Y1']), 'c_x1')
        eng_classic.setup_battle(['c_y12'], ['c_x1'], autochess_mode=False)

        sid_ac = eng_sum._create_summon('y_sum1', '朱雀')
        sid_cl = eng_classic._create_summon('c_y12', '朱雀')
        self.assertIsNotNone(sid_ac)
        self.assertIsNotNone(sid_cl)

        ac_skills = eng_sum._summon_members[sid_ac]['skills']
        cl_skills = eng_classic._summon_members[sid_cl]['skills']
        self.assertEqual(len(ac_skills), len(cl_skills))
        for sk_ac, sk_cl in zip(ac_skills, cl_skills):
            self.assertEqual(sk_ac['val'], sk_cl['val'] + 28)

        ac_il = eng_sum._unit_il_entry(sid_ac, eng_sum._get_initiative())
        cl_il = eng_classic._unit_il_entry(sid_cl, eng_classic._get_initiative())
        self.assertEqual(ac_il['skill_val'], cl_il['skill_val'] + 28)


if __name__ == '__main__':
    unittest.main()
