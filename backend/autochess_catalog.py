"""Auto-Chess unit catalog, pool counts, star scaling, synergies, augments, and PvE waves."""

import copy
import math

from characters_data import ALL_CHARACTERS, load_character_to_engine

AUTOCHESS_RANGE_OVERRIDES = {
    '火球术': 7,
    '星闪攻击': 8,
    '发送雪球': 7,
    '制造雪带': 5,
    '火焰附魔': 2,
    '万众瞩目的乌托邦': 8,
    '月光王座全额率输出': 12,
}

# Canonical character lookup excluding legacy Y60 (kept only in classic mode).
CHAR_DATA_BY_SERIAL = {
    c['serial']: c for c in ALL_CHARACTERS
    if isinstance(c, dict) and c.get('serial') and c.get('serial') != 'Y60'
}

POOL_COUNTS = {1: 18, 2: 15, 3: 12, 4: 9}

LEVEL_TABLE = {
    1: {'max_pop': 2, 'xp_to_next': 2, 'odds': {1: 75, 2: 25, 3: 0, 4: 0}},
    2: {'max_pop': 3, 'xp_to_next': 6, 'odds': {1: 55, 2: 35, 3: 10, 4: 0}},
    3: {'max_pop': 4, 'xp_to_next': 10, 'odds': {1: 30, 2: 40, 3: 25, 4: 5}},
    4: {'max_pop': 5, 'xp_to_next': 16, 'odds': {1: 18, 2: 32, 3: 35, 4: 15}},
    5: {'max_pop': 6, 'xp_to_next': 24, 'odds': {1: 10, 2: 25, 3: 35, 4: 30}},
    6: {'max_pop': 6, 'xp_to_next': 0, 'odds': {1: 10, 2: 25, 3: 35, 4: 30}},
}

STAR_SCALING = {
    1: {
        'hp_mult': 1.0,
        'mp_mult': 1.0,
        'skill_bonus': 0,
        'flat_dmg': 0,
        'flat_dr': 0,
        'summon_hp_mult': 1.0,
        'summon_skill_bonus': 0,
    },
    2: {
        'hp_mult': 1.65,
        'mp_mult': 1.25,
        'skill_bonus': 10,
        'flat_dmg': 1,
        'flat_dr': 0,
        'summon_hp_mult': 1.5,
        'summon_skill_bonus': 8,
    },
    3: {
        'hp_mult': 2.6,
        'mp_mult': 1.55,
        'skill_bonus': 20,
        'flat_dmg': 3,
        'flat_dr': 1,
        'summon_hp_mult': 2.2,
        'summon_skill_bonus': 16,
    },
}

