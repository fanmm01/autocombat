"""AI commander preparation heuristics for 4-player lobbies and 8-player ranked tiers."""

import itertools
import random

from autochess_catalog import AUGMENTS, LEVEL_TABLE, UNIT_CATALOG, compute_active_synergies

# 12 distinct strategy archetypes present in every tier (> 10 strategies per tier).
RANKED_AI_ARCHETYPES = (
    {
        'id': 'synergy_flame',
        'label': '炎域爆发流',
        'personality': 'balanced',
        'preferred_traits': ('炎域', '星祈'),
        'preferred_augs': ('aug_pop', 'aug_execute', 'aug_mana'),
        'interest_floor': 12,
        'reroll_bias': 1,
        'level_bias': 1,
        'band': 'strong',
    },
    {
        'id': 'synergy_blood',
        'label': '血月收割流',
        'personality': 'balanced',
        'preferred_traits': ('血月', '武斗'),
        'preferred_augs': ('aug_pop', 'aug_blood', 'aug_execute'),
        'interest_floor': 10,
        'reroll_bias': 1,
        'level_bias': 1,
        'band': 'strong',
    },
    {
        'id': 'synergy_shield',
        'label': '重盾铁壁流',
        'personality': 'econ',
        'preferred_traits': ('重盾', '秘愈'),
        'preferred_augs': ('aug_bastion', 'aug_titan', 'aug_pop'),
        'interest_floor': 12,
        'reroll_bias': 0,
        'level_bias': 1,
        'band': 'strong',
    },
    {
        'id': 'synergy_star',
        'label': '星祈法核流',
        'personality': 'fast_lv',
        'preferred_traits': ('星祈', '破空'),
        'preferred_augs': ('aug_mana', 'aug_zone', 'aug_pop'),
        'interest_floor': 14,
        'reroll_bias': 0,
        'level_bias': 2,
        'band': 'mid_high',
    },
    {
        'id': 'synergy_summon',
        'label': '灵召人海流',
        'personality': 'econ',
        'preferred_traits': ('灵召', '秘愈'),
        'preferred_augs': ('aug_summon', 'aug_pop', 'aug_zone'),
        'interest_floor': 16,
        'reroll_bias': 0,
        'level_bias': 1,
        'band': 'mid_high',
    },
    {
        'id': 'macro_tempo',
        'label': '连胜压制流',
        'personality': 'fast_lv',
        'preferred_traits': ('武斗', '重盾'),
        'preferred_augs': ('aug_pop', 'aug_xp', 'aug_precision'),
        'interest_floor': 8,
        'reroll_bias': 1,
        'level_bias': 2,
        'band': 'mid_high',
    },
    {
        'id': 'macro_flex',
        'label': '摇摆均衡流',
        'personality': 'balanced',
        'preferred_traits': (),
        'preferred_augs': ('aug_pop', 'aug_econ', 'aug_xp'),
        'interest_floor': 12,
        'reroll_bias': 1,
        'level_bias': 1,
        'band': 'mid',
    },
    {
        'id': 'macro_econ',
        'label': '稳健吃息流',
        'personality': 'econ',
        'preferred_traits': (),
        'preferred_augs': ('aug_econ', 'aug_xp', 'aug_pop'),
        'interest_floor': 16,
        'reroll_bias': 0,
        'level_bias': 0,
        'band': 'mid',
    },
    {
        'id': 'macro_fast_lv',
        'label': '速升抢四流',
        'personality': 'fast_lv',
        'preferred_traits': (),
        'preferred_augs': ('aug_xp', 'aug_pop', 'aug_econ'),
        'interest_floor': 8,
        'reroll_bias': 0,
        'level_bias': 2,
        'band': 'mid',
    },
    {
        'id': 'synergy_sky',
        'label': '破空风筝流',
        'personality': 'balanced',
        'preferred_traits': ('破空', '星祈'),
        'preferred_augs': ('aug_swift', 'aug_mana', 'aug_reroll'),
        'interest_floor': 12,
        'reroll_bias': 0,
        'level_bias': 1,
        'band': 'mid_low',
    },
    {
        'id': 'macro_reroll',
        'label': '低费赌狗流',
        'personality': 'reroll',
        'preferred_traits': (),
        'preferred_augs': ('aug_reroll', 'aug_pair', 'aug_reserves'),
        'interest_floor': 20,
        'reroll_bias': 0,
        'level_bias': -1,
        'band': 'weak',
    },
    {
        'id': 'macro_greed',
        'label': '贪心奇袭流',
        'personality': 'econ',
        'preferred_traits': (),
        'preferred_augs': ('aug_reserves', 'aug_pair', 'aug_reroll'),
        'interest_floor': 24,
        'reroll_bias': -1,
        'level_bias': -1,
        'band': 'weak',
    },
)

