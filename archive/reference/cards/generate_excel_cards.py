#!/usr/bin/env python3
"""
Generate 12 Excel character cards from COC7空白卡CY23Final-紫.xlsx template.
- Clears existing sample spells from 法术表 before filling
- Places .st command at the very bottom of 简化卡 (sheet2)
"""

import os, sys, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from characters_data import ALL_CHARACTERS, CN_NUMS, CAT_LETTERS, SUMMON_TEMPLATES

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        'COC7空白卡CY23Final-紫.xlsx')
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

EFFECT_VALUE_FIELDS = {
    1: {'伤害骰': 'B', '成功率': 'C', '成功率奖惩骰': 'D', '可反应性': 'E', '可贯穿性': 'F',
        '致死值': 'G', '致死值优劣': 'H', '附加效果': 'I', '附加效果时长': 'J'},
    2: {'护盾值': 'B', '持续回合': 'C'},
    3: {'回复hp': 'B', '回复san': 'C', '回复mp': 'D'},
    4: {'技能加减值': 'B', '其他辅助效果a': 'C', '辅助效果值a': 'D'},
    5: {'召唤个数': 'B', '召唤物模板': 'C', '持续回合': 'D'},
    6: {'制造个数': 'B', '制造花费回合数': 'C', '制造物模板': 'D'},
    7: {'引发延迟回合': 'B', '引发目标法术': 'C'},
    8: {'每回合伤害骰': 'B', '回复hp': 'C', '回复mp': 'D', '作用半径': 'E'},
}

CAT_DROPDOWN = {1:'1伤害', 2:'2护盾', 3:'3回复', 4:'4辅助', 5:'5召唤', 6:'6制造', 7:'7引发', 8:'8领域'}

SPELL_START_ROWS = [15, 31, 47, 63, 79]  # 5 spell slots, 16 rows each


def safe_write(ws, cell_ref, value):
    """Write to cell, handling merged cells by unmerging first."""
    try:
        ws[cell_ref] = value
    except Exception:
        try:
            for mr in list(ws.merged_cells.ranges):
                if cell_ref in mr:
                    ws.unmerge_cells(str(mr))
                    break
            ws[cell_ref] = value
        except Exception:
            pass


def clear_spell_area(ws):
    """Clear all sample spell data from rows 15-93, preserving IF formulas in headers."""
    for row in range(15, 94):
        for col in range(1, 13):  # A-L
            cell = ws.cell(row=row, column=col)
            if cell.value is None:
                continue
            # Preserve formula cells (IF headers that auto-populate based on category)
            if isinstance(cell.value, str) and cell.value.startswith('='):
                continue
            # Clear everything else (data, text labels, merged name cells)
            try:
                cell.value = None
            except Exception:
                pass


def fill_spell_sheet(ws, char_data):
    """Clear samples and fill 法术表 with character spells."""
    clear_spell_area(ws)
    spells = char_data.get('spells', [])

    for slot_idx, spell in enumerate(spells[:5]):
        base_row = SPELL_START_ROWS[slot_idx]

        # Spell name
        safe_write(ws, f'A{base_row}', f'{char_data["serial"]} {spell["name"]}')

        # Data row (base_row + 2): MP/SAN/duration/chant/persist
        dr = base_row + 2
        mp = spell.get('消耗mp', 0)
        san = spell.get('消耗san', 0)
        if mp > 0: safe_write(ws, f'G{dr}', mp)
        if san > 0: safe_write(ws, f'H{dr}', san)
        if spell.get('default_persist', 0): safe_write(ws, f'L{dr}', 1)
        safe_write(ws, f'A{dr}', spell.get('timing', '2'))

        # Effect categories
        for ei, eff in enumerate(spell.get('effects', [])[:6]):
            cat_type = eff.get('type', 1)
            cd_row = base_row + 4 + ei * 2  # category data row

            safe_write(ws, f'A{cd_row}', CAT_DROPDOWN.get(cat_type, ''))
            safe_write(ws, f'K{cd_row}', eff.get('客体', 4))

            field_map = EFFECT_VALUE_FIELDS.get(cat_type, {})
            for key, col in field_map.items():
                val = eff.get(key)
                if val is not None and val != '' and val != 0:
                    safe_write(ws, f'{col}{cd_row}', val)

            # Additional effect fields
            if eff.get('每回合伤害骰'):
                safe_write(ws, f'B{cd_row}', eff['每回合伤害骰'])
            if eff.get('吸血比例'):
                safe_write(ws, f'D{cd_row}', eff['吸血比例'])

        # 熟练度 + 简介
        safe_write(ws, f'B{base_row + 13}', 0)
        safe_write(ws, f'B{base_row + 14}', f'{char_data["serial"]} {spell["name"]}')