UNIT_CATALOG = {
    'Y1': {
        'serial': 'Y1', 'name': '炎焱', 'cost': 1, 'role': 'bruiser',
        'traits': ['炎域', '重盾'], 'range': 2,
        'tag': '烈焰前锋', 'blurb': '高血量火焰斗士，开火附魔后近战爆发极强。',
    },
    'Y2': {
        'serial': 'Y2', 'name': '达尼厄斯', 'cost': 3, 'role': 'ranged',
        'traits': ['炎域', '星祈'], 'range': 7, 'dmg_pct_offset': -10,
        'tag': '火球魔导', 'blurb': '稳定远程火球输出并可召唤使魔牵制敌方。',
    },
    'Y3': {
        'serial': 'Y3', 'name': '灵牛', 'cost': 1, 'role': 'bruiser',
        'traits': ['重盾', '武斗'], 'range': 2,
        'tag': '附魔拳师', 'blurb': '稳健体魄与附魔近战兼备的前排战力。',
    },
    'Y8': {
        'serial': 'Y8', 'name': '比哈米', 'cost': 1, 'role': 'support',
        'traits': ['秘愈', '星祈'], 'range': 5, 'hp_offset': 3,
        'tag': '甜点支援', 'blurb': '为队友供应回复与增益道具的百搭团队辅助。',
    },
    'Y10': {
        'serial': 'Y10', 'name': '春晌', 'cost': 1, 'role': 'support',
        'traits': ['秘愈', '灵召'], 'range': 5, 'hp_offset': 2,
        'tag': '护盾治愈', 'blurb': '兼顾护盾、治疗、藤蔓控场与蜂鸟召唤。',
    },
    'Y4': {
        'serial': 'Y4', 'name': '星闪', 'cost': 2, 'role': 'ranged',
        'traits': ['星祈', '破空'], 'range': 8,
        'tag': '远程星炮', 'blurb': '超远距离星闪火力，适合在掩体与后排持续压制。',
    },
    'Y5': {
        'serial': 'Y5', 'name': '血天使', 'cost': 3, 'role': 'assassin',
        'traits': ['血月', '破空'], 'range': 2, 'hp_offset': 1,
        'tag': '空袭吸血', 'blurb': '飞行越障切入后排，攻击附带吸血续航。',
    },
    'Y6': {
        'serial': 'Y6', 'name': '雪人v2', 'cost': 2, 'role': 'ranged',
        'traits': ['破空', '秘愈'], 'range': 7,
        'tag': '霜雪控场', 'blurb': '远程雪球与雪带限制敌方走位与节奏。',
    },
    'Y11': {
        'serial': 'Y11', 'name': '蓝', 'cost': 1, 'role': 'assassin',
        'traits': ['血月', '武斗'], 'range': 2, 'flat_dmg_offset': 1,
        'tag': '死神镰刃', 'blurb': '黑雾突进与高爆发镰刀收割。',
    },
    'Y14': {
        'serial': 'Y14', 'name': '余烬', 'cost': 2, 'role': 'ranged',
        'traits': ['炎域', '破空'], 'range': 6,
        'tag': '街机切卡', 'blurb': '多卡带切换兼顾散射压制与高机动反打。',
    },
    'Y7': {
        'serial': 'Y7', 'name': '环花暖', 'cost': 2, 'role': 'support',
        'traits': ['星祈', '秘愈'], 'range': 6, 'hp_offset': 3,
        'tag': '花咏治愈', 'blurb': '大范围治愈领域、战意削弱与返生核心辅助。',
    },
    'Y9': {
        'serial': 'Y9', 'name': '木落', 'cost': 3, 'role': 'summoner',
        'traits': ['灵召', '秘愈'], 'range': 5, 'hp_offset': 3, 'dmg_pct_offset': 12,
        'tag': '生灵统御', 'blurb': '召唤生灵并展开生命领域，越打越厚的阵地核心。',
    },
    'Y13': {
        'serial': 'Y13', 'name': '“巨人”', 'cost': 3, 'role': 'bruiser',
        'traits': ['重盾', '武斗'], 'range': 2,
        'tag': '飞行重装', 'blurb': '可越墙突入的魔力护体战士，承伤与爆发兼备。',
    },
    'Y15': {
        'serial': 'Y15', 'name': '葬火', 'cost': 3, 'role': 'ranged',
        'traits': ['炎域', '秘愈'], 'range': 6, 'dmg_pct_offset': 12,
        'tag': '爆破焦土', 'blurb': '爆破圈叠加瞬爆造成毁灭性范围伤害。',
    },
    'Y12': {
        'serial': 'Y12', 'name': '斯瑞提卡', 'cost': 4, 'role': 'tank',
        'traits': ['重盾', '灵召'], 'range': 2,
        'tag': '四象空间盾', 'blurb': '四灵召唤与高额格挡减伤，三位一体合体毁天灭地。',
    },
    'Y16': {
        'serial': 'Y16', 'name': '罗杰', 'cost': 4, 'role': 'summoner',
        'traits': ['星祈', '灵召'], 'range': 12, 'hp_offset': 2,
        'tag': '幻月王座', 'blurb': '虚假之月充能配合远距毁灭光束的主宰核心。',
    },
    'Y17': {
        'serial': 'Y17', 'name': '夜诏明', 'cost': 4, 'role': 'bruiser',
        'traits': ['血月', '武斗'], 'range': 3, 'hp_offset': 3, 'dmg_pct_offset': 15, 'flat_dmg_offset': 1,
        'tag': '血律宗师', 'blurb': '庞大魔力与血池体系加持的多面手主C。',
    },
}