# Per-tier baselines: legacy lobby4 AI sits between platinum and diamond.
TIER_AI_BASELINES = {
    'bronze': {
        'shop_noise': 26.0,
        'pair_bonus_scale': 0.42,
        'synergy_lookahead': 0.05,
        'interest_discipline': 0.25,
        'level_discipline': 0.30,
        'reroll_cap': 0,
        'all_in_hp': 0,
        'lock_shop_prob': 0.0,
        'board_synergy_opt': 0.0,
        'formation_opt': 0.32,
        'stance_opt': 0.0,
        'frontline_req': 0,
        'tactics_profile': {
            'suboptimal_prob': 0.48,
            'terrain_scale': 0.22,
            'focus_scale': 0.28,
            'skill_scale': 0.58,
        },
    },
    'silver': {
        'shop_noise': 18.0,
        'pair_bonus_scale': 0.56,
        'synergy_lookahead': 0.14,
        'interest_discipline': 0.45,
        'level_discipline': 0.44,
        'reroll_cap': 0,
        'all_in_hp': 0,
        'lock_shop_prob': 0.0,
        'board_synergy_opt': 0.0,
        'formation_opt': 0.48,
        'stance_opt': 0.0,
        'frontline_req': 1,
        'tactics_profile': {
            'suboptimal_prob': 0.36,
            'terrain_scale': 0.38,
            'focus_scale': 0.44,
            'skill_scale': 0.68,
        },
    },
    'gold': {
        'shop_noise': 13.0,
        'pair_bonus_scale': 0.68,
        'synergy_lookahead': 0.22,
        'interest_discipline': 0.70,
        'level_discipline': 0.56,
        'reroll_cap': 0,
        'all_in_hp': 0,
        'lock_shop_prob': 0.10,
        'board_synergy_opt': 0.0,
        'formation_opt': 0.68,
        'stance_opt': 0.0,
        'frontline_req': 1,
        'tactics_profile': {
            'suboptimal_prob': 0.24,
            'terrain_scale': 0.58,
            'focus_scale': 0.60,
            'skill_scale': 0.78,
        },
    },
    'platinum': {
        'shop_noise': 9.0,
        'pair_bonus_scale': 0.80,
        'synergy_lookahead': 0.28,
        'interest_discipline': 0.82,
        'level_discipline': 0.70,
        'reroll_cap': 0,
        'all_in_hp': 0,
        'lock_shop_prob': 0.15,
        'board_synergy_opt': 0.0,
        'formation_opt': 0.80,
        'stance_opt': 0.0,
        'frontline_req': 2,
        'tactics_profile': {
            'suboptimal_prob': 0.17,
            'terrain_scale': 0.72,
            'focus_scale': 0.74,
            'skill_scale': 0.85,
        },
    },
    'diamond': {
        'shop_noise': 0.0,
        'pair_bonus_scale': 1.15,
        'synergy_lookahead': 0.92,
        'interest_discipline': 0.90,
        'level_discipline': 1.05,
        'reroll_cap': 2,
        'all_in_hp': 26,
        'lock_shop_prob': 0.80,
        'board_synergy_opt': 0.95,
        'formation_opt': 1.0,
        'stance_opt': 0.95,
        'frontline_req': 2,
        'tactics_profile': {
            'suboptimal_prob': 0.0,
            'terrain_scale': 1.12,
            'focus_scale': 1.15,
            'skill_scale': 1.08,
        },
    },
    'king': {
        'shop_noise': 0.0,
        'pair_bonus_scale': 1.30,
        'synergy_lookahead': 1.25,
        'interest_discipline': 1.0,
        'level_discipline': 1.15,
        'reroll_cap': 3,
        'all_in_hp': 28,
        'lock_shop_prob': 1.0,
        'board_synergy_opt': 1.25,
        'formation_opt': 1.0,
        'stance_opt': 1.0,
        'frontline_req': 2,
        'tactics_profile': {
            'suboptimal_prob': 0.0,
            'terrain_scale': 1.20,
            'focus_scale': 1.25,
            'skill_scale': 1.12,
        },
    },
}

