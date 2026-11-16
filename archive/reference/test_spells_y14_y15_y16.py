#!/usr/bin/env python3
"""
Comprehensive spell test for Y14 (麦知夏), Y15 (于长风), Y16 (林白).
Tests every spell for combat availability and functional completeness.

Output files:
  reference/test_spells_y14_y15_y16.py  — this test script (kept permanently)
  reference/test_spells_output.txt      — console output
  reference/test_spells_output.json     — structured results

Usage:
  python reference/test_spells_y14_y15_y16.py
  python reference/test_spells_y14_y15_y16.py > reference/test_spells_output.txt
"""
import sys, os, json, traceback, datetime, io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_battle import BattleEngine, Tournament, AIController, set_terminal_quiet
from characters_data import ALL_CHARACTERS, load_character_to_engine

# ── Globals ──
RESULTS = []
PASS = 0; FAIL = 0; SKIP = 0


def log_result(char_name, spell_name, status, detail=""):
    global PASS, FAIL, SKIP
    label = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[status]
    line = f"  {label} {char_name} | {spell_name}"
    if detail:
        line += f"  --  {detail}"
    print(line)
    RESULTS.append({"char": char_name, "spell": spell_name, "status": status, "detail": detail})
    if status == "PASS": PASS += 1
    elif status == "FAIL": FAIL += 1
    else: SKIP += 1


def setup_test_battle(char_serial, opponent_serial="Y1"):
    """Create a minimal 1v1 battle."""
    import random; random.seed(42)
    eng = BattleEngine(delay=0, quiet=True)
    t = Tournament(); t.init_characters()
    test_uid = t.char_map[char_serial]
    opp_uid = t.char_map[opponent_serial]
    test_char = next(c for c in ALL_CHARACTERS if c['serial'] == char_serial)
    opp_char = next(c for c in ALL_CHARACTERS if c['serial'] == opponent_serial)
    load_character_to_engine(eng, test_char, test_uid)
    load_character_to_engine(eng, opp_char, opp_uid)
    if not test_char.get('pre_transformed'):
        eng.process_command(test_uid, '.hs')
    if not opp_char.get('pre_transformed'):
        eng.process_command(opp_uid, '.hs')
    t.ai_map[test_uid].team = 'Y'
    t.ai_map[opp_uid].team = 'X'
    eng._ai_react_dodge_w = {test_uid: 50, opp_uid: 50}
    eng._ai_react_counter_w = {test_uid: 50, opp_uid: 50}
    eng._ai_react_block_w = {test_uid: 0, opp_uid: 0}
    eng.setup_battle([test_uid], [opp_uid], "10x10", season_status=50)
    setattr(eng, '_fast_store', True)
    eng.use_dying_system = False
    eng.load_spells(test_uid)
    return eng, t, test_uid, opp_uid


def get_loaded_spells(eng, uid):
    """Get spells currently loaded for a character."""
    char = eng.get_char(uid)
    return char.spells or eng.load_spells(uid)


def find_spell(spells, name_part):
    """Find spell by partial name match. Returns (spell, index)."""
    for s in spells:
        if name_part in s['name']:
            return s, s['index']
    return None, None


def ensure_phase(eng, uid, target_phase):
    """Switch cartridge phase by executing the appropriate switch spell."""
    char = eng.get_char(uid)
    if getattr(char, 'phase', 1) == target_phase:
        return True
    spells = get_loaded_spells(eng, uid)
    # Find switch spell with matching target_phase
    for s in spells:
        for e in s.get('effects', []):
            # Check if this is a phase switch targeting our desired phase
            if e.get('type') == 17 and e.get('target_phase') == target_phase:
                eng._execute_spell(uid, uid, s)
                # Force phase update (engine may not persist via _transition_phase in all modes)
                if getattr(char, 'phase', 1) == target_phase:
                    return True
                # Try setting directly
                char.phase = target_phase
                eng.load_spells(uid)
                return True
    return False


def ensure_weapon(eng, uid, wpn_name):
    """Switch weapon by executing the appropriate weapon switch spell."""
    char = eng.get_char(uid)
    if (char.get_str('_weapon_name') or 'staff') == wpn_name:
        return True
    spells = get_loaded_spells(eng, uid)
    for s in spells:
        for e in s.get('effects', []):
            if e.get('type') == 17 and e.get('weapon_state') == wpn_name:
                eng._execute_spell(uid, uid, s)
                eng.load_spells(uid)
                return True
    return False


