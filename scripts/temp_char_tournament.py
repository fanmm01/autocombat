#!/usr/bin/env python3
"""CLI developer tool: define a temporary character in memory and run tournament rounds."""

import argparse
import contextlib
import copy
import io
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND_DIR = os.path.join(ROOT, 'backend')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
_py_parts = [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p]
if BACKEND_DIR not in _py_parts:
    os.environ['PYTHONPATH'] = os.pathsep.join([BACKEND_DIR, *_py_parts])
os.environ.setdefault('AUTOCOMBAT_NO_FILE_LOG', '1')

from battle_engine import AUX_NAME_TO_CODE, CAT_LETTERS, CN_NUMS, CombatEngine  # noqa: E402
from characters_data import (  # noqa: E402
    ALL_CHARACTERS,
    ITEM_TEMPLATES,
    SUMMON_TEMPLATES,
    load_character_to_engine,
)
from combat_defaults import DEFAULTS as SETTING_DEFAULTS  # noqa: E402
from combat_settings import settings_scope  # noqa: E402
from sim_parallel import parallel_session  # noqa: E402
from skill_identity import identify_skills, validate_global_skill_ids  # noqa: E402
import ai_battle  # noqa: E402

MODES = ('1v1', '2v2', '3v3')
VALID_EFFECT_TYPES = frozenset((*range(1, 15), 17, 18, 19))
SERIAL_RE = re.compile(r'^[A-Z][A-Z0-9_]{0,31}$')
MAP_RE = re.compile(r'^(?:[8-9]|1[0-6])x(?:[8-9]|1[0-6])$')

DEFAULT_ATTRS = {
    '等级': 1,
    '体力': 10,
    '体力上限': 10,
    '魔力': 10,
    '魔力上限': 10,
    '行动力': 8,
    '额外行动数': 0,
    '敏捷': 50,
    '闪避': 50,
    '体格': 0,
    '斗殴': 50,
    '伤害贯穿': 1,
    '可反击': 1,
    '力量': 50,
    '体质': 50,
    '体型': 50,
    '外貌': 50,
    '教育': 50,
    '智力': 50,
    '意志': 50,
    '幸运': 50,
    '理智': 50,
    '状态': 60,
    '魔法少女序号': 999,
}
DEFAULT_STR_ATTRS = {'伤害值': '1d6'}

ATTR_ALIASES = {
    'LV': '等级',
    'LEVEL': '等级',
    'HP': '体力',
    'MAX_HP': '体力上限',
    'MAXHP': '体力上限',
    'MP': '魔力',
    'MAX_MP': '魔力上限',
    'MAXMP': '魔力上限',
    'MOV': '行动力',
    'EXTRA_ACTIONS': '额外行动数',
    'DEX': '敏捷',
    'DODGE': '闪避',
    'BUILD': '体格',
    'BRAWL': '斗殴',
    'PIERCE': '伤害贯穿',
    'COUNTERABLE': '可反击',
    'STR': '力量',
    'CON': '体质',
    'SIZ': '体型',
    'APP': '外貌',
    'EDU': '教育',
    'INT': '智力',
    'POW': '意志',
    'LUCK': '幸运',
    'SAN': '理智',
    'STATUS': '状态',
    'FLYING': '飞行',
    'UNTARGETABLE': '不可指定',
    'BLOCK': '格挡',
    'BLOCKABLE': '可格挡',
    'REACTABLE': '可反应',
    'SWORD': '剑',
}

STR_ATTR_ALIASES = {
    'DMG': '伤害值',
    'DAMAGE': '伤害值',
}

SPELL_KEY_ALIASES = {
    'mp': '消耗mp',
    'san': '消耗san',
    'persist': 'default_persist',
    'chant': '吟唱回合',
    'cd': 'cooldown_rounds',
    'cooldown': 'cooldown_rounds',
    'once': '_once_per_battle',
}

SPELL_INT_OR_STR_KEYS = {'消耗mp', '消耗san', 'charge_moon'}
SPELL_INT_KEYS = {
    'category', 'phase', 'default_persist', '吟唱回合', 'cooldown_rounds',
    'cost_blood_ml', 'cost_hp_pct_current', 'cost_mp_pct_max',
    'cost_mp_pct_current', 'cost_counter_amount', 'chant_interrupt_hp_pct',
    'chant_interrupt_mp_pct', 'on_kill_heal_hp', 'on_kill_heal_san',
    'on_kill_blood_ml', 'blood_per_hit_ml', 'chain_on_blood_ml',
    'extra_attack_per_blood', 'blood_ml_per_hp', 'heal_limit_not_dying',
}
SPELL_BOOL_KEYS = {'_once_per_battle', 'chant_interruptible', 'prep_free'}
SPELL_STR_KEYS = {
    'name', 'timing', '_mp_formula', '_mp_formula_transformed',
    'weapon_required', 'cost_counter_type', 'blood_kind',
    'cost_hp_dice', 'mp_cost_formula', 'skill_id',
}
SPELL_JSON_KEYS = {'counter_required'}
ALL_SPELL_KEYS = (
    SPELL_INT_OR_STR_KEYS | SPELL_INT_KEYS | SPELL_BOOL_KEYS
    | SPELL_STR_KEYS | SPELL_JSON_KEYS
)

EFFECT_KEY_ALIASES = {
    'target': '客体',
    'dmg': '伤害骰',
    'damage': '伤害骰',
    'hit': '成功率',
    'rate': '成功率',
    'range': '射程',
    'shield': '护盾值',
    'heal_hp': '回复hp',
    'heal_mp': '回复mp',
    'heal_san': '回复san',
    'duration': '持续回合',
    'radius': '作用半径',
    'dodgeable': '可闪避性',
    'counterable': '可反击性',
    'blockable': '可格挡性',
    'pierce': '可贯穿性',
    'pierceable': '可贯穿性',
    'bp': '成功率奖惩骰',
    'dot': '每回合伤害骰',
    'lifesteal': '吸血比例',
    'aux': '辅助效果',
    'aux_val': '辅助效果值',
    'summon': '召唤物模板',
    'summon_count': '召唤个数',
    'item': '制造物模板',
    'item_count': '制造个数',
    'skill_mod': '技能加减值',
    'attr_debuff': '属性削减',
    'follow': '领域中心跟随',
    'ignore_bp': '忽略全局奖惩骰',
}