# Intra-tier spread calibrated to push strongest vs weakest toward ~65% vs ~35%.
BAND_DELTAS = {
    'strong': {
        'noise_add': -6.0,
        'syn_add': 0.25,
        'pair_add': 0.22,
        'level_disc_add': 0.10,
        'reroll_add': 0,
        'board_opt_add': 0.35,
        'form_add': 0.18,
        'subopt_add': -0.10,
        'scale_add': 0.14,
    },
    'mid_high': {
        'noise_add': -1.0,
        'syn_add': 0.08,
        'pair_add': 0.06,
        'level_disc_add': 0.04,
        'reroll_add': 0,
        'board_opt_add': 0.08,
        'form_add': 0.05,
        'subopt_add': -0.03,
        'scale_add': 0.04,
    },
    'mid': {
        'noise_add': 0.0,
        'syn_add': 0.0,
        'pair_add': 0.0,
        'level_disc_add': 0.0,
        'reroll_add': 0,
        'board_opt_add': 0.0,
        'form_add': 0.0,
        'subopt_add': 0.0,
        'scale_add': 0.0,
    },
    'mid_low': {
        'noise_add': 4.0,
        'syn_add': -0.08,
        'pair_add': -0.08,
        'level_disc_add': -0.06,
        'reroll_add': 0,
        'board_opt_add': -0.10,
        'form_add': -0.06,
        'subopt_add': 0.05,
        'scale_add': -0.05,
    },
    'weak': {
        'noise_add': 15.0,
        'syn_add': -0.25,
        'pair_add': -0.32,
        'level_disc_add': -0.10,
        'reroll_add': 0,
        'board_opt_add': -0.25,
        'form_add': -0.25,
        'subopt_add': 0.22,
        'scale_add': -0.22,
    },
}

_BOT_PREFIXES = (
    '星穹', '绯月', '苍星', '霜序', '炽羽', '岚风', '幻夜', '琉璃',
    '银翼', '耀辰', '暮光', '黎明', '墨影', '青岚', '紫微', '赤焰',
    '极光', '天枢', '天璇', '天权', '玉衡', '开阳', '摇光', '织梦',
    '聆音', '逐光', '沉渊', '澄空', '晴岚', '星尘', '溯洄', '千羽',
    '绯樱', '苍梧', '冰弦', '烁金', '霁雪', '朔夜', '初晴', '流萤',
)

_BOT_SUFFIXES = (
    '观测者', '织星师', '守序者', '裁决官', '引路人', '弈星者', '司律者', '游侠',
    '魔导师', '契约师', '近卫长', '祈愿者', '先驱', '旅人', '统领', '执棋人',
    '共鸣者', '咏唱者', '破阵使', '观星家', '剑姬', '圣女', '游吟者', '秘术师',
    '凛羽', '微光', '千星', '零时', '夜歌', '晨曦', '绯刃', '霜华',
    '凌霜', '听风', '望月', '巡星',
)


def generate_random_bot_names(count=7, rng=None):
    """Generate distinct non-repeating Starlight Auto-Chess commander names."""
    roller = rng or random
    names = []
    used = set()
    attempts = 0
    while len(names) < count and attempts < count * 30:
        attempts += 1
        candidate = f'{roller.choice(_BOT_PREFIXES)}·{roller.choice(_BOT_SUFFIXES)}'
        if candidate not in used:
            used.add(candidate)
            names.append(candidate)
    while len(names) < count:
        names.append(f'星序棋手#{len(names) + 1}')
    return names


