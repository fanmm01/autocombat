"""Seasonal domains, physical summons and delayed finishers across both engines."""
import unittest
from unittest.mock import patch

import battle_engine as be
from characters_data import MULUO, MULUO_FENQIU, ZHANGSHIYAO, load_character_to_engine
from autochess_catalog import apply_autochess_modifiers, build_unit_wiki


def battles():
    for cls in (be.FullBattleEngine, be.FastBattleEngine):
        engine = cls()
        for uid, card in [('bard', ZHANGSHIYAO), ('leaf', MULUO_FENQIU), ('old', MULUO)]:
            load_character_to_engine(engine, card, uid)
            engine.process_command(uid, '.hs')
        engine.setup_battle(['bard', 'old'], ['leaf'], '10x10', season_status=50,
                            initial_coords={'bard': 'C3', 'old': 'D3', 'leaf': 'F3'})
        yield engine


def cast(engine, uid, index, target=None):
    spell = next(sp for sp in engine.load_spells(uid) if sp['index'] == index)
    return engine._execute_spell(uid, target or uid, spell)


def advance(engine, rnd):
    engine._set_state(dict(engine._get_state(), round=rnd))
    with patch.object(engine, '_round_mp_regeneration'):
        engine._tick_down()
    engine._apply_zone_effects()


