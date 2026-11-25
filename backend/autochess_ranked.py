"""Ranked mode tier system, LP rules, shield cards, off-match coins, and leaderboard."""

import random
import time

SILVER_FLOOR_LP = 300
SHIELD_CARD_CAP = 5
BASE_WIN_COINS = {1: 120, 2: 80, 3: 55, 4: 35}
WIN_STREAK_LP_BONUS = {2: 5, 3: 10, 4: 15}

RANK_TIERS = (
    {
        'id': 'bronze',
        'name': '青铜',
        'divisions': 3,
        'division_labels': ('III', 'II', 'I'),
        'base_lp': 0,
        'color': '#b47348',
        'lp_table': (100, 75, 55, 35, 20, 10, 5, 0),
        'coin_mult': 1.0,
    },
    {
        'id': 'silver',
        'name': '白银',
        'divisions': 4,
        'division_labels': ('IV', 'III', 'II', 'I'),
        'base_lp': 300,
        'color': '#94a3b8',
        'lp_table': (75, 55, 35, 20, 5, -5, -15, -25),
        'coin_mult': 1.15,
    },
    {
        'id': 'gold',
        'name': '黄金',
        'divisions': 5,
        'division_labels': ('V', 'IV', 'III', 'II', 'I'),
        'base_lp': 700,
        'color': '#eab308',
        'lp_table': (50, 35, 22, 12, -5, -15, -28, -40),
        'coin_mult': 1.3,
    },
    {
        'id': 'platinum',
        'name': '铂金',
        'divisions': 5,
        'division_labels': ('V', 'IV', 'III', 'II', 'I'),
        'base_lp': 1200,
        'color': '#14b8a6',
        'lp_table': (50, 35, 20, 10, -10, -22, -35, -50),
        'coin_mult': 1.5,
    },
    {
        'id': 'diamond',
        'name': '钻石',
        'divisions': 5,
        'division_labels': ('V', 'IV', 'III', 'II', 'I'),
        'base_lp': 1700,
        'color': '#3b82f6',
        'lp_table': (35, 24, 14, 5, -12, -25, -40, -55),
        'coin_mult': 1.75,
    },
    {
        'id': 'king',
        'name': '王者',
        'divisions': None,
        'division_labels': (),
        'base_lp': 2200,
        'color': '#a855f7',
        'lp_table': (20, 12, 5, 1, -15, -30, -45, -60),
        'coin_mult': 2.0,
    },
)

RANK_TIER_BY_ID = {t['id']: t for t in RANK_TIERS}


def describe_rank(total_lp, silver_floor_unlocked=False):
    """Convert total_lp (with permanent silver floor flag) into structured tier & division info."""
    raw_lp = max(0, int(total_lp or 0))
    floor_unlocked = bool(silver_floor_unlocked or raw_lp >= SILVER_FLOOR_LP)
    lp = max(SILVER_FLOOR_LP, raw_lp) if floor_unlocked else raw_lp
    division_index = lp // 100
    division_lp = lp % 100

    picked_tier = RANK_TIERS[0]
    for tier in RANK_TIERS:
        if lp >= tier['base_lp']:
            picked_tier = tier
        else:
            break

    if picked_tier['divisions'] is None:
        king_level = 1 + (lp - picked_tier['base_lp']) // 100
        division_label = str(king_level)
        full_label = f"{picked_tier['name']} {king_level}"
    else:
        sub_idx = (lp - picked_tier['base_lp']) // 100
        sub_idx = max(0, min(len(picked_tier['division_labels']) - 1, sub_idx))
        division_label = picked_tier['division_labels'][sub_idx]
        king_level = None
        full_label = f"{picked_tier['name']} {division_label}"

    return {
        'total_lp': lp,
        'tier_id': picked_tier['id'],
        'tier_name': picked_tier['name'],
        'tier_color': picked_tier['color'],
        'division_index': division_index,
        'division_label': division_label,
        'full_label': full_label,
        'division_lp': division_lp,
        'next_division_lp': 100,
        'king_level': king_level,
        'silver_floor_unlocked': floor_unlocked,
    }