def build_ranked_ai_profile(tier_id, archetype_def):
    """Compose a concrete ranked AI profile from tier baseline + strategy archetype."""
    tid = tier_id if tier_id in TIER_AI_BASELINES else 'bronze'
    base = TIER_AI_BASELINES[tid]
    band = archetype_def.get('band', 'mid')
    delta = BAND_DELTAS.get(band, BAND_DELTAS['mid'])
    tp_base = base['tactics_profile']

    subopt = max(0.0, min(0.75, tp_base['suboptimal_prob'] + delta['subopt_add']))
    t_scale = max(0.08, min(1.32, tp_base['terrain_scale'] + delta['scale_add']))
    f_scale = max(0.10, min(1.38, tp_base['focus_scale'] + delta['scale_add']))
    s_scale = max(0.35, min(1.25, tp_base['skill_scale'] + delta['scale_add'] * 0.55))

    return {
        'tier_id': tid,
        'archetype_id': archetype_def['id'],
        'archetype_label': archetype_def['label'],
        'band': band,
        'preferred_traits': list(archetype_def.get('preferred_traits', ())),
        'preferred_augs': list(archetype_def.get('preferred_augs', ())),
        'interest_floor': int(round(archetype_def.get('interest_floor', 12) * base['interest_discipline'])),
        'reroll_bias': int(archetype_def.get('reroll_bias', 0)),
        'level_bias': int(archetype_def.get('level_bias', 0)),
        'shop_noise': max(0.0, base['shop_noise'] + delta['noise_add']),
        'pair_bonus_scale': max(0.20, base['pair_bonus_scale'] + delta['pair_add']),
        'synergy_lookahead': max(0.0, min(1.40, base['synergy_lookahead'] + delta['syn_add'])),
        'level_discipline': max(0.15, min(1.25, base['level_discipline'] + delta.get('level_disc_add', 0.0))),
        'reroll_cap': max(0, base['reroll_cap'] + delta.get('reroll_add', 0)),
        'all_in_hp': 0 if band == 'weak' else (max(base['all_in_hp'], 16) if band == 'strong' else base['all_in_hp']),
        'lock_shop_prob': 0.0 if band == 'weak' else (max(base['lock_shop_prob'], 0.45) if band == 'strong' else base['lock_shop_prob']),
        'board_synergy_opt': max(0.0, min(1.40, base['board_synergy_opt'] + delta['board_opt_add'])),
        'formation_opt': max(0.15, min(1.0, base['formation_opt'] + delta['form_add'])),
        'stance_opt': 0.0 if band == 'weak' else (max(base['stance_opt'], 0.55) if band == 'strong' else base['stance_opt']),
        'frontline_req': 0 if band == 'weak' else base['frontline_req'],
        'tactics_profile': {
            'suboptimal_prob': round(subopt, 3),
            'terrain_scale': round(t_scale, 3),
            'focus_scale': round(f_scale, 3),
            'skill_scale': round(s_scale, 3),
        },
    }


def generate_ranked_bots(tier_id, count=7, rng=None):
    """Sample distinct strategy archetypes and random names for a ranked lobby."""
    roller = rng or random
    picked_archs = roller.sample(RANKED_AI_ARCHETYPES, min(count, len(RANKED_AI_ARCHETYPES)))
    names = generate_random_bot_names(len(picked_archs), rng=roller)
    bots = []
    for name, arch in zip(names, picked_archs):
        bots.append({
            'name': name,
            'personality': arch['personality'],
            'ai_style_label': arch['label'],
            'ai_profile': build_ranked_ai_profile(tier_id, arch),
        })
    return bots