EFFECT_STRICT_STR_KEYS = {
    '伤害骰', '附加效果', '护盾值', '回复hp', '回复san', '回复mp',
    '技能加减值', '辅助效果', '辅助效果值', '其他辅助效果a', '辅助效果值a',
    '召唤物模板', '制造物模板', '每回合伤害骰', '吸血比例', '属性削减',
    '友方行为', '友方伤害骰', '友方延迟回复骰', '友方延迟回复公式',
    '敌方回复', '敌方回复骰', 'ignite_dmg_dice', 'on_enter_attr_debuff',
    'variant', 'weapon_state', 'counter_type', 'linked_summon',
    'turn_mp_refund', 'damage_table', 'mp_cost_formula', '制造分发',
    '复活召唤物主人政策', '消费追加回复hp', 'tasteBonusOwnerSerial',
}
EFFECT_INT_OR_STR_KEYS = {
    '客体', '持续回合', '吟唱回合', '召唤个数', '制造个数',
    '制造花费回合数', 'charge_moon',
}
EFFECT_FLOAT_KEYS = {
    'on_enter_mp_drain_pct', 'on_enter_trigger_rate',
    'damage_pct_caster_max_hp', 'damage_pct_target_max_hp',
    'damage_pct_caster_cur_hp', 'damage_mp_multiplier',
    'damage_moon_mult', 'shield_absorb_moon_ratio',
    '复活回复比例', '触发HP比例',
}
EFFECT_BOOL_KEYS = {'ignite'}
EFFECT_JSON_KEYS = {
    'hp_thresholds', 'exclude', 'eject_phases', 'on_enter_zone_damage',
    'hp_threshold_grant', '分发给总数公式', '分发人数覆盖', '分发削减顺序',
}

DEFAULT_TARGET_BY_TYPE = {
    1: 4,
    2: 1,
    3: 12,
    4: 1,
    5: 1,
    6: 1,
    8: 45,
}


def _parse_int(raw, label):
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} 需要整数，收到: {raw!r}') from exc


def _parse_number(raw, label):
    s = str(raw).strip()
    if re.fullmatch(r'[+-]?\d+', s):
        return int(s)
    try:
        val = float(s)
        if not (val == val and abs(val) != float('inf')):
            raise ValueError
        return val
    except ValueError as exc:
        raise ValueError(f'{label} 需要数字，收到: {raw!r}') from exc


def _parse_bool(raw, label):
    s = str(raw).strip().lower()
    if s in ('1', 'true', 'yes', 'y', 'on'):
        return True
    if s in ('0', 'false', 'no', 'n', 'off'):
        return False
    raise ValueError(f'{label} 需要布尔值，收到: {raw!r}')


def _parse_int_or_str(raw):
    s = str(raw).strip()
    if re.fullmatch(r'[+-]?\d+', s):
        return int(s)
    return s


def _split_kv_pairs(raw, allow_semicolon_sep=True):
    """Split k=v pairs without breaking values that contain semicolons or commas."""
    text = raw.strip()
    if not text:
        return []
    pattern = r'[,;，；]\s*(?=[^,;，；=]+=)' if allow_semicolon_sep else r'[,，]\s*(?=[^,，=]+=)'
    parts = re.split(pattern, text)
    pairs = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '=' not in part:
            raise ValueError(f'无效的键值对 {part!r}，应为 KEY=VALUE')
        k, v = part.split('=', 1)
        k, v = k.strip(), v.strip()
        if not k:
            raise ValueError(f'键值对缺少键名: {part!r}')
        pairs.append((k, v))
    return pairs


def resolve_attr_key(key):
    return ATTR_ALIASES.get(key.upper(), key)


def resolve_str_attr_key(key):
    return STR_ATTR_ALIASES.get(key.upper(), key)


def apply_attr_overrides(attrs, updates, explicit_keys):
    """Merge numeric attribute overrides and sync HP/MP max if not explicitly given."""
    for raw_k, raw_v in updates.items():
        k = resolve_attr_key(str(raw_k).strip())
        if isinstance(raw_v, bool):
            attrs[k] = 1 if raw_v else 0
        elif isinstance(raw_v, (int, float)):
            attrs[k] = raw_v
        else:
            attrs[k] = _parse_number(raw_v, f'属性 {k}')
        explicit_keys.add(k)
    if '体力' in explicit_keys and '体力上限' not in explicit_keys:
        attrs['体力上限'] = attrs['体力']
    if '魔力' in explicit_keys and '魔力上限' not in explicit_keys:
        attrs['魔力上限'] = attrs['魔力']


def _infer_effect_type(eff):
    if '伤害骰' in eff:
        return 1
    if '护盾值' in eff:
        return 2
    if any(k in eff for k in ('回复hp', '回复mp', '回复san')):
        return 3
    if '召唤物模板' in eff or '召唤个数' in eff:
        return 5
    if '制造物模板' in eff or '制造个数' in eff:
        return 6
    if '作用半径' in eff or '领域中心跟随' in eff or '每回合伤害骰' in eff:
        return 8
    if any(k in eff for k in ('技能加减值', '属性削减', '辅助效果', '其他辅助效果a')):
        return 4
    return None


def _coerce_spell_field(key, raw_val):
    if key in SPELL_INT_OR_STR_KEYS:
        return _parse_int_or_str(raw_val)
    if key in SPELL_INT_KEYS:
        return _parse_int(raw_val, f'技能字段 {key}')
    if key in SPELL_BOOL_KEYS:
        return _parse_bool(raw_val, f'技能字段 {key}')
    if key in SPELL_JSON_KEYS:
        try:
            return json.loads(raw_val)
        except json.JSONDecodeError as exc:
            raise ValueError(f'技能字段 {key} JSON 解析失败: {exc}') from exc
    return str(raw_val)


def _coerce_effect_field(key, raw_val):
    if key in EFFECT_STRICT_STR_KEYS:
        return str(raw_val)
    if key in EFFECT_INT_OR_STR_KEYS:
        return _parse_int_or_str(raw_val)
    if key in EFFECT_FLOAT_KEYS:
        return float(_parse_number(raw_val, f'效果字段 {key}'))
    if key in EFFECT_BOOL_KEYS:
        return _parse_bool(raw_val, f'效果字段 {key}')
    if key in EFFECT_JSON_KEYS:
        try:
            return json.loads(raw_val)
        except json.JSONDecodeError as exc:
            raise ValueError(f'效果字段 {key} JSON 解析失败: {exc}') from exc
    s = str(raw_val).strip()
    if re.fullmatch(r'[+-]?\d+', s):
        return int(s)
    try:
        return float(s)
    except ValueError:
        return s


def parse_skill_spec(spec, fallback_index=1):
    """Parse a single --skill argument (JSON dict or k=v shorthand) into a spell dict."""
    stripped = spec.strip()
    if stripped.startswith('{'):
        try:
            spell = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f'--skill JSON 解析失败: {exc}') from exc
        if not isinstance(spell, dict):
            raise ValueError('--skill JSON 必须是对象')
        return spell

    pairs = _split_kv_pairs(stripped, allow_semicolon_sep=False)
    if not pairs:
        raise ValueError('--skill 不能为空')

    spell = {}
    effect = {}
    for raw_k, raw_v in pairs:
        sk = SPELL_KEY_ALIASES.get(raw_k.lower(), raw_k)
        if sk in ALL_SPELL_KEYS:
            spell[sk] = _coerce_spell_field(sk, raw_v)
            continue
        ek = EFFECT_KEY_ALIASES.get(raw_k.lower(), raw_k)
        effect[ek] = _coerce_effect_field(ek, raw_v)

    if 'type' not in effect:
        inferred = _infer_effect_type(effect)
        if inferred is None:
            raise ValueError(f'--skill 缺少效果类型 type（且无法自动推断）: {spec!r}')
        effect['type'] = inferred

    eff_type = effect['type']
    if '客体' not in effect:
        effect['客体'] = DEFAULT_TARGET_BY_TYPE.get(eff_type, 1)
    if 'name' not in spell:
        spell['name'] = f'临时技能{fallback_index}'
    spell.setdefault('timing', '2')
    spell['timing'] = str(spell['timing'])
    if 'category' not in spell:
        spell['category'] = eff_type if 1 <= eff_type <= 8 else 9
    spell.setdefault('消耗mp', 0)
    spell['effects'] = [effect]
    return spell


