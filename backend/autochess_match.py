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

BENCH_CAPACITY = 10


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
    ):
        self.id = match_id or f'ac_{uuid.uuid4().hex[:10]}'
        self.mode = mode if mode in ('lobby4', 'pve12') else 'lobby4'
        self.arena_preset = arena_preset if arena_preset in ARENA_PRESETS else 'autochess_standard'
        self.seed = int(seed if seed is not None else random.randint(1, 10**9))
        self._rng = random.Random(self.seed)
        self.round_num = 1
        self.prep_deadline = time.time() + 30
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
        self.commanders = {}
        self.player_id = 'P1'
        self._live_engine = None
        self._live_matchup = None

        self._init_commanders(player_name)
        for cid in self.commanders:
            self._roll_shop_for(cid, free=True)
        self._deal_starter_units()
        self.logs.append(f'星序自走棋开启：模式={self.mode}，战场={ARENA_PRESETS[self.arena_preset]["name"]}')

    def _init_commanders(self, player_name):
        init_hp = 58 if self.mode == 'lobby4' else 45
        self.commanders['P1'] = self._new_commander('P1', player_name, is_human=True, hp=init_hp, personality='balanced')
        if self.mode == 'lobby4':
            bots = [
                ('P2', '苍星·守序者 (运营AI)', 'econ'),
                ('P3', '绯月·跃迁者 (速升AI)', 'fast_lv'),
                ('P4', '炽羽·强袭者 (追三AI)', 'reroll'),
            ]
            for bid, bname, pers in bots:
                self.commanders[bid] = self._new_commander(bid, bname, is_human=False, hp=init_hp, personality=pers)

    def _new_commander(self, cid, name, *, is_human, hp, personality):
        return {
            'id': cid,
            'name': name,
            'is_human': is_human,
            'personality': personality,
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

    def _free_bench_slot(self, cid):
        used = {u['bench_idx'] for u in self.bench_units(cid)}
        for idx in range(BENCH_CAPACITY):
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
            return False, f'备战席已满（{BENCH_CAPACITY}/{BENCH_CAPACITY}）且上阵人口已满'

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
        if cmd['level'] >= 5:
            return False
        if cmd['gold'] < 4:
            return False
        cmd['gold'] -= 4
        self._grant_xp(cid, 4)
        return True

    def _grant_xp(self, cid, amount):
        cmd = self.commanders[cid]
        cmd['xp'] += int(amount)
        while cmd['level'] < 5:
            need = LEVEL_TABLE[cmd['level']]['xp_to_next']
            if need <= 0 or cmd['xp'] < need:
                break
            cmd['xp'] -= need
            cmd['level'] += 1
        if cmd['level'] >= 5:
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
        if self.round_num not in (4, 8):
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

    def _advance_one_engine_turn(self, eng):
        """Advance a single unit's turn on FullBattleEngine cleanly."""
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

        actions_log = []
        reason = ''
        last_cmd = ''
        if entry.get('isSummon', False):
            gkey = eng._summon_group_key(uid)
            r = eng._execute_summon_group_action(gkey, lambda m_uid: (eng._summon_attack(m_uid), False, None))
            actions_log.extend(r.get('lines') or [])
            reason = f'召唤物 {entry.get("name", uid)} 自动攻击'
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
                    eng._consume_action(base, res.slot)
                    eng._ai_failed_commands.clear()
                    failures = 0
                    if cmd.startswith('.a m '):
                        if not hasattr(eng, '_moved_this_turn'):
                            eng._moved_this_turn = set()
                        eng._moved_this_turn.add(base)
                else:
                    failures += 1
                    eng._ai_failed_commands.add(cmd)
                    if failures >= 5:
                        eng._end_turn(uid)
                        break
            else:
                eng._end_turn(uid)

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

    def start_combat(self):
        if self.phase != 'prep':
            return False, '当前非备战阶段'
        p1 = self.commanders[self.player_id]
        if p1.get('pending_augments'):
            return False, '请先在【星序祝福】弹窗中选择本回合强化祝福'

        # Ensure P1 deploys at least one unit if available on bench
        if not self.board_units(self.player_id) and self.bench_units(self.player_id):
            self.deploy_unit(self.player_id, self.bench_units(self.player_id)[0]['id'])

        # Run prep AI for alive AI commanders
        for cid, cmd in self.commanders.items():
            if not cmd['is_human'] and not cmd.get('eliminated'):
                run_commander_prep(self, cid)

        # Pair opponents & construct live player bout
        other_outcomes = []
        if self.mode == 'lobby4':
            pairs = self._pair_lobby_opponents()
            p1_bout = None
            for a_id, b_id, is_ghost in pairs:
                if a_id == self.player_id or b_id == self.player_id:
                    opp_id = b_id if a_id == self.player_id else a_id
                    opp_cmd = self.commanders[opp_id]
                    p1_bout = {
                        'opponent_id': opp_id,
                        'opponent_name': f'{opp_cmd["name"]}' + (' (镜像)' if is_ghost else ''),
                        'is_ghost': is_ghost and b_id != self.player_id,
                        'opp_side_is_ghost': is_ghost and a_id == self.player_id,
                        'left_cfg': {'units': copy.deepcopy(self.board_units(self.player_id)), 'augments': list(p1['augments'])},
                        'right_cfg': {'units': copy.deepcopy(self.board_units(opp_id)), 'augments': list(opp_cmd['augments'])},
                        'arena_preset': self.arena_preset,
                    }
                else:
                    left_cmd, right_cmd = self.commanders[a_id], self.commanders[b_id]
                    out = self._run_headless_bout(
                        {'units': self.board_units(a_id), 'augments': left_cmd['augments']},
                        {'units': self.board_units(b_id), 'augments': right_cmd['augments']},
                        self.arena_preset,
                        self.seed + self.round_num * 37 + hash(a_id) % 997,
                    )
                    other_outcomes.append((a_id, b_id, is_ghost, out))
        else:
            wave = PVE_WAVES[min(self.round_num - 1, len(PVE_WAVES) - 1)]
            opp_units = [
                {'serial': s, 'star': st, 'stance': 'balanced', 'coord': None}
                for s, st in wave['units']
            ]
            p1_bout = {
                'opponent_id': f'WAVE_{wave["wave"]}',
                'opponent_name': f'第{wave["wave"]}波 · {wave["name"]}',
                'is_ghost': False,
                'opp_side_is_ghost': False,
                'left_cfg': {'units': copy.deepcopy(self.board_units(self.player_id)), 'augments': list(p1['augments'])},
                'right_cfg': {'units': opp_units, 'augments': []},
                'arena_preset': self.arena_preset,
            }

        self._live_matchup = {
            'player_bout': p1_bout,
            'other_outcomes': other_outcomes,
        }
        self._live_engine = self._build_battle_engine(
            p1_bout['left_cfg'],
            p1_bout['right_cfg'],
            p1_bout['arena_preset'],
            self.seed + self.round_num * 1009,
        )
        self.combat_frames = [
            {
                'round': 1,
                'actor_uid': None,
                'actor_name': '战斗开始',
                'team': 'Y',
                'cmd': '',
                'reason': f'VS {p1_bout["opponent_name"]}',
                'lines': [f'双方进入【{ARENA_PRESETS[p1_bout["arena_preset"]]["name"]}】准备接战'],
                'snapshot': self._engine_snapshot(self._live_engine),
            }
        ]
        self.phase = 'combat'
        self.logs.append(f'第 {self.round_num} 回合开战：{p1["name"]} vs {p1_bout["opponent_name"]}')
        return True, '战斗开始'

    def step_combat(self, steps=1):
        if self.phase != 'combat' or self._live_engine is None:
            return {'done': self.phase != 'combat', 'frames': []}
        new_frames = []
        for _ in range(max(1, int(steps))):
            st = self._live_engine._get_state() or {}
            if st.get('phase') != 'active' or st.get('round', 1) > self._live_engine.max_rounds:
                break
            frame = self._advance_one_engine_turn(self._live_engine)
            if frame is not None:
                self.combat_frames.append(frame)
                new_frames.append(frame)
                if len(self.combat_frames) > 220:
                    self.combat_frames = self.combat_frames[-220:]

        st = self._live_engine._get_state() or {}
        ended = (
            st.get('phase') != 'active'
            or st.get('round', 1) > self._live_engine.max_rounds
            or getattr(self._live_engine, '_battle_result', None) is not None
        )
        if ended:
            self._finalize_round()
        return {'done': ended, 'frames': new_frames, 'state': self.to_public_dict()}

    def resolve_combat(self):
        if self.phase == 'prep':
            ok, msg = self.start_combat()
            if not ok:
                return False, msg
        if self.phase in ('round_result', 'finished'):
            return True, '本回合战斗已结束'
        if self.phase != 'combat' or self._live_engine is None:
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

    def _finalize_round(self):
        if self.phase != 'combat' or self._live_engine is None:
            return
        outcome = self._extract_bout_outcome(self._live_engine)
        bout = self._live_matchup['player_bout']
        p1_won = (outcome['winner'] == 'Y')
        p1_dmg = self._apply_combat_hp_and_streak(self.player_id, p1_won, outcome['surviving_x'])
        if p1_won:
            self.commanders[self.player_id]['gold'] += 1  # Victory gold bonus

        opp_id = bout['opponent_id']
        if self.mode == 'lobby4' and opp_id in self.commanders and not bout.get('opp_side_is_ghost'):
            opp_dmg = self._apply_combat_hp_and_streak(opp_id, not p1_won, outcome['surviving_y'])
            if not p1_won:
                self.commanders[opp_id]['gold'] += 1
        for a_id, b_id, is_ghost, res in self._live_matchup.get('other_outcomes', []):
            a_won = (res['winner'] == 'Y')
            self._apply_combat_hp_and_streak(a_id, a_won, res['surviving_x'])
            if not is_ghost:
                self._apply_combat_hp_and_streak(b_id, not a_won, res['surviving_y'])
                if not a_won:
                    self.commanders[b_id]['gold'] += 1
            if a_won:
                self.commanders[a_id]['gold'] += 1

        self.last_round_report = {
            'round': self.round_num,
            'opponent_name': bout['opponent_name'],
            'won': p1_won,
            'battle_rounds': outcome['rounds'],
            'timeout': outcome['timeout'],
            'hp_damage': p1_dmg,
            'telemetry': outcome['telemetry'],
            'mvp': outcome['mvp'],
        }
        self._live_engine = None
        self._live_matchup = None

        status_str = '胜利' if p1_won else f'落败 (-{p1_dmg}HP)'
        self.logs.append(f'第 {self.round_num} 回合结束：{status_str}（{outcome["rounds"]}轮）')

        # Check end-of-match conditions
        p1 = self.commanders[self.player_id]
        if p1.get('eliminated'):
            self.phase = 'finished'
            self.winner_id = next(
                (c['id'] for c in self.commanders.values() if not c.get('eliminated')),
                None,
            )
            return
        if self.mode == 'pve12':
            if p1_won and self.round_num >= len(PVE_WAVES):
                p1['placement'] = 1
                self.phase = 'finished'
                self.winner_id = self.player_id
                self.logs.append('🏆 恭喜通关 12 波星序试炼！')
                return
        else:
            alive = [c for c in self.commanders.values() if not c.get('eliminated')]
            if len(alive) <= 1:
                if alive:
                    alive[0]['placement'] = 1
                    self.winner_id = alive[0]['id']
                self.phase = 'finished'
                self.logs.append(f'🏆 决胜结束！冠军：{self.commanders[self.winner_id]["name"]}')
                return

        self.phase = 'round_result'

    def next_round(self):
        if self.phase != 'round_result':
            return False, '当前无法进入下一回合'
        self.round_num += 1
        incomes = {}
        for cid in self.commanders:
            inc = self._grant_round_income(cid)
            if cid == self.player_id and inc:
                incomes = inc
        self._offer_augments_if_due()
        self.prep_deadline = time.time() + 30
        self.phase = 'prep'
        if incomes:
            self.logs.append(
                f'进入第 {self.round_num} 回合：+{incomes["total"]}G（基础{incomes["base"]}+利息{incomes["interest"]}+连胜败{incomes["streak"]}）'
            )
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

    def to_public_dict(self):
        md = build_arena_map(self.arena_preset)
        p1 = self.commanders[self.player_id]
        p1_board = self.board_units(self.player_id)
        p1_synergies = compute_active_synergies(p1_board)
        hints = self._upgrade_hints_for(self.player_id)
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

        live_snapshot = None
        if self._live_engine is not None:
            live_snapshot = self._engine_snapshot(self._live_engine)
        elif self.combat_frames:
            live_snapshot = self.combat_frames[-1].get('snapshot')

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
            'map': md,
            'player': {
                'id': p1['id'],
                'name': p1['name'],
                'hp': p1['hp'],
                'max_hp': p1['max_hp'],
                'gold': p1['gold'],
                'level': p1['level'],
                'xp': p1['xp'],
                'xp_to_next': LEVEL_TABLE[p1['level']]['xp_to_next'],
                'max_pop': self.max_pop(self.player_id),
                'max_interest': p1['max_interest'],
                'free_rerolls': p1['free_rerolls'],
                'streak': p1['streak'],
                'shop_locked': p1['shop_locked'],
                'shop': shop_view,
                'board': [dict(u, **UNIT_CATALOG[u['serial']]) for u in p1_board],
                'bench_capacity': BENCH_CAPACITY,
                'bench': [dict(u, **UNIT_CATALOG[u['serial']]) for u in self.bench_units(self.player_id)],
                'synergies': list(p1_synergies.values()),
                'augments': [next((a for a in AUGMENTS if a['id'] == aid), {'id': aid, 'name': aid}) for aid in p1['augments']],
                'pending_augments': p1['pending_augments'],
                'placement': p1['placement'],
            },
            'commanders': commanders_view,
            'combat_frames': self.combat_frames[-40:],
            'live_snapshot': live_snapshot,
            'last_round_report': self.last_round_report,
            'logs': self.logs[-50:],
            'pool_remaining': sum(self.pool.values()),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'mode': self.mode,
            'arena_preset': self.arena_preset,
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
        }

    @classmethod
    def from_dict(cls, data):
        obj = cls.__new__(cls)
        obj.id = data['id']
        obj.mode = data.get('mode', 'lobby4')
        obj.arena_preset = data.get('arena_preset', 'autochess_standard')
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
        obj._live_engine = None
        obj._live_matchup = None
        return obj
