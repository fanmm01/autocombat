#!/usr/bin/env python3
"""
生成12个角色卡 .st 命令文件
输出到 autocombat/reference/cards/
每个文件包含完整的一次性 .st 录卡命令
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from characters_data import ALL_CHARACTERS, CN_NUMS, CAT_LETTERS, SUMMON_TEMPLATES

OUTPUT_DIR = os.path.dirname(__file__)  # reference/cards/

def build_st_command(char_data: dict) -> str:
    """Build the full .st command string for a character."""
    parts = []

    # Add all integer attributes
    for k, v in char_data.get('attrs', {}).items():
        parts.append(f"{k}{v}")

    # Add all string attributes
    for k, v in char_data.get('str_attrs', {}).items():
        parts.append(f'{k}="{v}"')

    # Add spells
    for si, spell in enumerate(char_data.get('spells', []), 1):
        prefix = f"技能{CN_NUMS[si]}"

        # Spell name
        parts.append(f'{prefix}名称="{spell["name"]}"')

        # Timing (string)
        parts.append(f'{prefix}时机="{spell.get("timing", "2")}"')

        # Category
        parts.append(f'{prefix}类别{spell.get("category", 1)}')

        # MP/SAN cost
        mp_cost = spell.get('消耗mp', 0)
        if mp_cost > 0:
            parts.append(f'{prefix}消耗mp{mp_cost}')
        san_cost = spell.get('消耗san', 0)
        if san_cost > 0:
            parts.append(f'{prefix}消耗san{san_cost}')

        # 默认延续性
        if spell.get('default_persist', 0):
            parts.append(f'{prefix}默认延续性1')

        # 吟唱回合
        chant = spell.get('吟唱回合', 0)
        if chant > 0:
            parts.append(f'{prefix}吟唱回合{chant}')

        # Effects (categories a-f)
        for ei, eff in enumerate(spell.get('effects', [])):
            letter = CAT_LETTERS[ei]
            pl = f"{prefix}类别{letter}"

            for k, v in eff.items():
                if k == 'type':
                    continue  # type is inferred, not stored
                if isinstance(v, int):
                    parts.append(f"{pl}{k}{v}")
                elif isinstance(v, str) and v:
                    parts.append(f'{pl}{k}="{v}"')

    # Add summon template data
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

    return '.st ' + ''.join(parts)


def generate_all_cards():
    """Generate 12 .st command files + summary cards."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for i, char_data in enumerate(ALL_CHARACTERS):
        serial = char_data['serial']
        name = char_data['name']
        filename = f"{serial}_{name}.st.txt"

        # Build .st command
        st_cmd = build_st_command(char_data)

        # Build human-readable summary
        attrs = char_data.get('attrs', {})
        summary = f"""角色卡: {serial} {name}
{'=' * 50}
属性:
  HP: {attrs.get('体力', '?')}/{attrs.get('体力上限', '?')}  MP: {attrs.get('魔力', '?')}/{attrs.get('魔力上限', '?')}
  SAN: {attrs.get('理智', '?')}  等级: {attrs.get('等级', '?')}
  敏捷: {attrs.get('敏捷', '?')}  闪避: {attrs.get('闪避', '?')}  行动力: {attrs.get('行动力', '?')}
  斗殴: {attrs.get('斗殴', '?')}  体格: {attrs.get('体格', '?')}
  力量{attrs.get('力量','?')} 体质{attrs.get('体质','?')} 体型{attrs.get('体型','?')}
  外貌{attrs.get('外貌','?')} 智力{attrs.get('智力','?')} 意志{attrs.get('意志','?')}
  DB: {attrs.get('体格', 0)} → dmg_bonus

法术 ({len(char_data.get('spells', []))}个):
"""
        for si, spell in enumerate(char_data.get('spells', []), 1):
            timing_str = spell.get('timing', '2')
            timing_names = {'1': '被动', '2': '主动作', '3': '附加动作', '4': '反应',
                           '23': '主动作+附加动作', '12': '被动+主动作'}
            cat_types = {1: '伤害', 2: '护盾', 3: '回复', 4: '辅助', 5: '召唤', 6: '制造', 7: '引发', 8: '领域'}
            summary += f"  技能{si}: {spell['name']} [{timing_names.get(timing_str, timing_str)} | {cat_types.get(spell.get('category','?'), '?')}]\n"
            for ei, eff in enumerate(spell.get('effects', [])):
                details = []
                if eff.get('伤害骰'): details.append(f"伤害{eff['伤害骰']}")
                if eff.get('每回合伤害骰'): details.append(f"DOT{eff['每回合伤害骰']}")
                if eff.get('护盾值'): details.append(f"护盾{eff['护盾值']}")
                if eff.get('回复hp'): details.append(f"回复HP{eff['回复hp']}")
                if eff.get('回复mp'): details.append(f"回复MP{eff['回复mp']}")
                if eff.get('技能加减值'): details.append(f"修改{eff['技能加减值']}")
                if eff.get('吸血比例'): details.append(f"吸血{eff['吸血比例']}")
                if eff.get('成功率'): details.append(f"成功率{eff['成功率']}%")
                if eff.get('作用半径', 0) > 0: details.append(f"半径{eff['作用半径']}")
                if eff.get('领域中心跟随'): details.append("跟随中心")
                if details:
                    summary += f"    效果{ei+1}: {', '.join(details)}\n"
                else:
                    summary += f"    效果{ei+1}: {cat_types.get(eff.get('type','?'), '?')}\n"

        summary += f"""
一键录卡 (.st 命令):
{st_cmd[:200]}...
[完整命令见下方，共 {len(st_cmd)} 字符]
"""

        # Write file
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(summary)
            f.write('\n\n')
            f.write('=' * 50)
            f.write('\n.st 命令 (复制到骰子机器人):\n')
            f.write('=' * 50)
            f.write('\n')
            f.write(st_cmd)
            f.write('\n')

        print(f"  [{serial}] {name}: {filepath} ({len(st_cmd)} chars, {len(char_data.get('spells', []))} spells)")

    # Generate combined batch file
    batch_path = os.path.join(OUTPUT_DIR, '_all_characters.st.txt')
    with open(batch_path, 'w', encoding='utf-8') as f:
        f.write("=== 12角色批量录卡命令 ===\n\n")
        f.write("每个角色的 .st 命令请分别发送到对应的QQ号。\n")
        f.write("使用 .as <序号> 绑定后，用 .stc 带前缀录入。\n\n")
        for char_data in ALL_CHARACTERS:
            f.write(f"\n--- {char_data['serial']} {char_data['name']} ---\n")
            f.write(build_st_command(char_data))
            f.write('\n')
    print(f"\n  Batch file: {batch_path}")


if __name__ == '__main__':
    generate_all_cards()
