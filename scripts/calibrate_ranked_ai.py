"""Parallel Monte Carlo calibration & verification for 6-tier 12-archetype Auto-Chess AI."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in ('backend', 'dev', 'scripts'):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

from autochess_ai import (
    RANKED_AI_ARCHETYPES,
    build_ranked_ai_profile,
    generate_ranked_bots,
    run_commander_prep,
)
from autochess_match import AutoChessMatch
from autochess_ranked import RANK_TIERS


def _make_bot_cfg(name, personality, profile=None, style_label=''):
    return {
        'name': name,
        'personality': personality,
        'ai_profile': profile,
        'ai_style_label': style_label,
    }


def _simulate_duel_task(task):
    cfg_a, cfg_b, seed, swap = task
    random.seed(int(seed) ^ (0x9E3779B9 if swap else 0x517CC1B7))
    left_cfg, right_cfg = (cfg_b, cfg_a) if swap else (cfg_a, cfg_b)

    m = AutoChessMatch(mode='lobby4', arena_preset='autochess_standard', seed=seed)
    for cid in ('P3', 'P4'):
        m._eliminate_commander(cid)

    for cid, cfg in (('P1', left_cfg), ('P2', right_cfg)):
        cmd = m.commanders[cid]
        cmd['name'] = cfg['name']
        cmd['is_human'] = False
        cmd['personality'] = cfg['personality']
        cmd['ai_profile'] = cfg.get('ai_profile')
        cmd['ai_style_label'] = cfg.get('ai_style_label', '')

    max_rounds = 24
    while m.round_num <= max_rounds and m.phase != 'finished':
        run_commander_prep(m, 'P1')
        run_commander_prep(m, 'P2')
        p1 = m.commanders['P1']
        p2 = m.commanders['P2']
        out = m._run_headless_bout(
            {
                'units': m.board_units('P1'),
                'augments': p1['augments'],
                'tactics_profile': (p1.get('ai_profile') or {}).get('tactics_profile'),
            },
            {
                'units': m.board_units('P2'),
                'augments': p2['augments'],
                'tactics_profile': (p2.get('ai_profile') or {}).get('tactics_profile'),
            },
            m.arena_preset,
            seed + m.round_num * 1009,
        )
        p1_won = (out['winner'] == 'Y')
        m._apply_combat_hp_and_streak('P1', p1_won, out['surviving_x'])
        m._apply_combat_hp_and_streak('P2', not p1_won, out['surviving_y'])
        if p1['eliminated'] or p2['eliminated']:
            if p1['eliminated'] and p2['eliminated']:
                res = 'draw'
            elif p1['eliminated']:
                res = 'B' if not swap else 'A'
            else:
                res = 'A' if not swap else 'B'
            return res
        if p1_won:
            p1['gold'] += 1
        else:
            p2['gold'] += 1
        m.round_num += 1
        for cid in ('P1', 'P2'):
            m._grant_round_income(cid)
        m._offer_augments_if_due()

    p1_ahead = m.commanders['P1']['hp'] >= m.commanders['P2']['hp']
    return ('B' if p1_ahead else 'A') if swap else ('A' if p1_ahead else 'B')


def _evaluate_pairs(executor, tasks_by_key):
    flat_keys = []
    flat_tasks = []
    for key, task_list in tasks_by_key.items():
        for t in task_list:
            flat_keys.append(key)
            flat_tasks.append(t)

    counts = {k: [0.0, 0.0] for k in tasks_by_key}
    for key, res in zip(flat_keys, executor.map(_simulate_duel_task, flat_tasks)):
        if res == 'A':
            counts[key][0] += 1.0
        elif res == 'B':
            counts[key][1] += 1.0
        else:
            counts[key][0] += 0.5
            counts[key][1] += 0.5

    ratios = {}
    for key, (wa, wb) in counts.items():
        tot = max(1.0, wa + wb)
        ratios[key] = (wa / tot, wb / tot)
    return ratios


def main():
    parser = argparse.ArgumentParser(description='Calibrate Auto-Chess ranked AI winrates and tier curve.')
    parser.add_argument('--trials', type=int, default=24, help='Duels per pair (recommend 20-48)')
    parser.add_argument('--seed', type=int, default=202611, help='Base RNG seed')
    parser.add_argument('--workers', type=int, default=min(6, os.cpu_count() or 4), help='Worker processes')
    args = parser.parse_args()

    print(f'[1/3] Archetype coverage: {len(RANKED_AI_ARCHETYPES)} strategies x {len(RANK_TIERS)} tiers = {len(RANKED_AI_ARCHETYPES) * len(RANK_TIERS)} profiles (workers={args.workers})')
    assert len(RANKED_AI_ARCHETYPES) >= 12
    for t in RANK_TIERS:
        bots = generate_ranked_bots(t['id'], count=7, rng=random.Random(args.seed + len(t['id'])))
        assert len(bots) == 7
        assert len({b['ai_profile']['archetype_id'] for b in bots}) == 7
        assert len({b['name'] for b in bots}) == 7

    strong_archs = [a for a in RANKED_AI_ARCHETYPES if a['band'] == 'strong']
    weak_archs = [a for a in RANKED_AI_ARCHETYPES if a['band'] == 'weak']
    mid_archs = [a for a in RANKED_AI_ARCHETYPES if a['band'] == 'mid']
    legacy_cfgs = [
        _make_bot_cfg(f'Legacy-{p}', p, profile=None)
        for p in ('econ', 'fast_lv', 'reroll')
    ]

    t0 = time.time()
    all_tasks = {}

    for idx, t in enumerate(RANK_TIERS):
        tid = t['id']
        duels = []
        for i in range(args.trials):
            s_arch = strong_archs[i % len(strong_archs)]
            w_arch = weak_archs[i % len(weak_archs)]
            cfg_s = _make_bot_cfg(f'{t["name"]}-强', s_arch['personality'], build_ranked_ai_profile(tid, s_arch))
            cfg_w = _make_bot_cfg(f'{t["name"]}-弱', w_arch['personality'], build_ranked_ai_profile(tid, w_arch))
            duels.append((cfg_s, cfg_w, args.seed + idx * 10000 + i * 7919, bool(i % 2)))
        all_tasks[f'intra:{tid}'] = duels

    for idx, t in enumerate(RANK_TIERS):
        tid = t['id']
        duels = []
        for i in range(args.trials):
            leg_cfg = legacy_cfgs[i % len(legacy_cfgs)]
            m_arch = mid_archs[(i // 3 + idx) % len(mid_archs)]
            cfg_m = _make_bot_cfg(f'{t["name"]}-中', m_arch['personality'], build_ranked_ai_profile(tid, m_arch))
            duels.append((leg_cfg, cfg_m, args.seed + 90000 + idx * 10000 + i * 7919, bool(i % 2)))
        all_tasks[f'legacy:{tid}'] = duels

    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = _evaluate_pairs(pool, all_tasks)

    print(f'\n[2/3] Intra-tier Strongest vs Weakest calibration ({args.trials} paired duels/tier):')
    for t in RANK_TIERS:
        wr_s, wr_w = results[f'intra:{t["id"]}']
        print(f'  {t["name"]:4s} ({t["id"]:8s}): Strong {wr_s*100:5.1f}%  vs  Weak {wr_w*100:5.1f}%')

    print(f'\n[3/3] Legacy lobby4 AI anchor & cross-tier ladder ({args.trials} paired duels/tier):')
    for t in RANK_TIERS:
        wr_leg, wr_tier = results[f'legacy:{t["id"]}']
        print(f'  Legacy AI vs {t["name"]:4s} Mid: Legacy {wr_leg*100:5.1f}%  vs  {t["name"]} {wr_tier*100:5.1f}%')

    print(f'\n[Perf] Running 5 rounds of 8-player ranked match simulation...')
    p0 = time.time()
    rm = AutoChessMatch(mode='ranked', ranked_tier='gold', seed=args.seed + 555)
    for _ in range(5):
        if rm.phase == 'finished':
            break
        if rm.commanders[rm.player_id]['pending_augments']:
            rm.pick_augment(rm.player_id, rm.commanders[rm.player_id]['pending_augments'][0]['id'])
        rm.resolve_combat()
        if rm.phase == 'round_result':
            rm.next_round()
    dt = time.time() - p0
    print(f'  Completed 5 rounds in {dt:.2f}s ({dt/5*1000:.0f} ms/round), remaining alive: {sum(1 for c in rm.commanders.values() if not c["eliminated"])}/8')
    print(f'\nTotal calibration time: {time.time() - t0:.2f}s')


if __name__ == '__main__':
    main()