SYNERGIES = {
    '炎域': {
        'id': '炎域', 'name': '炎域', 'icon': '🔥',
        'desc': '炎域单位造成额外伤害，对残血敌人触发斩杀增伤。',
        'tiers': [
            {'count': 2, 'label': '全伤害+12%', 'dmg_pct': 12, 'low_hp_bonus': None},
            {'count': 4, 'label': '全伤害+25%，对<50%HP目标再+15%', 'dmg_pct': 25, 'low_hp_bonus': (0.5, 15)},
        ],
    },
    '星祈': {
        'id': '星祈', 'name': '星祈', 'icon': '✨',
        'desc': '全队每回合恢复额外MP；4星祈缩短主动技能冷却。',
        'tiers': [
            {'count': 2, 'label': '全队每轮+1 MP', 'round_mp_regen': 1, 'cd_reduction': 0},
            {'count': 4, 'label': '全队每轮+2 MP，星祈冷却-1', 'round_mp_regen': 2, 'cd_reduction': 1},
        ],
    },
    '重盾': {
        'id': '重盾', 'name': '重盾', 'icon': '🛡️',
        'desc': '在前排或掩体获得百分比与固定伤害减免，开局获得护盾。',
        'tiers': [
            {'count': 2, 'label': '前排/掩体减伤14%，开局+4盾', 'front_cover_dr_pct': 14, 'flat_dr': 1, 'shield': 4},
            {'count': 4, 'label': '全队前排/掩体减伤26%，固定减伤+2，+8盾', 'front_cover_dr_pct': 26, 'flat_dr': 2, 'shield': 8},
        ],
    },
    '血月': {
        'id': '血月', 'name': '血月', 'icon': '🩸',
        'desc': '血月棋子造成伤害时按比例回复体力，溢出转为护盾。',
        'tiers': [
            {'count': 2, 'label': '18% 伤害汲取为生命/护盾', 'bloodmoon_leech_pct': 18},
            {'count': 3, 'label': '34% 伤害汲取为生命/护盾', 'bloodmoon_leech_pct': 34},
        ],
    },
    '武斗': {
        'id': '武斗', 'name': '武斗', 'icon': '⚔️',
        'desc': '提升武斗棋子的攻击/闪避技能成功率并附加固定穿透伤害。',
        'tiers': [
            {'count': 2, 'label': '战斗技能+7，基础伤害+1', 'skill_bonus': 7, 'flat_dmg': 1},
            {'count': 4, 'label': '战斗技能+15，基础伤害+2', 'skill_bonus': 15, 'flat_dmg': 2},
        ],
    },
    '灵召': {
        'id': '灵召', 'name': '灵召', 'icon': '🐾',
        'desc': '大幅强化召唤物生命值与攻击检定技能。',
        'tiers': [
            {'count': 2, 'label': '召唤物HP×1.25、技能+8', 'summon_hp_mult': 1.25, 'summon_skill_bonus': 8},
            {'count': 4, 'label': '召唤物HP×1.55、技能+16', 'summon_hp_mult': 1.55, 'summon_skill_bonus': 16},
        ],
    },
    '破空': {
        'id': '破空', 'name': '破空', 'icon': '🕊️',
        'desc': '提升敏捷、移动预算与远程攻击射程。',
        'tiers': [
            {'count': 2, 'label': '移动+1格，远射程+1，敏捷+6', 'move_bonus': 1, 'range_bonus': 1, 'dex_bonus': 6},
            {'count': 4, 'label': '移动+2格，远射程+2，敏捷+12', 'move_bonus': 2, 'range_bonus': 2, 'dex_bonus': 12},
        ],
    },
    '秘愈': {
        'id': '秘愈', 'name': '秘愈', 'icon': '🌿',
        'desc': '扩展阵法范围并在战斗开始为全队提供守护屏障。',
        'tiers': [
            {'count': 2, 'label': '阵法半径+1，全队开局+4护盾', 'zone_radius_bonus': 1, 'team_shield': 4, 'flat_hp': 2},
            {'count': 4, 'label': '全队+6护盾、最大体力+4、每轮+1 MP', 'zone_radius_bonus': 1, 'team_shield': 6, 'flat_hp': 4, 'round_mp_regen': 1},
        ],
    },
}

AUGMENTS = [
    {'id': 'aug_reserves', 'name': '后备扩编', 'tier': '备战', 'desc': '本局永久解锁 2 个额外备战席，最多可用 12 格。'},
    {'id': 'aug_econ', 'name': '星辉投资', 'tier': '经济', 'desc': '立即获得 8 金币，且你的利息上限由 +5 提升至 +7。', 'instant_gold': 8, 'max_interest': 7},
    {'id': 'aug_xp', 'name': '秘典研习', 'tier': '经验', 'desc': '立即获得 6 点经验与 2 次免费商店刷新。', 'instant_xp': 6, 'free_rerolls': 2},
    {'id': 'aug_reroll', 'name': '黄金牌库', 'tier': '商店', 'desc': '立即获得 3 次免费刷新与 3 金币，刷新时更易搜到高费棋子。', 'instant_gold': 3, 'free_rerolls': 3},
    {'id': 'aug_pop', 'name': '星核扩容', 'tier': '人口', 'desc': '你的最大上阵人口永久 +1（可突破 6 人口上限）。', 'pop_bonus': 1},
    {'id': 'aug_bastion', 'name': '钢铁前线', 'tier': '防御', 'desc': '全队前排或掩体格减伤 +18%，开局获得 6 点护盾。', 'front_cover_dr_pct': 18, 'team_shield': 6},
    {'id': 'aug_execute', 'name': '绝地斩魄', 'tier': '输出', 'desc': '全队对体力低于 50% 的敌人伤害 +20%，低于 30% 时再 +20%。', 'low_hp_bonuses': [(0.5, 20), (0.3, 20)]},
    {'id': 'aug_blood', 'name': '血月盛宴', 'tier': '续航', 'desc': '所有友方单位获得 16% 全能汲取，溢出血量转为护盾。', 'bloodmoon_leech_pct': 16},
    {'id': 'aug_swift', 'name': '极速机动', 'tier': '空间', 'desc': '全队移动力 +2 格，远程射程 +1 格，闪避 +8。', 'move_bonus': 2, 'range_bonus': 1, 'dodge_bonus': 8},
    {'id': 'aug_mana', 'name': '法力洪流', 'tier': '魔力', 'desc': '全队每轮恢复 +2 MP，初始魔力上限与当前魔力 +4。', 'round_mp_regen': 2, 'flat_mp': 4},
    {'id': 'aug_zone', 'name': '阵域扩展', 'tier': '阵法', 'desc': '全队领域半径 +1，主动技能冷却缩短 1 回合。', 'zone_radius_bonus': 1, 'cd_reduction': 1},
    {'id': 'aug_summon', 'name': '英灵统御', 'tier': '召唤', 'desc': '我方所有召唤物体力×1.35，攻击技能命中 +12。', 'summon_hp_mult': 1.35, 'summon_skill_bonus': 12},
    {'id': 'aug_precision', 'name': '精密准则', 'tier': '技巧', 'desc': '全队所有攻击技能 +10，基础伤害 +2。', 'skill_bonus': 10, 'flat_dmg': 2},
    {'id': 'aug_titan', 'name': '不屈意志', 'tier': '体魄', 'desc': '全队最大体力 +25% 且受到任何伤害固定减免 1 点。', 'hp_pct': 25, 'flat_dr': 1},
    {'id': 'aug_pair', 'name': '双星奇点', 'tier': '奇遇', 'desc': '立刻为你招募 1 位随机 2 费核心棋子（优先凑对），并返还 3 金币。', 'instant_gold': 3, 'gift_cost': 2},
]