def default_ranked_profile():
    """Return initial ranked & economy state for newly registered Auto-Chess accounts."""
    return {
        'total_lp': 0,
        'peak_lp': 0,
        'silver_floor_unlocked': False,
        'win_streak': 0,
        'best_win_streak': 0,
        'shield_cards': 0,
        'games': 0,
        'wins': 0,
        'firsts': 0,
        'coins': 0,
        'history': [],
        'settled_match_ids': [],
    }


def normalize_ranked_profile(raw):
    """Safely normalize an existing or legacy account ranked dictionary."""
    base = default_ranked_profile()
    if not isinstance(raw, dict):
        return base
    total_lp = max(0, int(raw.get('total_lp', 0) or 0))
    floor_unlocked = bool(raw.get('silver_floor_unlocked', False) or total_lp >= SILVER_FLOOR_LP)
    if floor_unlocked and total_lp < SILVER_FLOOR_LP:
        total_lp = SILVER_FLOOR_LP
    base['total_lp'] = total_lp
    base['peak_lp'] = max(total_lp, int(raw.get('peak_lp', 0) or 0))
    base['silver_floor_unlocked'] = floor_unlocked
    base['win_streak'] = max(0, int(raw.get('win_streak', 0) or 0))
    base['best_win_streak'] = max(base['win_streak'], int(raw.get('best_win_streak', 0) or 0))
    base['shield_cards'] = max(0, min(SHIELD_CARD_CAP, int(raw.get('shield_cards', 0) or 0)))
    base['games'] = max(0, int(raw.get('games', 0) or 0))
    base['wins'] = max(0, int(raw.get('wins', 0) or 0))
    base['firsts'] = max(0, int(raw.get('firsts', 0) or 0))
    base['coins'] = max(0, int(raw.get('coins', 0) or 0))
    hist = raw.get('history')
    base['history'] = list(hist[-20:]) if isinstance(hist, list) else []
    settled = raw.get('settled_match_ids')
    base['settled_match_ids'] = [str(x) for x in settled[-100:]] if isinstance(settled, list) else []
    return base


def public_ranked_profile(raw):
    """Return UI-safe ranked payload including live computed rank_info."""
    prof = normalize_ranked_profile(raw)
    rank_info = describe_rank(prof['total_lp'], prof['silver_floor_unlocked'])
    return {
        'total_lp': prof['total_lp'],
        'peak_lp': prof['peak_lp'],
        'silver_floor_unlocked': prof['silver_floor_unlocked'],
        'win_streak': prof['win_streak'],
        'best_win_streak': prof['best_win_streak'],
        'shield_cards': prof['shield_cards'],
        'shield_card_cap': SHIELD_CARD_CAP,
        'games': prof['games'],
        'wins': prof['wins'],
        'firsts': prof['firsts'],
        'coins': prof['coins'],
        'history': prof['history'],
        'rank_info': rank_info,
    }