def copy_skill_from_roster(spec):
    """Copy a skill from an existing ALL_CHARACTERS entry by SERIAL:INDEX_OR_NAME."""
    if ':' not in spec:
        raise ValueError(f'--copy-skill 格式应为 SERIAL:INDEX_OR_NAME，收到: {spec!r}')
    serial, target = spec.split(':', 1)
    serial = serial.strip()
    target = target.strip()
    base = next((c for c in ALL_CHARACTERS if c['serial'] == serial), None)
    if base is None:
        avail = ', '.join(c['serial'] for c in ALL_CHARACTERS)
        raise ValueError(f'--copy-skill 未找到角色 {serial!r}（可用: {avail}）')
    spells = base.get('spells', [])
    matched = None
    if target.isdigit():
        idx = int(target)
        matched = next((s for s in spells if s.get('skill_index') == idx), None)
        if matched is None and 1 <= idx <= len(spells):
            matched = spells[idx - 1]
    if matched is None:
        matched = next((s for s in spells if s.get('name') == target), None)
    if matched is None:
        avail_s = ', '.join(f"{s.get('skill_index')}:{s.get('name')}" for s in spells)
        raise ValueError(f'--copy-skill 在 {serial} 中未找到技能 {target!r}（可用: {avail_s}）')
    copied = copy.deepcopy(matched)
    copied.pop('skill_id', None)
    copied.pop('skill_index', None)
    return copied


def parse_item_spec(spec):
    if '=' in spec:
        name, cnt = spec.split('=', 1)
        count = _parse_int(cnt.strip(), f'物品 {name.strip()} 数量')
    else:
        name, count = spec, 1
    name = name.strip()
    if not name or count <= 0:
        raise ValueError(f'无效物品配置: {spec!r}')
    return {'item': name, 'count': count}


def _strip_spell_identities(char_data):
    char_data['next_skill_index'] = 1
    for spell in char_data.get('spells', []):
        spell.pop('skill_id', None)
        spell.pop('skill_index', None)


def build_temp_character(args, stdin_text=None):
    """Build and normalize an in-memory character dict strictly from CLI inputs."""
    base_char = None
    if args.base:
        base_char = next((c for c in ALL_CHARACTERS if c['serial'] == args.base), None)
        if base_char is None:
            avail = ', '.join(c['serial'] for c in ALL_CHARACTERS)
            raise ValueError(f'--base 未找到角色 {args.base!r}（可用: {avail}）')

    json_char = None
    if args.char_json is not None:
        raw_json = stdin_text if args.char_json == '-' else args.char_json
        if args.char_json == '-' and raw_json is None:
            raw_json = sys.stdin.read()
        try:
            json_char = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f'--char-json JSON 解析失败: {exc}') from exc
        if not isinstance(json_char, dict):
            raise ValueError('--char-json 必须是 JSON 对象')

    if base_char is not None:
        char = copy.deepcopy(base_char)
    elif json_char is not None:
        char = {
            'name': '临时角色',
            'serial': 'TMP1',
            'attrs': copy.deepcopy(DEFAULT_ATTRS),
            'str_attrs': copy.deepcopy(DEFAULT_STR_ATTRS),
            'inventory': [],
            'spells': [],
        }
    else:
        char = {
            'name': '临时角色',
            'serial': 'TMP1',
            'attrs': copy.deepcopy(DEFAULT_ATTRS),
            'str_attrs': copy.deepcopy(DEFAULT_STR_ATTRS),
            'inventory': [],
            'spells': [],
        }

    if json_char is not None:
        for k, v in json_char.items():
            if k in ('attrs', 'str_attrs') and isinstance(v, dict):
                if k == 'attrs':
                    explicit_json = set()
                    apply_attr_overrides(char['attrs'], v, explicit_json)
                else:
                    char['str_attrs'].update({str(sk): str(sv) for sk, sv in v.items()})
            else:
                char[k] = copy.deepcopy(v)

    if args.serial is not None:
        char['serial'] = args.serial.strip()
    elif json_char is not None and 'serial' in json_char:
        char['serial'] = str(json_char['serial']).strip()
    else:
        char['serial'] = 'TMP1'

    if args.name is not None:
        char['name'] = args.name
    elif json_char is not None and 'name' in json_char:
        char['name'] = str(json_char['name'])
    elif base_char is not None:
        char['name'] = base_char['name'] if char['serial'] == base_char['serial'] else f"{base_char['name']}(临时)"
    else:
        char['name'] = '临时角色'

    if base_char is not None and char['serial'] != base_char['serial']:
        _strip_spell_identities(char)
    elif json_char is not None and char['serial'] != json_char.get('serial'):
        _strip_spell_identities(char)

    if args.pre_transformed:
        char['pre_transformed'] = True
    if args.initial_weapon is not None:
        char['initial_weapon'] = args.initial_weapon
    if args.initial_phase is not None:
        char['initial_phase'] = args.initial_phase
    if args.initial_blood is not None:
        char['初始血液'] = args.initial_blood

    explicit_attr_keys = set()
    if args.attrs_json:
        try:
            attrs_obj = json.loads(args.attrs_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f'--attrs-json 解析失败: {exc}') from exc
        if not isinstance(attrs_obj, dict):
            raise ValueError('--attrs-json 必须是 JSON 对象')
        apply_attr_overrides(char['attrs'], attrs_obj, explicit_attr_keys)

    for raw_attr in args.attr:
        pairs = _split_kv_pairs(raw_attr, allow_semicolon_sep=True)
        apply_attr_overrides(char['attrs'], dict(pairs), explicit_attr_keys)

    if args.str_attrs_json:
        try:
            sa_obj = json.loads(args.str_attrs_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f'--str-attrs-json 解析失败: {exc}') from exc
        if not isinstance(sa_obj, dict):
            raise ValueError('--str-attrs-json 必须是 JSON 对象')
        for k, v in sa_obj.items():
            char['str_attrs'][resolve_str_attr_key(str(k).strip())] = str(v)

    for raw_sa in args.str_attr:
        for k, v in _split_kv_pairs(raw_sa, allow_semicolon_sep=False):
            char['str_attrs'][resolve_str_attr_key(k)] = v

    if args.damage is not None:
        char['str_attrs']['伤害值'] = args.damage.strip()

    if args.clear_skills:
        char['spells'] = []
        char['next_skill_index'] = 1

    for copy_spec in args.copy_skill:
        char['spells'].append(copy_skill_from_roster(copy_spec))

    for skill_spec in args.skill:
        char['spells'].append(parse_skill_spec(skill_spec, fallback_index=len(char['spells']) + 1))

    if args.spells_json:
        try:
            extra_spells = json.loads(args.spells_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f'--spells-json 解析失败: {exc}') from exc
        if not isinstance(extra_spells, list) or any(not isinstance(s, dict) for s in extra_spells):
            raise ValueError('--spells-json 必须是技能对象数组')
        for sp in extra_spells:
            sp_copy = copy.deepcopy(sp)
            if sp_copy.get('skill_id') and not str(sp_copy['skill_id']).startswith(char['serial'] + '-'):
                sp_copy.pop('skill_id', None)
                sp_copy.pop('skill_index', None)
            char['spells'].append(sp_copy)

    if args.inventory_json:
        try:
            inv = json.loads(args.inventory_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f'--inventory-json 解析失败: {exc}') from exc
        if not isinstance(inv, list):
            raise ValueError('--inventory-json 必须是数组')
        char['inventory'].extend(copy.deepcopy(inv))

    for item_spec in args.item:
        char['inventory'].append(parse_item_spec(item_spec))

    return identify_skills(char)