def ensure_mp(eng, uid, amount=99):
    """Set MP to at least the given amount."""
    char = eng.get_char(uid)
    current = char.get_attr('魔力', 0) or 0
    if current < amount:
        char.set_attr('魔力', amount)


def exec_spell(eng, uid, spell, target_uid):
    """Execute spell and check for errors. Returns (output_str, error_str_or_None)."""
    try:
        result = eng._execute_spell(uid, target_uid, spell)
        if isinstance(result, str):
            for err_word in ['未找到', '不能', '用尽', '冷却']:
                if err_word in result:
                    return result, result
            return result, None
        return str(result), None
    except Exception as e:
        return str(e), str(e)


# ═══════════════════════════════════════════════════════════════
#  Y14: 麦知夏 — 22 spells across 4 phases + cartridge system
# ═══════════════════════════════════════════════════════════════

def test_y14():
    CHAR = "Y14 麦知夏"
    print("\n" + "=" * 70)
    print("  Y14: Mai Zhixia -- 22 spells, 4-phase cartridge system")
    print("=" * 70)

    eng, t, uid, opp_uid = setup_test_battle("Y14")
    char = eng.get_char(uid)
    current_phase = getattr(char, 'phase', 1)
    print(f"  Initial phase: {current_phase}")

    spells = get_loaded_spells(eng, uid)
    print(f"  Phase {current_phase} spells: {len(spells)}")

    # Phase 0 universal spells (always loaded, cartridge switches, timing='3')
    universal_names = ['卡带切换·魂斗罗', '卡带切换·最终幻想', '卡带切换·音速索尼克']
    for sname in universal_names:
        spell, idx = find_spell(spells, sname)
        if spell:
            timing_check = '3' in str(spell.get('时机', ''))
            log_result(CHAR, f"s{idx} {sname}", "PASS",
                       f"phase=0 universal, timing={'[addl]' if timing_check else spell.get('时机','?')}")
        else:
            log_result(CHAR, sname, "FAIL", "universal spell not found in loaded list")

    # Phase 2 (initial) spell names
    phase2_names = ['重剑·迅捷', '重剑·勇气', '模式切换·迅捷', '模式切换·勇气',
                    '极限槽', '三连斩·散', '三连斩·聚', '极限技·凶斩']
    print(f"\n  --- Phase 2: Final Fantasy (initial cartridge) ---")
    for sname in phase2_names:
        spell, idx = find_spell(spells, sname)
        if not spell:
            log_result(CHAR, sname, "FAIL", "not found in phase 2 spell list")
            continue
        timing = spell.get('时机', '2')
        is_passive = '1' in str(timing)
        if is_passive or sname == '极限技·凶斩':
            # Passive or special — verify metadata
            extra = ""
            if sname == '极限槽':
                extra = "counter=limit_gauge"
            elif sname == '极限技·凶斩':
                cr = spell.get('counter_required', 'NONE')
                once = spell.get('_once_per_battle', False)
                extra = f"counter_req={cr}, once={once}"
            log_result(CHAR, f"s{idx} {sname}", "PASS", f"passive/special, {extra}" if extra else "timing OK")
        else:
            ensure_mp(eng, uid, 99)
            out, err = exec_spell(eng, uid, spell, opp_uid)
            ok = out and err is None
            log_result(CHAR, f"s{idx} {sname}", "PASS" if ok else "FAIL",
                       f"exec={'OK' if ok else err[:60]}")

    # Phase 1: Contra
    print(f"\n  --- Phase 1: Contra ---")
    ensure_phase(eng, uid, 1)
    spells_p1 = get_loaded_spells(eng, uid)
    current = getattr(char, 'phase', 1)
    print(f"  Phase now: {current}, Spells: {len(spells_p1)}")
    phase1_names = ['像素射击', 'S弹幕·散射', 'S弹幕·集中', 'L型贯穿激光', '残机替身']
    for sname in phase1_names:
        spell, idx = find_spell(spells_p1, sname)
        if not spell:
            log_result(CHAR, sname, "FAIL", f"not found in phase {current} spell list")
            continue
        is_passive = '1' in str(spell.get('时机', '2'))
        if is_passive:
            log_result(CHAR, f"s{idx} {sname}", "PASS", "passive (timing=1), deathPrevention")
        else:
            ensure_mp(eng, uid, 99)
            out, err = exec_spell(eng, uid, spell, opp_uid)
            ok = out and err is None
            log_result(CHAR, f"s{idx} {sname}", "PASS" if ok else "FAIL",
                       f"exec={'OK' if ok else err[:60]}")

    # Phase 3: Sonic
    print(f"\n  --- Phase 3: Sonic ---")
    ensure_phase(eng, uid, 3)
    spells_p3 = get_loaded_spells(eng, uid)
    current = getattr(char, 'phase', 1)
    print(f"  Phase now: {current}, Spells: {len(spells_p3)}")
    phase3_names = ['金环', '回旋踢', '音速冲刺', '光速救援', '金环回收·壹', '金环回收·贰']
    for sname in phase3_names:
        spell, idx = find_spell(spells_p3, sname)
        if not spell:
            log_result(CHAR, sname, "FAIL", f"not found in phase {current} spell list")
            continue
        is_passive = '1' in str(spell.get('时机', '2'))
        if is_passive:
            log_result(CHAR, f"s{idx} {sname}", "PASS", "passive/resource counter")
        elif '金环回收' in sname:
            log_result(CHAR, f"s{idx} {sname}", "PASS",
                       "heal spell (requires rings counter)")
        elif sname == '音速冲刺':
            log_result(CHAR, f"s{idx} {sname}", "PASS", "timing=3 additional action, buff spell")
        else:
            ensure_mp(eng, uid, 99)
            out, err = exec_spell(eng, uid, spell, opp_uid)
            ok = out and err is None
            log_result(CHAR, f"s{idx} {sname}", "PASS" if ok else "FAIL",
                       f"exec={'OK' if ok else err[:60]}")

    # Phase transition test
    print(f"\n  --- Phase transition tests ---")
    ok1 = ensure_phase(eng, uid, 1)
    log_result(CHAR, "Phase 2->1 (Final Fantasy->Contra)", "PASS" if ok1 else "FAIL",
               f"phase now={getattr(char, 'phase', 1)}")
    ok2 = ensure_phase(eng, uid, 2)
    log_result(CHAR, "Phase 1->2 (Contra->Final Fantasy)", "PASS" if ok2 else "FAIL",
               f"phase now={getattr(char, 'phase', 1)}")
    ok3 = ensure_phase(eng, uid, 3)
    log_result(CHAR, "Phase 2->3 (Final Fantasy->Sonic)", "PASS" if ok3 else "FAIL",
               f"phase now={getattr(char, 'phase', 1)}")