def pick_augment_for_commander(commander, choices, rng=None):
    """Score augment choices against commander's personality, ranked profile, and current roster."""
    if not choices:
        return None
    ai_profile = commander.get('ai_profile')
    band = ai_profile.get('band') if isinstance(ai_profile, dict) else None
    personality = commander.get('personality', 'econ')
    board = [u for u in commander.get('units', []) if u.get('location') == 'board']
    synergies = compute_active_synergies(board)
    has_summon = any(UNIT_CATALOG.get(u['serial'], {}).get('role') == 'summoner' for u in board)
    has_ranged = any(UNIT_CATALOG.get(u['serial'], {}).get('role') == 'ranged' for u in board)
    pref_augs = set(ai_profile.get('preferred_augs', ())) if isinstance(ai_profile, dict) else set()
    noise = float(ai_profile.get('shop_noise', 0.0) or 0.0) if isinstance(ai_profile, dict) else 0.0
    roller = rng or random

    def _score(aug):
        aid = aug.get('id', '')
        sc = 50.0
        if band != 'weak':
            if personality == 'econ' and aid in ('aug_econ', 'aug_pop', 'aug_xp'):
                sc += 35.0
            elif personality == 'fast_lv' and aid in ('aug_xp', 'aug_pop', 'aug_mana'):
                sc += 35.0
            elif personality == 'reroll' and aid in ('aug_reroll', 'aug_pair', 'aug_precision'):
                sc += 35.0
        if aid in pref_augs:
            sc += 28.0
        if aid == 'aug_summon' and (has_summon or '灵召' in synergies):
            sc += 30.0
        if aid == 'aug_blood' and '血月' in synergies:
            sc += 28.0
        if aid == 'aug_bastion' and '重盾' in synergies:
            sc += 26.0
        if aid == 'aug_swift' and (has_ranged or '破空' in synergies):
            sc += 26.0
        if aid == 'aug_zone' and ('秘愈' in synergies or '星祈' in synergies):
            sc += 25.0
        if aid == 'aug_pop':
            sc += 22.0
        if noise > 0:
            sc += roller.uniform(-noise, noise)
        return sc

    return max(choices, key=_score)['id']


def _evaluate_shop_offer(commander, serial, occupied_traits):
    meta = UNIT_CATALOG.get(serial)
    if not meta:
        return -999.0
    units = commander.get('units', [])
    owned_same = [u for u in units if u['serial'] == serial]
    score = meta['cost'] * 8.0 + len(owned_same) * 26.0
    if len(owned_same) == 2:
        score += 45.0  # Instant 2-star!
    for tr in meta['traits']:
        if tr in occupied_traits:
            score += 11.0
    board = [u for u in units if u.get('location') == 'board']
    front_cnt = sum(
        1 for u in board
        if UNIT_CATALOG.get(u['serial'], {}).get('role') in ('tank', 'bruiser', 'assassin')
    )
    if front_cnt < 2 and meta['role'] in ('tank', 'bruiser'):
        score += 16.0
    return score


def _evaluate_ranked_shop_offer(match, cid, commander, serial, occupied_traits, profile, roller):
    meta = UNIT_CATALOG.get(serial)
    if not meta:
        return -999.0
    units = commander.get('units', [])
    board = [u for u in units if u.get('location') == 'board']
    owned_same = [u for u in units if u['serial'] == serial]
    pair_scale = float(profile.get('pair_bonus_scale', 1.0))
    syn_look = float(profile.get('synergy_lookahead', 0.4))

    score = meta['cost'] * 7.5 + len(owned_same) * 25.0 * pair_scale
    if len(owned_same) == 2:
        score += 46.0 * pair_scale
    if any(u['star'] == 2 for u in owned_same):
        score += 18.0 * pair_scale

    # Preferred archetype traits
    pref_traits = set(profile.get('preferred_traits') or ())
    for tr in meta['traits']:
        if tr in occupied_traits:
            score += 10.0 * max(0.3, syn_look)
        if tr in pref_traits:
            score += 8.5 * max(0.3, syn_look)

    # Exact trait activation lookahead for Platinum/Diamond/King
    if syn_look >= 0.45 and (len(board) < match.max_pop(cid) or not owned_same):
        base_syn = compute_active_synergies(board)
        base_active = sum(1 for s in base_syn.values() if s.get('active_tier'))
        hypo_syn = compute_active_synergies(board + [{'serial': serial}])
        hypo_active = sum(1 for s in hypo_syn.values() if s.get('active_tier'))
        if hypo_active > base_active:
            score += (hypo_active - base_active) * 32.0 * syn_look

    # Frontline protection quota
    front_req = int(profile.get('frontline_req', 1) or 0)
    front_cnt = sum(
        1 for u in board
        if UNIT_CATALOG.get(u['serial'], {}).get('role') in ('tank', 'bruiser')
    )
    if front_cnt < front_req and meta['role'] in ('tank', 'bruiser'):
        score += 18.0

    noise = float(profile.get('shop_noise', 0.0) or 0.0)
    if noise > 0:
        score += roller.uniform(-noise, noise)
    return score