PVE_WAVES = [
    {'wave': 1, 'name': '星屑巡逻兵', 'arena': 'autochess_compact', 'units': [('Y1', 1), ('Y8', 1)]},
    {'wave': 2, 'name': '火焰与星光', 'arena': 'autochess_standard', 'units': [('Y2', 1), ('Y4', 1), ('Y3', 1)]},
    {'wave': 3, 'name': '甜点守卫阵', 'arena': 'autochess_standard', 'units': [('Y3', 1), ('Y10', 1), ('Y8', 2)]},
    {'wave': 4, 'name': '霜雪拦截网', 'arena': 'autochess_standard', 'units': [('Y1', 2), ('Y6', 1), ('Y2', 2)]},
    {'wave': 5, 'name': '血月游猎团', 'arena': 'autochess_standard', 'units': [('Y5', 2), ('Y11', 2), ('Y8', 1)]},
    {'wave': 6, 'name': '像素轰炸队', 'arena': 'autochess_citadel', 'units': [('Y14', 2), ('Y15', 1), ('Y13', 1), ('Y10', 2)]},
    {'wave': 7, 'name': '生灵圣愈阵', 'arena': 'autochess_citadel', 'units': [('Y9', 2), ('Y7', 2), ('Y3', 2), ('Y4', 2)]},
    {'wave': 8, 'name': '空天强袭队', 'arena': 'autochess_standard', 'units': [('Y13', 2), ('Y5', 2), ('Y14', 2), ('Y6', 2), ('Y7', 1)]},
    {'wave': 9, 'name': '四象空间壁', 'arena': 'autochess_citadel', 'units': [('Y12', 2), ('Y9', 2), ('Y15', 2), ('Y10', 2), ('Y4', 2)]},
    {'wave': 10, 'name': '血律统御者', 'arena': 'autochess_citadel', 'units': [('Y17', 2), ('Y11', 2), ('Y5', 2), ('Y7', 2), ('Y1', 2)]},
    {'wave': 11, 'name': '幻月星辰议会', 'arena': 'autochess_citadel', 'units': [('Y16', 2), ('Y12', 2), ('Y4', 3), ('Y7', 2), ('Y15', 2)]},
    {'wave': 12, 'name': '终焉星序共鸣', 'arena': 'autochess_citadel', 'units': [('Y12', 3), ('Y16', 2), ('Y17', 2), ('Y7', 2), ('Y13', 2), ('Y15', 2)]},
]


def _pick_tier(syn_def, count):
    active = None
    for tier in syn_def['tiers']:
        if count >= tier['count']:
            active = tier
    return active


def compute_active_synergies(board_units):
    """Count distinct champion serials on board and compute active synergy tiers."""
    distinct = set()
    for u in board_units or ():
        serial = u.get('serial') if isinstance(u, dict) else getattr(u, 'serial', '')
        if serial in UNIT_CATALOG:
            distinct.add(serial)

    counts = {syn_id: 0 for syn_id in SYNERGIES}
    for serial in distinct:
        for trait in UNIT_CATALOG[serial]['traits']:
            if trait in counts:
                counts[trait] += 1

    active = {}
    for syn_id, syn_def in SYNERGIES.items():
        cnt = counts[syn_id]
        tier = _pick_tier(syn_def, cnt)
        if cnt > 0 or tier is not None:
            active[syn_id] = {
                'id': syn_id,
                'name': syn_def['name'],
                'icon': syn_def['icon'],
                'count': cnt,
                'next_tier': next((t['count'] for t in syn_def['tiers'] if t['count'] > cnt), None),
                'max_tier': syn_def['tiers'][-1]['count'],
                'active_tier': tier,
                'desc': syn_def['desc'],
            }
    return active


