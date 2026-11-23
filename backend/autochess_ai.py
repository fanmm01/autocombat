"""AI commander preparation heuristics for 4-player Auto-Chess lobbies."""

from autochess_catalog import AUGMENTS, LEVEL_TABLE, UNIT_CATALOG, compute_active_synergies


def pick_augment_for_commander(commander, choices):
    """Score augment choices against commander's personality and current roster."""
    if not choices:
        return None
    personality = commander.get('personality', 'econ')
    board = [u for u in commander.get('units', []) if u.get('location') == 'board']
    synergies = compute_active_synergies(board)
    has_summon = any(UNIT_CATALOG.get(u['serial'], {}).get('role') == 'summoner' for u in board)
    has_ranged = any(UNIT_CATALOG.get(u['serial'], {}).get('role') == 'ranged' for u in board)

    def _score(aug):
        aid = aug.get('id', '')
        sc = 50.0
        if personality == 'econ' and aid in ('aug_econ', 'aug_pop', 'aug_xp'):
            sc += 35.0
        elif personality == 'fast_lv' and aid in ('aug_xp', 'aug_pop', 'aug_mana'):
            sc += 35.0
        elif personality == 'reroll' and aid in ('aug_reroll', 'aug_pair', 'aug_precision'):
            sc += 35.0
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
    # Need at least one frontline role if team lacks tank/bruiser
    board = [u for u in units if u.get('location') == 'board']
    front_cnt = sum(
        1 for u in board
        if UNIT_CATALOG.get(u['serial'], {}).get('role') in ('tank', 'bruiser', 'assassin')
    )
    if front_cnt < 2 and meta['role'] in ('tank', 'bruiser'):
        score += 16.0
    return score


def run_commander_prep(match, cid):
    """Execute one AI commander's shop, XP, deployment, and positioning logic."""
    cmd = match.commanders[cid]
    if cmd.get('eliminated'):
        return

    # 1. Pick pending augment if Round 4 / Round 8 offered choices
    if cmd.get('pending_augments'):
        chosen = pick_augment_for_commander(cmd, cmd['pending_augments'])
        if chosen:
            match.pick_augment(cid, chosen)

    personality = cmd.get('personality', 'econ')
    interest_floor = 20 if personality == 'econ' else (10 if personality in ('fast_lv', 'balanced') else 4)

    # 2. Leveling priority before shopping
    for _ in range(4):
        lvl = cmd['level']
        if lvl >= 5:
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

    # 3. Shop & reroll loop
    max_rerolls = 3 if personality == 'reroll' else (2 if personality == 'fast_lv' else 1)
    for step in range(max_rerolls + 1):
        units = cmd['units']
        board_traits = {
            t for u in units if u['location'] == 'board'
            for t in UNIT_CATALOG.get(u['serial'], {}).get('traits', ())
        }
        # Evaluate affordable shop offers sorted by utility
        offers = []
        for idx, slot in enumerate(cmd['shop']):
            if not slot or slot.get('bought'):
                continue
            serial = slot['serial']
            cost = UNIT_CATALOG[serial]['cost']
            if cmd['gold'] < cost:
                continue
            val = _evaluate_shop_offer(cmd, serial, board_traits)
            # Reserve interest unless completing pair/2-star or early rounds
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

        # Consider reroll if free rerolls exist or gold safely exceeds reserve
        can_free = cmd.get('free_rerolls', 0) > 0
        min_gold_for_roll = 2 if can_free else (interest_floor + 2 if match.round_num > 2 else 6)
        if step < max_rerolls and cmd['gold'] >= min_gold_for_roll:
            if match.reroll_shop(cid):
                continue
        break

    # 4. Optimize board deployment up to max_pop (prioritize higher stars & cost + synergy fit)
    cap = match.max_pop(cid)
    all_units = list(cmd['units'])

    def _unit_power(u):
        meta = UNIT_CATALOG.get(u['serial'], {})
        role_w = 4 if meta.get('role') in ('tank', 'bruiser') else (2 if meta.get('role') == 'support' else 3)
        return (u['star'] * 100 + meta.get('cost', 1) * 12 + role_w, u['id'])

    ranked = sorted(all_units, key=_unit_power, reverse=True)
    keep_on_board = {u['id'] for u in ranked[:cap]}

    # Recall bench replacements if needed
    for u in list(cmd['units']):
        if u['location'] == 'board' and u['id'] not in keep_on_board:
            match.recall_unit(cid, u['id'])
    for u in ranked[:cap]:
        if u['location'] != 'board':
            match.deploy_unit(cid, u['id'], None)

    # If bench is overly cluttered with weak 1-stars while strapped for gold, sell lowest 1-star surplus
    bench_surplus = [
        u for u in cmd['units']
        if u['location'] == 'bench' and u['star'] == 1
        and sum(1 for x in cmd['units'] if x['serial'] == u['serial']) == 1
    ]
    if len([u for u in cmd['units'] if u['location'] == 'bench']) >= 5 and bench_surplus:
        weakest = min(bench_surplus, key=lambda u: UNIT_CATALOG.get(u['serial'], {}).get('cost', 1))
        match.sell_unit(cid, weakest['id'])

    match.auto_arrange(cid)
