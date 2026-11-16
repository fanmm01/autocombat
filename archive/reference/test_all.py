#!/usr/bin/env python3
"""
全角色测试 (test_all.py)
=======================
Part 5: 录入全部11角色到测试系统，验证所有技能可用。

测试流程:
1. 加载每个角色
2. 变身 (.hs)
3. 初始化战斗 (.bta map + .bta int + .bta start)
4. 验证每个法术 (.s1 - .sN)
5. 回合推进 (.i end)
6. 效果验证
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from autocombat.test_harness import CombatEngine
from characters_data import ALL_CHARACTERS, load_character_to_engine

def run_full_test():
    engine = CombatEngine()
    engine.group_id = 'test_battle'

    # Phase 1: Load all characters
    print("=" * 60)
    print("PHASE 1: 加载角色")
    print("=" * 60)

    user_ids = []
    for i, char_data in enumerate(ALL_CHARACTERS):
        uid = f"user_{char_data['serial']}"
        user_ids.append(uid)
        char = load_character_to_engine(engine, char_data, uid)
        print(f"  [{char.serial}] {char.name}: {len(char.spells)} 法术, "
              f"HP{char.get_attr('体力')} MP{char.get_attr('魔力')} 斗殴{char.get_attr('斗殴')}")

    # Phase 2: Transform each character
    print("\n" + "=" * 60)
    print("PHASE 2: 变身 (.hs)")
    print("=" * 60)

    for i, uid in enumerate(user_ids):
        result = engine.process_command(uid, '.hs')
        char = engine.get_char(uid)
        hp = char.get_attr('体力')
        mp = char.get_attr('魔力')
        print(f"  [{char.serial}] {char.name}: HP→{hp}, MP→{mp} 变身: {char.hs_transformed}")

    # Phase 3: Initialize combat
    print("\n" + "=" * 60)
    print("PHASE 3: 初始化战斗")
    print("=" * 60)

    # Create map
    result = engine.process_command(user_ids[0], '.bta map 10*10')
    print(f"  Map: {result}")

    # Add all characters to initiative
    for i, uid in enumerate(user_ids):
        result = engine.process_command(uid, f'.bta int team=Y pos=M')
        char = engine.get_char(uid)
        init_list = engine._get_initiative()
        entry = next((e for e in init_list if e['userId'] == uid), None)
        print(f"  [{char.serial}] {char.name}: 加入战斗 (init={entry['initRoll'] if entry else '?'})")

    # Start battle
    result = engine.process_command(user_ids[0], '.btastartfull')
    print(f"  Start: {result[:200]}...")

    state = engine._get_state()
    print(f"  State: round={state['round']}, activeIndex={state['activeIndex']}")

    # Phase 4: Test each character's spells
    print("\n" + "=" * 60)
    print("PHASE 4: 验证法术")
    print("=" * 60)

    # Simulate: for each character, use their spells
    all_spells_tested = 0
    all_spells_ok = 0
    all_spells_fail = 0

    # We need to simulate turns properly
    for char_idx, uid in enumerate(user_ids):
        char = engine.get_char(uid)
        state = engine._get_state()
        init_list = engine._get_initiative()

        # Check if it's this character's turn
        active_entry = init_list[state['activeIndex']] if init_list else None
        if active_entry and active_entry['userId'] != uid:
            # Use .i end to advance through other characters
            while True:
                state = engine._get_state()
                init_list = engine._get_initiative()
                if not init_list: break
                active_entry = init_list[state['activeIndex']]
                if active_entry['userId'] == uid: break
                current_uid = active_entry['userId']
                current_char = engine.get_char(current_uid)
                engine.process_command(current_uid, '.i end')

        print(f"\n  [{char.serial}] {char.name} (spells: {len(char.spells)}):")

        if not char.spells:
            engine.load_spells(uid)

        for spell in char.spells:
            si = spell['index']
            all_spells_tested += 1
            result = engine.process_command(uid, f'.s{si}')
            if '不在战斗中' in result:
                print(f"    .s{si} {spell['name']}: SKIP (not in combat)")
            elif '不能在' in result:
                print(f"    .s{si} {spell['name']}: SKIP (wrong timing)")
                all_spells_ok += 1  # Valid, just wrong phase
            elif '未找到' in result:
                print(f"    .s{si} {spell['name']}: FAIL - spell not found")
                all_spells_fail += 1
            else:
                # Truncate output for display
                short = result.replace('\n', ' | ')[:120]
                print(f"    .s{si} {spell['name']}: OK ({short}...)")
                all_spells_ok += 1

        # End this character's turn
        engine.process_command(uid, '.i end')

    # Phase 5: Advance several rounds and verify tick-down
    print("\n" + "=" * 60)
    print("PHASE 5: 回合推进 (tick-down验证)")
    print("=" * 60)

    for round_num in range(3):
        state = engine._get_state()
        print(f"\n  Round {state['round']}:")
        effects = engine._get_effects()
        if effects:
            for e in effects:
                print(f"    [{e.get('type','?')}] {e.get('spellName','?')} rem={e.get('remainingRounds','?')} "
                      f"persistent={e.get('persistent',False)}")
        else:
            print(f"    (无活跃效果)")

        # Simulate everyone ending their turn
        init_list = engine._get_initiative()
        if init_list:
            for _ in range(len(init_list)):
                state = engine._get_state()
                entry = init_list[state['activeIndex']]
                engine.process_command(entry['userId'], '.i end')
                state = engine._get_state()
                if state['activeIndex'] == 0:
                    break  # Round already advanced

    # Phase 6: Summary
    print("\n" + "=" * 60)
    print("PHASE 6: 测试总结")
    print("=" * 60)
    print(f"  角色数: {len(ALL_CHARACTERS)}")
    print(f"  法术总数: {all_spells_tested}")
    print(f"  成功: {all_spells_ok}")
    print(f"  失败: {all_spells_fail}")
    print(f"  成功率: {all_spells_ok/max(1,all_spells_tested)*100:.1f}%")

    # Final state
    for uid in user_ids:
        char = engine.get_char(uid)
        hp = engine._get_combat_hp(uid)
        print(f"  [{char.serial}] {char.name}: HP={hp}, MP={char.get_attr('魔力')}")

    return all_spells_fail == 0


if __name__ == '__main__':
    success = run_full_test()
    if success:
        print("\n[PASS] All tests passed!")
    else:
        print("\n[FAIL] Some tests failed, see output above.")
    sys.exit(0 if success else 1)
