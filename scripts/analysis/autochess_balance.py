#!/usr/bin/env python3
"""Spatial & Auto-Chess balance verification harness.

Checks:
1. Mirror side-swap symmetry (Y vs X win rate & 95% CI).
2. Spatial Tactical AI vs Legacy Rule AI win rate on spatial arenas.
3. 2v2 / 3v3 role & unit win rates, overtime/timeout rates across Y1-Y17.
4. Full 4-commander AI lobby simulations (personality meta, round length, pool conservation).

Outputs summary report to archive/artifacts/balance_autochess/report.md.
"""

import copy
import datetime
import math
import os
import random
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_BACKEND = os.path.join(_ROOT, 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from ai_battle import AIController, BattleEngine, DisplayLevel
from ai_trainer import affordable_actions, get_available_actions
from ai_tactics import plan_formation
from arena_presets import build_arena_map
from autochess_ai import run_commander_prep
from autochess_catalog import CHAR_DATA_BY_SERIAL, POOL_COUNTS, UNIT_CATALOG
from autochess_match import AutoChessMatch
from characters_data import load_character_to_engine


class _LegacyRuleAI(AIController):
    """Runs classic Q-table / legacy rule AI inside autochess arenas as a baseline."""

    def decide_action(self, engine, user_id):
        if engine._get_my_actions(user_id).get('主动', 0) <= 0:
            return '.i end'
        failed = getattr(engine, '_ai_failed_commands', set())
        try:
            cmd = self._decide_action(engine, user_id)
        except UnboundLocalError:
            cmd = '.s0'
        if cmd not in failed:
            return cmd
        for key, _ in affordable_actions(engine, user_id, get_available_actions(engine, user_id)):
            alt = self._command_for_action(engine, user_id, key)
            if alt and alt not in failed:
                return alt
        return '.i end'


def _wilson_ci(wins, total):
    if total <= 0:
        return (0.0, 0.0, 0.0)
    z = 1.96
    p = wins / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = (z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def _run_arena_bout(team_y, team_x, preset, seed, *, legacy_side=None, star=1):
    random.seed(seed)
    md = build_arena_map(preset)
    eng = BattleEngine(display_level=DisplayLevel.WINLOSS, delay=0, quiet=True, max_rounds=22)
    ai_map = {}
    y_uids, x_uids = [], []
    for side, roster, uid_list in (('Y', team_y, y_uids), ('X', team_x, x_uids)):
        for i, cid in enumerate(roster):
            uid = f'{side}{i}_{cid}'
            cd = copy.deepcopy(CHAR_DATA_BY_SERIAL[cid])
            load_character_to_engine(eng, cd, uid)
            uid_list.append(uid)
            if legacy_side == side:
                ai_map[uid] = _LegacyRuleAI(uid, cd, side)
            else:
                ai_map[uid] = AIController(uid, cd, side)
    coords = {}
    if legacy_side != 'Y':
        coords.update(plan_formation('Y', [{'uid': u, 'role': UNIT_CATALOG[u.split('_', 1)[1]]['role']} for u in y_uids], md))
    if legacy_side != 'X':
        coords.update(plan_formation('X', [{'uid': u, 'role': UNIT_CATALOG[u.split('_', 1)[1]]['role']} for u in x_uids], md))
    eng.setup_battle(
        y_uids, x_uids,
        arena_preset=preset,
        autochess_mode=True,
        overtime_start_round=15,
        initial_coords=coords,
        track_stats=True,
    )
    res = eng.run_battle(ai_map)
    return res, eng


def bench_mirror_symmetry(n_pairs=60, seed=1001):
    rng = random.Random(seed)
    serials = list(UNIT_CATALOG.keys())
    presets = ['autochess_standard', 'autochess_compact', 'autochess_citadel']
    y_wins = 0
    total = 0
    per_preset = {p: [0, 0] for p in presets}
    for i in range(n_pairs):
        preset = presets[i % len(presets)]
        sz = 2 if i % 2 == 0 else 3
        a = rng.sample(serials, sz)
        b = rng.sample(serials, sz)
        s = rng.randint(1, 10**8)
        for ta, tb in ((a, b), (b, a)):
            res, _ = _run_arena_bout(ta, tb, preset, s)
            total += 1
            per_preset[preset][1] += 1
            if res.get('winner') == 'Y':
                y_wins += 1
                per_preset[preset][0] += 1
    p, lo, hi = _wilson_ci(y_wins, total)
    return {
        'y_wins': y_wins,
        'total': total,
        'y_rate': p,
        'ci_low': lo,
        'ci_high': hi,
        'per_preset': {k: (v[0], v[1], v[0] / max(1, v[1])) for k, v in per_preset.items()},
    }


def bench_spatial_vs_legacy(n_pairs=45, seed=2002):
    rng = random.Random(seed)
    serials = list(UNIT_CATALOG.keys())
    presets = ['autochess_standard', 'autochess_citadel']
    spatial_wins = 0
    total = 0
    for i in range(n_pairs):
        preset = presets[i % len(presets)]
        sz = 2 if i % 2 == 0 else 3
        team = rng.sample(serials, sz)
        s = rng.randint(1, 10**8)
        for legacy_side in ('X', 'Y'):
            res, _ = _run_arena_bout(team, team, preset, s, legacy_side=legacy_side)
            spatial_side = 'Y' if legacy_side == 'X' else 'X'
            total += 1
            if res.get('winner') == spatial_side:
                spatial_wins += 1
    p, lo, hi = _wilson_ci(spatial_wins, total)
    return {'wins': spatial_wins, 'total': total, 'rate': p, 'ci_low': lo, 'ci_high': hi}


def bench_team_roster(n_bouts=120, seed=3003):
    rng = random.Random(seed)
    serials = list(UNIT_CATALOG.keys())
    presets = ['autochess_standard', 'autochess_compact', 'autochess_citadel']
    unit_stats = {s: {'games': 0, 'wins': 0, 'dmg': 0, 'heal': 0} for s in serials}
    timeouts = 0
    rounds_sum = 0
    for i in range(n_bouts):
        preset = presets[i % len(presets)]
        sz = 2 if i % 2 == 0 else 3
        pick = rng.sample(serials, sz * 2)
        ta, tb = pick[:sz], pick[sz:]
        res, eng = _run_arena_bout(ta, tb, preset, rng.randint(1, 10**8))
        winner = res.get('winner')
        rounds_sum += int(res.get('rounds', 0) or 0)
        if res.get('timeout'):
            timeouts += 1
        stats = getattr(eng, '_battle_stats', {}) or {}
        for uid, team in getattr(eng, '_team_roster', []):
            cid = eng.get_char(uid).serial
            if cid not in unit_stats:
                continue
            st = stats.get(eng._resolve_uid(uid), {})
            unit_stats[cid]['games'] += 1
            if team == winner:
                unit_stats[cid]['wins'] += 1
            unit_stats[cid]['dmg'] += int(st.get('damage_dealt', 0) or 0)
            unit_stats[cid]['heal'] += int(st.get('healing_done', 0) or 0)
    return {
        'bouts': n_bouts,
        'timeout_rate': timeouts / max(1, n_bouts),
        'avg_rounds': rounds_sum / max(1, n_bouts),
        'units': unit_stats,
    }


def bench_ai_lobbies(n_lobbies=40, seed=4004):
    presets = ['autochess_standard', 'autochess_compact', 'autochess_citadel']
    expected_pool_total = sum(POOL_COUNTS[m['cost']] for m in UNIT_CATALOG.values())
    pers_wins = {}
    pers_top2 = {}
    pers_games = {}
    rounds_list = []
    two_stars_total = 0
    three_stars_total = 0
    winning_serials = {}
    pool_leaks = 0

    for idx in range(n_lobbies):
        preset = presets[idx % len(presets)]
        m = AutoChessMatch(mode='lobby4', arena_preset=preset, seed=seed + idx * 17, player_name='苍星·平衡测试AI')
        # Turn P1 into balanced AI commander for symmetrical 4-AI lobby telemetry
        m.commanders['P1']['is_human'] = False
        m.commanders['P1']['personality'] = 'balanced'

        guard = 0
        while m.phase != 'finished' and guard < 35:
            guard += 1
            if m.phase == 'prep':
                if m.commanders['P1'].get('pending_augments'):
                    m.pick_augment('P1', m.commanders['P1']['pending_augments'][0]['id'])
                run_commander_prep(m, 'P1')
                m.start_combat()
            if m.phase == 'combat':
                m.resolve_combat()
            if m.phase == 'round_result':
                m.next_round()

        # Check pool conservation at match end
        owned = sum(
            3 ** (u['star'] - 1)
            for cmd in m.commanders.values() if not cmd.get('eliminated')
            for u in cmd['units']
        )
        if owned + sum(m.pool.values()) != expected_pool_total:
            pool_leaks += 1

        rounds_list.append(m.round_num)
        for cid, cmd in m.commanders.items():
            pers = cmd['personality']
            pers_games[pers] = pers_games.get(pers, 0) + 1
            pl = cmd.get('placement') or (1 if cid == m.winner_id else 4)
            if cid == m.winner_id or pl == 1:
                pers_wins[pers] = pers_wins.get(pers, 0) + 1
                for u in cmd['units']:
                    if u['location'] == 'board':
                        winning_serials[u['serial']] = winning_serials.get(u['serial'], 0) + 1
            if pl <= 2:
                pers_top2[pers] = pers_top2.get(pers, 0) + 1
            for u in cmd['units']:
                if u['star'] == 2:
                    two_stars_total += 1
                elif u['star'] == 3:
                    three_stars_total += 1

    return {
        'lobbies': n_lobbies,
        'avg_rounds': sum(rounds_list) / max(1, len(rounds_list)),
        'pool_leaks': pool_leaks,
        'two_stars_per_lobby': two_stars_total / max(1, n_lobbies),
        'three_stars_per_lobby': three_stars_total / max(1, n_lobbies),
        'pers_rates': {
            p: {
                'games': pers_games[p],
                'win_rate': pers_wins.get(p, 0) / pers_games[p],
                'top2_rate': pers_top2.get(p, 0) / pers_games[p],
            }
            for p in sorted(pers_games)
        },
        'top_winning_units': sorted(winning_serials.items(), key=lambda x: -x[1])[:8],
    }


def write_report(sym, svl, team_res, lobby_res, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    lines = [
        '# 空间与自走棋模式平衡性验证报告',
        '',
        f'- 生成时间：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        '- 测试基准：全部战斗均运行于 `autochess_mode=True` 独立分支；经典模式未受任何改动。',
        '',
        '## 1. 镜像换边对称性校验',
        '',
        f'- 对局规模：{sym["total"]} 场镜像互换双边对局（覆盖 10×7 / 8×6 / 12×8）',
        f'- Y队（先手/左方阵地）胜率：**{sym["y_rate"] * 100:.2f}%** （95% Wilson CI: `{sym["ci_low"] * 100:.2f}% ~ {sym["ci_high"] * 100:.2f}%`）',
        '',
        '| 战场预设 | Y队胜场 | 总场次 | Y胜率 |',
        '|---|---:|---:|---:|',
    ]
    for p, (yw, tot, r) in sym['per_preset'].items():
        lines.append(f'| `{p}` | {yw} | {tot} | {r * 100:.1f}% |')

    lines.extend([
        '',
        '## 2. 空间战术 AI 对阵传统规则 AI',
        '',
        f'- 对局规模：{svl["total"]} 场同阵容双边互换对局',
        f'- 空间战术 AI（`ai_tactics` + 自动排阵）胜率：**{svl["rate"] * 100:.2f}%** （95% CI: `{svl["ci_low"] * 100:.2f}% ~ {svl["ci_high"] * 100:.2f}%`）',
        '',
        '## 3. 2v2 / 3v3 角色贡献与加时压迫统计',
        '',
        f'- 总局数：{team_res["bouts"]} | 平均战斗轮次：**{team_res["avg_rounds"]:.2f}** | 超时率：**{team_res["timeout_rate"] * 100:.2f}%**',
        '',
        '| 编号 | 角色 | 费/定位 | 参战 | 胜率 | 场均伤害 | 场均治疗 |',
        '|---|---|---|---:|---:|---:|---:|',
    ])
    for s, st in sorted(team_res['units'].items(), key=lambda kv: (-kv[1]['wins'] / max(1, kv[1]['games']), kv[0])):
        meta = UNIT_CATALOG[s]
        g = max(1, st['games'])
        wr = st['wins'] / g * 100
        lines.append(f'| {s} | {meta["name"]} | {meta["cost"]}费 · {meta["role"]} | {st["games"]} | {wr:.1f}% | {st["dmg"]/g:.1f} | {st["heal"]/g:.1f} |')

    lines.extend([
        '',
        '## 4. 4 人自走棋 AI 大厅全流程生态模拟',
        '',
        f'- 模拟局数：**{lobby_res["lobbies"]}** | 平均结算回合：**{lobby_res["avg_rounds"]:.1f}** | 公共牌库泄露：**{lobby_res["pool_leaks"]}**',
        f'- 场均最终场上/席位 2★ 数：**{lobby_res["two_stars_per_lobby"]:.2f}** | 3★ 数：**{lobby_res["three_stars_per_lobby"]:.2f}**',
        '',
        '| 指挥官策略 | 局数 | 吃鸡率 | 前二率 |',
        '|---|---:|---:|---:|',
    ])
    for pers, pr in lobby_res['pers_rates'].items():
        lines.append(f'| `{pers}` | {pr["games"]} | {pr["win_rate"]*100:.1f}% | {pr["top2_rate"]*100:.1f}% |')

    lines.append('')
    lines.append('- 冠军高频核心：' + '、'.join(f'{UNIT_CATALOG[s]["name"]}({s})×{c}' for s, c in lobby_res['top_winning_units']))

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    AIController.load_q_table()
    sym = bench_mirror_symmetry(n_pairs=100)
    print(f'[1/4 Symmetry] Y={sym["y_wins"]}/{sym["total"]} ({sym["y_rate"]*100:.1f}%), CI=[{sym["ci_low"]*100:.1f}%, {sym["ci_high"]*100:.1f}%]')
    svl = bench_spatial_vs_legacy(n_pairs=45)
    print(f'[2/4 Spatial vs Legacy] Spatial={svl["wins"]}/{svl["total"]} ({svl["rate"]*100:.1f}%)')
    team_res = bench_team_roster(n_bouts=120)
    print(f'[3/4 2v2/3v3 Roster] avg_rounds={team_res["avg_rounds"]:.2f}, timeout_rate={team_res["timeout_rate"]*100:.1f}%')
    lobby_res = bench_ai_lobbies(n_lobbies=40)
    print(f'[4/4 4-AI Lobbies] avg_rounds={lobby_res["avg_rounds"]:.1f}, leaks={lobby_res["pool_leaks"]}, 2★/lobby={lobby_res["two_stars_per_lobby"]:.2f}, 3★/lobby={lobby_res["three_stars_per_lobby"]:.2f}')

    out_path = os.path.join(_ROOT, 'archive', 'artifacts', 'balance_autochess', 'report.md')
    write_report(sym, svl, team_res, lobby_res, out_path)
    print(f'Report saved to {out_path}')


if __name__ == '__main__':
    main()
