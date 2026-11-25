import copy
import unittest

import autochess_catalog as catalog
from autochess_match import AutoChessMatch
from battle_engine import FullBattleEngine
from characters_data import SUMMON_TEMPLATES


class AutoChessHalfHsTests(unittest.TestCase):
    def test_battle_and_wiki_agree_for_every_star(self):
        templates = copy.deepcopy(SUMMON_TEMPLATES)
        snapshots = {}
        for ruleset in catalog.RULESETS:
            snapshots[ruleset] = {}
            for serial in catalog.UNIT_CATALOG:
                wiki = catalog.build_unit_wiki(serial, ruleset)
                snapshots[ruleset][serial] = []
                for star in (1, 2, 3):
                    with self.subTest(ruleset=ruleset, serial=serial, star=star):
                        engine = FullBattleEngine()
                        units = [{'uid': 'unit', 'serial': serial, 'star': star}]
                        catalog.apply_autochess_modifiers(engine, 'Y', units, {}, ruleset=ruleset)
                        char = engine.get_char('unit')
                        self.assertEqual(char.hs_transformed, ruleset == 'half_hs')
                        registry = getattr(engine, '_summon_templates_snapshot', None)
                        if ruleset == 'half_hs':
                            self.assertIsNot(registry, SUMMON_TEMPLATES)
                            self.assertEqual(registry['虚假之月'], templates['虚假之月'])
                            for name, template in templates.items():
                                if not isinstance(template, dict) or template.get('_meta') or name == '虚假之月':
                                    continue
                                for field in ('HP', 'MP', 'shield_block'):
                                    value = template.get(field)
                                    if isinstance(value, (int, float)) and value > 0:
                                        self.assertEqual(registry[name][field], max(1, round(value * 0.5)))
                        else:
                            self.assertIsNone(registry)
                        mods = engine._autochess_unit_mods['unit']
                        stats = {
                            'hp': char.get_attr('体力上限'),
                            'mp': char.get_attr('魔力上限'),
                            'flat_dmg': mods['flat_dmg'],
                            'flat_dr': mods['flat_dr'],
                            'summon_hp_mult': round(mods['summon_hp_mult'], 4),
                            'summon_skill_bonus': mods['summon_skill_bonus'],
                        }
                        for field, value in stats.items():
                            self.assertEqual(value, wiki['star_stats'][str(star)][field])
                        stats.update({key: mods[key] for key in ('dmg_pct', 'bloodmoon_leech_pct')})
                        snapshots[ruleset][serial].append(stats)
                for rows in zip(snapshots[ruleset][serial], snapshots[ruleset][serial][1:]):
                    for field in rows[0]:
                        self.assertLessEqual(rows[0][field], rows[1][field], (ruleset, serial, field))
        self.assertEqual(SUMMON_TEMPLATES, templates)
        self.assertEqual(snapshots['standard']['Y16'][0]['hp'], 14)
        self.assertEqual(snapshots['half_hs']['Y16'][0]['hp'], 50)
        self.assertEqual(snapshots['half_hs']['Y1'][2]['hp'], 267)
        self.assertEqual(snapshots['standard']['Y12'][2]['summon_hp_mult'], 1.4575)
        self.assertEqual(snapshots['half_hs']['Y12'][2]['summon_hp_mult'], 2.65)
        for ruleset in catalog.RULESETS:
            self.assertEqual([row['flat_dmg'] for row in snapshots[ruleset]['Y11']], [0, 1, 4])

    def test_half_hs_shop_prices_pool_combat_and_legacy_save(self):
        match = AutoChessMatch(ruleset='half_hs', seed=10001)
        cid = match.player_id
        commander = match.commanders[cid]
        self.assertEqual(catalog.get_unit_cost(commander['units'][0]['serial'], match.ruleset), 1)
        self.assertEqual(match.pool['Y16'], catalog.POOL_COUNTS[4])
        self.assertEqual(AutoChessMatch(mode='ranked', ruleset='half_hs', seed=7).pool['Y16'],
                         catalog.POOL_COUNTS_8P[4])
        self.assertTrue(all(slot['cost'] <= 2 for slot in match.to_public_dict()['player']['shop'] if slot))
        odds = match._apply_reroll_odds_boost(catalog.get_level_table(match.ruleset)[7]['odds'], 7, match.ruleset)
        self.assertEqual((sum(odds.values()), odds[5], odds[6]), (100, 0, 0))

        commander['gold'] = 10
        commander['shop'][0] = {'serial': 'Y16', 'bought': False}
        self.assertEqual(match.to_public_dict()['player']['shop'][0]['cost'], 4)
        self.assertTrue(match.buy_unit(cid, 0)[0])
        self.assertEqual(commander['gold'], 6)
        unit = next(unit for unit in commander['units'] if unit['serial'] == 'Y16')
        self.assertTrue(match.sell_unit(cid, unit['id'])[0])
        self.assertEqual(commander['gold'], 10)
        self.assertEqual(match.pool['Y16'], catalog.POOL_COUNTS[4])
        data = match.to_dict()
        restored = AutoChessMatch.from_dict(data)
        self.assertEqual(restored.ruleset, 'half_hs')
        self.assertEqual(restored.to_public_dict()['ruleset'], 'half_hs')
        self.assertTrue(restored.resolve_combat()[0])
        self.assertIsNotNone(restored.last_round_report)
        legacy = AutoChessMatch(seed=10001).to_dict()
        legacy.pop('ruleset')
        self.assertEqual(AutoChessMatch.from_dict(legacy).ruleset, 'standard')
        self.assertEqual(AutoChessMatch(mode='pve12', ruleset='half_hs').ruleset, 'standard')