def apply_autochess_modifiers(engine, team_code, unit_configs, active_synergies, augments=None):
    """Instantiate board units onto ``engine`` with star, synergy, and augment scaling.

    Never mutates global ALL_CHARACTERS or engine defaults outside autochess dicts.
    """
    augments = list(augments or ())
    aug_defs = {a['id']: a for a in AUGMENTS}
    resolved_augs = [aug_defs[a] if isinstance(a, str) and a in aug_defs else a for a in augments]

    team_mod = getattr(engine, '_autochess_team_mods', None)
    if team_mod is None:
        team_mod = {}
        engine._autochess_team_mods = team_mod
    t_cfg = team_mod.setdefault(team_code, {'round_mp_regen': 0})

    unit_mods = getattr(engine, '_autochess_unit_mods', None)
    if unit_mods is None:
        unit_mods = {}
        engine._autochess_unit_mods = unit_mods

    range_bonus = getattr(engine, '_autochess_range_bonus', None)
    if range_bonus is None:
        range_bonus = {}
        engine._autochess_range_bonus = range_bonus

    move_bonus = getattr(engine, '_autochess_move_bonus', None)
    if move_bonus is None:
        move_bonus = {}
        engine._autochess_move_bonus = move_bonus

    if not getattr(engine, '_autochess_range_overrides', None):
        engine._autochess_range_overrides = dict(AUTOCHESS_RANGE_OVERRIDES)

    team_shield_total = 0
    team_flat_hp = 0
    team_hp_pct = 0
    team_flat_mp = 0
    team_dodge_bonus = 0
    team_skill_bonus = 0
    team_flat_dmg = 0
    team_flat_dr = 0
    team_front_cover_dr = 0
    team_bloodmoon = 0
    team_cd_red = 0
    team_summon_hp_mult = 1.0
    team_summon_skill_bonus = 0
    team_zone_radius_bonus = 0
    team_move_bonus = 0
    team_range_bonus = 0
    team_low_hp_bonuses = []

    for syn_id, info in (active_synergies or {}).items():
        tier = info.get('active_tier')
        if not tier:
            continue
        t_cfg['round_mp_regen'] += int(tier.get('round_mp_regen', 0) or 0)
        team_shield_total += int(tier.get('team_shield', 0) or 0)
        team_flat_hp += int(tier.get('flat_hp', 0) or 0)

    for aug in resolved_augs:
        if not isinstance(aug, dict):
            continue
        t_cfg['round_mp_regen'] += int(aug.get('round_mp_regen', 0) or 0)
        team_shield_total += int(aug.get('team_shield', 0) or 0)
        team_hp_pct += int(aug.get('hp_pct', 0) or 0)
        team_flat_mp += int(aug.get('flat_mp', 0) or 0)
        team_dodge_bonus += int(aug.get('dodge_bonus', 0) or 0)
        team_skill_bonus += int(aug.get('skill_bonus', 0) or 0)
        team_flat_dmg += int(aug.get('flat_dmg', 0) or 0)
        team_flat_dr += int(aug.get('flat_dr', 0) or 0)
        team_front_cover_dr += int(aug.get('front_cover_dr_pct', 0) or 0)
        team_bloodmoon += int(aug.get('bloodmoon_leech_pct', 0) or 0)
        team_cd_red += int(aug.get('cd_reduction', 0) or 0)
        if aug.get('summon_hp_mult'):
            team_summon_hp_mult *= float(aug['summon_hp_mult'])
        team_summon_skill_bonus += int(aug.get('summon_skill_bonus', 0) or 0)
        team_zone_radius_bonus += int(aug.get('zone_radius_bonus', 0) or 0)
        team_move_bonus += int(aug.get('move_bonus', 0) or 0)
        team_range_bonus += int(aug.get('range_bonus', 0) or 0)
        for pair in (aug.get('low_hp_bonuses') or ()):
            team_low_hp_bonuses.append(tuple(pair))

    spawned_uids = []
    unit_shields = {}
    for cfg in unit_configs:
        uid = cfg['uid']
        serial = cfg['serial']
        star = max(1, min(3, int(cfg.get('star', 1) or 1)))
        raw = CHAR_DATA_BY_SERIAL[serial]
        cdata = copy.deepcopy(raw)
        cdata['name'] = f"{raw['name']}{'★' * star if star > 1 else ''}"
        load_character_to_engine(engine, cdata, uid)
        char = engine.get_char(uid)
        sc = STAR_SCALING[star]
        meta = UNIT_CATALOG.get(serial, {})
        traits = set(meta.get('traits', ()))

        # Compute effective HP/MP scaling (plus optional Auto-Chess-only per-unit offsets)
        base_hp = char.get_attr('体力上限', char.get_attr('体力', 10)) + int(meta.get('hp_offset', 0) or 0)
        scaled_hp = max(1, int(round(base_hp * sc['hp_mult'] * (1.0 + team_hp_pct / 100.0))) + team_flat_hp)
        char.set_attr('体力上限', scaled_hp)
        char.set_attr('体力', scaled_hp)

        base_mp = char.get_attr('魔力上限', char.get_attr('魔力', 10))
        scaled_mp = max(0, int(round(base_mp * sc['mp_mult'])) + team_flat_mp)
        char.set_attr('魔力上限', scaled_mp)
        char.set_attr('魔力', scaled_mp)

        # Trait-specific synergy modifiers
        syn_skill = team_skill_bonus + sc['skill_bonus']
        syn_dmg_pct = int(meta.get('dmg_pct_offset', 0) or 0)
        syn_flat_dmg = team_flat_dmg + sc['flat_dmg'] + int(meta.get('flat_dmg_offset', 0) or 0)
        syn_flat_dr = team_flat_dr + sc['flat_dr']
        syn_front_cover = team_front_cover_dr
        syn_bloodmoon = team_bloodmoon
        syn_cd = team_cd_red
        syn_sum_hp = sc['summon_hp_mult'] * team_summon_hp_mult
        syn_sum_sk = sc['summon_skill_bonus'] + team_summon_skill_bonus
        syn_zone_r = team_zone_radius_bonus
        syn_mv = team_move_bonus
        syn_rng = team_range_bonus
        syn_low_hp = list(team_low_hp_bonuses)
        u_shield = team_shield_total
        dex_bonus = 0
        dodge_bonus = team_dodge_bonus + (4 if star == 2 else 8 if star == 3 else 0)

        for syn_id in traits:
            tier = (active_synergies or {}).get(syn_id, {}).get('active_tier')
            if not tier:
                continue
            syn_dmg_pct += int(tier.get('dmg_pct', 0) or 0)
            if tier.get('low_hp_bonus'):
                syn_low_hp.append(tuple(tier['low_hp_bonus']))
            syn_cd += int(tier.get('cd_reduction', 0) or 0)
            syn_front_cover += int(tier.get('front_cover_dr_pct', 0) or 0)
            syn_flat_dr += int(tier.get('flat_dr', 0) or 0)
            u_shield += int(tier.get('shield', 0) or 0)
            syn_bloodmoon += int(tier.get('bloodmoon_leech_pct', 0) or 0)
            syn_skill += int(tier.get('skill_bonus', 0) or 0)
            syn_flat_dmg += int(tier.get('flat_dmg', 0) or 0)
            if tier.get('summon_hp_mult'):
                syn_sum_hp *= float(tier['summon_hp_mult'])
            syn_sum_sk += int(tier.get('summon_skill_bonus', 0) or 0)
            syn_mv += int(tier.get('move_bonus', 0) or 0)
            syn_rng += int(tier.get('range_bonus', 0) or 0)
            dex_bonus += int(tier.get('dex_bonus', 0) or 0)
            syn_zone_r += int(tier.get('zone_radius_bonus', 0) or 0)

        if dex_bonus:
            char.set_attr('敏捷', min(92, char.get_attr('敏捷', 50) + dex_bonus))
        if dodge_bonus:
            char.set_attr('闪避', min(85, char.get_attr('闪避', 25) + dodge_bonus))
        if syn_skill:
            for attr_key, val in list(char.attrs.items()):
                if attr_key in ('斗殴', '剑术', '武术', '射击:弓', '弓术', '魔法', '施法', '灵感', '格挡', '盾击', '神秘学', '技艺:演唱', '写作'):
                    if val > 0:
                        char.set_attr(attr_key, min(92, int(val) + syn_skill))

        unit_mods[uid] = {
            'dmg_pct': syn_dmg_pct,
            'flat_dmg': syn_flat_dmg,
            'flat_dr': syn_flat_dr,
            'front_cover_dr_pct': syn_front_cover,
            'bloodmoon_leech_pct': syn_bloodmoon,
            'cd_reduction': syn_cd,
            'summon_hp_mult': syn_sum_hp,
            'summon_skill_bonus': syn_sum_sk,
            'zone_radius_bonus': syn_zone_r,
            'low_hp_bonuses': syn_low_hp,
        }
        if syn_rng:
            range_bonus[uid] = syn_rng
        if syn_mv:
            move_bonus[uid] = syn_mv
        if u_shield > 0:
            unit_shields[uid] = u_shield
        spawned_uids.append(uid)

    return spawned_uids, unit_shields


