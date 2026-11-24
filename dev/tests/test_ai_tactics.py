import copy
import json
import random
import unittest
from unittest.mock import patch

import ai_battle
import ai_tactics
import arena_presets as ap
import battle_engine as be
from autochess_catalog import CHAR_DATA_BY_SERIAL
from battle_engine import FullBattleEngine
from characters_data import load_character_to_engine


class AiTacticsTests(unittest.TestCase):
    def test_role_classification_and_conflict_free_formation(self):
        eng = FullBattleEngine()
        for serial in ('Y1', 'Y4', 'Y5', 'Y7', 'Y8', 'Y10', 'Y12', 'Y16', 'Y17'):
            load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL[serial]), serial)

        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y12')), 'tank')
        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y1')), 'bruiser')
        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y17')), 'bruiser')
        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y4')), 'ranged')
        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y5')), 'assassin')
        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y16')), 'summoner')
        for sup in ('Y7', 'Y8', 'Y10'):
            self.assertEqual(ai_tactics.classify_role(eng.get_char(sup)), 'support')

        for preset in ('autochess_standard', 'autochess_compact', 'autochess_citadel'):
            md = ap.build_arena_map(preset)
            units = [{'uid': s, 'char': eng.get_char(s)} for s in ('Y12', 'Y1', 'Y4', 'Y7')]
            coords = ai_tactics.plan_formation('Y', units, md)
            self.assertEqual(len(coords), 4)
            self.assertEqual(len(set(coords.values())), 4)
            for c in coords.values():
                self.assertTrue(ap.is_in_deploy_zone(md, 'Y', c))
            col_y12 = ai_tactics.parse_coord(coords['Y12'])[0]
            col_y4 = ai_tactics.parse_coord(coords['Y4'])[0]
            self.assertGreaterEqual(col_y12, col_y4)

    def test_tactical_decision_cover_preference_and_anti_loop(self):
        eng = FullBattleEngine()
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y4']), 'Y_Y4')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'X_Y1')
        eng.setup_battle(
            ['Y_Y4'], ['X_Y1'],
            arena_preset='autochess_standard',
            autochess_mode=True,
            initial_coords={'Y_Y4': 'C4', 'X_Y1': 'H4'},
        )
        # Cover tile D3 should outscore open flank tile A1 for ranged Y4
        self.assertGreater(
            ai_tactics.score_tile(eng, 'Y_Y4', 'D3', role='ranged', desired_range=8),
            ai_tactics.score_tile(eng, 'Y_Y4', 'A1', role='ranged', desired_range=8),
        )
        cmd, reason = ai_tactics.decide_tactical_action(eng, 'Y_Y4')
        self.assertNotEqual(cmd, '.i end')
        self.assertTrue(reason)

        # Marking returned command as failed forces fallback cleanly without repeating it
        eng._ai_failed_commands = {cmd}
        cmd2, _ = ai_tactics.decide_tactical_action(eng, 'Y_Y4')
        self.assertNotEqual(cmd2, cmd)

    def test_classic_ai_bypasses_spatial_tactics(self):
        eng = ai_battle.BattleEngine(display_level=0, delay=0, quiet=True)
        cd_y1 = copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1'])
        cd_y2 = copy.deepcopy(CHAR_DATA_BY_SERIAL['Y2'])
        load_character_to_engine(eng, cd_y1, 'Y_Y1')
        load_character_to_engine(eng, cd_y2, 'X_Y2')
        eng.setup_battle(['Y_Y1'], ['X_Y2'])
        self.assertFalse(eng.autochess_mode)
        ctrl = ai_battle.AIController('Y_Y1', cd_y1, 'Y')
        with patch.object(ai_battle, 'decide_tactical_action') as mock_tac:
            cmd = ctrl.decide_action(eng, 'Y_Y1')
            self.assertTrue(cmd)
            mock_tac.assert_not_called()

    def _run_unit_turn(self, eng, uid, limit=10):
        cmds = []
        eng._ai_failed_commands = set()
        for _ in range(limit):
            if eng._get_my_actions(uid).get('主动', 0) <= 0:
                break
            cmd, _reason = ai_tactics.decide_tactical_action(eng, uid)
            cmds.append(cmd)
            if cmd == '.i end':
                break
            res = eng._execute_ai_command(uid, cmd)
            self.assertTrue(getattr(res, 'committed', True), f'{cmd} rejected: {res}')
            eng._consume_action(uid, res.slot)
            if cmd.startswith('.a m '):
                eng._moved_this_turn = getattr(eng, '_moved_this_turn', set()) | {uid}
        return cmds

    def test_y17_advances_shapes_sword_and_slashes_without_suicide(self):
        random.seed(17)
        eng = FullBattleEngine()
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y17']), 'Y_Y17')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'X_Y1')
        eng.setup_battle(
            ['Y_Y17'], ['X_Y1'],
            arena_preset='autochess_standard',
            autochess_mode=True,
            initial_coords={'Y_Y17': 'C4', 'X_Y1': 'H4'},
            track_stats=True,
        )
        # Guarantee Y17's slash hits and Y1's reaction fails so damage is deterministic.
        with patch.object(
            be, 'roll_d100',
            side_effect=[(15, '10位1, 个位5'), (99, '10位9, 个位9'), (99, '10位9, 个位9'), (99, '10位9, 个位9')],
        ):
            cmds = self._run_unit_turn(eng, 'Y_Y17')

        self.assertTrue(any(c.startswith('.a m ') for c in cmds), cmds)
        self.assertTrue(any(c.startswith('.a s3 blood=') for c in cmds), cmds)
        self.assertIn('.a s5 form=sword', cmds)
        self.assertTrue(any(c.startswith('.s11 blood=') and 'moon=' in c for c in cmds), cmds)
        self.assertFalse(any(c.startswith('.s4') for c in cmds), cmds)

        audit = json.loads(eng.get_char('Y_Y17').get_str('_blood_audit') or '{}')
        self.assertGreaterEqual(audit.get('blade_casts', 0), 1)
        self.assertGreaterEqual(audit.get('slash_casts', 0), 1)
        self.assertEqual(audit.get('sacrifice_casts', 0), 0)
        self.assertGreater(audit.get('slash_damage', 0), 0)

    def test_y17_shapes_bow_when_out_of_slash_reach_and_swaps_to_sword_close(self):
        eng = FullBattleEngine()
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y17']), 'Y_Y17')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'X_Y1')
        eng.setup_battle(
            ['Y_Y17'], ['X_Y1'],
            arena_preset='autochess_standard',
            autochess_mode=True,
            initial_coords={'Y_Y17': 'A4', 'X_Y1': 'I4'},
        )
        # Immobilized / already moved this turn -> cannot reach slash range, must shape bow.
        eng._set_combat_hp('Y_Y17', 8)
        eng._moved_this_turn = {'Y_Y17'}
        cmds = self._run_unit_turn(eng, 'Y_Y17')
        self.assertIn('.a s5 form=bow', cmds)
        self.assertIn('.s0', cmds)
        self.assertEqual(eng._y17_blade('Y_Y17').get('bloodForm'), 'bow')

        # Next turn, enemy closes into slash distance (<= 3): Y17 swaps to sword and slashes.
        eng._moved_this_turn = set()
        il = eng._get_initiative()
        for row in il:
            if row['userId'] == 'X_Y1':
                row['coord'] = 'C4'
        eng._set_initiative(il)
        acts = eng._get_actions()
        acts['Y_Y17'] = {'主动': 1, '附加': 3}
        eng._set_actions(acts)
        cmds_close = self._run_unit_turn(eng, 'Y_Y17')
        self.assertIn('.a s5 form=sword', cmds_close)
        self.assertTrue(any(c.startswith('.s11 ') for c in cmds_close), cmds_close)

    def test_y17_spear_throw_targeting_and_decision(self):
        eng = FullBattleEngine()
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y17']), 'Y_Y17')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'X_Y1')
        eng.setup_battle(
            ['Y_Y17'], ['X_Y1'],
            arena_preset='autochess_standard',
            autochess_mode=True,
            initial_coords={'Y_Y17': 'C4', 'X_Y1': 'H4'},
        )
        # Keep X_Y1 alive through the first throw (even on a crit), then test AI throw decision.
        eng.get_char('X_Y1').set_attr('体力上限', 100)
        eng._set_combat_hp('X_Y1', 100)
        self.assertTrue(be.action_committed(eng._execute_ai_command('Y_Y17', '.a s12')))
        eng._set_autochess_pending_target('Y_Y17', 'X_Y1')
        throw_res = eng._execute_ai_command('Y_Y17', '.s12 mode=throw')
        self.assertTrue(be.action_committed(throw_res), f'{throw_res}')
        self.assertEqual(eng._y17_spears('Y_Y17'), [])

        eng.get_char('Y_Y17').set_str('_blood_spears', '[1]')
        eng.get_char('Y_Y17').set_attr('储血ml', 0)
        eng._moved_this_turn = {'Y_Y17'}
        eng._consume_action('Y_Y17', '附加', 3)
        cmd, reason = ai_tactics.decide_tactical_action(eng, 'Y_Y17')
        self.assertEqual(cmd, '.s12 mode=throw', reason)

    def test_y17_avoids_war_friendly_fire_and_handles_arcana_chant(self):
        eng = FullBattleEngine()
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y17']), 'Y_Y17')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'Y_Y1')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'X_Y1')
        eng.setup_battle(
            ['Y_Y17', 'Y_Y1'], ['X_Y1'],
            arena_preset='autochess_standard',
            autochess_mode=True,
            initial_coords={'Y_Y17': 'C4', 'Y_Y1': 'D4', 'X_Y1': 'F4'},
        )
        eng.get_char('Y_Y17').set_attr('储血ml', 0)
        eng._moved_this_turn = {'Y_Y17'}
        cmd, _ = ai_tactics.decide_tactical_action(eng, 'Y_Y17')
        self.assertFalse(cmd.startswith('.s6'), cmd)

        # Active arcana chant with no ally in firing direction -> continue chant (.s2).
        eng.get_char('Y_Y17').set_attr('储血ml', 1000)
        il = eng._get_initiative()
        for row in il:
            if row['userId'] == 'Y_Y1':
                row['coord'] = 'A1'
        eng._set_initiative(il)
        eng._set_autochess_pending_target('Y_Y17', 'X_Y1')
        self.assertTrue(be.action_committed(eng._execute_ai_command('Y_Y17', '.s2')))
        self.assertIsNotNone(eng._y17_chant('Y_Y17'))
        eng._consume_action('Y_Y17', '附加', 3)
        cmd_cont, _ = ai_tactics.decide_tactical_action(eng, 'Y_Y17')
        self.assertEqual(cmd_cont, '.s2')

        # Move ally directly into the locked eastbound arcana beam -> cancel chant (.s2 mode=cancel).
        for row in il:
            if row['userId'] == 'Y_Y1':
                row['coord'] = 'E4'
        eng._set_initiative(il)
        cmd_cancel, _ = ai_tactics.decide_tactical_action(eng, 'Y_Y17')
        self.assertEqual(cmd_cancel, '.s2 mode=cancel')

    def test_y17_anti_loop_skips_failed_parameterized_command(self):
        eng = FullBattleEngine()
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y17']), 'Y_Y17')
        load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL['Y1']), 'X_Y1')
        eng.setup_battle(
            ['Y_Y17'], ['X_Y1'],
            arena_preset='autochess_standard',
            autochess_mode=True,
            initial_coords={'Y_Y17': 'F4', 'X_Y1': 'H4'},
        )
        eng._moved_this_turn = {'Y_Y17'}
        cmd1, _ = ai_tactics.decide_tactical_action(eng, 'Y_Y17')
        self.assertTrue(cmd1.startswith('.a s3 blood='), cmd1)
        eng._ai_failed_commands = {cmd1}
        cmd2, _ = ai_tactics.decide_tactical_action(eng, 'Y_Y17')
        self.assertNotEqual(cmd2, cmd1)
        self.assertNotEqual(cmd2, '.i end')


if __name__ == '__main__':
    unittest.main()