def _legacy_commander_prep(match, cid):
    """Original 4-player Auto-Chess AI preparation logic (benchmarked around Platinum-Diamond)."""
    cmd = match.commanders[cid]
    if cmd.get('pending_augments'):
        chosen = pick_augment_for_commander(cmd, cmd['pending_augments'])
        if chosen:
            match.pick_augment(cid, chosen)

    personality = cmd.get('personality', 'econ')
    interest_floor = 20 if personality == 'econ' else (10 if personality in ('fast_lv', 'balanced') else 4)

    for _ in range(4):
        lvl = cmd['level']
        if lvl >= max(LEVEL_TABLE):
            break
        gold = cmd['gold']
        need_xp = max(0, LEVEL_TABLE[lvl]['xp_to_next'] - cmd['xp'])
        if personality == 'fast_lv' and gold >= 4 + (0 if lvl < 3 else 4):
            if not match.buy_xp(cid):
                break
        elif personality in ('econ', 'balanced') and gold - 4 >= interest_floor and need_xp <= 12:
            if not match.buy_xp(cid):
                break
        elif personality == 'reroll' and ((lvl < 3 and gold >= 8) or (lvl < 4 and match.round_num >= 5 and gold >= 14)):
            if not match.buy_xp(cid):
                break
        else:
            break

    max_rerolls = 3 if personality == 'reroll' else (2 if personality == 'fast_lv' else 1)
    for step in range(max_rerolls + 1):
        units = cmd['units']
        board_traits = {
            t for u in units if u['location'] == 'board'
            for t in UNIT_CATALOG.get(u['serial'], {}).get('traits', ())
        }
        offers = []
        for idx, slot in enumerate(cmd['shop']):
            if not slot or slot.get('bought'):
                continue
            serial = slot['serial']
            cost = UNIT_CATALOG[serial]['cost']
            if cmd['gold'] < cost:
                continue
            val = _evaluate_shop_offer(cmd, serial, board_traits)
            same_cnt = sum(1 for u in units if u['serial'] == serial)
            if (cmd['gold'] - cost) < interest_floor and same_cnt < 2 and match.round_num > 3:
                if len([u for u in units if u['location'] == 'board']) >= match.max_pop(cid):
                    continue
            offers.append((val, idx, serial))
        offers.sort(reverse=True)

        bought_any = False
        for val, idx, _serial in offers:
            if val < 14.0 and len(cmd['units']) >= match.max_pop(cid) + 3:
                continue
            ok, _msg = match.buy_unit(cid, idx)
            if ok:
                bought_any = True
                break

        if bought_any:
            continue

        can_free = cmd.get('free_rerolls', 0) > 0
        min_gold_for_roll = 2 if can_free else (interest_floor + 2 if match.round_num > 2 else 6)
        if step < max_rerolls and cmd['gold'] >= min_gold_for_roll:
            if match.reroll_shop(cid):
                continue
        break

    cap = match.max_pop(cid)
    all_units = list(cmd['units'])

    def _unit_power(u):
        meta = UNIT_CATALOG.get(u['serial'], {})
        role_w = 4 if meta.get('role') in ('tank', 'bruiser') else (2 if meta.get('role') == 'support' else 3)
        return (u['star'] * 100 + meta.get('cost', 1) * 12 + role_w, u['id'])

    ranked = sorted(all_units, key=_unit_power, reverse=True)
    keep_on_board = {u['id'] for u in ranked[:cap]}

    for u in list(cmd['units']):
        if u['location'] == 'board' and u['id'] not in keep_on_board:
            match.recall_unit(cid, u['id'])
    for u in ranked[:cap]:
        if u['location'] != 'board':
            match.deploy_unit(cid, u['id'], None)

    bench_surplus = [
        u for u in cmd['units']
        if u['location'] == 'bench' and u['star'] == 1
        and sum(1 for x in cmd['units'] if x['serial'] == u['serial']) == 1
    ]
    if len([u for u in cmd['units'] if u['location'] == 'bench']) >= 5 and bench_surplus:
        weakest = min(bench_surplus, key=lambda u: UNIT_CATALOG.get(u['serial'], {}).get('cost', 1))
        match.sell_unit(cid, weakest['id'])

    match.auto_arrange(cid)


