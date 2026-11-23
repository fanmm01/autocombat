"""Full Auto-Chess match engine supporting 4-commander AI lobbies and 12-wave PvE runs."""

import copy
import random
import time
import uuid

from ai_battle import AIController, DisplayLevel
from ai_tactics import decide_tactical_action, plan_formation
from arena_presets import ARENA_PRESETS, build_arena_map, is_in_deploy_zone
from autochess_ai import run_commander_prep
from autochess_catalog import (
    AUGMENTS,
    CHAR_DATA_BY_SERIAL,
    LEVEL_TABLE,
    POOL_COUNTS,
    PVE_WAVES,
    UNIT_CATALOG,
    apply_autochess_modifiers,
    apply_opening_shields,
    compute_active_synergies,
)
from battle_engine import FullBattleEngine, action_committed, parse_coord
from grid_nav import terrain_type


def _classify_vfx_kind(serial, cmd, skill_name, lines):
    text = f"{skill_name} {' '.join(lines or ())}"
    if any(k in text for k in ('召唤', '四象', '使魔', '蜂鸟', '藤蔓', '生灵', '虚假之月')):
        return 'summon'
    if any(k in text for k in ('冰', '雪', '寒霜', '冻')):
        return 'frost'
    if any(k in text for k in ('回复HP', '治愈', '蛋糕', '护盾', '生命之歌', '急救', '复活', '返生')):
        return 'heal'
    if any(k in text for k in ('火', '炎', '燃', '爆破', '焚', '熔')):
        return 'fire'
    if any(k in text for k in ('血月', '吸血', '血池', '镰', '血蝠', '血之')):
        return 'blood'
    if any(k in text for k in ('星闪', '星辰', '月光', '乌托邦', '激光', '星光', '王座')):
        return 'star'
    if cmd and cmd.startswith('.a m '):
        return 'slash'
    by_serial = {
        'Y1': 'fire', 'Y2': 'fire', 'Y14': 'star', 'Y15': 'fire',
        'Y6': 'frost', 'Y4': 'star', 'Y16': 'star',
        'Y5': 'blood', 'Y11': 'blood', 'Y17': 'blood',
        'Y7': 'heal', 'Y8': 'heal', 'Y10': 'heal',
        'Y9': 'summon', 'Y12': 'summon',
    }
    return by_serial.get(serial, 'slash')


def _extract_skill_name(cmd, lines):
    import re
    for ln in lines or ():
        m = re.search(r'【([^】]{1,24})】', str(ln))
        if m:
            return m.group(1)
        if '使用技能' in str(ln) or '施放' in str(ln):
            m2 = re.search(r'(?:使用技能|施放)[「【]?([^\s」】]+)', str(ln))
            if m2:
                return m2.group(1)
    if cmd and (cmd == 'att' or cmd.startswith('att ') or '攻击' in cmd):
        return '普通攻击'
    if cmd and cmd.startswith('.a s'):
        return cmd
    return ''


class _HeadlessEngineProxy(FullBattleEngine):
    """FullBattleEngine wrapper providing clean step-by-step playback and telemetry."""

    def __init__(self, max_rounds=22):
        super().__init__(fast_mode=False)
        self.max_rounds = max_rounds


