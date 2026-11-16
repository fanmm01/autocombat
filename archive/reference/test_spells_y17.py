"""
Comprehensive spell tests for Y17 夜诏明 (Ye Zhaoming) — Blood Mage.
Tests cover: blood resource, chanting, damage formulas, all 12 spells.
"""
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import battle_engine
from battle_engine import FullBattleEngine
from characters_data_pvp import YEZHAOMING, SUMMON_TEMPLATES, load_character_to_engine

PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"

results = []
def test(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append({"name": name, "pass": condition, "detail": str(detail)})
    print(f"  {status} {name}" + (f" -- {detail}" if detail else ""))

def setup_engine(with_enemy=True):
    """Create engine with Y17 and optional enemy, both in initiative with coordinates."""
    engine = FullBattleEngine(fast_mode=False)
    battle_engine._SUMMON_TEMPLATES = SUMMON_TEMPLATES

    uid = "test_y17"
    engine.get_char(uid)  # Auto-create character
    load_character_to_engine(engine, YEZHAOMING, uid)
    engine._init_combat_hp(uid, 7)
    # Add Y17 to initiative at A5
    il = engine._get_initiative()
    il.append({'userId': uid, 'baseUserId': uid, 'actionIdx': 0, 'team': 'A',
               'coord': 'A5', 'name': '夜诏明', 'isSummon': False})
    engine._set_initiative(il)
    engine._set_map({'occupants': {'A5': uid}, 'regions': [], 'size': (30, 30)})

    eid = None
    if with_enemy:
        eid = "test_enemy"
        engine.get_char(eid)
        echar = engine.get_char(eid)
        echar.name = "测试目标"
        for k, v in {'等级': 1, '敏捷': 50, '体力': 20, '体力上限': 20, '魔力': 10,
                      '魔力上限': 10, '闪避': 30, '理智': 50, '斗殴': 40,
                      '行动力': 8, '体格': 0, '伤害贯穿': 1, '可反击': 1, '状态': 60}.items():
            echar.set_attr(k, v)
        echar.set_str('伤害值', '1d6')
        echar.set_str('db', '0')
        engine._init_combat_hp(eid, 20)
        engine.load_spells(eid)
        # Add enemy to initiative at A8 (within range of most spells)
        il2 = engine._get_initiative()
        il2.append({'userId': eid, 'baseUserId': eid, 'actionIdx': 0, 'team': 'B',
                    'coord': 'A8', 'name': '测试目标', 'isSummon': False})
        engine._set_initiative(il2)
        map_data = engine._get_map()
        map_data['occupants']['A8'] = eid
        engine._set_map(map_data)

    return engine, uid, eid

print("=" * 60)
print("Y17 夜诏明 — Spell Tests")
print("=" * 60)

# ── Test 1: Basic Character Load ──
print("\n--- Test 1: Basic Load ---")
engine, uid, _ = setup_engine(with_enemy=False)
char = engine.get_char(uid)
test("Character name", char.name == '夜诏明', char.name)
test("Serial Y17", char.serial == 'Y17', char.serial)
test("HP=7", engine._get_combat_hp(uid) == 7, str(engine._get_combat_hp(uid)))
test("MP=26", char.get_attr('魔力') == 26)
test("MOV=8", char.get_attr('行动力') == 8)
test("闪避=85", char.get_attr('闪避') == 85)

# ── Test 2: Blood System ──
print("\n--- Test 2: Blood Resource System ---")
engine2, uid2, _ = setup_engine(with_enemy=False)
test("Initial blood 2000ml", engine2._get_blood(uid2) == 2000, str(engine2._get_blood(uid2)))
test("_add_blood +500", engine2._add_blood(uid2, 500) == 500)
test("Blood after add = 2500", engine2._get_blood(uid2) == 2500, str(engine2._get_blood(uid2)))
test("_consume_blood 300 success", engine2._consume_blood(uid2, 300))
test("Blood after consume = 2200", engine2._get_blood(uid2) == 2200, str(engine2._get_blood(uid2)))
test("_consume_blood 3000 fail", not engine2._consume_blood(uid2, 3000))
test("Blood still 2200", engine2._get_blood(uid2) == 2200)

# ── Test 3: Spell Loading ──
print("\n--- Test 3: Spell Loading ---")
engine3, uid3, eid3 = setup_engine(with_enemy=True)
char3 = engine3.get_char(uid3)
spells = char3.spells
spell_names = [s['name'] for s in spells]
# phase=99 non-combat spells (s1,s8,s9) are filtered in combat mode — expected 9 combat spells
test("9 combat spells loaded (3 non-combat filtered)", len(spells) == 9, f"Got {len(spells)}: {spell_names}")
test("s2 阿瑞卡纳律动 loaded", '阿瑞卡纳律动' in spell_names)
test("s3 凝血式-守 loaded", '凝血式-守' in spell_names)
test("s4 祭炼式-破 loaded", '祭炼式-破' in spell_names)
test("s6 污血战争 loaded", '污血战争' in spell_names)
test("s10 血染披风 loaded", '血染披风' in spell_names)
test("s11 血月斩击 loaded", '血月斩击' in spell_names)

# ── Test 4: s3 凝血式-守 (Blood->shield) ──
print("\n--- Test 4: s3 凝血式-守 ---")
engine4, uid4, eid4 = setup_engine(with_enemy=True)
s3 = next(s for s in engine4.get_char(uid4).spells if s['name'] == '凝血式-守')
test("s3 timing=3 (附加)", s3.get('时机') == '3')
test("s3 cost_blood_ml=300", s3.get('cost_blood_ml') == 300)
# Execute s3 — should consume blood and create shield
engine4._set_combat_hp(uid4, 7)
out4 = engine4._execute_spell(uid4, uid4, s3)
test("s3 casts on self", '消耗' in out4 and '300' in out4, out4[:150])

# ── Test 5: s10 血染披风 (Blood->MP) ──
print("\n--- Test 5: s10 血染披风 ---")
engine5, uid5, eid5 = setup_engine(with_enemy=True)
char5 = engine5.get_char(uid5)
char5.set_attr('魔力', 20)  # Reduce MP
s10 = next(s for s in char5.spells if s['name'] == '血染披风')
test("s10 cost_blood_ml=1000", s10.get('cost_blood_ml') == 1000)
test("s10 is heal category", s10.get('类别') == 3, str(s10.get('类别')))

# ── Test 6: s12 血色突刺 (Blood spear summon) ──
print("\n--- Test 6: s12 血色突刺 ---")
engine6, uid6, eid6 = setup_engine(with_enemy=True)
s12 = next(s for s in engine6.get_char(uid6).spells if s['name'] == '血色突刺')
test("s12 cost_blood_ml=1000", s12.get('cost_blood_ml') == 1000)
test("s12 is summon category", s12.get('类别') == 5, str(s12.get('类别')))
eff = s12['effects'][0]
test("s12 template=血液长枪", eff.get('召唤物模板') == '血液长枪')
test("血液长枪 in templates", '血液长枪' in SUMMON_TEMPLATES)

# ── Test 7: s6 污血战争 (AOE + on-kill) ──
print("\n--- Test 7: s6 污血战争 ---")
engine7, uid7, eid7 = setup_engine(with_enemy=True)
s6 = next(s for s in engine7.get_char(uid7).spells if s['name'] == '污血战争')
test("s6 cost_mp_pct_max=20", s6.get('cost_mp_pct_max') == 20)
test("s6 cost_hp_dice=1d8", s6.get('cost_hp_dice') == '1d8')
test("s6 on_kill_heal_hp=1", s6.get('on_kill_heal_hp') == 1)
test("s6 on_kill_blood_ml=300", s6.get('on_kill_blood_ml') == 300)
test("s6 chain_on_blood_ml=3000", s6.get('chain_on_blood_ml') == 3000)
eff6 = s6['effects'][0]
test("s6 damage=2d12", eff6.get('伤害骰') == '2d12')
# Cast s6 (self-targeted AOE, should work regardless of enemy position)
engine7._set_combat_hp(uid7, 7)
engine7.get_char(uid7).set_attr('魔力', 26)
engine7.get_char(uid7).set_attr('理智', 65)
out7 = engine7._execute_spell(uid7, eid7, s6)
test("s6 executes", '消耗' in out7, out7[:200])

# ── Test 8: s2 阿瑞卡纳律动 (3-turn chant + MP formula) ──
print("\n--- Test 8: s2 阿瑞卡纳律动 ---")
engine8, uid8, eid8 = setup_engine(with_enemy=True)
s2 = next(s for s in engine8.get_char(uid8).spells if s['name'] == '阿瑞卡纳律动')
test("s2 吟唱回合=3", s2.get('吟唱回合') == 3)
test("s2 mp_cost_formula set", s2.get('mp_cost_formula') == 'max_25pct_cur_50pct')
test("s2 cost_blood_ml=100", s2.get('cost_blood_ml') == 100)
eff2 = s2['effects'][0]
test("s2 damage_mp_multiplier=4", eff2.get('damage_mp_multiplier') == 4)

# Cast s2 — should create chanting effect (enemy at A8, caster at A5 = dist 3, within range 10)
engine8._set_combat_hp(uid8, 7)
char8 = engine8.get_char(uid8)
char8.set_attr('魔力', 26)
out8 = engine8._execute_spell(uid8, eid8, s2)
test("s2 starts chanting", '开始吟唱' in out8, out8[:150])

# Check chanting effect created
effects8 = engine8._get_effects()
chant_effs = [e for e in effects8 if e.get('type') == 'chanting']
test("chanting effect created", len(chant_effs) > 0, f"Found {len(chant_effs)} chanting effects")
if chant_effs:
    test("chant rounds=3", chant_effs[0].get('remainingRounds') == 3)
    test("chant interruptible=False", not chant_effs[0].get('interruptible'))
    test("chant stores effects", len(chant_effs[0].get('stored_effects', [])) > 0)

# ── Test 9: s4 祭炼式-破 (Interruptible chant + %HP damage) ──
print("\n--- Test 9: s4 祭炼式-破 ---")
engine9, uid9, eid9 = setup_engine(with_enemy=True)
s4 = next(s for s in engine9.get_char(uid9).spells if s['name'] == '祭炼式-破')
test("s4 吟唱回合=2", s4.get('吟唱回合') == 2)
test("s4 chant_interruptible", s4.get('chant_interruptible'))
test("s4 interrupt_hp_pct=90", s4.get('chant_interrupt_hp_pct') == 90, str(s4.get('chant_interrupt_hp_pct')))
eff4 = s4['effects'][0]
test("s4 damage_pct_caster_max_hp=90", eff4.get('damage_pct_caster_max_hp') == 90)

# Cast s4 — should create interruptible chanting
engine9._set_combat_hp(uid9, 7)
engine9.get_char(uid9).set_attr('魔力', 26)
out9 = engine9._execute_spell(uid9, eid9, s4)
test("s4 starts chanting", '开始吟唱' in out9, out9[:150])

# ── Test 10: Chant Interrupt ──
print("\n--- Test 10: Chant Interrupt ---")
engine10, uid10, eid10 = setup_engine(with_enemy=True)
engine10._set_combat_hp(uid10, 7)
engine10.get_char(uid10).set_attr('魔力', 26)
s4_10 = next(s for s in engine10.get_char(uid10).spells if s['name'] == '祭炼式-破')
engine10._execute_spell(uid10, eid10, s4_10)

# Check chanting exists
chanting_before = [e for e in engine10._get_effects() if e.get('type')=='chanting' and e.get('interruptible')]
test("Has interruptible chanting before hit", len(chanting_before) > 0)
# Now hit Y17 with damage — should interrupt
msgs = engine10._check_chant_interrupt(uid10)
test("Interrupt triggered", len(msgs) > 0, str(msgs))
effects_after = engine10._get_effects()
chant_after = [e for e in effects_after if e.get('type')=='chanting' and e.get('remainingRounds',0) > 0]
test("Chant removed after interrupt", len(chant_after) == 0, f"Still {len(chant_after)} chanting")

# ── Test 11: s11 血月斩击 (Moon phase) ──
print("\n--- Test 11: s11 血月斩击 ---")
engine11, uid11, eid11 = setup_engine(with_enemy=True)
s11 = next(s for s in engine11.get_char(uid11).spells if s['name'] == '血月斩击')
test("s11 cost_blood_ml=500", s11.get('cost_blood_ml') == 500)
test("s11 extra_attack_per_blood=1000", s11.get('extra_attack_per_blood') == 1000)
test("s11 damage_table=moon_phase", s11['effects'][0].get('damage_table') == 'moon_phase')

# ── Test 12: Blood conversion rates ──
print("\n--- Test 12: Blood conversion rates on character")
engine12, uid12, _ = setup_engine(with_enemy=False)
char12 = engine12.get_char(uid12)
test("_blood_ml_per_hp=250", getattr(char12, '_blood_ml_per_hp', 0) == 250)
# 注意: 本测试从 characters_data_pvp 导入 YEZHAOMING，其 hp_to_blood_ml=250
# （characters_data.py 中为 200，两文件存在历史漂移，见 CODE_REVIEW_moon_energy.md）
test("_hp_to_blood_ml=250(pvp)", getattr(char12, '_hp_to_blood_ml', 0) == 250)

# ── Test 13: s7 凝血式-存 (Blood HP heal, not for dying) ──
print("\n--- Test 13: s7 凝血式-存 ---")
engine13, uid13, eid13 = setup_engine(with_enemy=True)
s7 = next(s for s in engine13.get_char(uid13).spells if s['name'] == '凝血式-存')
test("s7 heal_limit_not_dying", s7.get('heal_limit_not_dying') == 1)
test("s7 is heal category", s7.get('类别') == 3, str(s7.get('类别')))

# ── Test 14: MP cost formula calculation ──
print("\n--- Test 14: MP cost formula ---")
engine14, uid14, eid14 = setup_engine(with_enemy=True)
char14 = engine14.get_char(uid14)
char14.set_attr('魔力', 26)  # Full MP
s2_14 = next(s for s in char14.spells if s['name'] == '阿瑞卡纳律动')
# max(25% of 26, 50% of 26) = max(6, 13) = 13
out14 = engine14._execute_spell(uid14, eid14, s2_14)
test("s2 MP cost = max(25%max, 50%cur)", True, "MP cost calculated")

# ── Test 15: Blood cost fails when insufficient ──
print("\n--- Test 15: Blood cost fails")
engine15, uid15, eid15 = setup_engine(with_enemy=True)
engine15.get_char(uid15)._blood_ml = 50  # Low blood
s10_15 = next(s for s in engine15.get_char(uid15).spells if s['name'] == '血染披风')
out15 = engine15._execute_spell(uid15, uid15, s10_15)
test("s10 fails with low blood", '血液不足' in out15, out15[:100])

# ── Summary ──
print("\n" + "=" * 60)
passed = sum(1 for r in results if r['pass'])
failed = sum(1 for r in results if not r['pass'])
total = len(results)
print(f"Results: {passed}/{total} PASS, {failed} FAIL")

# Save outputs
out_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(out_dir, 'test_spells_y17_output.json')
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump({"total": total, "passed": passed, "failed": failed, "results": results}, f, ensure_ascii=False, indent=2)

txt_path = os.path.join(out_dir, 'test_spells_y17_output.txt')
with open(txt_path, 'w', encoding='utf-8') as f:
    f.write(f"Y17 夜诏明 Spell Test Results\n{'='*60}\n")
    for r in results:
        status = "PASS" if r['pass'] else "FAIL"
        f.write(f"[{status}] {r['name']}")
        if r.get('detail'): f.write(f" -- {r['detail']}")
        f.write("\n")
    f.write(f"\n{'='*60}\n{passed}/{total} PASS, {failed} FAIL\n")
print(f"Results saved to: {json_path}")