class SeasonalCombatTests(unittest.TestCase):
    def test_star_profiles_and_wiki_agree(self):
        for serial, skill, health, skill_values in [('Y18', '斗殴', [9, 15, 23], [50, 60, 70]),
                                                    ('Y19', '剑', [11, 18, 29], [78, 88, 92])]:
            wiki = build_unit_wiki(serial)
            for star in (1, 2, 3):
                engine = be.FullBattleEngine()
                apply_autochess_modifiers(engine, 'Y', [dict(uid='unit', serial=serial, star=star)], {})
                char = engine.get_char('unit')
                expected = (health[star-1], [18, 23, 28][star-1], skill_values[star-1])
                self.assertEqual(tuple(char.get_attr(k) for k in ('体力上限', '魔力上限', skill)), expected)
                stats = wiki['star_stats'][str(star)]
                self.assertEqual((stats['hp'], stats['mp']), expected[:2])

    def test_autochess_portal_relocation(self):
        for cls in (be.FullBattleEngine, be.FastBattleEngine):
            engine = cls()
            for uid, card in [('bard', ZHANGSHIYAO), ('leaf', MULUO_FENQIU)]:
                load_character_to_engine(engine, card, uid)
            engine.setup_battle(['bard'], ['leaf'], autochess_mode=True, arena_preset='autochess_standard',
                                initial_coords={'bard': 'A4', 'leaf': 'B4'})
            cast(engine, 'bard', 2)
            engine._begin_portal_hit('leaf', 'bard')
            engine._portal_escape(*engine._portal_hit)
            self.assertFalse(engine._in_range_of('leaf', 'bard', 2))
            self.assertEqual(engine._season_zone('bard')['portalCharges'], 3)

    def test_winter_cancellation_and_upkeep_failure(self):
        for engine in battles():
            cast(engine, 'bard', 4)
            engine.end_skill_effects('bard', 4)
            hp = engine._hp_safe('leaf')
            advance(engine, 2)
            advance(engine, 3)
            self.assertEqual(engine._hp_safe('leaf'), hp)
            cast(engine, 'bard', 2)
            engine.get_char('bard').set_attr('魔力', 0)
            advance(engine, 4)
            self.assertIsNone(engine._season_zone('bard'))

    def test_dash_rejects_out_of_range_without_spending(self):
        for engine in battles():
            engine._commit_unit_position('leaf', 'J10')
            mana = engine.get_char('leaf').get_attr('魔力')
            self.assertFalse(be.action_committed(cast(engine, 'leaf', 2, 'bard')))
            self.assertEqual(engine.get_char('leaf').get_attr('魔力'), mana)

    def test_domain_transitions_and_empowered_summons(self):
        for engine in battles():
            with self.subTest(engine=type(engine).__name__):
                bard = engine.get_char('bard')
                self.assertEqual(bard.get_attr('体力上限'), 108)
                self.assertFalse(be.action_committed(cast(engine, 'bard', 3)))
                self.assertEqual(bard.get_attr('魔力'), 99)
                cast(engine, 'bard', 2)
                self.assertEqual(engine._get_effective_mov('bard'), 12)
                mana = bard.get_attr('魔力')
                with patch.object(be, 'roll_dice', side_effect=lambda expr: {'1d3': 3, '1d4+1': 4}.get(expr, 1)):
                    cast(engine, 'bard', 1)
                self.assertEqual(bard.get_attr('魔力'), mana - 3)
                spirits = [uid for uid, e in engine._summon_members.items() if e['name'] == '仙境生灵']
                self.assertEqual(len(spirits), 4)
                self.assertTrue(all(engine.get_char(uid).get_attr('斗殴') == 77 for uid in spirits))
                cast(engine, 'bard', 3)
                self.assertEqual(engine._season_zone('bard')['spellIndex'], 3)
                self.assertFalse(be.action_committed(cast(engine, 'bard', 2)))
                engine._init_combat_hp('old', 3)
                advance(engine, 2)
                self.assertEqual(engine._hp_safe('old'), 3)
                cast(engine, 'bard', 4)
                advance(engine, 3)
                self.assertIsNotNone(engine._season_zone('bard'))
                advance(engine, 4)
                self.assertIsNone(engine._season_zone('bard'))
                self.assertEqual(bard.get_attr('魔力'), 0)

    def test_portal_and_silence(self):
        for engine in battles():
            cast(engine, 'bard', 2)
            zone = engine._season_zone('bard')
            engine._begin_portal_hit('leaf', 'old')
            self.assertEqual(zone['portalCharges'], 3)
            self.assertEqual(engine._absorb_damage_with_shield('old', 7)[0], 3)
            engine._portal_hit = None
            engine._begin_portal_hit('leaf', 'bard')
            self.assertIsNone(engine._portal_hit)
            cast(engine, 'bard', 1)
            engine._apply_target_effect('leaf', 'bard', {'type': 4, '辅助效果': '沉默', '持续回合': 2},
                                        {'name': '沉默测试', 'index': 9}, False, 0)
            self.assertIsNone(engine._season_zone('bard'))
            self.assertEqual(engine._get_summon_live_count('bard', '仙境生灵'), 0)

    def test_season_damage_respects_shields(self):
        for engine in battles():
            hp = engine._hp_safe('old')
            engine._set_effects([{
                'type': 'shield', 'targetUserId': 'old', 'sourceUserId': 'bard',
                'value': 5, 'remainingRounds': 2,
            }])
            engine._season_damage('leaf', 'old', 7)
            self.assertEqual(engine._hp_safe('old'), hp - 2)
            self.assertEqual(engine._get_active_shields('old')[0], 0)

    def test_equal_cost_summons_spear_and_bloom(self):
        for engine in battles():
            leaf = engine.get_char('leaf')
            mana = leaf.get_attr('魔力')
            cast(engine, 'leaf', 1)
            count = engine._get_summon_live_count('leaf', '锋叶魔物')
            self.assertEqual(count, mana - leaf.get_attr('魔力'))
            blade = next(uid for uid, e in engine._summon_members.items() if e['name'] == '锋叶魔物')
            engine._frost_on_hit(blade, 'bard')
            self.assertEqual(engine.get_char('bard').get_attr('leaf_marks'), 0.5)
            self.assertFalse(be.action_committed(cast(engine, 'leaf', 4)))
            engine._init_combat_hp('leaf', 50)
            with patch.object(engine, '_roll_spell_success_bp', return_value=(1, '')), patch.object(
                    engine, '_trigger_spell_reaction', return_value=(False, False, [])):
                cast(engine, 'leaf', 2, 'bard')
            self.assertTrue(engine._in_range_of('leaf', 'bard', 1))
            self.assertEqual(engine.get_char('bard').get_attr('leaf_marks'), 2.5)
            self.assertTrue(53 <= engine._hp_safe('leaf') <= 60)
            cast(engine, 'leaf', 3)
            self.assertEqual(leaf.get_attr('魔力'), 36)
            self.assertEqual(engine._get_effective_mov('leaf'), 14)
            self.assertEqual(engine._apply_autochess_damage_mods('leaf', 'bard', 100), 145)
            advance(engine, 2)
            self.assertLess(leaf.get_attr('魔力'), 36)
            self.assertEqual(leaf.phase, 2)

    def test_sunset_persists_on_death_and_cannot_be_cancelled(self):
        for engine in battles():
            engine.get_char('bard').set_attr('leaf_marks', 2)
            cast(engine, 'leaf', 4)
            self.assertEqual(engine._hp_safe('leaf'), 12)
            self.assertEqual(engine.get_char('leaf').get_attr('魔力'), 0)
            engine._set_combat_hp('leaf', 121)
            self.assertEqual(engine._hp_safe('leaf'), 30)
            engine.end_skill_effects('leaf', 4)
            engine._init_combat_hp('leaf', 0)
            engine._remove_summons_of_owner('leaf')
            self.assertIsNone(engine._check_battle_end())
            engine._init_combat_hp('bard', 4)
            advance(engine, 2)
            self.assertEqual(engine._hp_safe('bard'), 0)
            before = engine._hp_safe('old')
            advance(engine, 3)
            advance(engine, 4)
            self.assertLess(engine._hp_safe('old'), before)
            self.assertFalse(engine.get_json('sunset_casts'))

    def test_autochess_sunset_burst_skips_allies(self):
        for autochess_mode in (True, False):
            with self.subTest(autochess_mode=autochess_mode):
                engine = be.FastBattleEngine()
                for uid, card in [('leaf', MULUO_FENQIU), ('ally', ZHANGSHIYAO), ('enemy', MULUO)]:
                    load_character_to_engine(engine, card, uid)
                    engine.process_command(uid, '.hs')
                engine.setup_battle(
                    ['leaf', 'ally'], ['enemy'], '10x10',
                    autochess_mode=autochess_mode,
                    season_status=50,
                    initial_coords={'leaf': 'D3', 'ally': 'C3', 'enemy': 'F3'},
                )
                engine.get_char('enemy').set_attr('leaf_marks', 2)
                cast(engine, 'leaf', 4)
                ally_before = engine._hp_safe('ally')
                enemy_before = engine._hp_safe('enemy')
                advance(engine, 2)
                advance(engine, 3)
                advance(engine, 4)
                self.assertLess(engine._hp_safe('enemy'), enemy_before)
                if autochess_mode:
                    self.assertEqual(engine._hp_safe('ally'), ally_before)
                else:
                    self.assertLess(engine._hp_safe('ally'), ally_before)

    def test_y19_ai_holds_sunset_until_low_hp(self):
        from ai_tactics import decide_tactical_action

        engine = be.FastBattleEngine()
        for uid, card in [('leaf', MULUO_FENQIU), ('enemy', MULUO)]:
            load_character_to_engine(engine, card, uid)
            engine.process_command(uid, '.hs')
        engine.setup_battle(
            ['leaf'], ['enemy'], '10x10',
            autochess_mode=True,
            initial_coords={'leaf': 'D3', 'enemy': 'F3'},
        )
        engine.get_char('enemy').set_attr('leaf_marks', 2)
        cast(engine, 'leaf', 3)
        max_hp = engine.get_char('leaf').get_attr('体力上限')

        # Healthy Y19 should not suicide with S4
        engine._init_combat_hp('leaf', max_hp)
        cmd_healthy, _ = decide_tactical_action(engine, 'leaf')
        self.assertFalse(cmd_healthy.startswith('.s4'), f'Expected healthy Y19 to hold S4, got {cmd_healthy}')

        # Low-HP Y19 (<= 35%) should trigger S4 as last-stand finisher
        engine._init_combat_hp('leaf', max(1, int(max_hp * 0.30)))
        cmd_low, _ = decide_tactical_action(engine, 'leaf')
        self.assertTrue(cmd_low.startswith('.s4'), f'Expected low-HP Y19 to cast S4, got {cmd_low}')