def effective_roster(temp_char, replace=False):
    existing_serials = {c['serial'] for c in ALL_CHARACTERS}
    serial = temp_char['serial']
    if serial in existing_serials and not replace:
        raise ValueError(
            f'角色编号 {serial!r} 已存在于预设名单中；如需替换请加 --replace，或使用其他 --serial'
        )
    roster = [temp_char if c['serial'] == serial else c for c in ALL_CHARACTERS]
    if serial not in existing_serials:
        roster.append(temp_char)
    return roster


def validate_temp_character(temp_char, replace=False):
    """Validate character schema, skill IDs, templates, and engine loading."""
    if not isinstance(temp_char, dict) or not temp_char.get('name') or not isinstance(temp_char.get('serial'), str):
        raise ValueError('角色必须有非空名称和字符串编号')
    if not SERIAL_RE.fullmatch(temp_char['serial']):
        raise ValueError(f"角色编号格式无效 {temp_char['serial']!r}（需匹配 [A-Z][A-Z0-9_]{{0,31}}）")
    attrs = temp_char.get('attrs')
    if not isinstance(attrs, dict) or any(type(v) not in (int, float, bool) for v in attrs.values()):
        raise ValueError('attrs 必须为字典，且所有值必须为数字')
    str_attrs = temp_char.get('str_attrs')
    if not isinstance(str_attrs, dict) or not str_attrs.get('伤害值'):
        raise ValueError('str_attrs 必须包含非空 伤害值')

    active_spells = [s for s in temp_char.get('spells', []) if not s.get('_disabled', False)]
    if len(active_spells) >= len(CN_NUMS):
        raise ValueError(f'技能数量不能超过 {len(CN_NUMS) - 1} 个')

    for spell in active_spells:
        if not spell.get('name'):
            raise ValueError('每个技能必须有 name')
        effects = spell.get('effects', [])
        if not isinstance(effects, list):
            raise ValueError(f"技能 {spell['name']} 的 effects 必须为列表")
        active_effects = [e for e in effects if not e.get('_disabled', False)]
        if len(active_effects) > len(CAT_LETTERS):
            raise ValueError(f"技能 {spell['name']} 的效果数量不能超过 {len(CAT_LETTERS)} 个")
        for eff in active_effects:
            if type(eff.get('type')) is not int or eff['type'] not in VALID_EFFECT_TYPES:
                raise ValueError(f"技能 {spell['name']} 包含无效效果类型 type={eff.get('type')!r}")
            summon_tmpl = eff.get('召唤物模板')
            if summon_tmpl and summon_tmpl not in SUMMON_TEMPLATES:
                raise ValueError(f"技能 {spell['name']} 引用了不存在的召唤物模板 {summon_tmpl!r}")
            item_tmpl = eff.get('制造物模板')
            if item_tmpl and item_tmpl not in ITEM_TEMPLATES:
                raise ValueError(f"技能 {spell['name']} 引用了不存在的制造物模板 {item_tmpl!r}")

    for inv in temp_char.get('inventory', []):
        iname = inv.get('item', '')
        if iname and iname not in ITEM_TEMPLATES:
            raise ValueError(f'物品栏引用了不存在的物品模板 {iname!r}')

    roster = effective_roster(temp_char, replace=replace)
    validate_global_skill_ids(roster)

    eng = CombatEngine()
    load_character_to_engine(eng, temp_char, 'validation')
    if not temp_char.get('pre_transformed'):
        eng.process_command('validation', '.hs')
    return roster


def parse_formats(raw_list):
    picked = []
    for raw in raw_list:
        parts = [p.strip().lower() for p in re.split(r'[,+;/\s]+', raw) if p.strip()]
        if not parts:
            raise ValueError('--format 不能为空')
        for p in parts:
            if p in ('all', '*'):
                picked.extend(MODES)
            elif p in MODES:
                picked.append(p)
            else:
                raise ValueError(f'不支持的赛制 {p!r}，可用: 1v1, 2v2, 3v3, all')
    return [m for m in MODES if m in set(picked)]


def _parse_team_list(raw, team_size, valid_serials, flag_name):
    teams = []
    for entry in raw.split(','):
        entry = entry.strip()
        if not entry:
            continue
        members = [m.strip() for m in re.split(r'[\s+]+', entry) if m.strip()]
        if len(members) != team_size:
            raise ValueError(f'{flag_name} 中队伍 {entry!r} 需要恰好 {team_size} 名成员')
        if len(set(members)) != len(members):
            raise ValueError(f'{flag_name} 中队伍 {entry!r} 包含重复角色')
        unknown = [m for m in members if m not in valid_serials]
        if unknown:
            raise ValueError(f'{flag_name} 中存在未知角色: {", ".join(unknown)}')
        teams.append(members)
    return teams


def _augment_team_table(base_teams, custom_teams, auto_count, team_size, temp_serial, roster, seed_val):
    teams = [list(t) for t in base_teams if all(s in {c['serial'] for c in roster} for s in t)]
    seen = {tuple(sorted(t)) for t in teams}
    for team in custom_teams:
        ident = tuple(sorted(team))
        if ident not in seen:
            teams.append(list(team))
            seen.add(ident)

    has_temp = any(temp_serial in t for t in teams)
    if not has_temp and not custom_teams and auto_count > 0:
        partners = [c['serial'] for c in roster if c['serial'] != temp_serial]
        rng = random.Random(seed_val + team_size * 1009)
        if team_size == 2:
            candidates = [[temp_serial, p] for p in partners]
        else:
            import itertools
            candidates = [[temp_serial, a, b] for a, b in itertools.combinations(partners, 2)]
        rng.shuffle(candidates)
        added = 0
        for cand in candidates:
            ident = tuple(sorted(cand))
            if ident not in seen:
                teams.append(cand)
                seen.add(ident)
                added += 1
                if added >= auto_count:
                    break
    return teams