def _select_best_board_ids(all_units, cap, profile):
    """Select optimal board lineup balancing star/cost power, active synergies, and frontline."""
    if len(all_units) <= cap:
        return {u['id'] for u in all_units}

    def _unit_power(u):
        meta = UNIT_CATALOG.get(u['serial'], {})
        role_w = 5 if meta.get('role') in ('tank', 'bruiser') else (2 if meta.get('role') == 'support' else 3)
        return u['star'] * 100 + meta.get('cost', 1) * 12 + role_w

    ranked = sorted(all_units, key=lambda u: (_unit_power(u), u['id']), reverse=True)
    syn_weight = float(profile.get('board_synergy_opt', 0.0) or 0.0)
    if syn_weight <= 0.15 or cap <= 1:
        return {u['id'] for u in ranked[:cap]}

    pool = ranked[:min(len(ranked), max(cap + 4, 10))]
    front_req = int(profile.get('frontline_req', 1) or 0)
    best_score = -1e9
    best_combo = ranked[:cap]

    # Limit combinatorial evaluations for responsiveness
    combos = itertools.combinations(pool, min(cap, len(pool)))
    for idx, combo in enumerate(combos):
        if idx >= 180:
            break
        pwr = sum(_unit_power(u) for u in combo)
        syn = compute_active_synergies(combo)
        syn_pts = 0.0
        for s_info in syn.values():
            tier = s_info.get('active_tier')
            if tier:
                syn_pts += 34.0 * s_info['count']
        front_cnt = sum(
            1 for u in combo
            if UNIT_CATALOG.get(u['serial'], {}).get('role') in ('tank', 'bruiser')
        )
        front_pen = -28.0 if (front_req > 0 and front_cnt == 0) else 0.0
        total = pwr + syn_pts * syn_weight + front_pen
        if total > best_score:
            best_score = total
            best_combo = combo

    return {u['id'] for u in best_combo}


