#!/usr/bin/env python3
"""Tests for scripts/temp_char_tournament.py (in-memory temp character CLI tool)."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / 'scripts'
BACKEND_DIR = ROOT / 'backend'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import characters_data  # noqa: E402
from combat_defaults import DEFAULTS as SETTING_DEFAULTS  # noqa: E402
import temp_char_tournament as tct  # noqa: E402


def _parse_args(cli_args):
    return tct.build_arg_parser().parse_args(cli_args)


class BuildTempCharacterTests(unittest.TestCase):
    def test_attr_aliases_separators_and_max_autosync(self):
        args = _parse_args([
            '--name', '测角',
            '--serial', 'TMP1',
            '--attr', 'HP=14,MP=18;MOV=10',
            '--attr', '闪避=68,BRAWL=72',
            '--damage', '2d6+1',
            '--str-attr', '不可指定召唤物=藤蔓',
        ])
        ch = tct.build_temp_character(args)
        self.assertEqual(ch['name'], '测角')
        self.assertEqual(ch['serial'], 'TMP1')
        self.assertEqual(ch['attrs']['体力'], 14)
        self.assertEqual(ch['attrs']['体力上限'], 14)
        self.assertEqual(ch['attrs']['魔力'], 18)
        self.assertEqual(ch['attrs']['魔力上限'], 18)
        self.assertEqual(ch['attrs']['行动力'], 10)
        self.assertEqual(ch['attrs']['闪避'], 68)
        self.assertEqual(ch['attrs']['斗殴'], 72)
        self.assertEqual(ch['str_attrs']['伤害值'], '2d6+1')
        self.assertEqual(ch['str_attrs']['不可指定召唤物'], '藤蔓')

    def test_explicit_max_hp_mp_not_overwritten(self):
        args = _parse_args([
            '--attr', 'HP=9,MAX_HP=15',
            '--attr', 'MP=6',
            '--attr', 'MAX_MP=20',
            '--attrs-json', '{"敏捷": 75}',
            '--str-attrs-json', '{"伤害值": "1d8+2"}',
        ])
        ch = tct.build_temp_character(args)
        self.assertEqual(ch['attrs']['体力'], 9)
        self.assertEqual(ch['attrs']['体力上限'], 15)
        self.assertEqual(ch['attrs']['魔力'], 6)
        self.assertEqual(ch['attrs']['魔力上限'], 20)
        self.assertEqual(ch['attrs']['敏捷'], 75)
        self.assertEqual(ch['str_attrs']['伤害值'], '1d8+2')

    def test_skill_shorthand_preserves_string_fields_and_semicolons(self):
        args = _parse_args([
            '--serial', 'TMP2',
            '--skill', 'name=吸血斩,mp=2,timing=23,type=1,target=4,dmg=1d10+2,hit=80,lifesteal=0.35,aux=反应惩罚骰,aux_val=p',
            '--skill', 'name=寒霜域,mp=4,type=8,客体=45,radius=5,属性削减=行动力-5;斗殴-10,dot=1d6,duration=3,follow=0',
            '--skill', '{"name": "自定义盾", "timing": "3", "category": 2, "消耗mp": 3, "effects": [{"type": 2, "客体": 1, "护盾值": "2d6"}]}',
            '--spells-json', '[{"name": "JSON治疗", "timing": "2", "category": 3, "消耗mp": 2, "effects": [{"type": 3, "客体": 12, "回复hp": "1d8"}]}]',
            '--item', '蛋糕HP=2',
        ])
        ch = tct.build_temp_character(args)
        self.assertEqual(len(ch['spells']), 4)

        sp0 = ch['spells'][0]
        self.assertEqual(sp0['skill_id'], 'TMP2-S001')
        self.assertEqual(sp0['skill_index'], 1)
        self.assertIsInstance(sp0['timing'], str)
        self.assertEqual(sp0['timing'], '23')
        self.assertIsInstance(sp0['effects'][0]['吸血比例'], str)
        self.assertEqual(sp0['effects'][0]['吸血比例'], '0.35')
        self.assertEqual(sp0['effects'][0]['辅助效果'], '反应惩罚骰')
        self.assertEqual(sp0['effects'][0]['辅助效果值'], 'p')

        sp1 = ch['spells'][1]
        self.assertEqual(sp1['effects'][0]['type'], 8)
        self.assertEqual(sp1['effects'][0]['属性削减'], '行动力-5;斗殴-10')
        self.assertEqual(sp1['effects'][0]['每回合伤害骰'], '1d6')
        self.assertEqual(sp1['effects'][0]['领域中心跟随'], 0)

        sp2 = ch['spells'][2]
        self.assertEqual(sp2['name'], '自定义盾')
        self.assertEqual(sp2['skill_id'], 'TMP2-S003')

        sp3 = ch['spells'][3]
        self.assertEqual(sp3['name'], 'JSON治疗')
        self.assertEqual(sp3['skill_id'], 'TMP2-S004')
        self.assertEqual(ch['inventory'], [{'item': '蛋糕HP', 'count': 2}])

    def test_base_copy_skill_clear_skills_and_char_json_stdin(self):
        args_base = _parse_args([
            '--base', 'Y1',
            '--serial', 'TMP_Y1',
            '--attr', 'HP=20',
            '--copy-skill', 'Y2:1',
        ])
        ch = tct.build_temp_character(args_base)
        self.assertEqual(ch['serial'], 'TMP_Y1')
        self.assertIn('炎焱', ch['name'])
        self.assertEqual(ch['attrs']['体力'], 20)
        self.assertEqual(ch['attrs']['体力上限'], 20)
        self.assertGreaterEqual(len(ch['spells']), 3)
        self.assertTrue(all(s['skill_id'].startswith('TMP_Y1-S') for s in ch['spells']))
        tct.validate_temp_character(ch)

        args_clear = _parse_args(['--base', 'Y1', '--clear-skills', '--copy-skill', 'Y1:火焰附魔'])
        ch_cleared = tct.build_temp_character(args_clear)
        self.assertEqual(len(ch_cleared['spells']), 1)
        self.assertEqual(ch_cleared['spells'][0]['name'], '火焰附魔')
        self.assertEqual(ch_cleared['spells'][0]['skill_id'], 'TMP1-S001')

        stdin_payload = json.dumps({
            'name': '标准输入角色',
            'serial': 'TMP_STDIN',
            'attrs': {'体力': 13},
            'str_attrs': {'伤害值': '1d8'},
            'spells': [{
                'name': '脉冲',
                'timing': '2',
                'category': 1,
                '消耗mp': 2,
                'effects': [{'type': 1, '客体': 4, '伤害骰': '2d6', '成功率': 75}],
            }],
        })
        args_stdin = _parse_args(['--char-json', '-'])
        ch_stdin = tct.build_temp_character(args_stdin, stdin_text=stdin_payload)
        self.assertEqual(ch_stdin['serial'], 'TMP_STDIN')
        self.assertEqual(ch_stdin['name'], '标准输入角色')
        self.assertEqual(ch_stdin['attrs']['体力上限'], 13)
        tct.validate_temp_character(ch_stdin)


class ValidationAndSettingsTests(unittest.TestCase):
    def test_validation_rejects_invalid_definitions(self):
        bad_serial = tct.build_temp_character(_parse_args(['--serial', '1bad']))
        with self.assertRaises(ValueError):
            tct.validate_temp_character(bad_serial)

        dup_serial = tct.build_temp_character(_parse_args(['--serial', 'Y1']))
        with self.assertRaises(ValueError):
            tct.validate_temp_character(dup_serial, replace=False)
        # Replacing an existing serial in memory is permitted with --replace
        roster = tct.validate_temp_character(dup_serial, replace=True)
        self.assertEqual(len(roster), len(characters_data.ALL_CHARACTERS))

        bad_summon = tct.build_temp_character(_parse_args([
            '--skill', 'name=坏召唤,type=5,summon=不存在模板,summon_count=1'
        ]))
        with self.assertRaises(ValueError):
            tct.validate_temp_character(bad_summon)

        bad_eff_type = tct.build_temp_character(_parse_args([
            '--skill', 'name=坏类型,type=99'
        ]))
        with self.assertRaises(ValueError):
            tct.validate_temp_character(bad_eff_type)

    def test_team_table_augmentation_and_target_parity(self):
        defaults_before = copy.deepcopy(SETTING_DEFAULTS)
        temp = tct.build_temp_character(_parse_args(['--serial', 'TMP1']))
        roster = tct.validate_temp_character(temp)

        args = _parse_args([
            '--format', '2v2,3v3',
            '--teams-2v2', 'TMP1+Y1',
            '--auto-teams-3v3', '4',
            '--rr-rounds', '1',
        ])
        cfg = tct.build_tournament_settings(args, ['2v2', '3v3'], roster, 'TMP1', 123)
        self.assertIn(['TMP1', 'Y1'], cfg['TEAM_TABLES_2V2'])
        t3_with_tmp = [t for t in cfg['TEAM_TABLES_3V3'] if 'TMP1' in t]
        self.assertEqual(len(t3_with_tmp), 4)
        self.assertEqual(SETTING_DEFAULTS, defaults_before)

        bad_target_args = _parse_args([
            '--format', '2v2',
            '--auto-teams-2v2', '1',  # 28 + 1 = 29 teams (odd)
            '--rr-rounds', '1',
            '--target-matches', '29',  # deficit=1 across 29 teams -> odd sum!
        ])
        with self.assertRaises(ValueError):
            tct.build_tournament_settings(bad_target_args, ['2v2'], roster, 'TMP1', 123)


class InMemoryTournamentTests(unittest.TestCase):
    def test_multi_round_tournament_and_disk_isolation(self):
        char_file = BACKEND_DIR / 'characters_data.py'
        before_bytes = char_file.read_bytes()
        before_hash = hashlib.sha256(before_bytes).hexdigest()
        before_roster = copy.deepcopy(characters_data.ALL_CHARACTERS)

        artifact_paths = [
            ROOT / 'ai_battle.log',
            ROOT / 'result.txt',
            ROOT / 'bracket_info.txt',
            BACKEND_DIR / 'ai_battle.log',
            BACKEND_DIR / 'result.txt',
            BACKEND_DIR / 'bracket_info.txt',
            BACKEND_DIR / 'prelim_avg_stats_results.txt',
        ]
        before_mtimes = {p: p.stat().st_mtime_ns if p.exists() else None for p in artifact_paths}

        args = _parse_args([
            '--name', '测试法师',
            '--serial', 'TMP1',
            '--attr', 'HP=11,MP=16,闪避=65,行动力=9',
            '--damage', '1d6+2',
            '--skill', 'name=星光弹,mp=2,type=1,客体=4,伤害骰=2d6+2,成功率=75,射程=8',
            '--skill', 'name=月华盾,mp=3,timing=23,type=2,客体=1,护盾值=2d6,持续回合=3',
            '--format', '1v1',
            '-n', '2',
            '--rr-rounds', '1',
            '--workers', '2',
            '-s', '42',
            '--season', '50',
            '--h2h',
        ])
        modes = tct.parse_formats(args.formats)
        temp_char = tct.build_temp_character(args)
        roster = tct.validate_temp_character(temp_char)
        cfg = tct.build_tournament_settings(args, modes, roster, temp_char['serial'], 42)
        report = tct.run_temp_tournament(temp_char, roster, cfg, modes, rounds=2, seed_val=42)

        n_opponents = len(before_roster)
        rows = report['standings']['1v1']
        self.assertEqual(len(rows), n_opponents + 1)
        tmp_row = next((r for r in rows if r['is_temp']), None)
        self.assertIsNotNone(tmp_row)
        self.assertEqual(tmp_row['key'], 'TMP1')
        self.assertEqual(tmp_row['avg_battles'], float(n_opponents))
        self.assertEqual(tmp_row['battles'], 2 * n_opponents)
        self.assertGreaterEqual(tmp_row['win_rate'], 0.0)
        self.assertLessEqual(tmp_row['win_rate'], 100.0)

        self.assertEqual(len(report['h2h_1v1']), n_opponents)
        self.assertTrue(all(r['battles'] == 2 for r in report['h2h_1v1']))

        text = tct.render_win_rate_report(report, show_h2h=True)
        self.assertIn('TMP1 测试法师', text)
        self.assertIn('<<< [临时角色]', text)
        self.assertIn('1v1 对位胜率明细', text)

        # Ensure zero mutation of global roster or characters_data.py or output logs
        self.assertEqual(characters_data.ALL_CHARACTERS, before_roster)
        self.assertEqual(hashlib.sha256(char_file.read_bytes()).hexdigest(), before_hash)
        for p in artifact_paths:
            after_mtime = p.stat().st_mtime_ns if p.exists() else None
            self.assertEqual(after_mtime, before_mtimes[p], f'Unexpected disk write to {p}')

    def test_replace_and_knockout_no_disk_writes(self):
        bracket_paths = [ROOT / 'bracket_info.txt', BACKEND_DIR / 'bracket_info.txt']
        before_mtimes = {p: p.stat().st_mtime_ns if p.exists() else None for p in bracket_paths}

        args = _parse_args([
            '--base', 'Y1',
            '--serial', 'Y1',
            '--name', '炎焱改',
            '--replace',
            '--attr', 'HP=17,闪避=72',
            '--format', '1v1',
            '-n', '1',
            '--rr-rounds', '1',
            '--workers', '2',
            '-s', '7',
            '--with-knockout',
        ])
        modes = tct.parse_formats(args.formats)
        temp_char = tct.build_temp_character(args)
        roster = tct.validate_temp_character(temp_char, replace=True)
        cfg = tct.build_tournament_settings(args, modes, roster, 'Y1', 7)
        report = tct.run_temp_tournament(
            temp_char, roster, cfg, modes, rounds=1, seed_val=7, with_knockout=True
        )
        overall_y1 = next(r for r in report['overall_win_rates'] if r['serial'] == 'Y1')
        self.assertEqual(overall_y1['name'], '炎焱改')
        self.assertTrue(overall_y1['is_temp'])
        self.assertGreaterEqual(overall_y1['battles'], len(characters_data.ALL_CHARACTERS) - 1)
        for p in bracket_paths:
            after_mtime = p.stat().st_mtime_ns if p.exists() else None
            self.assertEqual(after_mtime, before_mtimes[p], f'Unexpected knockout write to {p}')


class SubprocessCliTests(unittest.TestCase):
    def _clean_env(self):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env['PYTHONIOENCODING'] = 'utf-8'
        return env

    def test_show_schema_subprocess(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'temp_char_tournament.py'), '--show-schema'],
            cwd=str(ROOT),
            env=self._clean_env(),
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('临时角色参数速查', proc.stdout)
        self.assertIn('可用召唤物模板', proc.stdout)

    def test_cli_json_and_text_end_to_end_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / 'out.json'
            cmd = [
                sys.executable,
                str(SCRIPTS_DIR / 'temp_char_tournament.py'),
                '--name', '进程测试',
                '--serial', 'TMP_CLI',
                '--attr', 'HP=12,MP=14,闪避=60',
                '--damage', '1d6+1',
                '--skill', 'name=魔弹,mp=2,type=1,客体=4,伤害骰=2d6,成功率=75,射程=8',
                '--format', '1v1',
                '-n', '1',
                '--rr-rounds', '1',
                '--workers', '2',
                '-s', '99',
                '--h2h',
                '--json',
                '--out', str(out_file),
            ]
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=self._clean_env(),
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data['temp_character']['serial'], 'TMP_CLI')
            self.assertEqual(data['meta']['rounds'], 1)
            self.assertTrue(any(r['key'] == 'TMP_CLI' and r['is_temp'] for r in data['standings']['1v1']))
            self.assertEqual(len(data['h2h_1v1']), len(characters_data.ALL_CHARACTERS))
            self.assertEqual(json.loads(out_file.read_text(encoding='utf-8')), data)


if __name__ == '__main__':
    unittest.main()
