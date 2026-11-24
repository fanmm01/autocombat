#!/usr/bin/env python3
"""Auto-Chess multi-star composite power rating and balance calibration tool.

Evaluates every unit in ``autochess_catalog.UNIT_CATALOG`` across 1★/2★/3★ tiers
over three spatial arena presets (``autochess_standard``, ``autochess_compact``,
``autochess_citadel``) using mixed-star and same-star 2v2/3v3 bouts with active
synergies, tactical formation, and opening shields.

Composite Power Formula (0-100, roster-wide mean anchored at ~50.0):
    Power = 100.0 * (0.65 * sigmoid(BT_theta) + 0.25 * MixWR + 0.10 * PeerWR)
where BT_theta is fitted via L2-regularized team Bradley-Terry logistic regression
on all mixed-star bouts and zero-centered across all unit-star tiers.

Examples:
    python scripts/analysis/autochess_power_rating.py --workers 4
    python scripts/analysis/autochess_power_rating.py --star1-only --workers 4
    python scripts/analysis/autochess_power_rating.py --focus Y12 --workers 4
"""

import argparse
import concurrent.futures
import datetime
import json
import math
import os
import random
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_BACKEND = os.path.join(_ROOT, 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from ai_battle import AIController, BattleEngine, DisplayLevel
from ai_tactics import plan_formation
from arena_presets import build_arena_map
import autochess_catalog as ac

PRESETS = ('autochess_standard', 'autochess_compact', 'autochess_citadel')


def _ensure_backend_path():
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)


def _run_bout(preset, y_cfgs, x_cfgs, bout_seed):
    """Simulate a single Auto-Chess spatial bout under autochess_mode=True."""
    md = build_arena_map(preset)
    eng = BattleEngine(display_level=DisplayLevel.WINLOSS, delay=0, quiet=True, max_rounds=22)
    y_uids, y_sh = ac.apply_autochess_modifiers(eng, 'Y', y_cfgs, ac.compute_active_synergies(y_cfgs))
    x_uids, x_sh = ac.apply_autochess_modifiers(eng, 'X', x_cfgs, ac.compute_active_synergies(x_cfgs))
    ai_map = {c['uid']: AIController(c['uid'], ac.CHAR_DATA_BY_SERIAL[c['serial']], 'Y') for c in y_cfgs}
    ai_map.update({c['uid']: AIController(c['uid'], ac.CHAR_DATA_BY_SERIAL[c['serial']], 'X') for c in x_cfgs})

    coords = {}
    coords.update(plan_formation('Y', [{'uid': c['uid'], 'role': ac.UNIT_CATALOG[c['serial']]['role']} for c in y_cfgs], md))
    coords.update(plan_formation('X', [{'uid': c['uid'], 'role': ac.UNIT_CATALOG[c['serial']]['role']} for c in x_cfgs], md))
    eng.setup_battle(
        y_uids, x_uids,
        arena_preset=preset,
        autochess_mode=True,
        overtime_start_round=15,
        initial_coords=coords,
        track_stats=True,
    )
    shields = dict(y_sh)
    shields.update(x_sh)
    ac.apply_opening_shields(eng, shields)
    random.seed(bout_seed)
    res = eng.run_battle(ai_map)
    return eng, res


def _record_unit_stats(eng, res, y_cfgs, x_cfgs, stats, star_override=None):
    """Accumulate [games, wins, damage_dealt, healing_done] per unit key."""
    bst = getattr(eng, '_battle_stats', {}) or {}
    winner = res.get('winner')
    for side, cfgs in (('Y', y_cfgs), ('X', x_cfgs)):
        for cfg in cfgs:
            key = cfg['serial'] if star_override is not None else f"{cfg['serial']}:{cfg['star']}"
            row = stats[key]
            st = bst.get(eng._resolve_uid(cfg['uid']), {})
            row[0] += 1
            if winner == side:
                row[1] += 1
            row[2] += int(st.get('damage_dealt', 0) or 0)
            row[3] += int(st.get('healing_done', 0) or 0)


