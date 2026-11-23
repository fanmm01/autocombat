"""Spatial & tactical AI module for Auto-Chess mode (autochess_mode=True).

Classic mode (autochess_mode=False) never enters this module and preserves
classic Q-table / legacy rule AI behavior verbatim.

NOTE: Kept compatible with scripts/merge_backend.py (top-level unaliased
imports from grid_nav, arena_presets, battle_engine only).
"""

import json
import os

from grid_nav import (
    parse_coord,
    format_coord,
    grid_dist,
    terrain_type,
    compute_navigation,
)
from arena_presets import row_band, is_in_deploy_zone
from battle_engine import has_timing, avg_damage


DEFAULT_TACTICS_WEIGHTS = {
    'kill_bonus': 95.0,
    'dmg_weight': 3.2,
    'low_hp_focus': 28.0,
    'support_heal_weight': 46.0,
    'buff_weight': 26.0,
    'summon_weight': 38.0,
    'cc_weight': 32.0,
    'zone_weight': 28.0,
    'cover_bonus': 14.0,
    'leyline_bonus': 13.0,
    'hazard_penalty': 24.0,
    'threat_penalty': 16.0,
    'escort_bonus': 9.0,
    'move_threshold': 4.0,
}

STANCE_WEIGHTS = {
    'aggressive': {
        'threat_mult': 0.45,
        'cover_mult': 0.55,
        'advance_mult': 1.45,
        'heal_mult': 0.75,
    },
    'balanced': {
        'threat_mult': 1.0,
        'cover_mult': 1.0,
        'advance_mult': 1.0,
        'heal_mult': 1.0,
    },
    'defensive': {
        'threat_mult': 1.55,
        'cover_mult': 1.45,
        'advance_mult': 0.65,
        'heal_mult': 1.35,
    },
}

_WEIGHTS_CACHE = None