def apply_opening_shields(engine, unit_shields):
    """Apply starting barrier effects cleanly after engine.setup_battle initializes storage."""
    if not unit_shields:
        return
    effs = list(engine._get_effects() or [])
    for uid, val in unit_shields.items():
        if val <= 0:
            continue
        effs.append({
            'type': 'shield',
            'value': int(val),
            'remainingRounds': 4,
            'sourceUserId': uid,
            'targetUserId': uid,
            'spellName': '星序护盾',
            'spellIndex': 0,
            'persistent': 0,
        })
    engine._set_effects(effs)


_TIMING_LABELS = {
    '1': '准备/被动',
    '2': '主动作',
    '3': '附加动作',
    '4': '反应',
    '23': '主/附加',
}

_Y14_PHASE_LABELS = {
    0: '切卡',
    1: '魂斗罗',
    2: '最终幻想',
    3: '音速索尼克',
}


def _summarize_wiki_spell_effects(effects):
    parts = []
    seen = set()

    def _add(txt):
        if txt and txt not in seen:
            seen.add(txt)
            parts.append(txt)

    for eff in effects or ():
        et = int(eff.get('type', 0) or 0)
        if eff.get('伤害骰'):
            _add(f"伤害 {eff['伤害骰']}")
        elif eff.get('damage_pct_caster_max_hp'):
            _add(f"按最大体力百分比伤害({eff['damage_pct_caster_max_hp']}%)")
        elif eff.get('damage_table'):
            _add('按命中阶次分级伤害')
        if eff.get('每回合伤害骰'):
            _add(f"持续伤害 {eff['每回合伤害骰']}")
        if eff.get('ignite'):
            _add(f"点燃({eff.get('ignite_dmg_dice') or eff.get('ignite_tick_dmg') or '灼烧'})")
        if eff.get('吸血比例'):
            _add(f"吸血 {int(float(eff['吸血比例']) * 100)}%")
        if eff.get('回复hp'):
            _add(f"回复HP {eff['回复hp']}")
        if eff.get('回复mp'):
            _add(f"回魔 {eff['回复mp']}")
        if eff.get('回复san'):
            _add(f"恢复SAN {eff['回复san']}")
        if eff.get('护盾值'):
            _add(f"护盾 {eff['护盾值']}")
        if et == 5 or eff.get('召唤物模板'):
            tmpl = eff.get('召唤物模板') or '使魔'
            cnt = eff.get('召唤个数', 1)
            _add(f"召唤 {tmpl}×{cnt}")
        if et == 6 or eff.get('制造物模板'):
            _add(f"制作 {eff.get('制造物模板') or '道具'}")
        if et == 8 or eff.get('作用半径'):
            r = eff.get('作用半径', 0)
            _add(f"半径 {r} 格领域" if r else '触发领域')
        if et == 11 or eff.get('战意削弱概率'):
            _add('削弱敌方战意/输出')
        if et == 18:
            _add('队友濒死救援/急救')
        if et == 19 or eff.get('复活回复比例'):
            _add('复活阵亡友军')
        if eff.get('target_phase') is not None:
            _add(f"切换至形态 {eff['target_phase']}")
        if eff.get('辅助效果'):
            val = eff.get('辅助效果值')
            _add(f"{eff['辅助效果']}" + (f"({val})" if val not in (None, '') else ''))
        if eff.get('冰冻每轮层数'):
            _add('叠加寒霜/冰冻')
        dur = eff.get('持续回合')
        if isinstance(dur, (int, float)):
            if int(dur) > 0 and int(dur) < 90:
                _add(f"持续{int(dur)}轮")
        elif dur:
            _add(f"持续{dur}轮")
    return ' · '.join(parts) if parts else '强化或状态联动技能'