def _run_mixed_shard(task):
    """Worker entrypoint: simulate mixed-star 2v2/3v3 bouts for one RNG shard."""
    _ensure_backend_path()
    shard_seed, count, start_idx, serials = task
    rng = random.Random(shard_seed)
    bouts = []
    stats = {f'{s}:{st}': [0, 0, 0, 0] for s in serials for st in (1, 2, 3)}
    rounds_sum = 0
    timeouts = 0
    for offset in range(count):
        i = start_idx + offset
        preset = PRESETS[i % len(PRESETS)]
        sz = 2 if i % 2 == 0 else 3
        pick = rng.sample(serials, sz * 2)
        y_cfgs = [{'uid': f'Y{k}_{s}', 'serial': s, 'star': rng.randint(1, 3)} for k, s in enumerate(pick[:sz])]
        x_cfgs = [{'uid': f'X{k}_{s}', 'serial': s, 'star': rng.randint(1, 3)} for k, s in enumerate(pick[sz:])]
        bseed = rng.randint(1, 10**8)
        eng, res = _run_bout(preset, y_cfgs, x_cfgs, bseed)
        rounds_sum += int(res.get('rounds', 0) or 0)
        if res.get('timeout'):
            timeouts += 1
        w = 1 if res.get('winner') == 'Y' else (0 if res.get('winner') == 'X' else -1)
        if w in (0, 1):
            bouts.append(([f"{c['serial']}:{c['star']}" for c in y_cfgs],
                          [f"{c['serial']}:{c['star']}" for c in x_cfgs], w))
        _record_unit_stats(eng, res, y_cfgs, x_cfgs, stats)
    return {'stats': stats, 'bouts': bouts, 'rounds': rounds_sum, 'timeouts': timeouts, 'total': count}


def _run_peer_shard(task):
    """Worker entrypoint: simulate same-star 2v2/3v3 bouts at a fixed star level."""
    _ensure_backend_path()
    shard_seed, star, count, serials = task
    rng = random.Random(shard_seed)
    stats = {s: [0, 0, 0, 0] for s in serials}
    rounds_sum = 0
    timeouts = 0
    for i in range(count):
        preset = PRESETS[i % len(PRESETS)]
        sz = 2 if i % 2 == 0 else 3
        pick = rng.sample(serials, sz * 2)
        y_cfgs = [{'uid': f'Y{k}_{s}', 'serial': s, 'star': star} for k, s in enumerate(pick[:sz])]
        x_cfgs = [{'uid': f'X{k}_{s}', 'serial': s, 'star': star} for k, s in enumerate(pick[sz:])]
        bseed = rng.randint(1, 10**8)
        eng, res = _run_bout(preset, y_cfgs, x_cfgs, bseed)
        rounds_sum += int(res.get('rounds', 0) or 0)
        if res.get('timeout'):
            timeouts += 1
        _record_unit_stats(eng, res, y_cfgs, x_cfgs, stats, star_override=star)
    return {'star': star, 'stats': stats, 'rounds': rounds_sum, 'timeouts': timeouts, 'total': count}