def _is_valid_team_target(teams, rr_rounds, target, map_count):
    n = len(teams)
    if n <= 1:
        return True
    base = rr_rounds * (n - 1) * map_count
    deficits = [max(0, target - base) for _ in teams]
    return sum(deficits) % 2 == 0


def build_tournament_settings(args, modes, roster, temp_serial, seed_val):
    """Construct an in-memory settings dictionary for Tournament."""
    cfg = copy.deepcopy(SETTING_DEFAULTS)
    for k in list(cfg.keys()):
        if k.startswith('DELAY_'):
            cfg[k] = 0
    cfg['TOURNAMENT_EVENT_DELAY'] = 0
    cfg['DEFAULT_BATTLE_DELAY'] = 0
    cfg['DISPLAY_PRELIM'] = 0
    cfg['DISPLAY_KNOCKOUT'] = 0
    cfg['DISPLAY_CUSTOM'] = 0
    cfg['PRELIM_WORKERS'] = args.workers
    cfg['SEASON_AVG_STATUS'] = args.season

    if args.map:
        if not MAP_RE.fullmatch(args.map):
            raise ValueError(f'地图尺寸无效 {args.map!r}，格式需为 WxH（宽高 8-16，如 10x10）')
        cfg['DEFAULT_MAP_SIZE'] = args.map
        cfg['BONUS_MAP_SIZE'] = args.map
        cfg['KNOCKOUT_MAP_SIZE'] = args.map
        cfg['MAP_SIZES_2V2'] = [args.map]
        cfg['MAP_SIZES_3V3'] = [args.map]

    valid_serials = {c['serial'] for c in roster}
    custom_2v2 = _parse_team_list(args.teams_2v2, 2, valid_serials, '--teams-2v2') if args.teams_2v2 else []
    custom_3v3 = _parse_team_list(args.teams_3v3, 3, valid_serials, '--teams-3v3') if args.teams_3v3 else []

    if '2v2' in modes:
        cfg['TEAM_TABLES_2V2'] = _augment_team_table(
            cfg['TEAM_TABLES_2V2'], custom_2v2, args.auto_teams_2v2, 2, temp_serial, roster, seed_val
        )
    if '3v3' in modes:
        cfg['TEAM_TABLES_3V3'] = _augment_team_table(
            cfg['TEAM_TABLES_3V3'], custom_3v3, args.auto_teams_3v3, 3, temp_serial, roster, seed_val
        )

    if args.rr_rounds is not None:
        if args.rr_rounds <= 0:
            raise ValueError(f'--rr-rounds 必须 > 0，收到: {args.rr_rounds}')
        cfg['RR_ROUNDS_1V1'] = args.rr_rounds
        cfg['RR_ROUNDS_2V2'] = args.rr_rounds
        cfg['RR_ROUNDS_3V3'] = args.rr_rounds

    if args.target_matches is not None:
        if args.target_matches <= 0:
            raise ValueError(f'--target-matches 必须 > 0，收到: {args.target_matches}')
        for mode_name, key, maps_key in (('2v2', 'TEAM_TABLES_2V2', 'MAP_SIZES_2V2'), ('3v3', 'TEAM_TABLES_3V3', 'MAP_SIZES_3V3')):
            if mode_name in modes:
                rr_val = cfg['RR_ROUNDS_2V2'] if mode_name == '2v2' else cfg['RR_ROUNDS_3V3']
                teams = cfg[key]
                n_maps = len(cfg[maps_key])
                effective_rr = min(rr_val, args.target_matches // max(1, (len(teams) - 1) * n_maps))
                if not _is_valid_team_target(teams, effective_rr, args.target_matches, n_maps):
                    raise ValueError(
                        f'{mode_name} 共有 {len(teams)} 支队伍，无法精确调配每队 {args.target_matches} 场'
                        '（奇数队伍在单数赤字下总场次不能成对匹配，请改用偶数目标场数或增减队伍）'
                    )
        cfg['TARGET_1V1_MATCHES'] = args.target_matches
        cfg['TARGET_TEAM_MATCHES'] = args.target_matches
    elif args.rr_rounds is not None:
        if '1v1' in modes:
            cfg['TARGET_1V1_MATCHES'] = max(1, args.rr_rounds * max(1, len(roster) - 1))
        team_targets = []
        if '2v2' in modes and len(cfg['TEAM_TABLES_2V2']) > 1:
            team_targets.append(args.rr_rounds * (len(cfg['TEAM_TABLES_2V2']) - 1) * len(cfg['MAP_SIZES_2V2']))
        if '3v3' in modes and len(cfg['TEAM_TABLES_3V3']) > 1:
            team_targets.append(args.rr_rounds * (len(cfg['TEAM_TABLES_3V3']) - 1) * len(cfg['MAP_SIZES_3V3']))
        if team_targets:
            target_t = max(team_targets)
            while True:
                ok = True
                for mode_name, key, maps_key in (('2v2', 'TEAM_TABLES_2V2', 'MAP_SIZES_2V2'), ('3v3', 'TEAM_TABLES_3V3', 'MAP_SIZES_3V3')):
                    if mode_name in modes and len(cfg[key]) > 1:
                        n_maps = len(cfg[maps_key])
                        eff_rr = min(args.rr_rounds, target_t // max(1, (len(cfg[key]) - 1) * n_maps))
                        if not _is_valid_team_target(cfg[key], eff_rr, target_t, n_maps):
                            ok = False
                            break
                if ok:
                    break
                target_t += 1
            cfg['TARGET_TEAM_MATCHES'] = target_t

    return cfg


def display_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in text)


def pad_right(text, width):
    return text + ' ' * max(0, width - display_width(text))


def pad_left(text, width):
    return ' ' * max(0, width - display_width(text)) + text


def _team_serials_map(cfg, valid_serials):
    return {
        '2v2': [list(t) for t in cfg['TEAM_TABLES_2V2'] if all(s in valid_serials for s in t)],
        '3v3': [list(t) for t in cfg['TEAM_TABLES_3V3'] if all(s in valid_serials for s in t)],
    }


def run_temp_tournament(temp_char, roster, cfg, modes, rounds, seed_val, with_knockout=False, progress=None):
    """Execute 1..N tournament rounds in memory without writing files to disk."""
    temp_serial = temp_char['serial']
    name_map = {c['serial']: c['name'] for c in roster}
    serial_order = {c['serial']: i for i, c in enumerate(roster)}
    team_maps = _team_serials_map(cfg, set(name_map))

    prelim_totals = {mode: {} for mode in modes}
    overall = {c['serial']: {'wins': 0, 'battles': 0} for c in roster}
    h2h = {}
    total_matches = 0

    random.seed(seed_val)
    saved_level = ai_battle.logger.level
    ai_battle.logger.setLevel(logging.WARNING)
    t0 = time.monotonic()
    try:
        with settings_scope(cfg), parallel_session():
            for round_idx in range(1, rounds + 1):
                with contextlib.redirect_stdout(io.StringIO()):
                    t = ai_battle.Tournament(
                        tournament_type=1 if with_knockout else 0,
                        enabled_modes=list(modes),
                        settings=cfg,
                        extra_characters=[temp_char],
                    )
                    t.init_characters()
                    t.run_phases(write_results_flag=False)

                for mode in modes:
                    for _rank, key, pts, wins, battles, display in t._rankings_info.get(mode, []):
                        entry = prelim_totals[mode].get(key)
                        if entry is None:
                            members = [key] if mode == '1v1' else team_maps[mode][key]
                            prelim_totals[mode][key] = {
                                'key': key,
                                'display': display,
                                'members': members,
                                'pts': float(pts),
                                'wins': wins,
                                'battles': battles,
                                'is_temp': temp_serial in members,
                            }
                        else:
                            entry['pts'] += pts
                            entry['wins'] += wins
                            entry['battles'] += battles

                for a_str, b_str, winner, _rds, _ms, phase_label, _is_bo in t.results:
                    a_members = a_str.split('+')
                    b_members = b_str.split('+')
                    win_members = a_members if winner == a_str else b_members
                    for ch in a_members + b_members:
                        if ch not in overall:
                            overall[ch] = {'wins': 0, 'battles': 0}
                        overall[ch]['battles'] += 1
                    for ch in win_members:
                        overall[ch]['wins'] += 1

                    if len(a_members) == 1 and len(b_members) == 1:
                        ca, cb = a_members[0], b_members[0]
                        if ca == temp_serial and cb != temp_serial:
                            rec = h2h.setdefault(cb, {'wins': 0, 'battles': 0})
                            rec['battles'] += 1
                            if winner == a_str:
                                rec['wins'] += 1
                        elif cb == temp_serial and ca != temp_serial:
                            rec = h2h.setdefault(ca, {'wins': 0, 'battles': 0})
                            rec['battles'] += 1
                            if winner == b_str:
                                rec['wins'] += 1

                total_matches += len(t.results)
                if progress is not None:
                    progress(round_idx, rounds, len(t.results), time.monotonic() - t0)
    finally:
        ai_battle.logger.setLevel(saved_level)

    elapsed = time.monotonic() - t0

    standings_by_mode = {}
    for mode in modes:
        rows = []
        for entry in prelim_totals[mode].values():
            key = entry['key']
            avg_pts = entry['pts'] / rounds
            avg_wins = entry['wins'] / rounds
            avg_battles = entry['battles'] / rounds
            win_rate = (entry['wins'] / entry['battles'] * 100.0) if entry['battles'] else 0.0
            order = key if isinstance(key, int) else serial_order.get(key, len(serial_order))
            label = f'{key} {name_map.get(key, entry["display"])}' if mode == '1v1' else entry['display']
            rows.append({
                'rank': 0,
                'key': key,
                'label': label,
                'members': entry['members'],
                'avg_points': round(avg_pts, 4),
                'avg_wins': round(avg_wins, 4),
                'avg_battles': round(avg_battles, 4),
                'wins': entry['wins'],
                'battles': entry['battles'],
                'win_rate': round(win_rate, 2),
                'is_temp': entry['is_temp'],
                '_order': order,
            })
        rows.sort(key=lambda r: (-r['avg_points'], -r['avg_wins'], r['_order']))
        for idx, row in enumerate(rows, 1):
            row['rank'] = idx
            row.pop('_order', None)
        standings_by_mode[mode] = rows

    overall_rows = []
    for serial, st in overall.items():
        if st['battles'] == 0 and serial != temp_serial:
            continue
        wr = (st['wins'] / st['battles'] * 100.0) if st['battles'] else 0.0
        overall_rows.append({
            'rank': 0,
            'serial': serial,
            'name': name_map.get(serial, serial),
            'wins': st['wins'],
            'battles': st['battles'],
            'win_rate': round(wr, 2),
            'is_temp': serial == temp_serial,
            '_order': serial_order.get(serial, len(serial_order)),
        })
    overall_rows.sort(key=lambda r: (-r['win_rate'], -r['wins'], r['_order']))
    for idx, row in enumerate(overall_rows, 1):
        row['rank'] = idx
        row.pop('_order', None)

    h2h_rows = []
    for opp, st in h2h.items():
        wr = (st['wins'] / st['battles'] * 100.0) if st['battles'] else 0.0
        h2h_rows.append({
            'serial': opp,
            'name': name_map.get(opp, opp),
            'wins': st['wins'],
            'losses': st['battles'] - st['wins'],
            'battles': st['battles'],
            'win_rate': round(wr, 2),
            '_order': serial_order.get(opp, len(serial_order)),
        })
    h2h_rows.sort(key=lambda r: (-r['win_rate'], -r['wins'], r['_order']))
    for row in h2h_rows:
        row.pop('_order', None)

    return {
        'temp_character': {
            'serial': temp_char['serial'],
            'name': temp_char['name'],
            'attrs': temp_char['attrs'],
            'str_attrs': temp_char['str_attrs'],
            'spells': temp_char['spells'],
            'inventory': temp_char.get('inventory', []),
        },
        'meta': {
            'rounds': rounds,
            'modes': list(modes),
            'with_knockout': bool(with_knockout),
            'total_matches': total_matches,
            'elapsed_s': round(elapsed, 2),
            'workers': cfg['PRELIM_WORKERS'],
            'seed': seed_val,
            'season': cfg['SEASON_AVG_STATUS'],
        },
        'standings': standings_by_mode,
        'overall_win_rates': overall_rows,
        'h2h_1v1': h2h_rows,
    }


def render_win_rate_report(report_data, show_h2h=False):
    """Render CJK-aligned win-rate tables highlighting the temporary character."""
    meta = report_data['meta']
    tc = report_data['temp_character']
    temp_serial = tc['serial']
    season_str = '随机' if meta['season'] is None else str(meta['season'])
    spell_names = '、'.join(s['name'] for s in tc['spells']) or '无(仅普攻)'
    hp = tc['attrs'].get('体力', '?')
    hp_max = tc['attrs'].get('体力上限', '?')
    mp = tc['attrs'].get('魔力', '?')
    mp_max = tc['attrs'].get('魔力上限', '?')
    dmg = tc['str_attrs'].get('伤害值', '?')

    lines = [
        '=' * 78,
        f"  临时角色锦标赛胜率报告 — {meta['rounds']} 轮 ({', '.join(meta['modes'])})",
        '=' * 78,
        f"  临时角色: {temp_serial} {tc['name']}  HP {hp}/{hp_max}  MP {mp}/{mp_max}"
        f"  MOV {tc['attrs'].get('行动力', '?')}  闪避 {tc['attrs'].get('闪避', '?')}"
        f"  斗殴 {tc['attrs'].get('斗殴', '?')}  普攻 {dmg}",
        f"  技能组:   {spell_names}",
        f"  赛事配置: 总场次 {meta['total_matches']} | 淘汰赛={'开启' if meta['with_knockout'] else '关闭'}"
        f" | 耗时 {meta['elapsed_s']:.1f}s | workers={meta['workers']} | seed={meta['seed']} | 赛季={season_str}",
    ]

    for mode in meta['modes']:
        rows = report_data['standings'].get(mode, [])
        if not rows:
            continue
        label_w = max([16] + [display_width(r['label']) for r in rows]) + 2
        lines += [
            '',
            '=' * 78,
            f'  {mode} 预赛积分与胜率表（共 {len(rows)} 项）',
            '-' * 78,
            f"  {pad_left('排名', 4)}  {pad_right('角色/队伍', label_w)}"
            f"{pad_left('平均积分', 8)}  {pad_left('平均胜/场', 11)}  {pad_left('累计胜/场', 11)}  {pad_left('胜率', 7)}",
            '-' * 78,
        ]
        for r in rows:
            mark = '  <<< [临时角色]' if r['is_temp'] else ''
            avg_pts_s = f"{r['avg_points']:.1f}"
            avg_wb = f"{r['avg_wins']:.1f}/{r['avg_battles']:.1f}"
            tot_wb = f"{r['wins']}/{r['battles']}"
            wr_s = f"{r['win_rate']:.1f}%"
            lines.append(
                f"  {pad_left(str(r['rank']), 4)}  {pad_right(r['label'], label_w)}"
                f"{pad_left(avg_pts_s, 8)}  {pad_left(avg_wb, 11)}"
                f"  {pad_left(tot_wb, 11)}  {pad_left(wr_s, 7)}{mark}"
            )

    if len(meta['modes']) > 1 or meta['with_knockout']:
        overall = report_data['overall_win_rates']
        label_w = max([14] + [display_width(f"{r['serial']} {r['name']}") for r in overall]) + 2
        lines += [
            '',
            '=' * 78,
            '  全赛场综合胜率榜' + ('（含淘汰赛）' if meta['with_knockout'] else ''),
            '-' * 78,
            f"  {pad_left('排名', 4)}  {pad_right('角色', label_w)}"
            f"{pad_left('胜场', 6)}  {pad_left('总场', 6)}  {pad_left('胜率', 8)}",
            '-' * 78,
        ]
        for r in overall:
            mark = '  <<< [临时角色]' if r['is_temp'] else ''
            label = f"{r['serial']} {r['name']}"
            wr_s = f"{r['win_rate']:.1f}%"
            lines.append(
                f"  {pad_left(str(r['rank']), 4)}  {pad_right(label, label_w)}"
                f"{pad_left(str(r['wins']), 6)}  {pad_left(str(r['battles']), 6)}"
                f"  {pad_left(wr_s, 8)}{mark}"
            )

    if show_h2h and report_data['h2h_1v1']:
        h2h = report_data['h2h_1v1']
        label_w = max([14] + [display_width(f"{r['serial']} {r['name']}") for r in h2h]) + 2
        lines += [
            '',
            '=' * 78,
            f"  {temp_serial} {tc['name']} 1v1 对位胜率明细",
            '-' * 78,
            f"  {pad_right('对手', label_w)}{pad_left('胜-负', 9)}  {pad_left('场次', 6)}  {pad_left('胜率', 8)}",
            '-' * 78,
        ]
        for r in h2h:
            label = f"{r['serial']} {r['name']}"
            wl = f"{r['wins']}-{r['losses']}"
            wr_s = f"{r['win_rate']:.1f}%"
            lines.append(
                f"  {pad_right(label, label_w)}{pad_left(wl, 9)}  {pad_left(str(r['battles']), 6)}"
                f"  {pad_left(wr_s, 8)}"
            )

    lines.append('=' * 78)
    lines.append('')
    return '\n'.join(lines)


def render_schema_help():
    roster_str = ', '.join(f"{c['serial']}({c['name']})" for c in ALL_CHARACTERS)
    alias_str = ', '.join(f'{k}->{v}' for k, v in sorted(ATTR_ALIASES.items()))
    aux_str = ', '.join(sorted(AUX_NAME_TO_CODE))
    summons_str = ', '.join(sorted(SUMMON_TEMPLATES))
    items_str = ', '.join(sorted(ITEM_TEMPLATES))
    return '\n'.join([
        '=== 临时角色参数速查 ===',
        f'现有角色: {roster_str}',
        f'属性别名: {alias_str}',
        '默认属性: 等级=1, 体力/上限=10, 魔力/上限=10, 行动力=8, 额外行动数=0, 敏捷=50, 闪避=50, 斗殴=50, 状态=60, 伤害值=1d6',
        '技能简写: name=名称,mp=2,timing=2,type=1,客体=4,伤害骰=2d6+2,成功率=75,射程=8',
        '  常用效果类型 type: 1=伤害 2=护盾 3=恢复 4=增益/减益 5=召唤 6=制造 8=领域',
        '  常用目标码 客体: 1=自身 2=友方单体 3=其他友方全体 4=敌方单体 5=敌方群体 12=任意友方 13=自身+友方 45=敌方群体',
        '  常用技能别名: mp, san, persist, chant, cd, target, dmg, hit, range, shield, heal_hp, heal_mp, duration, radius, bp, dot, lifesteal, aux, aux_val, summon, summon_count, item, item_count, skill_mod, attr_debuff',
        f'可用 AUX 辅助效果: {aux_str}',
        f'可用召唤物模板: {summons_str}',
        f'可用制造物模板: {items_str}',
        '',
        '示例:',
        '  python scripts/temp_char_tournament.py --name 测试法师 --serial TMP1 \\',
        '    --attr "HP=11,MP=16,闪避=65,行动力=9" --damage 1d6+2 \\',
        '    --skill "name=星光弹,mp=2,type=1,客体=4,伤害骰=2d6+2,成功率=75,射程=8" \\',
        '    --skill "name=月华盾,mp=3,timing=23,type=2,客体=1,护盾值=2d6,持续回合=3" \\',
        '    --format 1v1 -n 1 --rr-rounds 1 --h2h',
    ])


def build_arg_parser():
    p = argparse.ArgumentParser(
        description='开发工具：从命令行输入临时角色属性与技能组（不读盘），运行1轮或多轮锦标赛并输出含它的胜率表。'
    )
    p.add_argument('--show-schema', action='store_true', help='输出可用属性别名、技能字段、模板与示例后退出')

    g_char = p.add_argument_group('临时角色定义（纯内存）')
    g_char.add_argument('--name', default=None, help='角色名称（默认：临时角色）')
    g_char.add_argument('--serial', default=None, help='角色编号，如 TMP1（默认：TMP1）')
    g_char.add_argument('--replace', action='store_true', help='允许覆盖同名预设编号（仅限本次内存运行）')
    g_char.add_argument('--base', default=None, help='基于现有角色编号在内存中复制模板后再覆盖参数（如 Y1）')
    g_char.add_argument('--char-json', default=None, help='完整角色 JSON 字符串，或传 - 从 stdin 读取')
    g_char.add_argument('--pre-transformed', action='store_true', help='以已变身状态入场')
    g_char.add_argument('--initial-weapon', choices=('staff', 'bow', 'sword'), default=None, help='初始武器')
    g_char.add_argument('--initial-phase', type=int, default=None, help='初始阶段号')
    g_char.add_argument('--initial-blood', type=int, default=None, help='初始血液 ml')

    g_attr = p.add_argument_group('属性配置')
    g_attr.add_argument('--attr', action='append', default=[], help='数值属性 KEY=VAL[,K2=V2...]（可重复，支持别名如 HP/MP/MOV/DEX）')
    g_attr.add_argument('--attrs-json', default=None, help='数值属性 JSON 字典')
    g_attr.add_argument('--damage', default=None, help='普攻伤害骰简写（等价于 --str-attr 伤害值=...）')
    g_attr.add_argument('--str-attr', action='append', default=[], help='字符串属性 KEY=VAL（可重复）')
    g_attr.add_argument('--str-attrs-json', default=None, help='字符串属性 JSON 字典')

    g_skill = p.add_argument_group('技能组与物品栏')
    g_skill.add_argument('--clear-skills', action='store_true', help='清空继承自 --base 或 --char-json 的技能列表')
    g_skill.add_argument('--copy-skill', action='append', default=[], help='从现有角色复制技能 SERIAL:INDEX_OR_NAME（可重复）')
    g_skill.add_argument('--skill', action='append', default=[], help='添加技能（k=v 简写或完整 JSON 对象，可重复）')
    g_skill.add_argument('--spells-json', default=None, help='技能数组 JSON 字符串')
    g_skill.add_argument('--item', action='append', default=[], help='初始物品 NAME[=COUNT]（可重复）')
    g_skill.add_argument('--inventory-json', default=None, help='物品栏 JSON 数组')

    g_tour = p.add_argument_group('锦标赛运行配置')
    g_tour.add_argument('-n', '--rounds', type=int, default=1, help='运行锦标赛轮数（默认 1）')
    g_tour.add_argument('--format', action='append', dest='formats', default=None,
                        help='赛制: 1v1, 2v2, 3v3, all（默认 1v1，支持逗号分隔或重复传参）')
    g_tour.add_argument('--workers', type=int, default=min(8, os.cpu_count() or 1), help='并行 worker 数 1-32')
    g_tour.add_argument('-s', '--seed', type=int, default=None, help='随机种子')
    g_tour.add_argument('--season', type=int, default=None, help='赛季平均状态 0-100（默认每轮随机）')
    g_tour.add_argument('-m', '--map', default=None, help='对战地图尺寸 WxH（如 10x10）')
    g_tour.add_argument('--rr-rounds', type=int, default=None, help='覆盖每赛制循环轮数（未传 --target-matches 时同步精简总场次）')
    g_tour.add_argument('--target-matches', type=int, default=None, help='覆盖每人/每队目标场次')
    g_tour.add_argument('--with-knockout', action='store_true', help='包含附加赛与淘汰赛阶段（默认为仅预赛）')
    g_tour.add_argument('--teams-2v2', default=None, help='追加 2v2 临时队伍，如 "TMP1+Y1,TMP1+Y6"')
    g_tour.add_argument('--teams-3v3', default=None, help='追加 3v3 临时队伍，如 "TMP1+Y1+Y2,TMP1+Y3+Y6"')
    g_tour.add_argument('--auto-teams-2v2', type=int, default=3, help='2v2 自动为临时角色配队数量（默认 3）')
    g_tour.add_argument('--auto-teams-3v3', type=int, default=5, help='3v3 自动为临时角色配队数量（默认 5）')

    g_out = p.add_argument_group('输出选项')
    g_out.add_argument('--h2h', action='store_true', help='附加输出临时角色 1v1 对各对手的对位胜率明细')
    g_out.add_argument('--json', action='store_true', help='以 JSON 格式输出胜率表及角色汇总')
    g_out.add_argument('--out', default=None, help='可选：仅在显式指定时将结果写入该路径')
    return p


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.show_schema:
        sys.stdout.write(render_schema_help() + '\n')
        return 0

    try:
        if args.rounds <= 0:
            raise ValueError(f'-n/--rounds 必须 > 0，收到: {args.rounds}')
        if not 1 <= args.workers <= 32:
            raise ValueError(f'--workers 必须在 1-32 之间，收到: {args.workers}')
        if args.season is not None and not 0 <= args.season <= 100:
            raise ValueError(f'--season 必须在 0-100 之间，收到: {args.season}')
        if args.auto_teams_2v2 < 0 or args.auto_teams_3v3 < 0:
            raise ValueError('--auto-teams-2v2 / --auto-teams-3v3 不能为负数')

        modes = parse_formats(args.formats or ['1v1'])
        seed_val = args.seed if args.seed is not None else random.randint(0, 99999)
        temp_char = build_temp_character(args)
        roster = validate_temp_character(temp_char, replace=args.replace)
        cfg = build_tournament_settings(args, modes, roster, temp_char['serial'], seed_val)
    except ValueError as exc:
        print(f'参数错误: {exc}', file=sys.stderr)
        return 2

    print(
        f"运行临时角色锦标赛: {temp_char['serial']} {temp_char['name']} | "
        f"轮数={args.rounds} | 赛制={','.join(modes)} | 淘汰赛={'开' if args.with_knockout else '关'} | "
        f"workers={args.workers} | seed={seed_val}",
        file=sys.stderr,
        flush=True,
    )

    def _on_progress(r_idx, total_r, matches_n, elapsed_s):
        print(
            f'  [{r_idx}/{total_r}] 完成: {matches_n} 场, 累计耗时 {elapsed_s:.1f}s',
            file=sys.stderr,
            flush=True,
        )

    report_data = run_temp_tournament(
        temp_char,
        roster,
        cfg,
        modes,
        args.rounds,
        seed_val,
        with_knockout=args.with_knockout,
        progress=_on_progress,
    )

    if args.json:
        output_text = json.dumps(report_data, ensure_ascii=False, indent=2) + '\n'
    else:
        output_text = render_win_rate_report(report_data, show_h2h=args.h2h)

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f'结果已写入: {args.out}', file=sys.stderr, flush=True)

    sys.stdout.write(output_text)
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('已取消', file=sys.stderr)
        raise SystemExit(130)