class AutoChessMatch:
    """State machine for multi-round CoC Magical-Girl Auto-Chess runs."""

    def __init__(
        self,
        match_id=None,
        mode='lobby4',
        arena_preset='autochess_standard',
        seed=None,
        player_name='指挥官',
        human_players=None,
        fill_bots=True,
        prep_duration=30,
    ):
        self.id = match_id or f'ac_{uuid.uuid4().hex[:10]}'
        self.mode = mode if mode in ('lobby4', 'pve12', 'pvp_room') else 'lobby4'
        self.arena_preset = arena_preset if arena_preset in ARENA_PRESETS else 'autochess_standard'
        self.seed = int(seed if seed is not None else random.randint(1, 10**9))
        self._rng = random.Random(self.seed)
        self.fill_bots = bool(fill_bots)
        self.prep_duration = max(15, int(prep_duration or 30))
        self.round_num = 1
        self.prep_deadline = time.time() + self.prep_duration
        self.phase = 'prep'  # 'prep' | 'combat' | 'round_result' | 'finished'
        self.winner_id = None
        self.uid_seq = 1
        self.pool = {
            serial: POOL_COUNTS[meta['cost']]
            for serial, meta in UNIT_CATALOG.items()
        }
        self.logs = []
        self.combat_frames = []
        self.last_round_report = None
        self.round_reports = {}
        self.commanders = {}
        self.player_id = 'P1'
        self._live_engine = None
        self._live_matchup = None
        self._live_bouts = []

        self._init_commanders(player_name, human_players=human_players)
        for cid in self.commanders:
            self._roll_shop_for(cid, free=True)
        self._deal_starter_units()
        self.logs.append(f'星序自走棋开启：模式={self.mode}，战场={ARENA_PRESETS[self.arena_preset]["name"]}')

    def _init_commanders(self, player_name, human_players=None):
        init_hp = 45 if self.mode == 'pve12' else 58
        if self.mode == 'pvp_room' and human_players:
            for idx, hp_info in enumerate(human_players[:4], start=1):
                cid = f'P{idx}'
                self.commanders[cid] = self._new_commander(
                    cid,
                    str(hp_info.get('name') or f'指挥官{idx}')[:24],
                    is_human=True,
                    hp=init_hp,
                    personality='balanced',
                    account_id=hp_info.get('account_id'),
                    token_overrides=hp_info.get('token_overrides'),
                )
            if self.fill_bots:
                bots = [
                    ('苍星·守序者 (运营AI)', 'econ'),
                    ('绯月·跃迁者 (速升AI)', 'fast_lv'),
                    ('炽羽·强袭者 (追三AI)', 'reroll'),
                    ('岚风·均衡者 (战术AI)', 'balanced'),
                ]
                b_idx = 0
                while len(self.commanders) < 4 and b_idx < len(bots):
                    cid = f'P{len(self.commanders) + 1}'
                    bname, pers = bots[b_idx]
                    self.commanders[cid] = self._new_commander(
                        cid, bname, is_human=False, hp=init_hp, personality=pers
                    )
                    b_idx += 1
            return

        self.commanders['P1'] = self._new_commander('P1', player_name, is_human=True, hp=init_hp, personality='balanced')
        if self.mode == 'lobby4':
            bots = [
                ('P2', '苍星·守序者 (运营AI)', 'econ'),
                ('P3', '绯月·跃迁者 (速升AI)', 'fast_lv'),
                ('P4', '炽羽·强袭者 (追三AI)', 'reroll'),
            ]
            for bid, bname, pers in bots:
                self.commanders[bid] = self._new_commander(bid, bname, is_human=False, hp=init_hp, personality=pers)

    def _new_commander(self, cid, name, *, is_human, hp, personality, account_id=None, token_overrides=None):
        return {
            'id': cid,
            'name': name,
            'account_id': account_id,
            'is_human': is_human,
            'personality': personality,
            'ready': False,
            'next_ready': False,
            'token_overrides': dict(token_overrides or {}),
            'hp': hp,
            'max_hp': hp,
            'gold': 6,
            'level': 1,
            'xp': 0,
            'streak': 0,  # >0 win streak, <0 loss streak
            'max_interest': 5,
            'pop_bonus': 0,
            'free_rerolls': 0,
            'shop_locked': False,
            'shop': [],
            'units': [],
            'augments': [],
            'pending_augments': [],
            'eliminated': False,
            'placement': None,
            'wins': 0,
            'losses': 0,
        }

    def commander_id_for_account(self, account_id):
        if not account_id:
            return None
        for cid, cmd in self.commanders.items():
            if cmd.get('is_human') and cmd.get('account_id') == account_id:
                return cid
        return None

    def human_commanders(self, alive_only=True):
        return [
            cmd for cmd in self.commanders.values()
            if cmd.get('is_human') and (not alive_only or not cmd.get('eliminated'))
        ]

    def set_ready(self, cid, ready=True):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        cmd = self.commanders.get(cid)
        if not cmd or cmd.get('eliminated'):
            return False, '指挥官不存在或已被淘汰'
        if ready and cmd.get('pending_augments'):
            return False, '请先选择【星序祝福】后再就绪'
        cmd['ready'] = bool(ready)
        return True, ('已准备就绪' if cmd['ready'] else '已取消准备')

    def all_humans_ready(self):
        humans = self.human_commanders(alive_only=True)
        return bool(humans) and all(bool(c.get('ready')) for c in humans)

    def set_next_ready(self, cid, ready=True):
        if self.phase != 'round_result':
            return False, '当前非结算阶段'
        cmd = self.commanders.get(cid)
        if not cmd:
            return False, '指挥官不存在'
        cmd['next_ready'] = bool(ready)
        return True, '已确认进入下一回合'

    def all_humans_next_ready(self):
        humans = self.human_commanders(alive_only=True)
        return bool(humans) and all(bool(c.get('next_ready')) for c in humans)

    def set_commander_tokens(self, account_id, token_overrides):
        for cmd in self.commanders.values():
            if cmd.get('account_id') == account_id:
                cmd['token_overrides'] = dict(token_overrides or {})

    def _next_unit_id(self):
        uid = f'u_{self.uid_seq:04d}'
        self.uid_seq += 1
        return uid

    def _deal_starter_units(self):
        one_costs = [s for s, m in UNIT_CATALOG.items() if m['cost'] == 1]
        for cid, cmd in self.commanders.items():
            starter = self._rng.choice(one_costs)
            if self.pool.get(starter, 0) > 0:
                self.pool[starter] -= 1
                md = build_arena_map(self.arena_preset)
                cols = sorted(md['deploy_cols']['Y'])
                default_c = md['width'] >= 10
                coord = None
                for c in reversed(cols):
                    alt = f'{chr(65 + c)}{md["height"] // 2 + 1}'
                    if terrain_type(md, alt) != 'wall':
                        coord = alt
                        break
                cmd['units'].append({
                    'id': self._next_unit_id(),
                    'serial': starter,
                    'star': 1,
                    'location': 'board',
                    'bench_idx': None,
                    'coord': coord,
                    'stance': 'balanced',
                })

    def max_pop(self, cid):
        cmd = self.commanders[cid]
        return LEVEL_TABLE[cmd['level']]['max_pop'] + int(cmd.get('pop_bonus', 0) or 0)

    def board_units(self, cid):
        return [u for u in self.commanders[cid]['units'] if u['location'] == 'board']

    def bench_units(self, cid):
        return sorted(
            [u for u in self.commanders[cid]['units'] if u['location'] == 'bench'],
            key=lambda u: u['bench_idx'] if u['bench_idx'] is not None else 99,
        )

    def bench_capacity(self, cid):
        cmd = self.commanders[cid]
        level = cmd['level']
        base = 10 if level >= 5 else 8 if level >= 3 else 6
        return base + (2 if 'aug_reserves' in cmd['augments'] else 0)

    def _free_bench_slot(self, cid):
        used = {u['bench_idx'] for u in self.bench_units(cid)}
        capacity = self.bench_capacity(cid)
        if len(used) >= capacity:
            return None
        for idx in range(capacity):
            if idx not in used:
                return idx
        return None

    def _free_board_coord(self, cid, arena_preset=None):
        md = build_arena_map(arena_preset or self.arena_preset)
        occupied = {u['coord'] for u in self.board_units(cid) if u.get('coord')}
        cols = sorted(md['deploy_cols']['Y'])
        mid_r = md['height'] // 2
        rows = sorted(range(md['height']), key=lambda r: (abs(r - mid_r), r))
        for col in reversed(cols):
            for r in rows:
                coord = f'{chr(65 + col)}{r + 1}'
                if coord not in occupied and terrain_type(md, coord) != 'wall':
                    return coord
        return None

    def _roll_shop_for(self, cid, free=False):
        cmd = self.commanders[cid]
        if cmd.get('eliminated'):
            return False
        lvl = cmd['level']
        odds = dict(LEVEL_TABLE[lvl]['odds'])
        if any(a == 'aug_reroll' for a in cmd.get('augments', [])):
            odds = {1: max(5, odds[1] - 8), 2: odds[2], 3: odds[3] + 5, 4: odds[4] + 3}
        temp_pool = dict(self.pool)
        slots = []
        for _ in range(5):
            # Sample cost tier filtered by costs that still have available copies
            avail_costs = [
                cost for cost, w in odds.items()
                if w > 0 and any(temp_pool.get(s, 0) > 0 for s, m in UNIT_CATALOG.items() if m['cost'] == cost)
            ]
            if not avail_costs:
                avail_all = [s for s, cnt in temp_pool.items() if cnt > 0]
                if not avail_all:
                    slots.append(None)
                    continue
                picked = self._rng.choice(avail_all)
            else:
                weights = [odds[c] for c in avail_costs]
                picked_cost = self._rng.choices(avail_costs, weights=weights, k=1)[0]
                pool_cands = []
                for s, m in UNIT_CATALOG.items():
                    if m['cost'] == picked_cost and temp_pool.get(s, 0) > 0:
                        pool_cands.extend([s] * temp_pool[s])
                picked = self._rng.choice(pool_cands)
            temp_pool[picked] -= 1
            slots.append({'serial': picked, 'bought': False})
        cmd['shop'] = slots
        cmd['shop_locked'] = False
        return True

    def _upgrade_hints_for(self, cid):
        cmd = self.commanders[cid]
        counts = {}
        for u in cmd['units']:
            counts[(u['serial'], u['star'])] = counts.get((u['serial'], u['star']), 0) + 1
        hints = []
        for slot in cmd['shop']:
            if not slot or slot.get('bought'):
                hints.append(None)
                continue
            s = slot['serial']
            if counts.get((s, 1), 0) >= 2:
                hints.append('3★!' if counts.get((s, 2), 0) >= 2 else '2★!')
            elif counts.get((s, 1), 0) == 1:
                hints.append('对子')
            else:
                hints.append(None)
        return hints

    def _check_star_up(self, cid):
        cmd = self.commanders[cid]
        msgs = []
        changed = True
        while changed:
            changed = False
            for star in (1, 2):
                buckets = {}
                for u in cmd['units']:
                    if u['star'] == star:
                        buckets.setdefault(u['serial'], []).append(u)
                for serial, group in buckets.items():
                    if len(group) >= 3:
                        # Prefer keeping board unit and its coordinate/stance
                        group_sorted = sorted(
                            group,
                            key=lambda u: (0 if u['location'] == 'board' else 1, u['id']),
                        )
                        keeper = group_sorted[0]
                        sacrificed = {group_sorted[1]['id'], group_sorted[2]['id']}
                        keeper['star'] = star + 1
                        cmd['units'] = [u for u in cmd['units'] if u['id'] not in sacrificed]
                        name = UNIT_CATALOG[serial]['name']
                        msgs.append(f'{cmd["name"]} 的 {name} 合成为 {star + 1}★！')
                        changed = True
                        break
                if changed:
                    break
        return msgs

    # ---- Player / AI Prep Actions ----

    def buy_unit(self, cid, shop_idx):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        cmd = self.commanders[cid]
        if not (0 <= shop_idx < len(cmd['shop'])):
            return False, '商店栏位无效'
        slot = cmd['shop'][shop_idx]
        if not slot or slot.get('bought'):
            return False, '该栏位已售空'
        serial = slot['serial']
        cost = UNIT_CATALOG[serial]['cost']
        if cmd['gold'] < cost:
            return False, '金币不足'
        if self.pool.get(serial, 0) <= 0:
            return False, '公共牌库该棋子已售罄'

        # Allow purchase directly into 3-merge even if bench full
        will_merge = sum(1 for u in cmd['units'] if u['serial'] == serial and u['star'] == 1) >= 2
        bench_slot = self._free_bench_slot(cid)
        auto_deploy = False
        board_coord = None
        if len(self.board_units(cid)) < self.max_pop(cid):
            board_coord = self._free_board_coord(cid)
            auto_deploy = board_coord is not None
        if not auto_deploy and bench_slot is None and not will_merge:
            return False, f'备战席已满（{len(self.bench_units(cid))}/{self.bench_capacity(cid)}）且上阵人口已满'

        cmd['gold'] -= cost
        self.pool[serial] -= 1
        slot['bought'] = True
        unit = {
            'id': self._next_unit_id(),
            'serial': serial,
            'star': 1,
            'location': 'board' if auto_deploy else 'bench',
            'bench_idx': None if auto_deploy else (bench_slot if bench_slot is not None else 0),
            'coord': board_coord if auto_deploy else None,
            'stance': 'balanced',
        }
        cmd['units'].append(unit)
        up_msgs = self._check_star_up(cid)
        if cid == self.player_id:
            for m in up_msgs:
                self.logs.append(f'✨ {m}')
        return True, f'购买 {UNIT_CATALOG[serial]["name"]}' + (f'（{up_msgs[-1]}）' if up_msgs else '')

    def sell_unit(self, cid, unit_id):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        cmd = self.commanders[cid]
        unit = next((u for u in cmd['units'] if u['id'] == unit_id), None)
        if not unit:
            return False, '未找到棋子'
        serial = unit['serial']
        cost = UNIT_CATALOG[serial]['cost']
        star = unit['star']
        refund = cost if star == 1 else max(cost, int(round(cost * (3 ** (star - 1)) * 0.7)))
        copies = 3 ** (star - 1)
        cap = POOL_COUNTS[cost]
        self.pool[serial] = min(cap, self.pool.get(serial, 0) + copies)
        cmd['units'] = [u for u in cmd['units'] if u['id'] != unit_id]
        cmd['gold'] += refund
        return True, f'出售 {UNIT_CATALOG[serial]["name"]} {star}★，返还 {refund}G'

    def reroll_shop(self, cid):
        if self.phase != 'prep':
            return False
        cmd = self.commanders[cid]
        if cmd.get('free_rerolls', 0) > 0:
            cmd['free_rerolls'] -= 1
        elif cmd['gold'] >= 2:
            cmd['gold'] -= 2
        else:
            return False
        return self._roll_shop_for(cid)

    def toggle_lock(self, cid):
        if self.phase != 'prep':
            return False
        cmd = self.commanders[cid]
        cmd['shop_locked'] = not bool(cmd.get('shop_locked'))
        return True

    def buy_xp(self, cid):
        if self.phase != 'prep':
            return False
        cmd = self.commanders[cid]
        if cmd['level'] >= max(LEVEL_TABLE):
            return False
        if cmd['gold'] < 4:
            return False
        cmd['gold'] -= 4
        self._grant_xp(cid, 4)
        return True

    def _grant_xp(self, cid, amount):
        cmd = self.commanders[cid]
        cmd['xp'] += int(amount)
        while cmd['level'] < max(LEVEL_TABLE):
            need = LEVEL_TABLE[cmd['level']]['xp_to_next']
            if need <= 0 or cmd['xp'] < need:
                break
            cmd['xp'] -= need
            cmd['level'] += 1
        if cmd['level'] >= max(LEVEL_TABLE):
            cmd['xp'] = 0

    def deploy_unit(self, cid, unit_id, coord=None):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        cmd = self.commanders[cid]
        unit = next((u for u in cmd['units'] if u['id'] == unit_id), None)
        if not unit:
            return False, '未找到棋子'
        md = build_arena_map(self.arena_preset)
        if coord is None:
            coord = self._free_board_coord(cid)
            if not coord:
                return False, '没有空闲部署格'
        coord = str(coord).upper().strip()
        if not parse_coord(coord) or not is_in_deploy_zone(md, 'Y', coord) or terrain_type(md, coord) == 'wall':
            return False, f'{coord} 不是有效我方部署格'

        occupant = next((u for u in self.board_units(cid) if u['coord'] == coord and u['id'] != unit_id), None)
        if occupant is not None:
            return self.swap_units(cid, unit_id, occupant['id'])

        if unit['location'] != 'board' and len(self.board_units(cid)) >= self.max_pop(cid):
            return False, f'人口已达上限 ({self.max_pop(cid)})，请先撤回或交换'

        unit['location'] = 'board'
        unit['bench_idx'] = None
        unit['coord'] = coord
        return True, f'部署至 {coord}'

    def recall_unit(self, cid, unit_id):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        cmd = self.commanders[cid]
        unit = next((u for u in cmd['units'] if u['id'] == unit_id), None)
        if not unit or unit['location'] != 'board':
            return False, '该棋子不在场上'
        slot = self._free_bench_slot(cid)
        if slot is None:
            return False, '备战席已满'
        unit['location'] = 'bench'
        unit['coord'] = None
        unit['bench_idx'] = slot
        return True, '已撤回备战席'

    def swap_units(self, cid, id_a, id_b):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        cmd = self.commanders[cid]
        ua = next((u for u in cmd['units'] if u['id'] == id_a), None)
        ub = next((u for u in cmd['units'] if u['id'] == id_b), None)
        if not ua or not ub or ua['id'] == ub['id']:
            return False, '交换目标无效'
        loc_a, idx_a, coord_a = ua['location'], ua['bench_idx'], ua['coord']
        ua['location'], ua['bench_idx'], ua['coord'] = ub['location'], ub['bench_idx'], ub['coord']
        ub['location'], ub['bench_idx'], ub['coord'] = loc_a, idx_a, coord_a
        return True, '换位完成'

    def set_stance(self, cid, unit_id, stance):
        if stance not in ('aggressive', 'balanced', 'defensive'):
            return False, '未知战术姿态'
        unit = next((u for u in self.commanders[cid]['units'] if u['id'] == unit_id), None)
        if not unit:
            return False, '未找到棋子'
        unit['stance'] = stance
        return True, f'姿态设为 {stance}'

    def auto_arrange(self, cid):
        md = build_arena_map(self.arena_preset)
        board = self.board_units(cid)
        if not board:
            return True, '无上阵棋子'
        payload = [
            {
                'uid': u['id'],
                'role': UNIT_CATALOG[u['serial']]['role'],
                'stance': u.get('stance', 'balanced'),
            }
            for u in board
        ]
        coords = plan_formation('Y', payload, md)
        for u in board:
            if u['id'] in coords:
                u['coord'] = coords[u['id']]
        return True, '自动排阵完成'

    def _offer_augments_if_due(self):
        if self.round_num not in (4, 8, 12):
            return
        for cid, cmd in self.commanders.items():
            if cmd.get('eliminated') or cmd.get('pending_augments'):
                continue
            owned = set(cmd.get('augments', []))
            pool = [a for a in AUGMENTS if a['id'] not in owned]
            if len(pool) >= 3:
                cmd['pending_augments'] = copy.deepcopy(self._rng.sample(pool, 3))
            elif pool:
                cmd['pending_augments'] = copy.deepcopy(pool)

    def pick_augment(self, cid, aug_id):
        cmd = self.commanders[cid]
        pending = cmd.get('pending_augments') or []
        chosen = next((a for a in pending if a['id'] == aug_id), None)
        if not chosen:
            return False, '无效祝福选项'
        cmd['augments'].append(aug_id)
        cmd['pending_augments'] = []
        if chosen.get('instant_gold'):
            cmd['gold'] += int(chosen['instant_gold'])
        if chosen.get('max_interest'):
            cmd['max_interest'] = max(cmd['max_interest'], int(chosen['max_interest']))
        if chosen.get('instant_xp'):
            self._grant_xp(cid, int(chosen['instant_xp']))
        if chosen.get('free_rerolls'):
            cmd['free_rerolls'] += int(chosen['free_rerolls'])
        if chosen.get('pop_bonus'):
            cmd['pop_bonus'] += int(chosen['pop_bonus'])
        if chosen.get('gift_cost'):
            two_costs = [s for s, m in UNIT_CATALOG.items() if m['cost'] == chosen['gift_cost'] and self.pool.get(s, 0) > 0]
            if two_costs:
                owned_serials = {u['serial'] for u in cmd['units']}
                pair_cands = [s for s in two_costs if s in owned_serials]
                pick_s = self._rng.choice(pair_cands or two_costs)
                slot = self._free_bench_slot(cid)
                if slot is not None or sum(1 for u in cmd['units'] if u['serial'] == pick_s and u['star'] == 1) >= 2:
                    self.pool[pick_s] -= 1
                    cmd['units'].append({
                        'id': self._next_unit_id(),
                        'serial': pick_s,
                        'star': 1,
                        'location': 'bench',
                        'bench_idx': slot if slot is not None else 0,
                        'coord': None,
                        'stance': 'balanced',
                    })
                    self._check_star_up(cid)
        if cid == self.player_id:
            self.logs.append(f'🌟 选择祝福【{chosen["name"]}】：{chosen["desc"]}')
        return True, f'获得祝福：{chosen["name"]}'

    # ---- Combat Construction & Simulation ----

    def _pair_lobby_opponents(self):
        alive = [cid for cid, cmd in self.commanders.items() if not cmd.get('eliminated')]
        self._rng.shuffle(alive)
        pairs = []
        ghost = None
        if len(alive) % 2 == 1:
            odd_cid = alive.pop()
            opp_pool = alive or [self.player_id]
            ghost_src = self._rng.choice(opp_pool)
            pairs.append((odd_cid, ghost_src, True))
        for i in range(0, len(alive), 2):
            pairs.append((alive[i], alive[i + 1], False))
        return pairs

    def _mirror_coord(self, coord, width):
        pt = parse_coord(coord)
        if not pt:
            return coord
        mc = max(0, width - 1 - pt[0])
        return f'{chr(65 + mc)}{pt[1] + 1}'

    def _build_battle_engine(self, left_cfg, right_cfg, preset_id, seed):
        """Construct configured FullBattleEngine(autochess_mode=True) for a bout."""
        self._rng.seed(seed)
        eng = _HeadlessEngineProxy(max_rounds=22)
        md = build_arena_map(preset_id)

        y_configs, x_configs = [], []
        init_coords = {}
        stances = {}

        # Left side ('Y')
        y_auto = plan_formation(
            'Y',
            [{'uid': f"Y_{i}_{u['serial']}", 'role': UNIT_CATALOG[u['serial']]['role'], 'stance': u.get('stance', 'balanced')}
             for i, u in enumerate(left_cfg['units'])],
            md,
        )
        used_y = set()
        for i, u in enumerate(left_cfg['units']):
            uid = f"Y_{i}_{u['serial']}"
            c = u.get('coord')
            if not c or c in used_y or not is_in_deploy_zone(md, 'Y', c) or terrain_type(md, c) == 'wall':
                c = y_auto.get(uid)
            if c:
                used_y.add(c)
                init_coords[uid] = c
            stances[uid] = u.get('stance', 'balanced')
            y_configs.append({'uid': uid, 'serial': u['serial'], 'star': u.get('star', 1)})

        # Right side ('X')
        x_auto = plan_formation(
            'X',
            [{'uid': f"X_{i}_{u['serial']}", 'role': UNIT_CATALOG[u['serial']]['role'], 'stance': u.get('stance', 'balanced')}
             for i, u in enumerate(right_cfg['units'])],
            md,
        )
        used_x = set()
        for i, u in enumerate(right_cfg['units']):
            uid = f"X_{i}_{u['serial']}"
            raw_c = u.get('coord')
            mc = self._mirror_coord(raw_c, md['width']) if raw_c else None
            if not mc or mc in used_x or not is_in_deploy_zone(md, 'X', mc) or terrain_type(md, mc) == 'wall':
                mc = x_auto.get(uid)
            if mc:
                used_x.add(mc)
                init_coords[uid] = mc
            stances[uid] = u.get('stance', 'balanced')
            x_configs.append({'uid': uid, 'serial': u['serial'], 'star': u.get('star', 1)})

        y_syn = compute_active_synergies(y_configs)
        x_syn = compute_active_synergies(x_configs)
        y_uids, y_shields = apply_autochess_modifiers(eng, 'Y', y_configs, y_syn, left_cfg.get('augments', []))
        x_uids, x_shields = apply_autochess_modifiers(eng, 'X', x_configs, x_syn, right_cfg.get('augments', []))

        eng.setup_battle(
            y_uids, x_uids,
            arena_preset=preset_id,
            autochess_mode=True,
            overtime_start_round=12 if (len(y_uids) <= 1 and len(x_uids) <= 1) else 15,
            initial_coords=init_coords,
            unit_stances=stances,
            track_stats=True,
        )
        merged_shields = {}
        merged_shields.update(y_shields)
        merged_shields.update(x_shields)
        apply_opening_shields(eng, merged_shields)
        return eng

    def _run_headless_bout(self, left_cfg, right_cfg, preset_id, seed):
        eng = self._build_battle_engine(left_cfg, right_cfg, preset_id, seed)
        steps = 0
        while steps < 260:
            steps += 1
            state = eng._get_state() or {}
            if state.get('phase') != 'active':
                break
            if state.get('round', 1) > eng.max_rounds:
                break
            self._advance_one_engine_turn(eng)
        return self._extract_bout_outcome(eng)

    def _capture_eng_units(self, eng):
        snap = {}
        for e in eng._battle_unit_entries():
            base = eng._resolve_uid(e['userId'])
            if base in snap:
                continue
            hp = max(0, eng._get_combat_hp(base) or 0)
            shield = sum(
                eff.get('value', 0) for eff in eng._get_effects()
                if eff.get('type') == 'shield' and eng._resolve_uid(eff.get('targetUserId', '')) == base
            )
            char = eng.get_char(base)
            snap[base] = {
                'coord': e.get('coord', ''),
                'hp': hp,
                'shield': shield,
                'team': e.get('team', 'Y'),
                'is_summon': bool(e.get('isSummon', False)),
                'serial': getattr(char, 'serial', '') if char else '',
            }
        return snap

    def _mirror_snapshot_for_right(self, snap):
        if not snap:
            return snap
        w = int(snap.get('width', 10) or 10)
        mir_terrain = {self._mirror_coord(c, w): t for c, t in (snap.get('terrain') or {}).items()}
        dc = snap.get('deploy_cols') or {}
        mir_deploy = {
            'Y': [w - 1 - c for c in dc.get('X', [])],
            'X': [w - 1 - c for c in dc.get('Y', [])],
        }
        mir_units = []
        for u in snap.get('units', ()):
            nu = dict(u)
            nu['team'] = 'X' if u.get('team') == 'Y' else 'Y'
            nu['coord'] = self._mirror_coord(u.get('coord', ''), w)
            nu['coord_history'] = [self._mirror_coord(c, w) for c in u.get('coord_history', ())]
            mir_units.append(nu)
        res = dict(snap)
        res['terrain'] = mir_terrain
        res['deploy_cols'] = mir_deploy
        res['units'] = mir_units
        return res

    def _mirror_frame_for_right(self, frame):
        if not frame:
            return frame
        snap = frame.get('snapshot') or {}
        w = int(snap.get('width', 10) or 10)
        nf = dict(frame)
        nf['team'] = 'X' if frame.get('team') == 'Y' else 'Y'
        nf['snapshot'] = self._mirror_snapshot_for_right(snap)
        mir_vfx = []
        for ev in frame.get('vfx_events', ()):
            nev = dict(ev)
            if nev.get('from_coord'):
                nev['from_coord'] = self._mirror_coord(nev['from_coord'], w)
            if nev.get('to_coord'):
                nev['to_coord'] = self._mirror_coord(nev['to_coord'], w)
            if nev.get('path'):
                nev['path'] = [self._mirror_coord(c, w) for c in nev['path']]
            if nev.get('to_coords'):
                nev['to_coords'] = [self._mirror_coord(c, w) for c in nev['to_coords']]
            if nev.get('popups'):
                nev['popups'] = [
                    dict(p, coord=self._mirror_coord(p['coord'], w)) if p.get('coord') else p
                    for p in nev['popups']
                ]
            mir_vfx.append(nev)
        nf['vfx_events'] = mir_vfx
        return nf

    def _advance_one_engine_turn(self, eng):
        """Advance a single unit's turn on FullBattleEngine cleanly and emit move/VFX events."""
        eng._reconcile_summon_groups()
        state = eng._get_state() or {}
        il = eng._get_initiative()
        if state.get('phase') != 'active' or not il:
            eng._check_and_mark_end(state)
            return None

        idx = min(state.get('activeIndex', 0), len(il) - 1)
        entry = il[idx]
        uid = entry['userId']
        base = eng._resolve_uid(uid)

        if entry.get('_suppressed', False):
            eng._end_turn(uid)
            return None

        hp = eng._get_combat_hp(uid) or 0
        if hp <= 0:
            eng._end_turn(uid)
            return None

        if entry.get('actionIdx', 0) == 0:
            eng._sync_initiative_slots(uid)

        before_units = self._capture_eng_units(eng)
        actor_before = before_units.get(base, {})
        actor_coord_start = actor_before.get('coord', entry.get('coord', ''))
        actor_serial = actor_before.get('serial', '')
        move_path = [actor_coord_start] if actor_coord_start else []
        acted_cmds = []

        actions_log = []
        reason = ''
        last_cmd = ''
        if entry.get('isSummon', False):
            gkey = eng._summon_group_key(uid)
            r = eng._execute_summon_group_action(gkey, lambda m_uid: (eng._summon_attack(m_uid), False, None))
            actions_log.extend(r.get('lines') or [])
            reason = f'召唤物 {entry.get("name", uid)} 自动攻击'
            last_cmd = 'summon_att'
            eng._end_turn(uid)
        else:
            eng._ai_failed_commands = set()
            failures = 0
            for _ in range(12):
                st = eng._get_state() or {}
                if st.get('phase') != 'active':
                    break
                cur_il = eng._get_initiative()
                if not cur_il or cur_il[st.get('activeIndex', 0) % len(cur_il)]['userId'] != uid:
                    break
                if eng._get_my_actions(base).get('主动', 0) <= 0 or eng._is_dying(base):
                    eng._end_turn(uid)
                    break
                cmd, cmd_reason = decide_tactical_action(eng, base)
                last_cmd = cmd
                if cmd_reason:
                    reason = cmd_reason
                if cmd == '.i end':
                    eng._end_turn(uid)
                    break
                res = eng._execute_ai_command(base, cmd)
                actions_log.extend(str(res).splitlines())
                actions_log.extend(eng._drain_battle_events())
                if getattr(res, 'committed', True):
                    acted_cmds.append(cmd)
                    eng._consume_action(base, res.slot)
                    eng._ai_failed_commands.clear()
                    failures = 0
                    if cmd.startswith('.a m '):
                        if not hasattr(eng, '_moved_this_turn'):
                            eng._moved_this_turn = set()
                        eng._moved_this_turn.add(base)
                        cur_entry = eng._unit_il_entry(base, eng._get_initiative())
                        if cur_entry and cur_entry.get('coord'):
                            if not move_path or move_path[-1] != cur_entry['coord']:
                                move_path.append(cur_entry['coord'])
                else:
                    failures += 1
                    eng._ai_failed_commands.add(cmd)
                    if failures >= 5:
                        eng._end_turn(uid)
                        break
            else:
                eng._end_turn(uid)

        after_units = self._capture_eng_units(eng)
        vfx_events = []

        # Track movement animations (actor path & any unit displaced by pull/knockback)
        actor_coord_end = after_units.get(base, {}).get('coord', actor_coord_start)
        if len(move_path) >= 2 and actor_coord_start != actor_coord_end:
            vfx_events.append({
                'type': 'move',
                'uid': base,
                'from_coord': actor_coord_start,
                'to_coord': actor_coord_end,
                'path': move_path,
                'flying': bool(eng._is_flying(base)),
            })
        for u_id, aft in after_units.items():
            bef = before_units.get(u_id)
            if bef and bef['coord'] and aft['coord'] and bef['coord'] != aft['coord']:
                if u_id == base and len(move_path) >= 2:
                    continue
                vfx_events.append({
                    'type': 'move',
                    'uid': u_id,
                    'from_coord': bef['coord'],
                    'to_coord': aft['coord'],
                    'path': [bef['coord'], aft['coord']],
                    'flying': bool(eng._is_flying(u_id)),
                })

        # Track damage, heal, shield, summon & dodge/block popups for dynamic VFX
        target_uids = []
        to_coords = []
        popups = []
        spawned_summons = False
        for u_id, aft in after_units.items():
            bef = before_units.get(u_id)
            coord = aft.get('coord') or (bef.get('coord') if bef else '')
            if not bef:
                if aft.get('is_summon') and coord:
                    spawned_summons = True
                    target_uids.append(u_id)
                    to_coords.append(coord)
                    popups.append({'uid': u_id, 'coord': coord, 'text': '召唤!', 'kind': 'summon'})
                continue
            hp_diff = aft['hp'] - bef['hp']
            sh_diff = aft['shield'] - bef['shield']
            if hp_diff < 0:
                target_uids.append(u_id)
                if coord:
                    to_coords.append(coord)
                    popups.append({'uid': u_id, 'coord': coord, 'text': f'{hp_diff}', 'kind': 'dmg'})
            elif sh_diff < 0:
                target_uids.append(u_id)
                if coord:
                    to_coords.append(coord)
                    popups.append({'uid': u_id, 'coord': coord, 'text': f'盾{sh_diff}', 'kind': 'shield'})
            elif hp_diff > 0:
                target_uids.append(u_id)
                if coord:
                    to_coords.append(coord)
                    popups.append({'uid': u_id, 'coord': coord, 'text': f'+{hp_diff}', 'kind': 'heal'})
            elif sh_diff > 0:
                target_uids.append(u_id)
                if coord:
                    to_coords.append(coord)
                    popups.append({'uid': u_id, 'coord': coord, 'text': f'+{sh_diff}盾', 'kind': 'shield'})

        non_move_cmd = next((c for c in reversed(acted_cmds) if not c.startswith('.a m ')), last_cmd)
        skill_name = _extract_skill_name(non_move_cmd, actions_log)
        vfx_kind = 'summon' if spawned_summons else _classify_vfx_kind(actor_serial, non_move_cmd, skill_name, actions_log)
        joined_log = ' '.join(str(x) for x in actions_log)
        if not popups and any(w in joined_log for w in ('闪避', '未命中', '失败')):
            opp_team = 'X' if entry.get('team', 'Y') == 'Y' else 'Y'
            opp_u = next(
                ((uid_o, st_o) for uid_o, st_o in after_units.items() if st_o['team'] == opp_team and st_o['hp'] > 0),
                None,
            )
            if opp_u and opp_u[1].get('coord'):
                target_uids.append(opp_u[0])
                to_coords.append(opp_u[1]['coord'])
                lbl = '闪避!' if '闪避' in joined_log else '未命中'
                popups.append({'uid': opp_u[0], 'coord': opp_u[1]['coord'], 'text': lbl, 'kind': 'miss'})

        if popups or (non_move_cmd and not non_move_cmd.startswith('.a m ') and non_move_cmd != '.i end'):
            vfx_events.append({
                'type': 'action',
                'actor_uid': base,
                'from_coord': actor_coord_end or actor_coord_start,
                'target_uids': target_uids,
                'to_coords': to_coords or ([actor_coord_end] if actor_coord_end else []),
                'skill_name': skill_name or non_move_cmd,
                'vfx_kind': vfx_kind,
                'popups': popups,
            })

        end_res = eng._check_battle_end()
        if end_res:
            eng._battle_result = end_res
            st = eng._get_state() or {}
            st['phase'] = 'ended'
            eng._set_state(st)

        return {
            'round': (eng._get_state() or {}).get('round', 1),
            'actor_uid': base,
            'actor_name': entry.get('name', base),
            'team': entry.get('team', 'Y'),
            'cmd': last_cmd,
            'reason': reason or getattr(eng, '_last_ai_reason', ''),
            'lines': [ln.strip() for ln in actions_log if str(ln).strip()][:12],
            'vfx_events': vfx_events,
            'snapshot': self._engine_snapshot(eng),
        }

    def _engine_snapshot(self, eng):
        md = eng._get_map() or {}
        il = eng._get_initiative() or []
        seen = set()
        units = []
        for e in eng._battle_unit_entries():
            base = eng._resolve_uid(e['userId'])
            if base in seen:
                continue
            seen.add(base)
            hp = max(0, eng._get_combat_hp(base) or 0)
            char = eng.get_char(base)
            max_hp = (char.get_attr('体力上限', hp) if char else hp) or max(hp, 1)
            mp = (char.get_attr('魔力', 0) if char else 0) or 0
            shield = sum(
                eff.get('value', 0) for eff in eng._get_effects()
                if eff.get('type') == 'shield' and eng._resolve_uid(eff.get('targetUserId', '')) == base
            )
            units.append({
                'uid': base,
                'name': e.get('displayName', e.get('name', base)),
                'serial': getattr(char, 'serial', '') if char else '',
                'team': e.get('team', 'Y'),
                'coord': e.get('coord', ''),
                'hp': hp,
                'max_hp': max_hp,
                'mp': mp,
                'shield': shield,
                'flying': bool(eng._is_flying(base)),
                'dying': bool(eng._is_dying(base)),
                'is_summon': bool(e.get('isSummon', False)),
                'coord_history': list(e.get('coord_history', [])),
            })
        return {
            'round': (eng._get_state() or {}).get('round', 1),
            'overtime_start_round': getattr(eng, 'overtime_start_round', 15),
            'width': md.get('width', 10),
            'height': md.get('height', 7),
            'terrain': dict(md.get('terrain', {})),
            'deploy_cols': md.get('deploy_cols', {}),
            'units': units,
        }

    def _extract_bout_outcome(self, eng):
        res = getattr(eng, '_battle_result', None) or eng._check_battle_end()
        if not res:
            # Timeout adjudication by remaining non-summon HP percentage
            roster = getattr(eng, '_team_roster', [])
            ratios = {'Y': [], 'X': []}
            for uid, tm in roster:
                chp = max(0, eng._get_combat_hp(uid) or 0)
                c = eng.get_char(uid)
                mhp = max(1, (c.get_attr('体力上限', chp) if c else chp) or 1)
                ratios[tm].append(chp / mhp)
            ya = sum(ratios['Y']) / max(1, len(ratios['Y']))
            xa = sum(ratios['X']) / max(1, len(ratios['X']))
            winner = 'Y' if ya >= xa else 'X'
            res = {'winner': winner, 'rounds': (eng._get_state() or {}).get('round', eng.max_rounds), 'timeout': True}

        winner = res.get('winner', 'Y')
        surviving_x = sum(
            1 for uid, tm in getattr(eng, '_team_roster', [])
            if tm == 'X' and (eng._get_combat_hp(uid) or 0) > 0
        )
        surviving_y = sum(
            1 for uid, tm in getattr(eng, '_team_roster', [])
            if tm == 'Y' and (eng._get_combat_hp(uid) or 0) > 0
        )

        raw_stats = getattr(eng, '_battle_stats', {}) or {}
        telemetry = []
        for uid, tm in getattr(eng, '_team_roster', []):
            base = eng._resolve_uid(uid)
            st = raw_stats.get(base, {})
            ch = eng.get_char(base)
            telemetry.append({
                'uid': base,
                'name': ch.name if ch else base,
                'serial': getattr(ch, 'serial', '') if ch else '',
                'team': tm,
                'dmg_dealt': int(st.get('damage_dealt', st.get('dmg_dealt', 0)) or 0),
                'dmg_taken': int(st.get('damage_taken', st.get('dmg_taken', 0)) or 0),
                'heal_done': int(st.get('healing_done', st.get('heal_done', 0)) or 0),
                'shield_absorbed': int(st.get('shield_absorbed', 0) or 0),
                'tiles_moved': int(st.get('tiles_moved', 0) or 0),
                'kills': int(st.get('kills', 0) or 0),
                'alive': (eng._get_combat_hp(base) or 0) > 0,
            })

        # Compute MVP on winning side (else overall) by dmg_dealt + heal_done*0.8 + dmg_taken*0.35
        pool = [t for t in telemetry if t['team'] == winner] or telemetry
        mvp = max(pool, key=lambda t: (t['dmg_dealt'] + t['heal_done'] * 0.8 + t['dmg_taken'] * 0.35), default=None)
        return {
            'winner': winner,
            'rounds': int(res.get('rounds', (eng._get_state() or {}).get('round', 1)) or 1),
            'timeout': bool(res.get('timeout', False)),
            'surviving_y': surviving_y,
            'surviving_x': surviving_x,
            'telemetry': telemetry,
            'mvp': mvp,
        }

    def start_combat(self, auto_pick_pending=False):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        humans = self.human_commanders(alive_only=True)
        for hc in humans:
            if hc.get('pending_augments'):
                if auto_pick_pending:
                    self.pick_augment(hc['id'], hc['pending_augments'][0]['id'])
                else:
                    return False, '请先在【星序祝福】弹窗中选择本回合强化祝福'

        # Ensure every alive commander deploys at least one unit if available on bench
        for cid, cmd in self.commanders.items():
            if cmd.get('eliminated'):
                continue
            if cmd['is_human']:
                if not self.board_units(cid) and self.bench_units(cid):
                    self.deploy_unit(cid, self.bench_units(cid)[0]['id'])
                cmd['ready'] = False
            else:
                run_commander_prep(self, cid)

        live_bouts = []
        other_outcomes = []
        if self.mode in ('lobby4', 'pvp_room'):
            pairs = self._pair_lobby_opponents()
            for idx, (a_id, b_id, is_ghost) in enumerate(pairs):
                left_cmd, right_cmd = self.commanders[a_id], self.commanders[b_id]
                if left_cmd.get('is_human') or right_cmd.get('is_human'):
                    eng = self._build_battle_engine(
                        {'units': copy.deepcopy(self.board_units(a_id)), 'augments': list(left_cmd['augments'])},
                        {'units': copy.deepcopy(self.board_units(b_id)), 'augments': list(right_cmd['augments'])},
                        self.arena_preset,
                        self.seed + self.round_num * 1009 + idx * 97,
                    )
                    init_snap = self._engine_snapshot(eng)
                    init_frame = {
                        'round': 1,
                        'actor_uid': None,
                        'actor_name': '战斗开始',
                        'team': 'Y',
                        'cmd': '',
                        'reason': f'{left_cmd["name"]} vs {right_cmd["name"]}' + (' (镜像)' if is_ghost else ''),
                        'lines': [f'双方进入【{ARENA_PRESETS[self.arena_preset]["name"]}】准备接战'],
                        'vfx_events': [],
                        'snapshot': init_snap,
                    }
                    live_bouts.append({
                        'bout_id': f'b_{idx}',
                        'left_cid': a_id,
                        'right_cid': b_id,
                        'is_ghost': is_ghost,
                        'engine': eng,
                        'frames': [init_frame],
                        'done': False,
                        'outcome': None,
                    })
                else:
                    out = self._run_headless_bout(
                        {'units': self.board_units(a_id), 'augments': left_cmd['augments']},
                        {'units': self.board_units(b_id), 'augments': right_cmd['augments']},
                        self.arena_preset,
                        self.seed + self.round_num * 37 + idx * 53,
                    )
                    other_outcomes.append((a_id, b_id, is_ghost, out))
        else:
            p1 = self.commanders[self.player_id]
            wave = PVE_WAVES[min(self.round_num - 1, len(PVE_WAVES) - 1)]
            opp_units = [
                {'serial': s, 'star': st, 'stance': 'balanced', 'coord': None}
                for s, st in wave['units']
            ]
            eng = self._build_battle_engine(
                {'units': copy.deepcopy(self.board_units(self.player_id)), 'augments': list(p1['augments'])},
                {'units': opp_units, 'augments': []},
                self.arena_preset,
                self.seed + self.round_num * 1009,
            )
            init_frame = {
                'round': 1,
                'actor_uid': None,
                'actor_name': '战斗开始',
                'team': 'Y',
                'cmd': '',
                'reason': f'VS 第{wave["wave"]}波 · {wave["name"]}',
                'lines': [f'双方进入【{ARENA_PRESETS[self.arena_preset]["name"]}】准备接战'],
                'vfx_events': [],
                'snapshot': self._engine_snapshot(eng),
            }
            live_bouts.append({
                'bout_id': 'b_0',
                'left_cid': self.player_id,
                'right_cid': f'WAVE_{wave["wave"]}',
                'right_name': f'第{wave["wave"]}波 · {wave["name"]}',
                'is_ghost': False,
                'engine': eng,
                'frames': [init_frame],
                'done': False,
                'outcome': None,
            })

        # Handle case where all surviving humans were eliminated or fallback
        if not live_bouts and self.phase == 'prep':
            self.phase = 'finished'
            return False, '没有可执行的玩家对局'

        self._live_bouts = live_bouts
        # Single-player compatibility aliases
        p1_b = self._bout_for_viewer(self.player_id) or live_bouts[0]
        self._live_engine = p1_b['engine']
        self.combat_frames = p1_b['frames']
        self._live_matchup = {
            'other_outcomes': other_outcomes,
        }
        self.phase = 'combat'
        self.logs.append(f'第 {self.round_num} 回合开战（共 {len(live_bouts)} 组实况对桌）')
        return True, '战斗开始'

    def _bout_for_viewer(self, target_cid):
        for b in self._live_bouts:
            if b['left_cid'] == target_cid:
                return b
        for b in self._live_bouts:
            if b['right_cid'] == target_cid and not b.get('is_ghost'):
                return b
        return self._live_bouts[0] if self._live_bouts else None

    def step_combat(self, steps=1):
        if self.phase != 'combat' or not self._live_bouts:
            return {'done': self.phase != 'combat', 'frames': []}
        new_frames = []
        for _ in range(max(1, int(steps))):
            any_active = False
            for b in self._live_bouts:
                if b['done']:
                    continue
                eng = b['engine']
                st = eng._get_state() or {}
                if (
                    st.get('phase') != 'active'
                    or st.get('round', 1) > eng.max_rounds
                    or getattr(eng, '_battle_result', None) is not None
                ):
                    b['done'] = True
                    continue
                any_active = True
                frame = self._advance_one_engine_turn(eng)
                if frame is not None:
                    b['frames'].append(frame)
                    if len(b['frames']) > 220:
                        b['frames'] = b['frames'][-220:]
                    if b['left_cid'] == self.player_id or b['right_cid'] == self.player_id:
                        new_frames.append(frame)
                st2 = eng._get_state() or {}
                if (
                    st2.get('phase') != 'active'
                    or st2.get('round', 1) > eng.max_rounds
                    or getattr(eng, '_battle_result', None) is not None
                ):
                    b['done'] = True
            if not any_active:
                break

        # Refresh single-player frame alias
        p1_b = self._bout_for_viewer(self.player_id)
        if p1_b:
            self.combat_frames = p1_b['frames']

        ended = all(b['done'] for b in self._live_bouts)
        if ended:
            self._finalize_round()
        return {'done': ended, 'frames': new_frames, 'state': self.to_public_dict()}

    def resolve_combat(self):
        if self.phase == 'prep':
            ok, msg = self.start_combat(auto_pick_pending=(self.mode == 'pvp_room'))
            if not ok:
                return False, msg
        if self.phase in ('round_result', 'finished'):
            return True, '本回合战斗已结束'
        if self.phase != 'combat' or not self._live_bouts:
            return False, '当前无进行中的战斗'
        self.step_combat(steps=260)
        return True, '战斗结算完成'

    def _apply_combat_hp_and_streak(self, cid, won, surviving_enemy_units, is_ghost_victim=False):
        cmd = self.commanders[cid]
        if cmd.get('eliminated'):
            return 0
        if won:
            cmd['wins'] += 1
            cmd['streak'] = cmd['streak'] + 1 if cmd['streak'] >= 0 else 1
            return 0
        cmd['losses'] += 1
        cmd['streak'] = cmd['streak'] - 1 if cmd['streak'] <= 0 else -1
        dmg = 2 + self.round_num // 2 + max(1, surviving_enemy_units)
        if self.mode == 'pve12':
            dmg = 3 + self.round_num // 2 + max(1, surviving_enemy_units)
        cmd['hp'] = max(0, cmd['hp'] - dmg)
        if cmd['hp'] <= 0:
            self._eliminate_commander(cid)
        return dmg

    def _eliminate_commander(self, cid):
        cmd = self.commanders[cid]
        if cmd.get('eliminated'):
            return
        cmd['eliminated'] = True
        alive_left = sum(1 for c in self.commanders.values() if not c.get('eliminated'))
        cmd['placement'] = alive_left + 1
        # Return all units back to shared pool
        for u in cmd['units']:
            s = u['serial']
            cost = UNIT_CATALOG[s]['cost']
            cap = POOL_COUNTS[cost]
            self.pool[s] = min(cap, self.pool.get(s, 0) + (3 ** (u['star'] - 1)))
        cmd['units'] = []
        self.logs.append(f'💀 {cmd["name"]} 被淘汰（第 {cmd["placement"]} 名）')

    def _grant_round_income(self, cid):
        cmd = self.commanders[cid]
        if cmd.get('eliminated'):
            return None
        base_g = min(8, 5 + self.round_num // 3)
        interest = min(cmd.get('max_interest', 5), cmd['gold'] // 10)
        ab_streak = abs(cmd.get('streak', 0))
        streak_bonus = 3 if ab_streak >= 5 else (2 if ab_streak >= 3 else (1 if ab_streak >= 2 else 0))
        total = base_g + interest + streak_bonus
        cmd['gold'] += total
        self._grant_xp(cid, 2)
        if not cmd.get('shop_locked'):
            self._roll_shop_for(cid, free=True)
        else:
            cmd['shop_locked'] = False
        return {'base': base_g, 'interest': interest, 'streak': streak_bonus, 'total': total}

    @staticmethod
    def _mirror_telemetry(telemetry):
        out = []
        for row in telemetry or ():
            nr = dict(row)
            nr['team'] = 'X' if row.get('team') == 'Y' else 'Y'
            out.append(nr)
        return out

    def _finalize_round(self):
        if self.phase != 'combat' or not self._live_bouts:
            return
        self.round_reports = {}
        last_snapshots = {}

        for b in self._live_bouts:
            outcome = self._extract_bout_outcome(b['engine'])
            a_id = b['left_cid']
            b_id = b['right_cid']
            is_ghost = b.get('is_ghost', False)
            left_won = (outcome['winner'] == 'Y')

            a_dmg = self._apply_combat_hp_and_streak(a_id, left_won, outcome['surviving_x'])
            if left_won:
                self.commanders[a_id]['gold'] += 1
            opp_label_a = b.get('right_name') or (
                f'{self.commanders[b_id]["name"]}' + (' (镜像)' if is_ghost else '')
                if b_id in self.commanders else str(b_id)
            )
            self.round_reports[a_id] = {
                'round': self.round_num,
                'opponent_name': opp_label_a,
                'won': left_won,
                'battle_rounds': outcome['rounds'],
                'timeout': outcome['timeout'],
                'hp_damage': a_dmg,
                'telemetry': outcome['telemetry'],
                'mvp': outcome['mvp'],
            }
            last_snapshots[a_id] = {
                'frames': list(b['frames'][-40:]),
                'opponent_name': opp_label_a,
                'token_overrides': {
                    'Y': dict(self.commanders[a_id].get('token_overrides') or {}),
                    'X': dict(self.commanders.get(b_id, {}).get('token_overrides') or {}),
                },
            }

            if self.mode != 'pve12' and not is_ghost and b_id in self.commanders:
                b_dmg = self._apply_combat_hp_and_streak(b_id, not left_won, outcome['surviving_y'])
                if not left_won:
                    self.commanders[b_id]['gold'] += 1
                opp_label_b = self.commanders[a_id]['name']
                self.round_reports[b_id] = {
                    'round': self.round_num,
                    'opponent_name': opp_label_b,
                    'won': not left_won,
                    'battle_rounds': outcome['rounds'],
                    'timeout': outcome['timeout'],
                    'hp_damage': b_dmg,
                    'telemetry': self._mirror_telemetry(outcome['telemetry']),
                    'mvp': outcome['mvp'],
                }
                last_snapshots[b_id] = {
                    'frames': [self._mirror_frame_for_right(f) for f in b['frames'][-40:]],
                    'opponent_name': opp_label_b,
                    'token_overrides': {
                        'Y': dict(self.commanders[b_id].get('token_overrides') or {}),
                        'X': dict(self.commanders[a_id].get('token_overrides') or {}),
                    },
                }

        for a_id, b_id, is_ghost, res in (self._live_matchup or {}).get('other_outcomes', []):
            a_won = (res['winner'] == 'Y')
            self._apply_combat_hp_and_streak(a_id, a_won, res['surviving_x'])
            if not is_ghost:
                self._apply_combat_hp_and_streak(b_id, not a_won, res['surviving_y'])
                if not a_won:
                    self.commanders[b_id]['gold'] += 1
            if a_won:
                self.commanders[a_id]['gold'] += 1

        self.last_round_report = self.round_reports.get(self.player_id)
        self._last_round_snapshots = last_snapshots
        p1_rep = self.last_round_report
        if p1_rep:
            self.combat_frames = list((last_snapshots.get(self.player_id) or {}).get('frames', self.combat_frames))
            status_str = '胜利' if p1_rep['won'] else f'落败 (-{p1_rep["hp_damage"]}HP)'
            self.logs.append(f'第 {self.round_num} 回合结束：{status_str}（{p1_rep["battle_rounds"]}轮）')
        else:
            self.logs.append(f'第 {self.round_num} 回合全桌战斗结算完成')

        self._live_engine = None
        self._live_matchup = None
        self._live_bouts = []

        # Check end-of-match conditions
        if self.mode == 'pve12':
            p1 = self.commanders[self.player_id]
            if p1.get('eliminated'):
                self.phase = 'finished'
                self.winner_id = None
                return
            if p1_won := (p1_rep and p1_rep.get('won')):
                if self.round_num >= len(PVE_WAVES):
                    p1['placement'] = 1
                    self.phase = 'finished'
                    self.winner_id = self.player_id
                    self.logs.append('🏆 恭喜通关 12 波星序试炼！')
                    return
        elif self.mode == 'lobby4':
            p1 = self.commanders[self.player_id]
            if p1.get('eliminated'):
                self.phase = 'finished'
                self.winner_id = next(
                    (c['id'] for c in self.commanders.values() if not c.get('eliminated')),
                    None,
                )
                return
            alive = [c for c in self.commanders.values() if not c.get('eliminated')]
            if len(alive) <= 1:
                if alive:
                    alive[0]['placement'] = 1
                    self.winner_id = alive[0]['id']
                self.phase = 'finished'
                self.logs.append(f'🏆 决胜结束！冠军：{self.commanders[self.winner_id]["name"]}')
                return
        else:
            # pvp_room: continues while >=2 commanders alive AND at least 1 human alive (or 1 survivor left)
            alive = [c for c in self.commanders.values() if not c.get('eliminated')]
            alive_humans = [c for c in alive if c.get('is_human')]
            if len(alive) <= 1 or not alive_humans:
                if alive:
                    if len(alive) == 1:
                        alive[0]['placement'] = 1
                        self.winner_id = alive[0]['id']
                    else:
                        alive_sorted = sorted(alive, key=lambda c: (-c['hp'], -c['wins']))
                        for rank, c in enumerate(alive_sorted, start=1):
                            c['placement'] = rank
                        self.winner_id = alive_sorted[0]['id']
                self.phase = 'finished'
                if self.winner_id and self.winner_id in self.commanders:
                    self.logs.append(f'🏆 决胜结束！冠军：{self.commanders[self.winner_id]["name"]}')
                return

        self.phase = 'round_result'

    def next_round(self):
        if self.phase != 'round_result':
            return False, '当前无法进入下一回合'
        self.round_num += 1
        incomes = {}
        for cid, cmd in self.commanders.items():
            cmd['ready'] = False
            cmd['next_ready'] = False
            inc = self._grant_round_income(cid)
            if cid == self.player_id and inc:
                incomes = inc
        self._offer_augments_if_due()
        self.prep_deadline = time.time() + self.prep_duration
        self.phase = 'prep'
        if self.mode != 'pvp_room' and incomes:
            self.logs.append(
                f'进入第 {self.round_num} 回合：+{incomes["total"]}G（基础{incomes["base"]}+利息{incomes["interest"]}+连胜败{incomes["streak"]}）'
            )
        else:
            self.logs.append(f'进入第 {self.round_num} 回合备战阶段')
        return True, f'第 {self.round_num} 回合备战开始'

    def handle_action(self, cid, action, payload=None):
        payload = payload or {}
        if action == 'buy':
            return self.buy_unit(cid, int(payload.get('slot_index', -1)))
        if action == 'sell':
            return self.sell_unit(cid, payload.get('unit_id', ''))
        if action == 'reroll':
            ok = self.reroll_shop(cid)
            return ok, ('已刷新商店' if ok else '金币不足（需2G）')
        if action == 'lock_shop':
            ok = self.toggle_lock(cid)
            return ok, ('已切换商店锁定' if ok else '操作无效')
        if action == 'buy_xp':
            ok = self.buy_xp(cid)
            return ok, ('购买经验 +4 XP' if ok else '金币不足或已满级')
        if action == 'deploy':
            return self.deploy_unit(cid, payload.get('unit_id', ''), payload.get('coord'))
        if action == 'recall':
            return self.recall_unit(cid, payload.get('unit_id', ''))
        if action == 'swap':
            return self.swap_units(cid, payload.get('unit_a', ''), payload.get('unit_b', ''))
        if action == 'set_stance':
            return self.set_stance(cid, payload.get('unit_id', ''), payload.get('stance', 'balanced'))
        if action == 'auto_arrange':
            return self.auto_arrange(cid)
        if action == 'pick_augment':
            return self.pick_augment(cid, payload.get('augment_id', ''))
        if action == 'ready_combat':
            if self.mode == 'pvp_room':
                return self.set_ready(cid, bool(payload.get('ready', True)))
            return self.start_combat()
        if action == 'ready_next':
            if self.mode == 'pvp_room':
                return self.set_next_ready(cid, bool(payload.get('ready', True)))
            return self.next_round()
        if action == 'start_combat':
            return self.start_combat()
        if action == 'step_combat':
            res = self.step_combat(int(payload.get('steps', 1)))
            return True, f'步进 {len(res["frames"])} 帧'
        if action == 'resolve_combat':
            return self.resolve_combat()
        if action == 'next_round':
            return self.next_round()
        return False, f'未知动作: {action}'

    def to_public_dict(self, viewer_cid=None, spectate_cid=None):
        md = build_arena_map(self.arena_preset)
        vcid = viewer_cid if viewer_cid in self.commanders else self.player_id
        p1 = self.commanders[vcid]
        p1_board = self.board_units(vcid)
        p1_synergies = compute_active_synergies(p1_board)
        hints = self._upgrade_hints_for(vcid)
        shop_view = []
        for idx, slot in enumerate(p1['shop']):
            if slot is None:
                shop_view.append(None)
                continue
            s = slot['serial']
            meta = UNIT_CATALOG[s]
            shop_view.append({
                'slot_index': idx,
                'serial': s,
                'name': meta['name'],
                'cost': meta['cost'],
                'role': meta['role'],
                'traits': meta['traits'],
                'tag': meta['tag'],
                'blurb': meta['blurb'],
                'emblem': meta['emblem'],
                'accent': meta['accent'],
                'emblem_url': meta['emblem_url'],
                'default_token_url': meta['default_token_url'],
                'bought': bool(slot.get('bought')),
                'hint': hints[idx],
            })

        standings = sorted(
            self.commanders.values(),
            key=lambda c: (0 if not c.get('eliminated') else 1, -c['hp'], c.get('placement') or 99),
        )
        commanders_view = [
            {
                'id': c['id'],
                'name': c['name'],
                'is_human': c['is_human'],
                'personality': c['personality'],
                'ready': bool(c.get('ready', False)),
                'next_ready': bool(c.get('next_ready', False)),
                'hp': c['hp'],
                'max_hp': c['max_hp'],
                'gold': c['gold'],
                'level': c['level'],
                'xp': c['xp'],
                'xp_to_next': LEVEL_TABLE[c['level']]['xp_to_next'],
                'max_pop': self.max_pop(c['id']),
                'board_count': len(self.board_units(c['id'])),
                'streak': c['streak'],
                'wins': c['wins'],
                'losses': c['losses'],
                'eliminated': c['eliminated'],
                'placement': c['placement'],
                'augments': [next((a for a in AUGMENTS if a['id'] == aid), {'id': aid, 'name': aid}) for aid in c['augments']],
                'synergies': [s for s in compute_active_synergies(self.board_units(c['id'])).values() if s.get('active_tier')],
            }
            for c in standings
        ]

        watch_cid = spectate_cid if spectate_cid in self.commanders else vcid
        bout_frames = []
        live_snapshot = None
        opponent_name = ''
        bout_token_overrides = {
            'Y': dict(self.commanders.get(watch_cid, {}).get('token_overrides') or {}),
            'X': {},
        }

        if self._live_bouts:
            tb = self._bout_for_viewer(watch_cid)
            if tb:
                left_id = tb['left_cid']
                right_id = tb['right_cid']
                on_right = (right_id == watch_cid and not tb.get('is_ghost'))
                raw_snap = self._engine_snapshot(tb['engine'])
                live_snapshot = self._mirror_snapshot_for_right(raw_snap) if on_right else raw_snap
                bout_frames = [
                    self._mirror_frame_for_right(f) if on_right else f
                    for f in tb['frames'][-40:]
                ]
                if on_right:
                    opponent_name = self.commanders.get(left_id, {}).get('name', '')
                    bout_token_overrides = {
                        'Y': dict(self.commanders.get(right_id, {}).get('token_overrides') or {}),
                        'X': dict(self.commanders.get(left_id, {}).get('token_overrides') or {}),
                    }
                else:
                    opponent_name = tb.get('right_name') or self.commanders.get(right_id, {}).get('name', str(right_id))
                    if tb.get('is_ghost') and right_id in self.commanders:
                        opponent_name += ' (镜像)'
                    bout_token_overrides = {
                        'Y': dict(self.commanders.get(left_id, {}).get('token_overrides') or {}),
                        'X': dict(self.commanders.get(right_id, {}).get('token_overrides') or {}),
                    }
        else:
            cached = getattr(self, '_last_round_snapshots', {}).get(watch_cid)
            if cached:
                bout_frames = list(cached.get('frames', []))[-40:]
                live_snapshot = bout_frames[-1].get('snapshot') if bout_frames else None
                opponent_name = cached.get('opponent_name', '')
                bout_token_overrides = cached.get('token_overrides') or bout_token_overrides
            elif self.combat_frames:
                bout_frames = self.combat_frames[-40:]
                live_snapshot = bout_frames[-1].get('snapshot')

        return {
            'id': self.id,
            'mode': self.mode,
            'arena_preset': self.arena_preset,
            'arena_name': ARENA_PRESETS[self.arena_preset]['name'],
            'round_num': self.round_num,
            'prep_deadline': self.prep_deadline,
            'max_waves': len(PVE_WAVES) if self.mode == 'pve12' else None,
            'phase': self.phase,
            'winner_id': self.winner_id,
            'watching_cid': watch_cid,
            'opponent_name': opponent_name,
            'bout_token_overrides': bout_token_overrides,
            'map': md,
            'player': {
                'id': p1['id'],
                'name': p1['name'],
                'account_id': p1.get('account_id'),
                'ready': bool(p1.get('ready', False)),
                'next_ready': bool(p1.get('next_ready', False)),
                'token_overrides': dict(p1.get('token_overrides') or {}),
                'hp': p1['hp'],
                'max_hp': p1['max_hp'],
                'gold': p1['gold'],
                'level': p1['level'],
                'xp': p1['xp'],
                'xp_to_next': LEVEL_TABLE[p1['level']]['xp_to_next'],
                'max_pop': self.max_pop(vcid),
                'max_interest': p1['max_interest'],
                'free_rerolls': p1['free_rerolls'],
                'streak': p1['streak'],
                'shop_locked': p1['shop_locked'],
                'shop': shop_view,
                'board': [dict(u, **UNIT_CATALOG[u['serial']]) for u in p1_board],
                'bench_capacity': self.bench_capacity(vcid),
                'bench': [dict(u, **UNIT_CATALOG[u['serial']]) for u in self.bench_units(vcid)],
                'synergies': list(p1_synergies.values()),
                'augments': [next((a for a in AUGMENTS if a['id'] == aid), {'id': aid, 'name': aid}) for aid in p1['augments']],
                'pending_augments': p1['pending_augments'],
                'placement': p1['placement'],
            },
            'commanders': commanders_view,
            'combat_frames': bout_frames,
            'live_snapshot': live_snapshot,
            'last_round_report': self.round_reports.get(vcid) or self.last_round_report,
            'logs': self.logs[-50:],
            'pool_remaining': sum(self.pool.values()),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'mode': self.mode,
            'arena_preset': self.arena_preset,
            'fill_bots': self.fill_bots,
            'prep_duration': self.prep_duration,
            'seed': self.seed,
            'round_num': self.round_num,
            'prep_deadline': self.prep_deadline,
            'phase': 'prep' if self.phase == 'combat' else self.phase,
            'winner_id': self.winner_id,
            'uid_seq': self.uid_seq,
            'pool': dict(self.pool),
            'commanders': copy.deepcopy(self.commanders),
            'logs': list(self.logs[-100:]),
            'last_round_report': copy.deepcopy(self.last_round_report),
            'round_reports': copy.deepcopy(getattr(self, 'round_reports', {})),
        }

    @classmethod
    def from_dict(cls, data):
        obj = cls.__new__(cls)
        obj.id = data['id']
        obj.mode = data.get('mode', 'lobby4')
        obj.arena_preset = data.get('arena_preset', 'autochess_standard')
        obj.fill_bots = bool(data.get('fill_bots', True))
        obj.prep_duration = int(data.get('prep_duration', 30) or 30)
        obj.seed = int(data.get('seed', 42))
        obj._rng = random.Random(obj.seed + int(data.get('round_num', 1)) * 97)
        obj.round_num = int(data.get('round_num', 1))
        obj.prep_deadline = data.get('prep_deadline', time.time() + 30)
        obj.phase = data.get('phase', 'prep')
        obj.winner_id = data.get('winner_id')
        obj.uid_seq = int(data.get('uid_seq', 1))
        obj.pool = dict(data.get('pool', {}))
        obj.commanders = copy.deepcopy(data.get('commanders', {}))
        obj.player_id = 'P1'
        obj.logs = list(data.get('logs', []))
        obj.combat_frames = []
        obj.last_round_report = copy.deepcopy(data.get('last_round_report'))
        obj.round_reports = copy.deepcopy(data.get('round_reports', {}))
        obj._last_round_snapshots = {}
        obj._live_engine = None
        obj._live_matchup = None
        obj._live_bouts = []
        return obj