def _run_focus_shard(task):
    """Worker entrypoint: run high-sample mixed + same-star bouts for one focus star."""
    _ensure_backend_path()
    shard_seed, focus_serial, star, mix_count, peer_count, serials = task
    others = [s for s in serials if s != focus_serial]
    rng = random.Random(shard_seed)
    mix_bouts = []
    mix_stat = [0, 0, 0, 0]
    peer_stat = [0, 0, 0, 0]
    rounds_sum = 0
    timeouts = 0

    def _run_side_focus(i, same_star):
        preset = PRESETS[i % len(PRESETS)]
        sz = 2 if i % 2 == 0 else 3
        pick = rng.sample(others, sz * 2 - 1)
        focus_on_y = (i % 4 < 2) if not same_star else (i % 2 == 0)
        ally_star = (lambda: star) if same_star else (lambda: rng.randint(1, 3))
        if focus_on_y:
            y_cfgs = [{'uid': f'Y0_{focus_serial}', 'serial': focus_serial, 'star': star}] + [
                {'uid': f'Y{k + 1}_{s}', 'serial': s, 'star': ally_star()} for k, s in enumerate(pick[:sz - 1])
            ]
            x_cfgs = [{'uid': f'X{k}_{s}', 'serial': s, 'star': ally_star()} for k, s in enumerate(pick[sz - 1:])]
            focus_uid, focus_side = f'Y0_{focus_serial}', 'Y'
        else:
            y_cfgs = [{'uid': f'Y{k}_{s}', 'serial': s, 'star': ally_star()} for k, s in enumerate(pick[:sz])]
            x_cfgs = [{'uid': f'X0_{focus_serial}', 'serial': focus_serial, 'star': star}] + [
                {'uid': f'X{k + 1}_{s}', 'serial': s, 'star': ally_star()} for k, s in enumerate(pick[sz:])
            ]
            focus_uid, focus_side = f'X0_{focus_serial}', 'X'
        bseed = rng.randint(1, 10**8)
        eng, res = _run_bout(preset, y_cfgs, x_cfgs, bseed)
        bst = getattr(eng, '_battle_stats', {}) or {}
        st = bst.get(eng._resolve_uid(focus_uid), {})
        target_stat = peer_stat if same_star else mix_stat
        target_stat[0] += 1
        if res.get('winner') == focus_side:
            target_stat[1] += 1
        target_stat[2] += int(st.get('damage_dealt', 0) or 0)
        target_stat[3] += int(st.get('healing_done', 0) or 0)
        return res, y_cfgs, x_cfgs

    for i in range(mix_count):
        res, y_cfgs, x_cfgs = _run_side_focus(i, same_star=False)
        rounds_sum += int(res.get('rounds', 0) or 0)
        if res.get('timeout'):
            timeouts += 1
        w = 1 if res.get('winner') == 'Y' else (0 if res.get('winner') == 'X' else -1)
        if w in (0, 1):
            mix_bouts.append(([f"{c['serial']}:{c['star']}" for c in y_cfgs],
                              [f"{c['serial']}:{c['star']}" for c in x_cfgs], w))

    for i in range(peer_count):
        _run_side_focus(i, same_star=True)

    return {
        'star': star,
        'mix_bouts': mix_bouts,
        'mix_stat': mix_stat,
        'peer_stat': peer_stat,
        'rounds': rounds_sum,
        'timeouts': timeouts,
        'mix_total': mix_count,
    }


def _dispatch_tasks(tasks, worker_fn, workers):
    if workers <= 1 or len(tasks) <= 1:
        return [worker_fn(t) for t in tasks]
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        return list(pool.map(worker_fn, tasks))


def fit_bradley_terry(bouts, keys, lam=3.0, iters=1200, lr=0.02):
    """Fit L2-regularized team Bradley-Terry ratings centered at 0 across keys."""
    ratings = {k: 0.0 for k in keys}
    for _ in range(iters):
        grad = {k: -lam * ratings[k] for k in keys}
        for yk, xk, w in bouts:
            diff = sum(ratings[u] for u in yk) - sum(ratings[u] for u in xk)
            p = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, diff))))
            err = w - p
            for u in yk:
                grad[u] += err
            for u in xk:
                grad[u] -= err
        for k in keys:
            ratings[k] += lr * grad[k] / 25.0
    mean_r = sum(ratings.values()) / max(1, len(ratings))
    for k in keys:
        ratings[k] -= mean_r
    return ratings


def fit_focus_bradley_terry(focus_serial, bouts, anchor_ratings, lam_focus=3.0, iters=1500, lr=0.015):
    """Fit focus unit's 1*/2*/3* BT ratings against anchored non-focus tier ratings."""
    focus_keys = [f'{focus_serial}:{st}' for st in (1, 2, 3)]
    rf = {k: 0.0 for k in focus_keys}
    for _ in range(iters):
        grad = {k: -lam_focus * rf[k] for k in focus_keys}
        for yk, xk, w in bouts:
            diff = (
                sum(rf[u] if u in rf else anchor_ratings[u] for u in yk)
                - sum(rf[u] if u in rf else anchor_ratings[u] for u in xk)
            )
            p = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, diff))))
            err = w - p
            for u in yk:
                if u in rf:
                    grad[u] += err
            for u in xk:
                if u in rf:
                    grad[u] -= err
        for k in focus_keys:
            rf[k] += lr * grad[k] / 25.0
    merged = dict(anchor_ratings)
    merged.update(rf)
    mean_r = sum(merged.values()) / max(1, len(merged))
    return {k: merged[k] - mean_r for k in focus_keys}


def compute_composite_power(bt_rating, mix_wr, peer_wr):
    bt_prob = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, bt_rating))))
    return 100.0 * (0.65 * bt_prob + 0.25 * mix_wr + 0.10 * peer_wr), bt_prob


