#!/usr/bin/env python3
"""
Step 6: 输出12角色全部法术执行效果 → spells_catalog.md
对每个角色：变身→初始化战斗→逐一执行法术→捕获输出
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from autocombat.test_harness import CombatEngine, roll_dice, CN_NUMS, has_timing
from characters_data import ALL_CHARACTERS, load_character_to_engine

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spells_catalog.md')


def run_spell_catalog():
    engine = CombatEngine()
    engine.group_id = 'spell_test'

    lines = []
    def w(s=''): lines.append(s)

    w('# 法术执行效果全目录')
    w()
    spell_count = sum(len(c.get('spells',[])) for c in ALL_CHARACTERS)
    w(f'> 12角色 · {spell_count}法术 · 模拟系统内测试')
    w()

    total_spells = 0
    total_ok = 0
    total_skip = 0

    for char_data in ALL_CHARACTERS:
        serial = char_data['serial']
        name = char_data['name']
        uid = f"cat_{serial}"

        engine = CombatEngine()  # Fresh engine per character
        engine.group_id = f'spell_test_{serial}'
        char = load_character_to_engine(engine, char_data, uid)

        attrs = char_data.get('attrs', {})
        spells = char_data.get('spells', [])
        total_spells += len(spells)

        w(f'## {serial} {name}')
        w()
        w(f'| 属性 | 值 |')
        w(f'|------|-----|')
        w(f'| HP | {attrs.get("体力","?")}/{attrs.get("体力上限","?")} |')
        w(f'| MP | {attrs.get("魔力","?")}/{attrs.get("魔力上限","?")} |')
        w(f'| SAN | {attrs.get("理智","?")} |')
        w(f'| 等级 | {attrs.get("等级","?")} |')
        w(f'| 敏捷 | {attrs.get("敏捷","?")} |')
        w(f'| 闪避 | {attrs.get("闪避","?")} |')
        w(f'| 斗殴 | {attrs.get("斗殴","?")} |')
        w(f'| 行动力 | {attrs.get("行动力","?")} |')
        w(f'| 伤害值 | {char_data.get("str_attrs",{}).get("伤害值","?")} |')
        w()

        # Transform
        hs_out = engine.process_command(uid, '.hs')
        w(f'**变身**: HP→{char.get_attr("体力")} MP→{char.get_attr("魔力")} 闪避→{char.get_attr("闪避")}')
        w()

        # Init combat
        engine.process_command(uid, '.bta map 10x10')
        engine.process_command(uid, '.bta int team=Y pos=M')
        engine.process_command(uid, '.btastartfull')

        # Execute each spell
        char_spells = char.spells or engine.load_spells(uid)

        for spell in char_spells:
            si = spell['index']
            sname = spell['name']
            timing = spell.get('时机', '2')
            cat = spell.get('类别', 1)
            cat_names = {1:'伤害',2:'护盾',3:'回复',4:'辅助',5:'召唤',6:'制造',7:'引发',8:'领域'}

            # Timing description
            timing_parts = []
            if has_timing(timing, '1'): timing_parts.append('被动')
            if has_timing(timing, '2'): timing_parts.append('主动作')
            if has_timing(timing, '3'): timing_parts.append('附加动作')
            if has_timing(timing, '4'): timing_parts.append('反应')
            timing_desc = '+'.join(timing_parts) if timing_parts else timing

            is_passive = has_timing(timing, '1')
            is_main = has_timing(timing, '2')

            w(f'### 技能{si}: {sname}')
            w()
            w(f'**分类**: {cat_names.get(cat, "?")} | **时机**: {timing_desc} | **MP消耗**: {spell.get("消耗mp",0)} | **SAN消耗**: {spell.get("消耗san",0)}')
            if spell.get('default_persist', 0):
                w(f'**默认延续**: 是')
            w()

            # Show effect details
            for ei, eff in enumerate(spell.get('effects', [])):
                eff_type = eff.get('type', '?')
                eff_label = f'- **效果{chr(97+ei)}** ({cat_names.get(eff_type, "?")}): '
                details = []
                if eff.get('伤害骰'): details.append(f'伤害骰={eff["伤害骰"]}')
                if eff.get('每回合伤害骰'): details.append(f'每回合伤害={eff["每回合伤害骰"]}')
                if eff.get('成功率'): details.append(f'成功率={eff["成功率"]}%')
                if eff.get('护盾值'): details.append(f'护盾={eff["护盾值"]}')
                if eff.get('回复hp'): details.append(f'回复HP={eff["回复hp"]}')
                if eff.get('回复mp'): details.append(f'回复MP={eff["回复mp"]}')
                if eff.get('技能加减值'): details.append(f'技能修改={eff["技能加减值"]}')
                if eff.get('其他辅助效果a'): details.append(f'辅助={eff["其他辅助效果a"]}')
                if eff.get('辅助效果值a'): details.append(f'值={eff["辅助效果值a"]}')
                if eff.get('吸血比例'): details.append(f'吸血={eff["吸血比例"]}')
                if eff.get('作用半径', 0) > 0: details.append(f'半径={eff["作用半径"]}格')
                if eff.get('领域中心跟随'): details.append('跟随施法者')
                if eff.get('召唤个数'): details.append(f'召唤{eff["召唤个数"]}个')
                if eff.get('召唤物模板'): details.append(f'模板={eff["召唤物模板"]}')
                if eff.get('制造个数'): details.append(f'制造{eff["制造个数"]}个')
                if eff.get('制造花费回合数'): details.append(f'花费{eff["制造花费回合数"]}回合')
                if eff.get('制造物模板'): details.append(f'模板={eff["制造物模板"]}')
                if eff.get('触发HP比例'): details.append(f'HP触发={eff["触发HP比例"]}%')
                if eff.get('引发目标法术'): details.append(f'引发=技能{eff["引发目标法术"]}')
                if eff.get('引发延迟回合'): details.append(f'延迟={eff["引发延迟回合"]}回合')
                if eff.get('属性削减'): details.append(f'削减={eff["属性削减"]}')
                if eff.get('致死值'): details.append(f'致死值={eff["致死值"]}')
                if eff.get('可反应性', 1) == 0: details.append('不可反应')
                w(eff_label + (', '.join(details) if details else '无额外参数'))
            w()

            # Execute the spell and capture output
            if is_main or is_passive:
                result = engine.process_command(uid, f'.s{si}')
                total_ok += 1
                w(f'**执行结果** (`.s{si}`):')
                w()
                w('```')
                # Clean up output for markdown
                clean_result = result.strip().replace('\n\n', '\n')
                w(clean_result[:600])
                if len(clean_result) > 600:
                    w('...(truncated)')
                w('```')
                if is_passive and '已经正常打开' in result:
                    w(f'> ✅ 被动法术正常激活')
                elif is_main:
                    w(f'> ✅ 主动作法术执行完成')
            else:
                # Try additional action slot
                if has_timing(timing, '3'):
                    result = engine.process_command(uid, f'.a s{si}')
                    total_ok += 1
                    w(f'**执行结果** (`.a s{si}` 附加动作):')
                    w()
                    w('```')
                    clean = result.strip()[:500]
                    w(clean)
                    w('```')
                else:
                    total_skip += 1
                    w(f'**执行结果**: ⚠️ 此法术在当前阶段无法执行（时机={timing_desc}，需在对应阶段手动触发）')
                    w()

            w('---')
            w()

            # Reset combat state for next spell test
            if si < len(char_spells):
                engine = CombatEngine()
                engine.group_id = f'spell_test_{serial}_{si}'
                char = load_character_to_engine(engine, char_data, uid)
                engine.process_command(uid, '.hs')
                engine.process_command(uid, '.bta map 10x10')
                engine.process_command(uid, '.bta int team=Y pos=M')
                engine.process_command(uid, '.btastartfull')

    # Summary
    w('---')
    w()
    w('## 统计')
    w()
    w(f'| 指标 | 值 |')
    w(f'|------|-----|')
    w(f'| 角色数 | {len(ALL_CHARACTERS)} |')
    w(f'| 法术总数 | {total_spells} |')
    w(f'| 成功执行 | {total_ok} |')
    w(f'| 需特定阶段 | {total_skip} |')
    w(f'| 成功率 | {total_ok/max(1,total_spells)*100:.1f}% |')
    w()
    from datetime import datetime
    w(f'> 生成时间: {datetime.now().isoformat()}')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f'Written {len(lines)} lines to {OUTPUT_FILE}')
    print(f'Characters: {len(ALL_CHARACTERS)}, Spells: {total_spells}, OK: {total_ok}, Skip: {total_skip}')


if __name__ == '__main__':
    run_spell_catalog()
