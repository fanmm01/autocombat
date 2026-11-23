#!/usr/bin/env python3
"""Cross-Entropy Method (CEM) weight trainer for Auto-Chess tactical AI.

Trains feature weights in ``backend/ai_weights_autochess.json`` using mirrored
side-swapped 2v2/3v3 spatial matches inside BattleEngine(autochess_mode=True).
Safe to import or run standalone with multiprocessing.
"""

import argparse
import copy
import json
import os
import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ai_battle import AIController, BattleEngine, DisplayLevel
from ai_tactics import DEFAULT_TACTICS_WEIGHTS, plan_formation
from arena_presets import build_arena_map
from characters_data import ALL_CHARACTERS, load_character_to_engine

_CHAR_BY_SERIAL = {
    c['serial']: c for c in ALL_CHARACTERS
    if isinstance(c, dict) and c.get('serial') and c.get('serial') != 'Y60'
}
_TRAINING_POOL = list(_CHAR_BY_SERIAL.keys())


def _sample_matchups(num_matches, seed):
    rng = random.Random(seed)
    matchups = []
    for idx in range(num_matches):
        sz = 2 if idx % 2 == 0 else 3
        a_pool = rng.sample(_TRAINING_POOL, sz)
        b_pool = rng.sample(_TRAINING_POOL, sz)
        preset = 'autochess_standard' if idx % 3 != 2 else 'autochess_citadel'
        matchups.append((a_pool, b_pool, preset, rng.randint(1, 10**9)))
    return matchups


def _run_mirror_pair(task):
    cand_weights, base_weights, a_ids, b_ids, preset, seed = task
    score = 0.0
    rng_state = random.getstate()
    try:
        random.seed(seed)
        md = build_arena_map(preset)
        for swap in (False, True):
            team_a = list(a_ids) if not swap else list(b_ids)
            team_b = list(b_ids) if not swap else list(a_ids)
            cand_side = 'Y' if not swap else 'X'
            base_side = 'X' if not swap else 'Y'

            eng = BattleEngine(display_level=DisplayLevel.WINLOSS, delay=0, quiet=True, max_rounds=22)
            ai_map = {}
            y_uids, x_uids = [], []
            for i, cid in enumerate(team_a):
                uid = f'Y{i}_{cid}'
                cdata = copy.deepcopy(_CHAR_BY_SERIAL[cid])
                load_character_to_engine(eng, cdata, uid)
                y_uids.append(uid)
                ai_map[uid] = AIController(uid, cdata, 'Y')
            for i, cid in enumerate(team_b):
                uid = f'X{i}_{cid}'
                cdata = copy.deepcopy(_CHAR_BY_SERIAL[cid])
                load_character_to_engine(eng, cdata, uid)
                x_uids.append(uid)
                ai_map[uid] = AIController(uid, cdata, 'X')

            coords = {}
            coords.update(plan_formation('Y', [{'uid': u, 'char': eng.characters[u]} for u in y_uids], md))
            coords.update(plan_formation('X', [{'uid': u, 'char': eng.characters[u]} for u in x_uids], md))
            eng.setup_battle(
                y_uids, x_uids,
                arena_preset=preset, autochess_mode=True,
                overtime_start_round=15, initial_coords=coords,
            )
            eng._autochess_team_weights = {cand_side: cand_weights, base_side: base_weights}
            res = eng.run_battle(ai_map)
            winner = res.get('winner')
            rounds = int(res.get('rounds', 22) or 22)
            if winner == cand_side:
                score += 1.0 + max(0.0, (16 - rounds) * 0.015)
            elif winner == base_side:
                score -= max(0.0, (16 - rounds) * 0.005)
    finally:
        random.setstate(rng_state)
    return score / 2.0


def evaluate_weights(cand_weights, base_weights, matchups, executor=None):
    tasks = [
        (cand_weights, base_weights, a_ids, b_ids, preset, seed)
        for a_ids, b_ids, preset, seed in matchups
    ]
    if executor is not None:
        scores = list(executor.map(_run_mirror_pair, tasks))
    else:
        scores = [_run_mirror_pair(t) for t in tasks]
    return sum(scores) / max(1, len(scores))


def train_weights(generations=4, pop_size=8, matches_per_cand=6, workers=1, seed=42, out_path=None):
    """Run CEM over DEFAULT_TACTICS_WEIGHTS keys and persist best vector."""
    rng = random.Random(seed)
    keys = list(DEFAULT_TACTICS_WEIGHTS.keys())
    mu = dict(DEFAULT_TACTICS_WEIGHTS)
    sigma = {k: max(1.0, abs(DEFAULT_TACTICS_WEIGHTS[k]) * 0.25) for k in keys}
    best_weights = dict(mu)
    best_score = 0.5
    elite_k = max(2, pop_size // 3)

    executor = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        for gen in range(generations):
            matchups = _sample_matchups(matches_per_cand, seed + gen * 101)
            candidates = [dict(best_weights)]
            while len(candidates) < pop_size:
                cand = {}
                for k in keys:
                    val = rng.gauss(mu[k], sigma[k])
                    cand[k] = round(max(0.5, val), 3)
                candidates.append(cand)

            scored = []
            for cand in candidates:
                sc = evaluate_weights(cand, best_weights, matchups, executor=executor)
                scored.append((sc, cand))
            scored.sort(key=lambda it: -it[0])

            elites = [c for _, c in scored[:elite_k]]
            for k in keys:
                vals = [c[k] for c in elites]
                mu[k] = round(statistics.mean(vals), 3)
                std = statistics.pstdev(vals) if len(vals) > 1 else sigma[k] * 0.8
                sigma[k] = max(0.5, std * 0.85)
            if scored[0][0] >= best_score or gen == 0:
                best_weights = dict(scored[0][1])
                best_score = scored[0][0]
            print(f'[gen {gen + 1}/{generations}] best={scored[0][0]:.3f} mean_top={statistics.mean(s for s, _ in scored[:elite_k]):.3f}')
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    if out_path:
        payload = {
            'version': 1,
            'best_score': round(best_score, 4),
            'weights': best_weights,
        }
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    return best_weights, best_score


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generations', type=int, default=4)
    parser.add_argument('--pop', type=int, default=8)
    parser.add_argument('--matches', type=int, default=6)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--out', default=os.path.join(_HERE, 'ai_weights_autochess.json'))
    args = parser.parse_args(argv)
    train_weights(
        generations=args.generations,
        pop_size=args.pop,
        matches_per_cand=args.matches,
        workers=args.workers,
        seed=args.seed,
        out_path=args.out,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