def evaluate_roster(mix_bouts, peer_bouts, workers, seed, lam):
    """Run full-roster mixed-star and same-star benchmarks and score all unit tiers."""
    serials = sorted(ac.UNIT_CATALOG.keys(), key=lambda x: int(x[1:]))
    keys = [f'{s}:{st}' for s in serials for st in (1, 2, 3)]

    n_shards = max(1, min(workers, mix_bouts)) if mix_bouts > 0 else 0
    mix_tasks = []
    if n_shards > 0:
        base_cnt, rem = divmod(mix_bouts, n_shards)
        cursor = 0
        for idx in range(n_shards):
            cnt = base_cnt + (1 if idx < rem else 0)
            if cnt > 0:
                mix_tasks.append((seed + idx * 10001, cnt, cursor, serials))
                cursor += cnt

    peer_tasks = [(seed + 30000 + star * 1001, star, peer_bouts, serials) for star in (1, 2, 3)]

    if workers <= 1:
        mix_results = [_run_mixed_shard(t) for t in mix_tasks]
        peer_results = [_run_peer_shard(t) for t in peer_tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            mix_futs = [pool.submit(_run_mixed_shard, t) for t in mix_tasks]
            peer_futs = [pool.submit(_run_peer_shard, t) for t in peer_tasks]
            mix_results = [f.result() for f in mix_futs]
            peer_results = [f.result() for f in peer_futs]

    all_bouts = []
    mix_stats = {k: [0, 0, 0, 0] for k in keys}
    total_rounds = 0
    total_timeouts = 0
    total_mix_games = 0
    for res in mix_results:
        all_bouts.extend(res['bouts'])
        total_rounds += res['rounds']
        total_timeouts += res['timeouts']
        total_mix_games += res['total']
        for k, v in res['stats'].items():
            for idx in range(4):
                mix_stats[k][idx] += v[idx]

    peer_stats = {}
    for res in peer_results:
        star = res['star']
        total_rounds += res['rounds']
        total_timeouts += res['timeouts']
        for s, v in res['stats'].items():
            peer_stats[f'{s}:{star}'] = v

    bt_ratings = fit_bradley_terry(all_bouts, keys, lam=lam)

    rows = []
    by_unit = {s: {} for s in serials}
    for s in serials:
        meta = ac.UNIT_CATALOG[s]
        base_cost = meta['cost']
        for star in (1, 2, 3):
            k = f'{s}:{star}'
            mg, mw, mdmg, mheal = mix_stats[k]
            pg, pw, pdmg, pheal = peer_stats[k]
            mix_wr = mw / max(1, mg)
            peer_wr = pw / max(1, pg)
            power, bt_prob = compute_composite_power(bt_ratings[k], mix_wr, peer_wr)
            avg_dmg = (mdmg + pdmg) / max(1, mg + pg)
            avg_heal = (mheal + pheal) / max(1, mg + pg)
            entry = {
                'serial': s,
                'name': meta['name'],
                'star': star,
                'cost': base_cost,
                'gold': base_cost * (3 ** (star - 1)),
                'role': meta['role'],
                'traits': list(meta['traits']),
                'power': round(power, 2),
                'bt_pct': round(bt_prob * 100.0, 1),
                'mix_wr_pct': round(mix_wr * 100.0, 1),
                'peer_wr_pct': round(peer_wr * 100.0, 1),
                'avg_dmg': round(avg_dmg, 1),
                'avg_heal': round(avg_heal, 1),
                'mix_games': mg,
                'mix_wins': mw,
                'peer_games': pg,
                'peer_wins': pw,
            }
            rows.append(entry)
            by_unit[s][star] = entry

    unit_summaries = []
    for s in serials:
        meta = ac.UNIT_CATALOG[s]
        s1, s2, s3 = by_unit[s][1], by_unit[s][2], by_unit[s][3]
        avg_power = (s1['power'] + s2['power'] + s3['power']) / 3.0
        avg_dmg = (s1['avg_dmg'] + s2['avg_dmg'] + s3['avg_dmg']) / 3.0
        avg_heal = (s1['avg_heal'] + s2['avg_heal'] + s3['avg_heal']) / 3.0
        unit_summaries.append({
            'serial': s,
            'name': meta['name'],
            'cost': meta['cost'],
            'role': meta['role'],
            'traits': list(meta['traits']),
            'star1': s1,
            'star2': s2,
            'star3': s3,
            'avg_power': round(avg_power, 2),
            'avg_dmg': round(avg_dmg, 1),
            'avg_heal': round(avg_heal, 1),
        })
    unit_summaries.sort(key=lambda u: (-u['avg_power'], u['serial']))

    total_games = total_mix_games + peer_bouts * 3
    return {
        'serials': serials,
        'rows': sorted(rows, key=lambda r: (-r['power'], r['serial'], r['star'])),
        'by_unit': by_unit,
        'unit_summaries': unit_summaries,
        'bt_ratings': bt_ratings,
        'total_bouts': total_games,
        'mix_bouts': total_mix_games,
        'peer_bouts_per_star': peer_bouts,
        'avg_rounds': round(total_rounds / max(1, total_games), 2),
        'timeout_rate_pct': round(100.0 * total_timeouts / max(1, total_games), 2),
    }


def evaluate_focus(focus_serial, anchor_ratings, focus_mix_per_star, focus_peer_per_star, workers, seed, lam):
    """Run high-precision focused evaluation for a single unit anchored on roster ratings."""
    serials = sorted(ac.UNIT_CATALOG.keys(), key=lambda x: int(x[1:]))
    tasks = [
        (seed + 70000 + star * 701, focus_serial, star, focus_mix_per_star, focus_peer_per_star, serials)
        for star in (1, 2, 3)
    ]
    results = _dispatch_tasks(tasks, _run_focus_shard, workers)

    mix_bouts = []
    mix_by_star = {}
    peer_by_star = {}
    rounds_sum = 0
    timeouts = 0
    mix_total = 0
    for res in results:
        st = res['star']
        mix_bouts.extend(res['mix_bouts'])
        mix_by_star[st] = res['mix_stat']
        peer_by_star[st] = res['peer_stat']
        rounds_sum += res['rounds']
        timeouts += res['timeouts']
        mix_total += res['mix_total']

    scaled_lam = lam * max(0.5, focus_mix_per_star / 100.0)
    r_scaled = fit_focus_bradley_terry(focus_serial, mix_bouts, anchor_ratings, lam_focus=scaled_lam)
    r_raw = fit_focus_bradley_terry(focus_serial, mix_bouts, anchor_ratings, lam_focus=lam)

    tiers = {}
    for star in (1, 2, 3):
        k = f'{focus_serial}:{star}'
        mg, mw, mdmg, mheal = mix_by_star[star]
        pg, pw, pdmg, pheal = peer_by_star[star]
        mix_wr = mw / max(1, mg)
        peer_wr = pw / max(1, pg)
        p_scaled, bt_scaled = compute_composite_power(r_scaled[k], mix_wr, peer_wr)
        p_raw, bt_raw = compute_composite_power(r_raw[k], mix_wr, peer_wr)
        tiers[star] = {
            'star': star,
            'power': round(p_scaled, 2),
            'power_lam_raw': round(p_raw, 2),
            'bt_pct': round(bt_scaled * 100.0, 1),
            'bt_raw_pct': round(bt_raw * 100.0, 1),
            'mix_wr_pct': round(mix_wr * 100.0, 1),
            'peer_wr_pct': round(peer_wr * 100.0, 1),
            'mix_wins': mw,
            'mix_games': mg,
            'peer_wins': pw,
            'peer_games': pg,
            'avg_dmg': round((mdmg + pdmg) / max(1, mg + pg), 1),
            'avg_heal': round((mheal + pheal) / max(1, mg + pg), 1),
        }

    return {
        'serial': focus_serial,
        'name': ac.UNIT_CATALOG[focus_serial]['name'],
        'cost': ac.UNIT_CATALOG[focus_serial]['cost'],
        'scaled_lam': round(scaled_lam, 2),
        'raw_lam': lam,
        'mix_per_star': focus_mix_per_star,
        'peer_per_star': focus_peer_per_star,
        'avg_rounds': round(rounds_sum / max(1, mix_total), 2),
        'timeout_rate_pct': round(100.0 * timeouts / max(1, mix_total), 2),
        'tiers': tiers,
        'avg_power': round(sum(tiers[st]['power'] for st in (1, 2, 3)) / 3.0, 2),
        'avg_power_lam_raw': round(sum(tiers[st]['power_lam_raw'] for st in (1, 2, 3)) / 3.0, 2),
    }


def render_markdown(report_data, star1_only=False):
    lines = [
        '# 自走棋棋子分星级综合强度评估报告',
        '',
        f'- 生成时间：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'- 样本规模：混星 {report_data["mix_bouts"]} 场 + 同星 {report_data["peer_bouts_per_star"]}×3 场（共 {report_data["total_bouts"]} 场）'
        f' | 场均回合：{report_data["avg_rounds"]:.2f} | 超时率：{report_data["timeout_rate_pct"]:.2f}%',
        '- 评分公式：`Power = 100 × (0.65 × sigmoid(BT) + 0.25 × MixWR + 0.10 × PeerWR)`',
        '',
    ]

    if not star1_only:
        lines.extend([
            '## 1. 全棋子综合强度总榜（按三星均强排序）',
            '',
            '| 排名 | 棋子 | 费 | 定位 | 1★ 强度 (同星胜率) | 2★ 强度 (同星胜率) | 3★ 强度 (同星胜率) | 三星均强 | 场均伤害 | 场均治疗 |',
            '|---:|---|---:|---|---:|---:|---:|---:|---:|---:|',
        ])
        for rank, u in enumerate(report_data['unit_summaries'], 1):
            s1, s2, s3 = u['star1'], u['star2'], u['star3']
            lines.append(
                f'| {rank} | {u["serial"]} {u["name"]} | {u["cost"]}G | {u["role"]} | '
                f'{s1["power"]:.1f} ({s1["peer_wr_pct"]:.1f}%) | '
                f'{s2["power"]:.1f} ({s2["peer_wr_pct"]:.1f}%) | '
                f'{s3["power"]:.1f} ({s3["peer_wr_pct"]:.1f}%) | '
                f'**{u["avg_power"]:.1f}** | {u["avg_dmg"]:.1f} | {u["avg_heal"]:.1f} |'
            )
        lines.append('')

    section_no = 1 if star1_only else 2
    star1_rows = sorted((u['star1'] for u in report_data['unit_summaries']), key=lambda r: (-r['power'], r['serial']))
    lines.extend([
        f'## {section_no}. 1★ 单星强度排行榜',
        '',
        '| 排名 | 棋子 | 费 | 定位 | 1★ 综合强度 | BT 胜率基线 | 混星胜率 | 同星胜率 | 场均伤害 | 场均治疗 |',
        '|---:|---|---:|---|---:|---:|---:|---:|---:|---:|',
    ])
    for rank, r in enumerate(star1_rows, 1):
        lines.append(
            f'| {rank} | {r["serial"]} {r["name"]} | {r["cost"]}G | {r["role"]} | '
            f'**{r["power"]:.1f}** | {r["bt_pct"]:.1f}% | {r["mix_wr_pct"]:.1f}% | {r["peer_wr_pct"]:.1f}% | '
            f'{r["avg_dmg"]:.1f} | {r["avg_heal"]:.1f} |'
        )
    lines.append('')

    if not star1_only:
        lines.extend([
            '## 3. 按费用分档均值对比',
            '',
            '| 费用 | 棋子数 | 1★ 均强 | 2★ 均强 | 3★ 均强 | 三星总均强 |',
            '|---:|---:|---:|---:|---:|---:|',
        ])
        costs = sorted({r['cost'] for r in report_data['rows']})
        for cost in costs:
            for_cost = [r for r in report_data['rows'] if r['cost'] == cost]
            n_units = len({r['serial'] for r in for_cost})
            star_avgs = [
                sum(r['power'] for r in for_cost if r['star'] == st) / max(1, n_units)
                for st in (1, 2, 3)
            ]
            total_avg = sum(r['power'] for r in for_cost) / max(1, len(for_cost))
            lines.append(
                f'| {cost}费 | {n_units} | {star_avgs[0]:.1f} | {star_avgs[1]:.1f} | {star_avgs[2]:.1f} | **{total_avg:.1f}** |'
            )
        lines.append('')

        lines.extend([
            f'## 4. 全池 {len(report_data["rows"])} 档完整强度榜（分棋子×星级）',
            '',
            '| 排名 | 棋子 | 星级 | 基础费 | 升星花费 | 定位 | 羁绊 | 综合强度 | BT | 混星胜率 | 同星胜率 | 场均伤害 | 场均治疗 |',
            '|---:|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|',
        ])
        for rank, r in enumerate(report_data['rows'], 1):
            lines.append(
                f'| {rank} | {r["serial"]} {r["name"]} | {r["star"]}★ | {r["cost"]}G | {r["gold"]}G | '
                f'{r["role"]} | {"/".join(r["traits"])} | **{r["power"]:.1f}** | {r["bt_pct"]:.1f}% | '
                f'{r["mix_wr_pct"]:.1f}% | {r["peer_wr_pct"]:.1f}% | {r["avg_dmg"]:.1f} | {r["avg_heal"]:.1f} |'
            )
        lines.append('')

    focus = report_data.get('focus')
    if focus:
        lines.extend([
            f'## 专项高精度校准：{focus["serial"]} {focus["name"]} ({focus["cost"]}G)',
            '',
            f'- 专项样本：每星级混星 {focus["mix_per_star"]} 场 + 同星 {focus["peer_per_star"]} 场（场均回合 {focus["avg_rounds"]:.2f}）',
            f'- 对齐先验 `lam={focus["scaled_lam"]}` 三星均强：**{focus["avg_power"]:.2f}**'
            f'（原始 `lam={focus["raw_lam"]}`：**{focus["avg_power_lam_raw"]:.2f}**）',
            '',
            '| 星级 | 综合强度 (对齐先验) | 综合强度 (原始先验) | BT | 混星胜率 | 同星胜率 | 场均伤害 | 场均治疗 |',
            '|---:|---:|---:|---:|---:|---:|---:|---:|',
        ])
        for star in (1, 2, 3):
            t = focus['tiers'][star]
            lines.append(
                f'| {star}★ | **{t["power"]:.2f}** | {t["power_lam_raw"]:.2f} | {t["bt_pct"]:.1f}% | '
                f'{t["mix_wr_pct"]:.1f}% ({t["mix_wins"]}/{t["mix_games"]}) | '
                f'{t["peer_wr_pct"]:.1f}% ({t["peer_wins"]}/{t["peer_games"]}) | '
                f'{t["avg_dmg"]:.1f} | {t["avg_heal"]:.1f} |'
            )
        lines.append('')

    return '\n'.join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Auto-Chess multi-star composite strength rating & calibration tool.')
    parser.add_argument('--mix-bouts', type=int, default=1050, help='Total mixed-star 2v2/3v3 bouts (default: 1050)')
    parser.add_argument('--peer-bouts', type=int, default=260, help='Same-star bouts per star 1★/2★/3★ (default: 260)')
    parser.add_argument('--workers', type=int, default=4, help='Worker processes for parallel simulation (default: 4)')
    parser.add_argument('--seed', type=int, default=10001, help='Base RNG seed (default: 10001)')
    parser.add_argument('--lam', type=float, default=3.0, help='Bradley-Terry L2 regularization strength (default: 3.0)')
    parser.add_argument('--star1-only', action='store_true', help='Only output the 1★ ranking table')
    parser.add_argument('--focus', type=str, default=None, help='Optional unit serial (e.g. Y12) for focused calibration')
    parser.add_argument('--focus-mix-per-star', type=int, default=250, help='Mixed-star bouts per star in --focus mode')
    parser.add_argument('--focus-peer-per-star', type=int, default=100, help='Same-star bouts per star in --focus mode')
    parser.add_argument('--out-md', type=str, default=None, help='Optional path to write Markdown report')
    parser.add_argument('--out-json', type=str, default=None, help='Optional path to write JSON results')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.focus:
        focus_serial = args.focus.strip().upper()
        if focus_serial not in ac.UNIT_CATALOG:
            raise SystemExit(f'Unknown serial for --focus: {args.focus}')
    else:
        focus_serial = None

    report_data = evaluate_roster(
        mix_bouts=args.mix_bouts,
        peer_bouts=args.peer_bouts,
        workers=max(1, args.workers),
        seed=args.seed,
        lam=args.lam,
    )
    if focus_serial:
        report_data['focus'] = evaluate_focus(
            focus_serial=focus_serial,
            anchor_ratings=report_data['bt_ratings'],
            focus_mix_per_star=args.focus_mix_per_star,
            focus_peer_per_star=args.focus_peer_per_star,
            workers=max(1, args.workers),
            seed=args.seed,
            lam=args.lam,
        )

    md_text = render_markdown(report_data, star1_only=args.star1_only)
    print(md_text)

    if args.out_md:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_md)), exist_ok=True)
        with open(args.out_md, 'w', encoding='utf-8') as f:
            f.write(md_text + '\n')

    if args.out_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
        payload = {k: v for k, v in report_data.items() if k != 'by_unit'}
        with open(args.out_json, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