def _build_wiki_passives(passive_rules):
    if not isinstance(passive_rules, dict) or not passive_rules:
        return []
    out = []
    if 'frost' in passive_rules:
        fr = passive_rules['frost']
        out.append(
            f"寒霜机制：命中叠加寒霜，引爆造成 {fr.get('burst', '1d10+1d6+2')} 伤害与 "
            f"{fr.get('dot', '1d4+2')} 持续冻伤，附带目标闪避/移速惩罚及友方周期回复。"
        )
    if 'cartridge' in passive_rules:
        cr = passive_rules['cartridge']
        out.append(
            f"街机三卡带：可切换魂斗罗 / 最终幻想 / 音速索尼克三形态（基础切换冷却 "
            f"{cr.get('cooldown', 3)} 回合），累计充能达 {cr.get('limit_cap', 5)} / "
            f"冲刺 {cr.get('dash_distance', 8)} 格解锁高阶技能。"
        )
    if 'cloak' in passive_rules:
        ck = passive_rules['cloak']
        out.append(
            f"魔导披风：免疫 <= {ck.get('immune_max', 3)} 点微伤，中等伤害减至 "
            f"{ck.get('middle_damage', 3)}，高伤倍率 ×{ck.get('high_multiplier', 0.6)}，受击 +{ck.get('mp_per_hit', 1)} MP。"
        )
    if 'moon' in passive_rules:
        mn = passive_rules['moon']
        out.append(
            f"虚假之月：技能积攒月能层数（满 {mn.get('ultimate_threshold', 20)} 层释放全额月光炮），"
            f"弓术攻击额外 +{mn.get('bow_extra_mp', 1)} MP。"
        )
    if 'phantom' in passive_rules:
        out.append('幻影秘术：按幻影检定阶次获得额外增伤/回蓝等辅助修正。')
    return out