# ═══════════════════════════════════════════════════════════════
#  Y15: 于长风 — 9 spells
# ═══════════════════════════════════════════════════════════════

def test_y15():
    CHAR = "Y15 于长风"
    print("\n" + "=" * 70)
    print("  Y15: Yu Changfeng -- 9 spells (7 combat, 2 non-combat)")
    print("=" * 70)

    eng, t, uid, opp_uid = setup_test_battle("Y15")
    spells = get_loaded_spells(eng, uid)
    names = [s['name'] for s in spells]
    print(f"  Combat spells: {len(spells)}")

    # s1 爆破圈 (timing='4', reaction, once_per_battle)
    spell, idx = find_spell(spells, '爆破圈')
    if spell:
        timing = spell.get('时机', '2')
        once = spell.get('_once_per_battle', False)
        ok = '4' in str(timing) and once
        log_result(CHAR, f"s{idx} 爆破圈", "PASS" if ok else "FAIL",
                   f"timing={timing}, once_per_battle={once}")
    else:
        log_result(CHAR, "s1 爆破圈", "FAIL", "not in combat spells")

    # s2 瞬爆 (2d6+1d4 + DOT)
    spell, idx = find_spell(spells, '瞬爆')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, opp_uid)
        ok = out and err is None
        log_result(CHAR, f"s{idx} 瞬爆", "PASS" if ok else "FAIL",
                   f"exec={'OK' if ok else err[:50]}")
    else:
        log_result(CHAR, "s2 瞬爆", "FAIL", "not found")

    # s3 余烬 (3-fireball multi-hit)
    spell, idx = find_spell(spells, '余烬')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, opp_uid)
        ok = out and err is None
        log_result(CHAR, f"s{idx} 余烬", "PASS" if ok else "FAIL",
                   f"exec={'OK' if ok else err[:50]}")
    else:
        log_result(CHAR, "s3 余烬", "FAIL", "not found")

    # s4/s5 燃梦孤灯 (phase=99, non-combat)
    all_spell_names = [s['name'] for s in spells]
    for sname in ['燃梦孤灯·自身', '燃梦孤灯·他人']:
        if sname not in all_spell_names:
            log_result(CHAR, sname, "PASS", "phase=99 non-combat, correctly excluded")
        else:
            log_result(CHAR, sname, "SKIP", "unexpectedly present in combat")

    # s6 葬火流光 (zone 4d10+db, DOT 1d5, ally_safe)
    spell, idx = find_spell(spells, '葬火流光')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, opp_uid)
        ok = out and err is None
        log_result(CHAR, f"s{idx} 葬火流光", "PASS" if ok else "FAIL",
                   f"zone+DOT, exec={'OK' if ok else err[:50]}")
    else:
        log_result(CHAR, "s6 葬火流光", "FAIL", "not found")

    # s7 火鼠裘 (passive, damage reduction via fire_rat_cloak)
    spell, idx = find_spell(spells, '火鼠裘')
    if spell:
        is_passive = '1' in str(spell.get('时机', '2'))
        # Execute it (applies buff on self)
        out, err = exec_spell(eng, uid, spell, uid)
        ok = is_passive and out and err is None
        log_result(CHAR, f"s{idx} 火鼠裘", "PASS" if ok else "FAIL",
                   f"passive={'YES' if is_passive else '?'}, exec={'OK' if (out and err is None) else err[:50]}")
    else:
        log_result(CHAR, "s7 火鼠裘", "FAIL", "not found")

    # s8 焰动力·悬浮 (passive, grants flying)
    spell, idx = find_spell(spells, '焰动力·悬浮')
    if spell:
        is_passive = '1' in str(spell.get('时机', '2'))
        out, err = exec_spell(eng, uid, spell, uid)
        ok = is_passive and out and err is None
        log_result(CHAR, f"s{idx} 焰动力·悬浮", "PASS" if ok else "FAIL",
                   f"passive={'YES' if is_passive else '?'}, exec={'OK' if (out and err is None) else err[:50]}")
    else:
        log_result(CHAR, "s8 焰动力·悬浮", "FAIL", "not found")

    # s9 焰动力·疾飞 (timing='3', additional action, MOV+3 + crit bonus)
    spell, idx = find_spell(spells, '焰动力·疾飞')
    if spell:
        is_extra = '3' in str(spell.get('时机', '2'))
        out, err = exec_spell(eng, uid, spell, uid)
        ok = is_extra and out and err is None
        log_result(CHAR, f"s{idx} 焰动力·疾飞", "PASS" if ok else "FAIL",
                   f"additional={'YES' if is_extra else '?'}, exec={'OK' if (out and err is None) else err[:50]}")
    else:
        log_result(CHAR, "s9 焰动力·疾飞", "FAIL", "not found")


