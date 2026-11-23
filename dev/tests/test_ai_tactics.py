import copy
import unittest
from unittest.mock import patch

import ai_battle
import ai_tactics
import arena_presets as ap
from autochess_catalog import CHAR_DATA_BY_SERIAL
from battle_engine import FullBattleEngine
from characters_data import load_character_to_engine


class AiTacticsTests(unittest.TestCase):
    def test_role_classification_and_conflict_free_formation(self):
        eng = FullBattleEngine()
        for serial in ('Y1', 'Y4', 'Y5', 'Y7', 'Y8', 'Y10', 'Y12', 'Y16'):
            load_character_to_engine(eng, copy.deepcopy(CHAR_DATA_BY_SERIAL[serial]), serial)

        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y12')), 'tank')
        self.assertEqual(ai_tactics.classify_role(eng.get_char('Y1')), 'bruiser')
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


if __name__ == '__main__':
    unittest.main()