def build_unit_wiki(serial):
    """Build Auto-Chess-specific wiki data strictly matching Auto-Chess mechanics and stats."""
    meta = UNIT_CATALOG[serial]
    raw = CHAR_DATA_BY_SERIAL[serial]
    attrs = raw.get('attrs', {}) or {}
    str_attrs = raw.get('str_attrs', {}) or {}
    passive_rules = raw.get('passive_rules') or {}

    base_hp = int(attrs.get('体力上限', attrs.get('体力', 10)) or 10) + int(meta.get('hp_offset', 0) or 0)
    base_mp = int(attrs.get('魔力上限', attrs.get('魔力', 10)) or 0)
    mov = int(attrs.get('行动力', 8) or 0)
    extra_acts = int(attrs.get('额外行动数', 0) or 0)
    tactical_move = 0 if mov <= 0 else min(8, max(2, math.ceil(mov / 2)))
    main_actions = max(1, (mov + 1) // 5 + extra_acts)
    dex = int(attrs.get('敏捷', 50) or 50)
    base_dodge = int(attrs.get('闪避', 25) or 25)
    can_block = bool(attrs.get('可格挡'))
    block_val = int(attrs.get('格挡', 0) or 0) if can_block else 0
    flying = serial in ('Y5', 'Y13')

    tuning_notes = []
    if meta.get('hp_offset'):
        hp_off = int(meta['hp_offset'])
        tuning_notes.append(f"自走棋基础体力 {'+' if hp_off > 0 else ''}{hp_off}")
    if meta.get('dmg_pct_offset'):
        pct_off = int(meta['dmg_pct_offset'])
        tuning_notes.append(f"自走棋输出倍率 {'+' if pct_off > 0 else ''}{pct_off}%")
    if meta.get('flat_dmg_offset'):
        fd_off = int(meta['flat_dmg_offset'])
        tuning_notes.append(f"自走棋附加伤害 {'+' if fd_off > 0 else ''}{fd_off}")

    star_stats = {}
    for star in (1, 2, 3):
        sc = STAR_SCALING[star]
        star_stats[str(star)] = {
            'star': star,
            'hp': max(1, int(round(base_hp * sc['hp_mult']))),
            'mp': max(0, int(round(base_mp * sc['mp_mult']))),
            'skill_bonus': sc['skill_bonus'],
            'flat_dmg': sc['flat_dmg'] + int(meta.get('flat_dmg_offset', 0) or 0),
            'flat_dr': sc['flat_dr'],
            'dodge': min(85, base_dodge + (4 if star == 2 else 8 if star == 3 else 0)),
            'summon_hp_mult': sc['summon_hp_mult'],
            'summon_skill_bonus': sc['summon_skill_bonus'],
        }

    skill_candidates = [
        (k, int(attrs[k]))
        for k in ('斗殴', '剑术', '武术', '射击:弓', '弓术')
        if int(attrs.get(k, 0) or 0) > 0
    ]
    best_skill_name, best_skill_val = max(skill_candidates, key=lambda x: x[1], default=('斗殴', 50))

    skills_wiki = []
    for sp in raw.get('spells', ()):
        sp_name = sp.get('name', '未命名技能')
        effs = sp.get('effects', ()) or ()
        phase = int(sp.get('phase', 0) or 0)
        if serial == 'Y14':
            phase_label = _Y14_PHASE_LABELS.get(phase, f'形态{phase}')
        else:
            phase_label = f'形态{phase}' if phase > 0 else ''

        if sp_name in AUTOCHESS_RANGE_OVERRIDES:
            eff_range = AUTOCHESS_RANGE_OVERRIDES[sp_name]
        else:
            raw_ranges = [int(e['射程']) for e in effs if isinstance(e.get('射程'), (int, float)) and e['射程'] > 0]
            if not raw_ranges:
                eff_range = None
            else:
                mr = max(raw_ranges)
                eff_range = meta['range'] if mr >= 90 else mr

        cd_vals = [
            int(v)
            for v in ([sp.get('cooldown_rounds', 0)] + [e.get('cooldown_rounds', 0) for e in effs])
            if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit())
        ] or [0]
        cooldown = max(cd_vals)
        if serial == 'Y14' and sp_name.startswith('卡带切换'):
            cooldown = int((passive_rules.get('cartridge') or {}).get('cooldown', 3) or 3)

        skills_wiki.append({
            'name': sp_name,
            'timing': _TIMING_LABELS.get(str(sp.get('timing', '2')), str(sp.get('timing', '主动作'))),
            'phase': phase,
            'phase_label': phase_label,
            'mp_cost': sp.get('消耗mp', 0),
            'range': eff_range,
            'cooldown': cooldown,
            'summary': _summarize_wiki_spell_effects(effs),
        })

    return {
        'serial': serial,
        'name': meta['name'],
        'cost': meta['cost'],
        'pool_count': POOL_COUNTS[meta['cost']],
        'role': meta['role'],
        'traits': list(meta['traits']),
        'range': meta['range'],
        'tag': meta['tag'],
        'blurb': meta['blurb'],
        'mov': mov,
        'tactical_move': tactical_move,
        'main_actions': main_actions,
        'dex': dex,
        'dodge': base_dodge,
        'can_block': can_block,
        'block_val': block_val,
        'flying': flying,
        'tuning_notes': tuning_notes,
        'star_stats': star_stats,
        'basic_attack': {
            'skill_name': best_skill_name,
            'skill_val': best_skill_val,
            'dice': str_attrs.get('伤害值') or '1d4',
            'pierce': bool(attrs.get('伤害贯穿')),
        },
        'passives': _build_wiki_passives(passive_rules),
        'skills': skills_wiki,
    }


def catalog_summary():
    """Return UI-friendly catalog metadata dictionary."""
    return {
        'units': sorted(UNIT_CATALOG.values(), key=lambda u: (u['cost'], u['serial'])),
        'wiki_units': {s: build_unit_wiki(s) for s in sorted(UNIT_CATALOG, key=lambda x: int(x[1:]))},
        'synergies': list(SYNERGIES.values()),
        'augments': AUGMENTS,
        'levels': LEVEL_TABLE,
        'pool_counts': POOL_COUNTS,
        'pve_waves': PVE_WAVES,
        'star_scaling': STAR_SCALING,
        'range_overrides': AUTOCHESS_RANGE_OVERRIDES,
    }