def settle_ranked_match(profile, placement, match_id=None, rng=None):
    """Settle one 8-player ranked placement, returning (updated_profile, settlement_report)."""
    prof = normalize_ranked_profile(profile)
    place = max(1, min(8, int(placement or 8)))
    old_lp = prof['total_lp']
    old_rank = describe_rank(old_lp, prof['silver_floor_unlocked'])
    tier = RANK_TIER_BY_ID[old_rank['tier_id']]
    base_delta = int(tier['lp_table'][place - 1])

    won = place <= 4
    if won:
        new_streak = prof['win_streak'] + 1
        best_streak = max(prof['best_win_streak'], new_streak)
        streak_bonus = 20 if new_streak >= 5 else int(WIN_STREAK_LP_BONUS.get(new_streak, 0))

        shield_card_earned = 0
        if prof['shield_cards'] < SHIELD_CARD_CAP:
            if new_streak == 3:
                shield_card_earned = 1
            elif new_streak >= 4:
                roller = rng or random
                chance = 0.50 if place == 1 else 0.35
                if roller.random() < chance:
                    shield_card_earned = 1

        base_coin = BASE_WIN_COINS[place]
        coins_earned = int(round(base_coin * tier['coin_mult'])) + 10 * min(new_streak, 5)
    else:
        new_streak = 0
        best_streak = prof['best_win_streak']
        streak_bonus = 0
        shield_card_earned = 0
        coins_earned = 0

    raw_delta = base_delta + streak_bonus
    min_floor = SILVER_FLOOR_LP if (prof['silver_floor_unlocked'] or old_lp >= SILVER_FLOOR_LP) else 0
    raw_new_lp = old_lp + raw_delta

    silver_floor_triggered = False
    shield_card_used = False

    if raw_delta < 0:
        clamped_lp = max(min_floor, raw_new_lp)
        would_drop_below_silver = (min_floor == SILVER_FLOOR_LP and raw_new_lp < SILVER_FLOOR_LP)

        if would_drop_below_silver:
            # Hard silver floor always takes precedence at 300 LP so we never waste a shield card.
            if old_lp == SILVER_FLOOR_LP:
                new_lp = SILVER_FLOOR_LP
                silver_floor_triggered = True
            elif (clamped_lp // 100) < (old_lp // 100) and prof['shield_cards'] > 0:
                shield_card_used = True
                new_lp = old_lp
                prof['shield_cards'] -= 1
            else:
                new_lp = clamped_lp
                silver_floor_triggered = True
        else:
            if (clamped_lp // 100) < (old_lp // 100) and prof['shield_cards'] > 0:
                shield_card_used = True
                new_lp = old_lp
                prof['shield_cards'] -= 1
            else:
                new_lp = clamped_lp
    else:
        new_lp = max(min_floor, raw_new_lp)

    prof['total_lp'] = new_lp
    prof['peak_lp'] = max(prof['peak_lp'], new_lp)
    prof['silver_floor_unlocked'] = bool(prof['silver_floor_unlocked'] or new_lp >= SILVER_FLOOR_LP)
    prof['win_streak'] = new_streak
    prof['best_win_streak'] = best_streak
    prof['shield_cards'] = max(0, min(SHIELD_CARD_CAP, prof['shield_cards'] + shield_card_earned))
    prof['coins'] += coins_earned
    prof['games'] += 1
    if won:
        prof['wins'] += 1
    if place == 1:
        prof['firsts'] += 1

    new_rank = describe_rank(prof['total_lp'], prof['silver_floor_unlocked'])
    net_delta = new_lp - old_lp

    settlement = {
        'match_id': match_id,
        'placement': place,
        'won': won,
        'old_lp': old_lp,
        'new_lp': new_lp,
        'base_delta': base_delta,
        'streak_bonus': streak_bonus,
        'net_delta': net_delta,
        'win_streak': new_streak,
        'old_rank': old_rank,
        'new_rank': new_rank,
        'promoted': new_rank['division_index'] > old_rank['division_index'],
        'demoted': new_rank['division_index'] < old_rank['division_index'],
        'tier_changed': new_rank['tier_id'] != old_rank['tier_id'],
        'silver_floor_triggered': silver_floor_triggered,
        'shield_card_used': shield_card_used,
        'shield_card_earned': shield_card_earned,
        'shield_cards_after': prof['shield_cards'],
        'coins_earned': coins_earned,
        'coins_after': prof['coins'],
    }

    prof['history'].append({
        'match_id': match_id,
        'placement': place,
        'old_lp': old_lp,
        'new_lp': new_lp,
        'net_delta': net_delta,
        'tier_label': new_rank['full_label'],
        'coins_earned': coins_earned,
        'shield_card_used': shield_card_used,
        'shield_card_earned': shield_card_earned,
        'timestamp': int(time.time()),
    })
    prof['history'] = prof['history'][-20:]
    if match_id:
        prof['settled_match_ids'].append(str(match_id))
        prof['settled_match_ids'] = prof['settled_match_ids'][-100:]

    return prof, settlement


def build_leaderboard(account_records, viewer_account_id=None, tier_filter=None, limit=100, ranked_field='ranked'):
    """Rank all registered accounts by total_lp and tie-breakers, supporting tier filtering."""
    tier_distribution = {t['id']: 0 for t in RANK_TIERS}
    normalized_rows = []
    for rec in account_records or ():
        if not isinstance(rec, dict) or not rec.get('id'):
            continue
        prof = normalize_ranked_profile(rec.get(ranked_field))
        if ranked_field != 'ranked':
            prof['coins'] = normalize_ranked_profile(rec.get('ranked'))['coins']
        rank_info = describe_rank(prof['total_lp'], prof['silver_floor_unlocked'])
        tier_distribution[rank_info['tier_id']] += 1
        games = prof['games']
        win_rate = round((prof['wins'] / games) * 100, 1) if games > 0 else 0.0
        normalized_rows.append({
            'account_id': rec['id'],
            'username': rec.get('username', rec['id']),
            'display_name': rec.get('display_name') or rec.get('username', rec['id']),
            'total_lp': prof['total_lp'],
            'peak_lp': prof['peak_lp'],
            'rank_info': rank_info,
            'games': games,
            'wins': prof['wins'],
            'firsts': prof['firsts'],
            'win_rate': win_rate,
            'win_streak': prof['win_streak'],
            'shield_cards': prof['shield_cards'],
            'coins': prof['coins'],
            'silver_floor_unlocked': prof['silver_floor_unlocked'],
            'created_at': float(rec.get('created_at', 0) or 0),
        })

    normalized_rows.sort(
        key=lambda row: (
            -row['total_lp'],
            -row['wins'],
            -row['firsts'],
            -row['games'],
            row['created_at'],
            row['username'],
        )
    )

    my_rank = None
    my_entry = None
    for idx, row in enumerate(normalized_rows, start=1):
        row['rank'] = idx
        row.pop('created_at', None)
        if viewer_account_id and row['account_id'] == viewer_account_id:
            my_rank = idx
            my_entry = dict(row)

    cleaned_filter = str(tier_filter or '').strip().lower()
    if cleaned_filter and cleaned_filter != 'all' and cleaned_filter in RANK_TIER_BY_ID:
        filtered = [r for r in normalized_rows if r['rank_info']['tier_id'] == cleaned_filter]
    else:
        filtered = normalized_rows

    safe_limit = max(1, min(500, int(limit or 100)))
    return {
        'entries': filtered[:safe_limit],
        'total_players': len(normalized_rows),
        'filtered_total': len(filtered),
        'tier_distribution': tier_distribution,
        'my_rank': my_rank,
        'my_entry': my_entry,
    }


def ranked_rules_summary():
    """Export UI/Wiki summary of ranked tiers, LP deltas, and mechanics."""
    return {
        'silver_floor_lp': SILVER_FLOOR_LP,
        'shield_card_cap': SHIELD_CARD_CAP,
        'win_streak_lp_bonus': {'2': 5, '3': 10, '4': 15, '5+': 20},
        'base_win_coins': {str(k): v for k, v in BASE_WIN_COINS.items()},
        'tiers': [
            {
                'id': t['id'],
                'name': t['name'],
                'divisions': t['divisions'],
                'division_labels': list(t['division_labels']),
                'base_lp': t['base_lp'],
                'color': t['color'],
                'lp_table': list(t['lp_table']),
                'coin_mult': t['coin_mult'],
            }
            for t in RANK_TIERS
        ],
    }