def fill_character_sheet(ws, char_data):
    """Fill 人物卡 with basic char info."""
    attrs = char_data.get('attrs', {})
    str_attrs = char_data.get('str_attrs', {})

    safe_write(ws, 'C3', f'{char_data["serial"]} {char_data["name"]}')
    safe_write(ws, 'C4', '魔法少女')

    hp = attrs.get('体力', 10)
    hp_max = attrs.get('体力上限', hp)
    mp = attrs.get('魔力', 10)
    mp_max = attrs.get('魔力上限', mp)
    san = attrs.get('理智', 50)

    safe_write(ws, 'C10', f'{hp}/{hp_max}')
    safe_write(ws, 'L10', san)
    safe_write(ws, 'U10', f'{mp}/{mp_max}')

    safe_write(ws, 'J29', attrs.get('闪避', 25))
    safe_write(ws, 'J34', attrs.get('斗殴', 25))
    safe_write(ws, 'C6', attrs.get('等级', 1))

    # Magic girl stats block below weapon table
    mg = [
        f'=== {char_data["serial"]} {char_data["name"]} 魔法少女 ===',
        f'等级:{attrs.get("等级",1)} MOV:{attrs.get("行动力",8)} 行动数:{attrs.get("回合行动数",1)}',
        f'伤害值:{str_attrs.get("伤害值","1d4")} 贯穿:{attrs.get("伤害贯穿",1)}',
        f'力量{attrs.get("力量",50)} 体质{attrs.get("体质",50)} 体型{attrs.get("体型",50)}',
        f'敏捷{attrs.get("敏捷",50)} 外貌{attrs.get("外貌",50)} 智力{attrs.get("智力",50)} 意志{attrs.get("意志",50)}',
        f'',
        f'=== 法术 ({len(char_data.get("spells",[]))}个) ===',
    ]
    for si, s in enumerate(char_data.get('spells', []), 1):
        cn = {1:'伤害',2:'护盾',3:'回复',4:'辅助',5:'召唤',6:'制造',7:'引发',8:'领域'}
        cat = s.get('category', 1)
        mg.append(f'  技能{si}: {s["name"]} [{cn.get(cat,"?")}] MP:{s.get("消耗mp",0)}')

    for i, line in enumerate(mg):
        safe_write(ws, f'B{55 + i}', line)


def build_st_command(char_data):
    """Build the full .st command string including summon templates."""
    parts = []
    for k, v in char_data.get('attrs', {}).items():
        parts.append(f"{k}{v}")
    for k, v in char_data.get('str_attrs', {}).items():
        parts.append(f'{k}="{v}"')

    # Summon templates
    summon_names = set()
    for spell in char_data.get('spells', []):
        for eff in spell.get('effects', []):
            tmpl = eff.get('召唤物模板', '')
            if tmpl and tmpl in SUMMON_TEMPLATES:
                summon_names.add(tmpl)
    for ti, tmpl_name in enumerate(sorted(summon_names), 1):
        tmpl = SUMMON_TEMPLATES[tmpl_name]
        st_prefix = f"召唤物模板{CN_NUMS[ti]}"
        parts.append(f'{st_prefix}名称="{tmpl_name}"')
        for k in ['HP','MP','SAN','STR','CON','SIZ','DEX','APP','INT','POW','EDU',
                  '闪避','MOV','行动次数','可反击','可反应']:
            if k in tmpl:
                parts.append(f'{st_prefix}{k}{tmpl[k]}')
        for si, sk in enumerate(tmpl.get('skills', []), 1):
            parts.append(f'{st_prefix}技能{si}="{sk}"')

    # Spells
    for si, spell in enumerate(char_data.get('spells', []), 1):
        prefix = f"技能{CN_NUMS[si]}"
        parts.append(f'{prefix}名称="{spell["name"]}"')
        parts.append(f'{prefix}时机="{spell.get("timing", "2")}"')
        parts.append(f'{prefix}类别{spell.get("category", 1)}')
        if spell.get('消耗mp', 0) > 0:
            parts.append(f'{prefix}消耗mp{spell.get("消耗mp", 0)}')
        if spell.get('消耗san', 0) > 0:
            parts.append(f'{prefix}消耗san{spell.get("消耗san", 0)}')
        if spell.get('default_persist', 0):
            parts.append(f'{prefix}默认延续性1')
        if spell.get('吟唱回合', 0) > 0:
            parts.append(f'{prefix}吟唱回合{spell.get("吟唱回合", 0)}')
        for ei, eff in enumerate(spell.get('effects', [])):
            letter = CAT_LETTERS[ei]
            pl = f"{prefix}类别{letter}"
            for k, v in eff.items():
                if k == 'type': continue
                if isinstance(v, int):
                    parts.append(f"{pl}{k}{v}")
                elif isinstance(v, str) and v:
                    parts.append(f'{pl}{k}="{v}"')
    return '.st ' + ''.join(parts)


def find_last_row(ws):
    """Find the last used row in a worksheet."""
    last = 1
    for row in ws.iter_rows(max_col=ws.max_column):
        for cell in row:
            if cell.value is not None:
                last = max(last, cell.row)
    return last


def generate_cards():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for char_data in ALL_CHARACTERS:
        serial = char_data['serial']
        name = char_data['name']
        filepath = os.path.join(OUTPUT_DIR, f'{serial}_{name}.xlsx')

        shutil.copy2(TEMPLATE, filepath)
        wb = load_workbook(filepath)

        fill_character_sheet(wb['人物卡'], char_data)
        fill_spell_sheet(wb['法术表'], char_data)

        # .st command at the very bottom of 简化卡 (sheet2)
        st_cmd = build_st_command(char_data)
        ws2 = wb['简化卡 骰娘导入']
        last_row = max(find_last_row(ws2), 50)
        start_row = last_row + 3

        safe_write(ws2, f'B{start_row}', f'=== {serial} {name} .st 一键录卡 ===')
        # Split long .st commands into readable chunks
        chunk_size = 500
        for ci in range(0, len(st_cmd), chunk_size):
            chunk = st_cmd[ci:ci + chunk_size]
            safe_write(ws2, f'B{start_row + 1 + ci // chunk_size}', chunk)

        wb.save(filepath)
        spells_n = len(char_data.get('spells', []))
        print(f'  [{serial}] {name}: {spells_n} spells, .st at row {start_row}')

    print(f'\n12 cards in {OUTPUT_DIR}')


if __name__ == '__main__':
    generate_cards()