def _ranked_commander_prep(match, cid, profile):
    """Tier-scaled Auto-Chess AI preparation using the assigned ranked archetype profile."""
    cmd = match.commanders[cid]
    roller = getattr(match, '_rng', random)

    if cmd.get('pending_augments'):
        chosen = pick_augment_for_commander(cmd, cmd['pending_augments'], rng=roller)
        if chosen:
            match.pick_augment(cid, chosen)

    all_in = cmd['hp'] <= int(profile.get('all_in_hp', 0) or 0)
    personality = cmd.get('personality', 'balanced')
    interest_floor = 0 if all_in else int(profile.get('interest_floor', 12) or 0)
    lvl_disc = float(profile.get('level_discipline', 1.0) or 1.0)

    # 1. Leveling with tier discipline and all-in survival override
    for _ in range(4):
        lvl = cmd['level']
        if lvl >= max(LEVEL_TABLE):
            break
        gold = cmd['gold']
        need_xp = max(0, LEVEL_TABLE[lvl]['xp_to_next'] - cmd['xp'])
        if roller.random() > min(1.0, lvl_disc + (0.25 if all_in else 0.0)):
            break
        if all_in and gold >= 4 and need_xp <= 8:
            if not match.buy_xp(cid):
                break
        elif personality == 'fast_lv' and gold >= max(4, interest_floor + (0 if lvl < 3 else 4)):
            if not match.buy_xp(cid):
                break
        elif gold - 4 >= interest_floor and need_xp <= (16 if lvl_disc >= 1.0 else 12):
            if not match.buy_xp(cid):
                break
        elif personality == 'reroll' and profile.get('band') != 'weak' and ((lvl < 3 and gold >= 8) or (lvl < 4 and match.round_num >= 5 and gold >= 14)):
            if not match.buy_xp(cid):
                break
        else:
            break

    # 2. Shop offers & reroll decisions
    base_rerolls = int(profile.get('reroll_cap', 1) or 0)
    max_rerolls = base_rerolls + (2 if all_in else (1 if (personality == 'reroll' and profile.get('band') != 'weak') else 0))
    for step in range(max_rerolls + 1):
        units = cmd['units']
        board_traits = {
            t for u in units if u['location'] == 'board'
            for t in UNIT_CATALOG.get(u['serial'], {}).get('traits', ())
        }
        offers = []
        for idx, slot in enumerate(cmd['shop']):
            if not slot or slot.get('bought'):
                continue
            serial = slot['serial']
            cost = UNIT_CATALOG[serial]['cost']
            if cmd['gold'] < cost:
                continue
            val = _evaluate_ranked_shop_offer(match, cid, cmd, serial, board_traits, profile, roller)
            same_cnt = sum(1 for u in units if u['serial'] == serial)
            if not all_in and (cmd['gold'] - cost) < interest_floor and same_cnt < 2 and match.round_num > 3:
                if len([u for u in units if u['location'] == 'board']) >= match.max_pop(cid):
                    continue
            offers.append((val, idx, serial))
        offers.sort(reverse=True)

        bought_any = False
        min_accept = 8.0 if profile.get('shop_noise', 0) >= 12 else 14.0
        for val, idx, _serial in offers:
            if val < min_accept and len(cmd['units']) >= match.max_pop(cid) + 3:
                continue
            ok, _msg = match.buy_unit(cid, idx)
            if ok:
                bought_any = True
                break

        if bought_any:
            continue

        can_free = cmd.get('free_rerolls', 0) > 0
        min_gold_for_roll = 2 if (can_free or all_in) else (interest_floor + 2 if match.round_num > 2 else 6)
        if step < max_rerolls and cmd['gold'] >= min_gold_for_roll:
            if match.reroll_shop(cid):
                continue
        break

    # 3. High-tier pair/upgrade shop locking if out of gold
    lock_prob = float(profile.get('lock_shop_prob', 0.0) or 0.0)
    if lock_prob > 0.0 and not cmd.get('shop_locked'):
        wants_lock = False
        for slot in cmd['shop']:
            if not slot or slot.get('bought'):
                continue
            s = slot['serial']
            cost = UNIT_CATALOG[s]['cost']
            if cmd['gold'] < cost:
                same_1 = sum(1 for u in cmd['units'] if u['serial'] == s and u['star'] == 1)
                if same_1 >= 2 or (same_1 >= 1 and cost >= 3):
                    wants_lock = True
                    break
        if wants_lock and roller.random() < lock_prob:
            match.toggle_lock(cid)

    # 4. Optimal deployment & role stances
    cap = match.max_pop(cid)
    all_units = list(cmd['units'])
    keep_on_board = _select_best_board_ids(all_units, cap, profile)

    for u in list(cmd['units']):
        if u['location'] == 'board' and u['id'] not in keep_on_board:
            match.recall_unit(cid, u['id'])
    for u in all_units:
        if u['id'] in keep_on_board and u['location'] != 'board':
            match.deploy_unit(cid, u['id'], None)

    # Trim bench clutter for economy when bench fills up
    bench_surplus = [
        u for u in cmd['units']
        if u['location'] == 'bench' and u['star'] == 1
        and sum(1 for x in cmd['units'] if x['serial'] == u['serial']) == 1
    ]
    if len([u for u in cmd['units'] if u['location'] == 'bench']) >= 5 and bench_surplus:
        weakest = min(bench_surplus, key=lambda u: UNIT_CATALOG.get(u['serial'], {}).get('cost', 1))
        match.sell_unit(cid, weakest['id'])

    # Assign role-sensitive tactical stance for higher tiers
    stance_opt = float(profile.get('stance_opt', 0.0) or 0.0)
    if stance_opt > 0.0:
        for u in match.board_units(cid):
            if roller.random() > stance_opt:
                continue
            role = UNIT_CATALOG.get(u['serial'], {}).get('role', 'bruiser')
            if role == 'assassin':
                match.set_stance(cid, u['id'], 'aggressive')
            elif role in ('ranged', 'support', 'summoner'):
                match.set_stance(cid, u['id'], 'defensive')
            else:
                match.set_stance(cid, u['id'], 'balanced')

    # Optimize formation according to tier discipline
    form_prob = float(profile.get('formation_opt', 1.0) or 1.0)
    if form_prob >= 0.99 or roller.random() < form_prob:
        match.auto_arrange(cid)


def run_commander_prep(match, cid):
    """Execute one AI commander's shop, XP, deployment, and positioning logic."""
    cmd = match.commanders[cid]
    if cmd.get('eliminated'):
        return
    ai_profile = cmd.get('ai_profile')
    if isinstance(ai_profile, dict):
        _ranked_commander_prep(match, cid, ai_profile)
        return
    _legacy_commander_prep(match, cid)