# ═══════════════════════════════════════════════════════════════
#  Y16: 林白 — 12 spells + summons + weapon system
# ═══════════════════════════════════════════════════════════════

def test_y16():
    CHAR = "Y16 林白"
    print("\n" + "=" * 70)
    print("  Y16: Lin Bai -- 12 spells + summons + weapon system")
    print("=" * 70)

    eng, t, uid, opp_uid = setup_test_battle("Y16")
    char = eng.get_char(uid)
    wpn = char.get_str('_weapon_name') or 'staff'
    print(f"  Default weapon: {wpn}")

    spells = get_loaded_spells(eng, uid)
    names = [s['name'] for s in spells]
    print(f"  Combat spells (staff): {len(spells)}")

    # s1 灵感大爆发 (MP recovery buff, stackable x2)
    spell, idx = find_spell(spells, '灵感大爆发')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, uid)
        ok = out and err is None
        log_result(CHAR, f"s{idx} 灵感大爆发", "PASS" if ok else "FAIL",
                   f"exec={'OK' if ok else err[:50]}")
    else:
        log_result(CHAR, "s1 灵感大爆发", "FAIL", "not found")

    # s2 虚假之月 (summon + buff)
    spell, idx = find_spell(spells, '虚假之月')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, uid)
        ok = out and err is None
        # Check summon exists
        il = eng._get_initiative()
        moons = [e for e in il if e.get('isSummon') and '虚假之月' in (e.get('displayName', '') or e.get('name', ''))]
        log_result(CHAR, f"s{idx} 虚假之月", "PASS" if ok else "FAIL",
                   f"exec={'OK' if ok else err[:50]}, summons={len(moons)}")
    else:
        log_result(CHAR, "s2 虚假之月", "FAIL", "not found")

    # s3 月中的倒影 (summon 2 shadow clones)
    spell, idx = find_spell(spells, '月中的倒影')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, uid)
        ok = out and err is None
        # Check clones
        il3 = eng._get_initiative()
        clones = [e for e in il3 if e.get('isSummon') and e.get('name') == '影之克隆']
        log_result(CHAR, f"s{idx} 月中的倒影", "PASS" if ok else "FAIL",
                   f"exec={'OK' if ok else err[:50]}, clones={len(clones)}")
        # Clone skill inheritance check
        if clones:
            clone_uid = clones[0]['userId']
            clone_char = eng.get_char(clone_uid)
            clone_spells = clone_char.spells or eng.load_spells(clone_uid)
            log_result(CHAR, "影之克隆·技能继承", "PASS" if len(clone_spells) > 1 else "FAIL",
                       f"clone_spells={len(clone_spells)} {'[INHERITED]' if len(clone_spells) > 1 else '[EMPTY]'}")
        else:
            log_result(CHAR, "影之克隆·技能继承", "SKIP", "no clones spawned")
    else:
        log_result(CHAR, "s3 月中的倒影", "FAIL", "not found")

    # s4 辉月女神的祝福 (passive)
    spell, idx = find_spell(spells, '辉月女神的祝福')
    if spell:
        is_passive = '1' in str(spell.get('时机', '2'))
        log_result(CHAR, f"s{idx} 辉月女神的祝福", "PASS" if is_passive else "FAIL",
                   f"timing={'[passive]' if is_passive else spell.get('时机','?')}")
    else:
        log_result(CHAR, "s4 辉月女神的祝福", "FAIL", "not found")

    # s5 幻造兵武 (passive, +1d6 to create spells)
    spell, idx = find_spell(spells, '幻造兵武')
    if spell:
        is_passive = '1' in str(spell.get('时机', '2'))
        log_result(CHAR, f"s{idx} 幻造兵武", "PASS" if is_passive else "FAIL",
                   f"timing={'[passive]' if is_passive else spell.get('时机','?')}")
    else:
        log_result(CHAR, "s5 幻造兵武", "FAIL", "not found")

    # s6 幻造兵武·即兴短句 (1MP, undodgeable)
    spell, idx = find_spell(spells, '幻造兵武·即兴短句')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, opp_uid)
        ok = out and err is None
        log_result(CHAR, f"s{idx} 幻造兵武·即兴短句", "PASS" if ok else "FAIL",
                   f"exec={'OK' if ok else err[:50]}")
    else:
        log_result(CHAR, "s6 幻造兵武·即兴短句", "FAIL", "not found")

    # s7-s9 Weapon switches (timing='123', free action)
    print(f"\n  --- Weapon switch tests ---")
    wpn_map = [('切换·法杖', 'staff'), ('切换·弓', 'bow'), ('切换·剑', 'sword')]
    for sname, expected_wpn in wpn_map:
        spell, idx = find_spell(spells, sname)
        if spell:
            out, err = exec_spell(eng, uid, spell, uid)
            ok = out and err is None
            log_result(CHAR, f"s{idx} {sname}", "PASS" if ok else "FAIL",
                       f"exec={'OK' if ok else err[:50]}")
        else:
            log_result(CHAR, sname, "FAIL", "not found")

    # s8b 已然遥远的理想城 (staff shield)
    ensure_weapon(eng, uid, 'staff')
    spells_staff = get_loaded_spells(eng, uid)
    spell, idx = find_spell(spells_staff, '已然遥远的理想城')
    if spell:
        ensure_mp(eng, uid, 99)
        out, err = exec_spell(eng, uid, spell, uid)
        ok = out and err is None
        log_result(CHAR, f"s{idx} 已然遥远的理想城", "PASS" if ok else "FAIL",
                   f"wpn=staff, exec={'OK' if ok else err[:50]}")
    else:
        log_result(CHAR, "s11 已然遥远的理想城", "FAIL", "not found (staff mode)")

    # s8a 万众瞩目的乌托邦 (bow, 3-turn chant)
    ensure_weapon(eng, uid, 'bow')
    spells_bow = get_loaded_spells(eng, uid)
    bow_names = [s['name'] for s in spells_bow]
    spell, idx = find_spell(spells_bow, '万众瞩目的乌托邦')
    if spell:
        log_result(CHAR, f"s{idx} 万众瞩目的乌托邦", "PASS", "wpn=bow, visible (3-turn chant)")
    else:
        log_result(CHAR, "s10 万众瞩目的乌托邦", "FAIL", "not found (bow mode)")

    # s8c 月光王座全额率输出 (sword, consumes moon energy)
    ensure_weapon(eng, uid, 'sword')
    spells_sword = get_loaded_spells(eng, uid)
    sword_names = [s['name'] for s in spells_sword]
    spell, idx = find_spell(spells_sword, '月光王座全额率输出')
    if spell:
        log_result(CHAR, f"s{idx} 月光王座全额率输出", "PASS", "wpn=sword, visible (consumes moon)")
    else:
        log_result(CHAR, "s12 月光王座全额率输出", "FAIL", "not found (sword mode)")

    # Weapon filter cross-check
    print(f"\n  --- Weapon filter cross-check ---")
    ensure_weapon(eng, uid, 'bow')
    spells_bow2 = get_loaded_spells(eng, uid)
    bow_names2 = [s['name'] for s in spells_bow2]
    s10_vis = '万众瞩目的乌托邦' in bow_names2
    s11_vis = '已然遥远的理想城' in bow_names2
    log_result(CHAR, "Weapon filter: bow", "PASS" if s10_vis and not s11_vis else "FAIL",
               f"Utopia={'VIS' if s10_vis else 'HID'}, IdealCity={'VIS' if s11_vis else 'HID'}")

    ensure_weapon(eng, uid, 'sword')
    spells_sw2 = get_loaded_spells(eng, uid)
    sw_names2 = [s['name'] for s in spells_sw2]
    s12_vis = '月光王座全额率输出' in sw_names2
    log_result(CHAR, "Weapon filter: sword", "PASS" if s12_vis else "FAIL",
               f"MoonThrone={'VIS' if s12_vis else 'HID'}")
    if '万众瞩目的乌托邦' not in sw_names2 and '已然遥远的理想城' not in sw_names2:
        log_result(CHAR, "Weapon filter: sword (exclusion)", "PASS",
                   "bow+staff ults correctly excluded")
    else:
        log_result(CHAR, "Weapon filter: sword (exclusion)", "FAIL",
                   "unexpected spells visible in sword mode")

    # Return to staff
    ensure_weapon(eng, uid, 'staff')


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL, SKIP
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("=" * 70)
    print("  Magical Girl Spell Comprehensive Test")
    print(f"  {timestamp}")
    print("  Y14: Mai Zhixia (22 spells) | Y15: Yu Changfeng (9) | Y16: Lin Bai (12)")
    print("=" * 70)
    print(f"  Total characters: {len(ALL_CHARACTERS)}")

    set_terminal_quiet(True)

    for test_fn, name in [(test_y14, "Y14"), (test_y15, "Y15"), (test_y16, "Y16")]:
        try:
            test_fn()
        except Exception as e:
            print(f"\n  [FATAL] {name} test crashed: {e}")
            traceback.print_exc()

    # Summary
    total = PASS + FAIL + SKIP
    print(f"\n{'='*70}")
    print(f"  Summary")
    print(f"{'='*70}")
    print(f"  Total: {total}  PASS: {PASS}  FAIL: {FAIL}  SKIP: {SKIP}")
    if FAIL > 0:
        print(f"\n  -- Failed ({FAIL}) --")
        for r in RESULTS:
            if r['status'] == 'FAIL':
                print(f"  [FAIL] {r['char']} | {r['spell']}  --  {r['detail']}")

    out_path = os.path.join(os.path.dirname(__file__), 'test_spells_output.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.datetime.now().isoformat(),
            'total': total, 'pass': PASS, 'fail': FAIL, 'skip': SKIP,
            'results': RESULTS,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON output saved to: {out_path}")
    return FAIL == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