def load_tactics_weights(path=None):
    """Load trained tactical weights JSON if available, else return defaults."""
    global _WEIGHTS_CACHE
    if path is None and _WEIGHTS_CACHE is not None:
        return dict(_WEIGHTS_CACHE)
    weights = dict(DEFAULT_TACTICS_WEIGHTS)
    candidate = path
    if candidate is None:
        base_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
        candidate = os.path.join(base_dir, 'ai_weights_autochess.json')
    try:
        if candidate and os.path.isfile(candidate):
            with open(candidate, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                src = data.get('weights', data)
                if isinstance(src, dict):
                    for k, v in src.items():
                        if k in weights and isinstance(v, (int, float)):
                            weights[k] = float(v)
    except Exception:
        pass
    if path is None:
        _WEIGHTS_CACHE = dict(weights)
    return weights


def _reset_weights_cache():
    global _WEIGHTS_CACHE
    _WEIGHTS_CACHE = None


def _get_unit_stance(engine, uid):
    stances = getattr(engine, '_unit_stances', None) or {}
    base = engine._resolve_uid(uid)
    st = stances.get(base) or stances.get(uid) or 'balanced'
    return st if st in STANCE_WEIGHTS else 'balanced'


def _spell_effects(spell):
    return spell.get('effects') or []


def _spell_mp_cost(spell):
    raw = spell.get('消耗MP', spell.get('消耗mp', spell.get('MP消耗', 0)))
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return 0


def classify_role(char, spells=None):
    """Classify unit into one of: tank / bruiser / assassin / ranged / support / summoner."""
    if char is None:
        return 'bruiser'
    if spells is None:
        spells = getattr(char, 'spells', None) or []
    hp = char.get_attr('体力上限', char.get_attr('体力', 10))
    can_block = bool(char.get_attr('可格挡', 0))
    flying = bool(char.get_attr('飞行', 0))
    mov = char.get_attr('MOV', char.get_attr('行动力', 8))
    bn, bv = char.get_best_melee()

    summon_cnt = 0
    heal_cnt = 0
    buff_cnt = 0
    dmg_cnt = 0
    max_dmg_range = 2
    for s in spells:
        if not has_timing(s.get('时机', '2'), '2') and not has_timing(s.get('时机', '2'), '3'):
            continue
        for e in _spell_effects(s):
            et = e.get('type')
            if et == 5:
                summon_cnt += 1
            elif et in (2, 6, 18, 19) or (et == 8 and e.get('回复hp')):
                heal_cnt += 1
            elif et == 4:
                if str(e.get('客体', 4)) in ('5', '124'):
                    dmg_cnt += 1
                else:
                    buff_cnt += 1
            elif et == 1:
                dmg_cnt += 1
                sname = str(s.get('name', ''))
                r = int(e.get('射程', 2) or 2)
                if sname == '火焰附魔':
                    r = 2
                elif r >= 90 and not e.get('全局射程'):
                    r = 8
                max_dmg_range = max(max_dmg_range, r)
            elif et == 8 and e.get('每回合伤害骰'):
                dmg_cnt += 1
                max_dmg_range = max(max_dmg_range, int(e.get('射程', 4) or 4))

    has_ranged_basic = ('射' in str(bn) or '弓' in str(bn) or max_dmg_range >= 4)
    pure_dmg_cnt = sum(
        1 for s in spells
        if (has_timing(s.get('时机', '2'), '2') or has_timing(s.get('时机', '2'), '3'))
        and any(e.get('type') == 1 or (e.get('type') == 8 and e.get('每回合伤害骰')) for e in _spell_effects(s))
    )
    if can_block or (hp >= 22 and not has_ranged_basic and dmg_cnt <= 1):
        return 'tank'
    if summon_cnt >= 1 and pure_dmg_cnt <= 1 and bv < 65:
        return 'summoner'
    if (heal_cnt + buff_cnt >= 1 and pure_dmg_cnt == 0) or (heal_cnt + buff_cnt >= max(2, dmg_cnt + 1) and bv < 65):
        return 'support'
    if (flying or mov >= 10) and not has_ranged_basic:
        return 'assassin'
    if has_ranged_basic:
        return 'ranged'
    return 'bruiser'


def plan_formation(team_code, units, map_data, stances=None):
    """Auto-assign conflict-free starting coordinates within team deploy zone.

    ``units`` is a sequence of dicts or objects with ``uid`` (or ``instance_id`` /
    ``unit_id``), ``char`` (optional Character), ``spells`` (optional list),
    ``role`` (optional str), and ``stance`` (optional str).
    Returns {uid: coord}.
    """
    if not map_data or not units:
        return {}
    w = int(map_data.get('width', 10) or 10)
    h = int(map_data.get('height', 7) or 7)
    deploy_cols = sorted((map_data.get('deploy_cols') or {}).get(team_code) or (
        list(range(min(3, w))) if team_code == 'Y' else list(range(max(0, w - 3), w))
    ))
    if not deploy_cols:
        return {}

    # Order columns from frontline (nearest opponent) to backline
    cols_front_to_back = list(reversed(deploy_cols)) if team_code == 'Y' else list(deploy_cols)
    mid_row = (h - 1) / 2.0

    def _row_order(flank=False):
        rows = list(range(h))
        if flank:
            return sorted(rows, key=lambda r: (-abs(r - mid_row), r))
        return sorted(rows, key=lambda r: (abs(r - mid_row), r))

    occupied = set()
    legal_cells = {}
    for c in deploy_cols:
        for r in range(h):
            coord = format_coord(c, r)
            if coord and terrain_type(map_data, coord) != 'wall' and is_in_deploy_zone(map_data, team_code, coord):
                legal_cells[(c, r)] = coord

    def _band_cols(pref_band, flank=False):
        if len(cols_front_to_back) == 1:
            return cols_front_to_back
        if len(cols_front_to_back) == 2:
            if pref_band == 'front':
                return [cols_front_to_back[0], cols_front_to_back[1]]
            return [cols_front_to_back[1], cols_front_to_back[0]]
        front_c = cols_front_to_back[0]
        mid_c = cols_front_to_back[1:-1]
        back_c = cols_front_to_back[-1]
        if pref_band == 'front':
            return [front_c] + mid_c + [back_c]
        if pref_band == 'mid':
            return mid_c + [back_c, front_c]
        return [back_c] + list(reversed(mid_c)) + [front_c]

    stances = stances or {}
    parsed_units = []
    for idx, u in enumerate(units):
        if isinstance(u, dict):
            uid = u.get('uid') or u.get('instance_id') or u.get('id') or f'u{idx}'
            char = u.get('char')
            spells = u.get('spells')
            role = u.get('role') or classify_role(char, spells)
            stance = u.get('stance') or stances.get(uid) or 'balanced'
        else:
            uid = str(u)
            role = 'bruiser'
            stance = stances.get(uid) or 'balanced'
        parsed_units.append((uid, role, stance, idx))

    role_priority = {'tank': 0, 'bruiser': 1, 'assassin': 2, 'summoner': 3, 'support': 4, 'ranged': 5}
    parsed_units.sort(key=lambda item: (role_priority.get(item[1], 3), item[3]))

    out = {}
    for uid, role, stance, _ in parsed_units:
        if role in ('tank', 'bruiser'):
            band = 'front'
        elif role == 'assassin':
            band = 'front' if stance != 'defensive' else 'mid'
        elif role == 'summoner':
            band = 'mid'
        else:
            band = 'back'

        if stance == 'aggressive' and band == 'back':
            band = 'mid'
        elif stance == 'defensive' and band == 'mid':
            band = 'back'

        col_order = _band_cols(band)
        flank = (role == 'assassin')
        rows = _row_order(flank=flank)
        # Rank candidates preferring legal cells matching cover (ranged/support) or leyline (casters)
        best = None
        for col_rank, col in enumerate(col_order):
            for row_rank, row in enumerate(rows):
                coord = legal_cells.get((col, row))
                if not coord or coord in occupied:
                    continue
                t = terrain_type(map_data, coord)
                terrain_pref = 0
                if role in ('ranged', 'support', 'summoner') and t == 'cover':
                    terrain_pref = -2
                elif role in ('support', 'ranged', 'summoner') and t == 'leyline':
                    terrain_pref = -1
                cand_key = (col_rank, terrain_pref, row_rank, coord)
                if best is None or cand_key < best[0]:
                    best = (cand_key, coord)
        if best is not None:
            occupied.add(best[1])
            out[uid] = best[1]
    return out


def _estimate_hit_prob(skill_val):
    return max(0.15, min(0.96, float(skill_val or 50) / 100.0))


def _spell_offensive_range(engine, uid, spell):
    dmg_effs = [e for e in _spell_effects(spell) if e.get('type') == 1]
    if dmg_effs:
        return engine._get_attack_range(spell_effect=dmg_effs[0], spell_name=spell.get('name'), uid=uid)
    return engine._get_attack_range(spell_name=spell.get('name'), uid=uid)


def _spell_is_already_active(engine, uid, spell):
    name = spell.get('name', '')
    if not name:
        return False
    base = engine._resolve_uid(uid)
    for e in engine._get_effects():
        if e.get('spellName') == name and e.get('remainingRounds', 0) > 0:
            if e.get('type') in ('buff', 'zone', 'damageModifier') and engine._resolve_uid(e.get('sourceUserId', '')) == base:
                return True
    return False


def _can_cast_spell(engine, uid, spell, my_acts, failed):
    sn = spell.get('index')
    if sn is None:
        return None
    timing = spell.get('时机', '2')
    cmd_main = f'.s{sn}'
    cmd_add = f'.a s{sn}'
    slot_cmd = None
    if has_timing(timing, '2') and my_acts.get('主动', 0) > 0 and cmd_main not in failed:
        slot_cmd = cmd_main
    elif has_timing(timing, '3') and my_acts.get('附加', 0) > 0 and cmd_add not in failed:
        slot_cmd = cmd_add
    else:
        return None

    if not engine._can_cast_active_skill(uid):
        return None
    if engine._get_cooldown(uid, sn) > 0:
        return None
    if engine._is_y14(uid) and engine._y14_preflight(uid, spell):
        return None
    if engine._revive_preflight(uid, spell):
        return None

    char = engine.get_char(uid)
    if not char:
        return None

    blood_req = int(spell.get('cost_blood_ml', spell.get('消耗血液', 0)) or 0)
    if blood_req > 0 and engine._is_y17(uid) and engine._get_blood(uid) < blood_req:
        return None

    if spell.get('_once_per_battle'):
        ledger = getattr(engine, '_revive_use_ledger', set())
        consumed = getattr(char, '_once_consumed', set())
        once_key = (engine._resolve_uid(uid), sn)
        if once_key in ledger or spell.get('name', '') in consumed:
            return None

    mp = char.get_attr('魔力', 0) or 0
    if mp < _spell_mp_cost(spell):
        return None

    cost_ct = spell.get('cost_counter_type', '')
    cost_ca = spell.get('cost_counter_amount', 0)
    if cost_ct and cost_ca and engine._get_counter(uid, cost_ct) < cost_ca:
        return None

    effects = _spell_effects(spell)
    if any(e.get('consume_moon') for e in effects):
        my_team = engine._battle_team_of(uid)
        moons = engine._find_summons_by_field(my_team, 'replenish_allies')
        if not moons or (moons[0][1].get_attr('魔力', 0) or 0) <= 0:
            return None

    if effects and all(e.get('type') == 5 for e in effects):
        has_slot = False
        for e in effects:
            tmpl_name = e.get('召唤物模板', '')
            if not tmpl_name:
                has_slot = True
                continue
            tmpl = engine._get_summon_template(tmpl_name) or {}
            if tmpl.get('_meta'):
                if engine._random_summon_candidates(uid, tmpl):
                    has_slot = True
                    break
            else:
                rem, _ = engine._get_summon_quota(uid, tmpl_name)
                if rem is None or rem > 0:
                    has_slot = True
                    break
        if not has_slot:
            return None

    return slot_cmd


def _team_allies(engine, uid):
    il = engine._get_initiative()
    my_team = engine._battle_team_of(uid)
    my_base = engine._resolve_uid(uid)
    seen = set()
    allies = []
    for e in engine._battle_unit_entries():
        if e.get('team') != my_team:
            continue
        base = engine._resolve_uid(e.get('userId', ''))
        if not base or base in seen:
            continue
        seen.add(base)
        hp = engine._get_combat_hp(base) or 0
        if hp <= 0 and not engine._is_dying(base):
            continue
        allies.append((base, e, base == my_base))
    return allies


def score_tile(engine, uid, coord, role='bruiser', stance='balanced', weights=None,
               desired_range=2, focus_coord=None):
    """Score the tactical desirability of standing on ``coord``."""
    weights = weights or DEFAULT_TACTICS_WEIGHTS
    st = STANCE_WEIGHTS.get(stance, STANCE_WEIGHTS['balanced'])
    md = engine._get_map() or {}
    char = engine.get_char(uid)
    cur_hp = max(1, engine._get_combat_hp(uid) or 10)
    max_hp = max(1, (char.get_attr('体力上限', cur_hp) if char else cur_hp) or cur_hp)
    hp_ratio = cur_hp / max_hp
    mp = (char.get_attr('魔力', 0) if char else 0) or 0
    max_mp = max(1, (char.get_attr('魔力上限', mp) if char else mp) or 1)
    mp_ratio = mp / max_mp

    score = 0.0
    t = terrain_type(md, coord)
    if t == 'cover':
        cover_mult = st['cover_mult'] * (1.25 if role in ('ranged', 'support', 'summoner') else 0.7)
        if hp_ratio < 0.55:
            cover_mult *= 1.3
        score += weights['cover_bonus'] * cover_mult
    elif t == 'leyline':
        caster_factor = 1.25 if (role in ('support', 'summoner', 'ranged') and mp_ratio < 0.85) else 0.55
        score += weights['leyline_bonus'] * caster_factor

    hazards = engine._unit_hazard_coords(uid)
    if coord in hazards:
        score -= weights['hazard_penalty']

    enemies = engine._enemy_target_entries(uid)
    if enemies:
        dists = [grid_dist(coord, e.get('coord', '')) for e in enemies if e.get('coord')]
        min_dist = min(dists) if dists else 6
        if role in ('tank', 'bruiser', 'assassin'):
            target_d = grid_dist(coord, focus_coord) if focus_coord else min_dist
            score += (8 - min(8, target_d)) * 4.2 * st['advance_mult']
            if min_dist <= 2:
                score += 6.0 * st['advance_mult']
        else:
            # Ranged / support / summoner: stay inside useful range but avoid melee crowding
            opt_low = 3
            opt_high = max(4, min(8, int(desired_range or 6)))
            if min_dist <= 1:
                score -= weights['threat_penalty'] * st['threat_mult'] * 1.4
            elif min_dist == 2:
                score -= weights['threat_penalty'] * st['threat_mult'] * 0.75
            elif opt_low <= min_dist <= opt_high:
                score += 10.0
            elif min_dist > opt_high:
                score -= (min_dist - opt_high) * 5.0 * st['advance_mult']
            if focus_coord:
                fd = grid_dist(coord, focus_coord)
                if fd <= opt_high:
                    score += 8.0
                else:
                    score -= (fd - opt_high) * 3.5

    allies = _team_allies(engine, uid)
    other_allies = [e for _, e, is_self in allies if not is_self and e.get('coord')]
    if other_allies:
        if role == 'tank':
            ally_dists = [grid_dist(coord, e['coord']) for e in other_allies]
            if min(ally_dists) <= 3:
                score += weights['escort_bonus'] * 0.8
        elif role == 'support':
            ally_dists = [grid_dist(coord, e['coord']) for e in other_allies]
            if min(ally_dists) <= 4:
                score += weights['escort_bonus']
            elif min(ally_dists) > 5:
                score -= (min(ally_dists) - 5) * 4.0

    # Slight preference for central rows rather than dead corners unless terrain dictates
    pt = parse_coord(coord)
    h = int(md.get('height', 7) or 7)
    if pt:
        edge_dist = min(pt[1], h - 1 - pt[1])
        score += min(2, edge_dist) * 1.2

    return score


def plan_best_move(engine, uid, role=None, stance=None, weights=None, desired_range=None, focus_coord=None):
    """Return (best_coord, score_gain, reason) among legal reachable cells."""
    weights = weights or DEFAULT_TACTICS_WEIGHTS
    if not engine._can_move(uid):
        return None, 0.0, ''
    budget = engine._remaining_move_budget(uid)
    if budget <= 0:
        return None, 0.0, ''
    il = engine._get_initiative()
    me = engine._unit_il_entry(uid, il)
    if not me or not me.get('coord'):
        return None, 0.0, ''
    cur_coord = me['coord']
    char = engine.get_char(uid)
    spells = (char.spells or engine.load_spells(uid)) if char else []
    role = role or classify_role(char, spells)
    stance = stance or _get_unit_stance(engine, uid)
    md = engine._get_map() or {}
    base = engine._resolve_uid(uid)
    group = engine._get_summon_group(uid)
    map_uid = group.get('representative_uid', uid) if group else base

    nav = compute_navigation(
        md, cur_coord, budget,
        flying=engine._is_flying(uid),
        team=me.get('team', 'Y'),
        unit_teams=engine._unit_teams_map(),
        ignore_uids={uid, base, map_uid},
        size=engine._unit_size(uid),
    )
    reachable = nav['reachable']
    if len(reachable) <= 1:
        return None, 0.0, ''

    cur_score = score_tile(
        engine, uid, cur_coord, role=role, stance=stance,
        weights=weights, desired_range=desired_range, focus_coord=focus_coord,
    )
    best_coord = None
    best_gain = 0.0
    best_reason = ''
    for cand, (cost, _prev) in reachable.items():
        if cand == cur_coord or cost <= 0:
            continue
        sc = score_tile(
            engine, uid, cand, role=role, stance=stance,
            weights=weights, desired_range=desired_range, focus_coord=focus_coord,
        )
        # Tiny tie-break preference for lower movement cost when scores match closely
        gain = sc - cur_score - cost * 0.25
        if gain > best_gain:
            best_gain = gain
            best_coord = cand
            t = terrain_type(md, cand)
            if t == 'cover':
                best_reason = f'抢占掩体 {cand}'
            elif t == 'leyline':
                best_reason = f'占领灵脉 {cand}'
            elif role in ('ranged', 'support', 'summoner'):
                best_reason = f'拉扯站位至 {cand}'
            else:
                best_reason = f'前压接战至 {cand}'
    return best_coord, best_gain, best_reason


def _enemy_target_score(engine, atk_uid, enemy_entry, expected_dmg, hit_prob, weights):
    eid = enemy_entry['userId']
    hp = max(1, engine._get_combat_hp(eid) or 10)
    echar = engine.get_char(eid)
    max_hp = max(1, (echar.get_attr('体力上限', hp) if echar else hp) or hp)
    hp_ratio = hp / max_hp
    score = expected_dmg * hit_prob * weights['dmg_weight']
    if expected_dmg >= hp * 0.95:
        score += weights['kill_bonus'] * hit_prob
    score += (1.0 - hp_ratio) * weights['low_hp_focus']
    if enemy_entry.get('isSummon'):
        score *= 0.72
    else:
        # Slightly prioritize squishy or dangerous casters/healers if similarly wounded
        e_role = classify_role(echar, getattr(echar, 'spells', None) if echar else None)
        if e_role in ('ranged', 'support'):
            score += 7.0
    return score


def _estimate_spell_damage(engine, uid, spell, echar_or_uid):
    char = engine.get_char(uid)
    total = 0.0
    is_aoe = False
    has_cc = False
    for e in _spell_effects(spell):
        et = e.get('type')
        obj = str(e.get('客体', 4)).upper().strip()
        if et == 1:
            if e.get('damage_fixed'):
                total += float(e['damage_fixed'])
            elif e.get('damage_moon_mult'):
                moons = engine._find_summons_by_field(engine._battle_team_of(uid), 'replenish_allies')
                mmp = (moons[0][1].get_attr('魔力', 0) if moons else 0) or 0
                total += float(mmp) * float(e['damage_moon_mult'])
            elif e.get('damage_mp_multiplier'):
                mp = _spell_mp_cost(spell) or (char.get_attr('魔力', 0) if char else 0)
                total += float(mp) * float(e['damage_mp_multiplier'])
            elif e.get('damage_pct_caster_max_hp'):
                mhp = char.get_attr('体力上限', 10) if char else 10
                total += float(mhp) * float(e['damage_pct_caster_max_hp'])
            else:
                total += float(avg_damage(e.get('伤害骰', '1d4')) or 2.5)
            if obj in ('R', 'RP', 'ALL', '45') or e.get('范围半径') or e.get('AOE'):
                is_aoe = True
            if e.get('贯穿') or e.get('pen'):
                total *= 1.15
        elif et == 4 and obj in ('5', '124'):
            has_cc = True
        elif et == 8 and e.get('每回合伤害骰'):
            total += float(avg_damage(e.get('每回合伤害骰', '1d4')) or 2.5) * 1.6
            is_aoe = True
    chant = 0
    for e in _spell_effects(spell):
        cr = e.get('吟唱回合', 0)
        if isinstance(cr, int):
            chant = max(chant, cr)
        elif isinstance(cr, str) and cr.strip():
            chant = max(chant, 1)
    if chant > 0 and total > 0:
        cur_hp = engine._get_combat_hp(uid) or 10
        divisor = 1.0 + 1.3 * chant
        if cur_hp <= 11:
            divisor *= 1.6
        total /= divisor
    return total, is_aoe, has_cc


def decide_tactical_action(engine, uid, weights=None):
    """Return (command, reason) for an AI unit in autochess_mode."""
    base = engine._resolve_uid(uid)
    if weights is None:
        tw = getattr(engine, '_autochess_team_weights', None) or {}
        team_w = tw.get(engine._battle_team_of(base))
        weights = team_w if isinstance(team_w, dict) else load_tactics_weights()
    engine._set_autochess_pending_target(base, None)
    my_acts = engine._get_my_actions(base)
    if my_acts.get('主动', 0) <= 0:
        reason = '主动作已用尽，结束回合'
        engine._last_ai_reason = reason
        return '.i end', reason

    failed = getattr(engine, '_ai_failed_commands', set())
    if engine._is_dying(base):
        if my_acts.get('附加', 0) > 0 and engine._has_healing_item(base) and '.a eat' not in failed:
            reason = '濒死使用蛋糕救急'
            engine._last_ai_reason = reason
            return '.a eat', reason
        reason = '濒死且无急救道具，结束回合'
        engine._last_ai_reason = reason
        return '.i end', reason

    char = engine.get_char(base)
    if not char:
        return '.i end', '单位无效'
    spells = char.spells or engine.load_spells(base)
    role = classify_role(char, spells)
    stance = _get_unit_stance(engine, base)
    st_mults = STANCE_WEIGHTS[stance]
    cur_hp = max(1, engine._get_combat_hp(base) or 10)
    max_hp = max(1, char.get_attr('体力上限', cur_hp) or cur_hp)
    hp_ratio = cur_hp / max_hp

    allies = _team_allies(engine, base)
    enemies = engine._enemy_target_entries(base)
    if not enemies:
        reason = '无敌方存活目标，结束回合'
        engine._last_ai_reason = reason
        return '.i end', reason

    # Emergency self-cake or teammate cake gift before risky action
    if my_acts.get('附加', 0) > 0 and engine._has_healing_item(base):
        if hp_ratio < 0.40 and '.a eat' not in failed:
            reason = f'生命偏低({cur_hp}/{max_hp})，先吃回复道具'
            engine._last_ai_reason = reason
            return '.a eat', reason
        wounded_allies = []
        for a_uid, a_entry, is_self in allies:
            if is_self or a_entry.get('isSummon'):
                continue
            ahp = engine._get_combat_hp(a_uid) or 0
            achar = engine.get_char(a_uid)
            amhp = max(1, (achar.get_attr('体力上限', ahp) if achar else ahp) or 1)
            if engine._is_dying(a_uid) or (ahp / amhp) < 0.35:
                wounded_allies.append((ahp / amhp, a_uid, a_entry.get('name', a_uid)))
        if wounded_allies:
            wounded_allies.sort()
            _, target_ally_uid, ally_name = wounded_allies[0]
            give_cmd = f'.a give {target_ally_uid}'
            if give_cmd not in failed and '.a give' not in failed:
                reason = f'救援低血量队友 {ally_name}'
                engine._last_ai_reason = reason
                return give_cmd, reason

    # Candidate list: (score, cmd, target_uid, reason)
    candidates = []
    out_of_range_best = 0.0
    out_of_range_coord = None
    best_desired_range = 2

    # 1. Evaluate basic attack (.s0)
    if '.s0' not in failed and engine._can_basic_attack(base):
        bn, bv = engine._get_attack_skill(base, char)
        bv = engine._apply_buff_skill_mod(base, bv, bn)
        profile = engine._y14_attack_profile(base)
        atk_range = profile[1] if profile else engine._get_attack_range(skill_name=bn, uid=base)
        best_desired_range = max(best_desired_range, atk_range)
        dd = engine._get_damage_dice(base, bn)
        exp_dmg = float(avg_damage(dd) or 3.5)
        hit_p = _estimate_hit_prob(bv)
        if profile:
            atk_range = profile[1]
        for e in enemies:
            can_m, fly_pen = (
                (True, False)
                if engine._y17_ranged(base) or (engine._is_y14(base) and getattr(char, 'phase', 2) == 1)
                else engine._can_melee(base, e['userId'])
            )
            if not can_m:
                continue
            eff_hit_p = hit_p * (0.72 if fly_pen else 1.0)
            sc = _enemy_target_score(engine, base, e, exp_dmg, eff_hit_p, weights)
            if engine._can_reach_attack_range(base, e['userId'], atk_range):
                ename = e.get('name', e['userId'])
                candidates.append((sc, '.s0', e['userId'], f'普攻【{bn}】集火 {ename}'))
            else:
                if sc > out_of_range_best:
                    out_of_range_best = sc
                    out_of_range_coord = e.get('coord')

    # 2. Evaluate castable active / additional spells
    need_heal_allies = []
    for a_uid, a_entry, _is_self in allies:
        ahp = engine._get_combat_hp(a_uid) or 0
        achar = engine.get_char(a_uid)
        amhp = max(1, (achar.get_attr('体力上限', ahp) if achar else ahp) or 1)
        missing = max(0, amhp - ahp)
        if engine._is_dying(a_uid) or ahp / amhp < 0.82:
            need_heal_allies.append((1.0 - ahp / amhp, missing, a_uid, a_entry.get('name', a_uid)))
    need_heal_allies.sort(reverse=True)

    for spell in spells:
        cmd = _can_cast_spell(engine, base, spell, my_acts, failed)
        if not cmd:
            continue
        effects = _spell_effects(spell)
        if not effects:
            continue
        sname = spell.get('name', cmd)
        cast_skill_name = spell.get('判定技能', spell.get('skill', ''))
        cast_skill_val = char.get_attr(cast_skill_name, 75) if cast_skill_name else 75
        hit_p = _estimate_hit_prob(engine._apply_buff_skill_mod(base, cast_skill_val, cast_skill_name) if cast_skill_name else 85)

        has_dmg = any(e.get('type') == 1 or (e.get('type') == 8 and e.get('每回合伤害骰')) for e in effects)
        has_heal = any(e.get('type') in (2, 18) or (e.get('type') == 8 and e.get('回复hp')) for e in effects)
        has_revive = any(e.get('type') == 19 for e in effects)
        has_morale_cc = any(e.get('type') == 11 for e in effects)
        has_summon = any(e.get('type') == 5 for e in effects)
        has_cc = has_morale_cc or any(e.get('type') == 4 and str(e.get('客体', 4)) in ('5', '124') for e in effects)
        has_buff = any(e.get('type') in (3, 4) and str(e.get('客体', 4)) not in ('5', '124') for e in effects)

        if has_revive:
            candidates.append((weights['support_heal_weight'] * 2.4, cmd, None, f'施放【{sname}】唤醒阵亡队友'))
        elif has_dmg or has_cc:
            est_dmg, is_aoe, effect_cc = _estimate_spell_damage(engine, base, spell, enemies[0])
            sr = _spell_offensive_range(engine, base, spell)
            best_desired_range = max(best_desired_range, sr)
            enemy_mult = min(len(enemies), 3) if is_aoe else 1.0
            for e in enemies:
                sc = _enemy_target_score(engine, base, e, est_dmg * enemy_mult, hit_p, weights)
                if has_morale_cc:
                    sc += weights['cc_weight'] * 1.15
                elif effect_cc or has_cc:
                    sc += weights['cc_weight'] * (0.85 if not e.get('isSummon') else 0.35)
                if any(ef.get('type') == 8 and ef.get('每回合伤害骰') for ef in effects):
                    sc += weights['zone_weight'] * 0.45
                if any(ef.get('consume_moon') for ef in effects):
                    sc *= 1.15
                # If command is pure range-checked (type==1) verify reachability
                has_type1_enemy = any(
                    ef.get('type') == 1 and str(ef.get('客体', 0)).upper() in ('4', '5', '24', '45', 'R', 'RP')
                    for ef in effects
                )
                reachable_ok = (not has_type1_enemy) or engine._can_reach_attack_range(base, e['userId'], sr)
                if reachable_ok:
                    ename = e.get('name', e['userId'])
                    candidates.append((sc, cmd, e['userId'], f'释放【{sname}】打击 {ename}'))
                else:
                    if sc > out_of_range_best:
                        out_of_range_best = sc
                        out_of_range_coord = e.get('coord')
        elif has_summon:
            sc = weights['summon_weight']
            if cmd.startswith('.a '):
                sc += 12.0  # Additional action summon leaves main action free
            candidates.append((sc, cmd, None, f'召唤伙伴【{sname}】增强战力'))
        elif has_heal:
            if need_heal_allies:
                urgency, missing, ally_uid, ally_name = need_heal_allies[0]
                sc = weights['support_heal_weight'] * (0.7 + urgency * 1.6) * st_mults['heal_mult']
                if missing <= 2 and not any(ef.get('type') == 8 for ef in effects):
                    sc *= 0.45
                if cmd.startswith('.a '):
                    sc += 10.0
                candidates.append((sc, cmd, ally_uid, f'施放【{sname}】治疗 {ally_name}'))
        elif has_buff:
            if not _spell_is_already_active(engine, base, spell):
                # Signature combat enchants stay high priority; minor self-buffs wait behind real attacks
                is_sig_buff = sname in ('火焰附魔', '幻造兵武', '斗殴精通', '斗殴强化', '猩红眼眸', '辉月女神的祝福')
                sc = (weights['buff_weight'] + 6.0) if is_sig_buff else (weights['buff_weight'] * 0.55)
                if cmd.startswith('.a '):
                    sc += 14.0
                candidates.append((sc, cmd, base, f'开启增益【{sname}】'))

    # 3. Check tactical movement (.a m <coord>) BEFORE burning main action
    can_move_now = (
        my_acts.get('附加', 0) > 0
        and base not in getattr(engine, '_moved_this_turn', set())
    )
    me_entry = engine._unit_il_entry(base, engine._get_initiative())
    cur_coord = me_entry.get('coord', '') if me_entry else ''

    if can_move_now and cur_coord:
        best_move_coord, move_gain, move_reason = plan_best_move(
            engine, base, role=role, stance=stance, weights=weights,
            desired_range=best_desired_range, focus_coord=out_of_range_coord,
        )
        if best_move_coord:
            move_cmd = f'.a m {best_move_coord}'
            if move_cmd not in failed:
                # Must move if NO attacks/spells can reach from current tile, OR
                # tile positioning score beats move_threshold significantly for ranged/hazard avoidance.
                enemies_close = any(
                    grid_dist(cur_coord, e.get('coord', '')) <= 1
                    for e in enemies if e.get('coord')
                )
                in_hazard = cur_coord in engine._unit_hazard_coords(base)
                has_good_offense = bool(candidates) and max(c[0] for c in candidates) >= 22.0
                should_reposition = (
                    not candidates
                    or in_hazard
                    or (role in ('ranged', 'support', 'summoner') and enemies_close and move_gain > 2.0)
                    or (not has_good_offense and move_gain >= weights['move_threshold'] * 1.75)
                    or move_gain >= weights['move_threshold'] * 2.8
                )
                if should_reposition and move_gain > -2.0:
                    engine._last_ai_reason = move_reason
                    return move_cmd, move_reason

    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        _best_score, best_cmd, best_tgt, reason = candidates[0]
        if best_tgt:
            engine._set_autochess_pending_target(base, best_tgt)
        engine._last_ai_reason = reason
        return best_cmd, reason

    # Last fallback: advance even slightly if out of range and movement still available
    if can_move_now and out_of_range_coord:
        best_move_coord, _gain, move_reason = plan_best_move(
            engine, base, role=role, stance=stance, weights=weights,
            desired_range=best_desired_range, focus_coord=out_of_range_coord,
        )
        if best_move_coord and f'.a m {best_move_coord}' not in failed:
            reason = move_reason or f'向敌方推进至 {best_move_coord}'
            engine._last_ai_reason = reason
            return f'.a m {best_move_coord}', reason

    reason = '暂无更优可执行动作，结束回合'
    engine._last_ai_reason = reason
    return '.i end', reason


def choose_tactical_reaction(engine, atk_uid, def_uid, can_dodge=True, can_counter=True,
                             can_block=False, atk_rank=None, dmg_dice='1d8', restim_mode=None):
    """Unified spatial/tactical reaction picker delegating to CombatEngine EV evaluator."""
    choice = engine._choose_autochess_reaction(
        atk_uid, def_uid, can_dodge, can_counter, can_block,
        atk_rank if atk_rank is not None else 1, dmg_dice, restim_mode=restim_mode,
    )
    if choice:
        return choice
    if can_dodge:
        return 'dodge'
    if can_counter:
        return 'counter'
    if can_block:
        return 'block'
    return 'dodge'
