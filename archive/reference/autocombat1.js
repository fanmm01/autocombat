// ==UserScript==
// @name         半自动战斗扩展
// @author       fanmm
// @version      0.4.0
// @description  CoC魔法少女半自动战斗规则扩展。支持.setab 0(最小自动化)与.setab 1(完全自动化)。
//               前置：loganalyser/logutil v5.0+ 与 coc7扩展。
// @timestamp    1759931652
// @diceRequireVer 1.4.0
// @license      MIT
// ==/UserScript==

// ============================================================
//  扩展注册
// ============================================================
let ext = seal.ext.find('autocombat');
if (!ext) {
  ext = seal.ext.new('autocombat', 'fanmm', '0.4.0');
  seal.ext.register(ext);
}

// 模式通过 .setab / .setrestim 指令切换，使用 $g 变量存储

// ============================================================
//  Helper functions
// ============================================================

/** Roll a dice expression (e.g. "1d4+1d6") and return integer result */
function rollDice(ctx, expr) {
  if (!expr || expr === '0') return 0;
  const result = seal.format(ctx, `{${expr}}`);
  const num = parseInt(result);
  return isNaN(num) ? 0 : num;
}

/** Roll a single d10 via seal.format, returning 1-10 (10 → 0 for COC digits). */
function rollD10(ctx) {
  const s = seal.format(ctx, '{1d10}');
  const n = parseInt(s);
  if (isNaN(n)) return 0;
  return n === 10 ? 0 : n; // 10→0 for COC d100 digit arithmetic
}

/** Roll D100 with optional bonus/penalty dice, using manual d10 rolls
 *  to avoid seal.format returning unparseable descriptive strings.
 *
 *  COC7 rule: a bonus die rolls an extra tens die, take the lower → better.
 *             a penalty die rolls an extra tens die, take the higher → worse.
 *  00 (0×10+0) is read as 100.
 *
 *  bpStr: '' | 'b' | 'p' | 'b2' | 'p2' | 'b3' etc.
 *  Returns { result, detail } where detail shows the extra tens values,
 *    e.g. "奖励4" or "惩罚8,3".
 */
function rollD100(ctx, bpStr) {
  if (!bpStr) {
    // Simple roll: one d100 as two d10 digits
    const tens = rollD10(ctx);
    const units = rollD10(ctx);
    const r = (tens === 0 && units === 0) ? 100 : tens * 10 + units;
    return { result: r, detail: '' };
  }
  const m = bpStr.match(/^([bp])(\d*)$/i);
  if (!m) {
    const tens = rollD10(ctx);
    const units = rollD10(ctx);
    const r = (tens === 0 && units === 0) ? 100 : tens * 10 + units;
    return { result: r, detail: '' };
  }
  const type = m[1].toLowerCase(); // 'b' or 'p'
  const count = m[2] ? parseInt(m[2]) : 1;

  // Roll the base tens & units
  let bestTens = rollD10(ctx);
  const units = rollD10(ctx);

  // Roll N extra tens dice
  const extraTens = [];
  for (let i = 0; i < count; i++) {
    extraTens.push(rollD10(ctx));
  }

  // Apply bonus (take lowest tens) or penalty (take highest tens)
  for (const t of extraTens) {
    if (type === 'b') {
      if (t < bestTens) bestTens = t;
    } else {
      if (t > bestTens) bestTens = t;
    }
  }

  const r = (bestTens === 0 && units === 0) ? 100 : bestTens * 10 + units;
  const label = type === 'b' ? '奖励' : '惩罚';
  // Show all extra tens values: e.g. "奖励4" or "奖励2,7"
  const extraStr = extraTens.join(',');
  return { result: r, detail: `${label}${extraStr}` };
}

/** COC7 success rank (rule 2: domestic common).
 *  大失败=-2  失败=-1  成功=1  困难成功=2  极难成功=3  大成功=4
 */
function successRank(d100, skillVal) {
  if (skillVal <= 0) return d100 <= 5 ? 4 : (d100 >= 96 ? -2 : -1);
  if (d100 === 1) return 4;
  if (d100 === 100) return -2;
  if (d100 > skillVal) {
    if (skillVal < 50 && d100 >= 96) return -2;
    return -1;
  }
  let rank = 1;
  if (d100 <= skillVal / 5) rank = 3;
  else if (d100 <= skillVal / 2) rank = 2;
  if (d100 <= 5) rank = 4;
  return rank;
}

/** Get human-readable success rank text */
function rankText(ctx, rank) {
  switch (rank) {
    case -2: return '大失败';
    case -1: return '失败';
    case  1: return '成功';
    case  2: return '困难成功';
    case  3: return '极难成功';
    case  4: return '大成功';
    default: return '';
  }
}

/** Get attribute value from character card */
function getAttr(ctx, name, fallback) {
  fallback = (fallback !== undefined) ? fallback : 0;
  const vr = seal.vars.intGet(ctx, name);
  if (vr[1] && vr[0] > 0) return vr[0];
  const result = seal.format(ctx, `{${name}}`);
  const n = parseInt(result);
  return isNaN(n) ? fallback : n;
}

/** Get string attribute */
function getStrAttr(ctx, name) {
  const vr = seal.vars.strGet(ctx, name);
  return vr[1] ? vr[0] : '';
}

/** Parse skill name that may have compound format:
 *   "50"        → raw number
 *   "斗殴"       → skill name
 *   "斗殴50"     → skill with value
 *   "斗殴+10"    → skill with positive modifier
 *   "斗殴-5"     → skill with negative modifier
 *   "斗殴a"      → suffixed skill (falls back to "斗殴" if not found)
 */
function parseSkillValue(ctx, rawName) {
  // Pure number
  const asNum = parseInt(rawName);
  if (!isNaN(asNum) && String(asNum) === rawName) {
    return { name: String(asNum), value: asNum, isRaw: true };
  }
  // "skill+N" or "skill-N"
  const pmMatch = rawName.match(/^(\D+?)([+-]\d+)$/);
  if (pmMatch) {
    const base = pmMatch[1];
    const mod = parseInt(pmMatch[2]);
    const baseVal = getAttr(ctx, base);
    if (baseVal > 0) return { name: base, value: Math.max(0, baseVal + mod) };
    return { name: base, value: Math.max(0, 50 + mod) };
  }
  // "skill50" compound (no sign) — number replaces the skill value
  const compound = rawName.match(/^(\D+?)(\d+)$/);
  if (compound) {
    const base = compound[1];
    const num = parseInt(compound[2]);
    const baseVal = getAttr(ctx, base);
    if (baseVal > 0) return { name: base, value: num };
    if (num >= 5 && num <= 99) {
      const skillOnly = rawName.replace(/\d+$/, '');
      const sv = getAttr(ctx, skillOnly);
      if (sv > 0) return { name: skillOnly, value: sv };
      return { name: skillOnly || String(num), value: num };
    }
    return { name: base || String(num), value: Math.max(baseVal, num) };
  }
  // Plain skill name (possibly suffixed with a/b)
  let sv = getAttr(ctx, rawName);
  if (sv > 0) return { name: rawName, value: sv };
  // Fallback: if suffixed, try without suffix
  if (/[ab]$/.test(rawName) && rawName.length > 1) {
    const baseName = rawName.slice(0, -1);
    sv = getAttr(ctx, baseName);
    if (sv > 0) return { name: baseName, value: sv };
  }
  return { name: rawName, value: sv };
}

/** Normalize damage dice string: "d6"→"1d6" */
function normalizeDice(expr) {
  if (!expr) return '1d4';
  if (/^\d+$/.test(expr)) return expr;
  return expr.replace(/(^|[^0-9])d/gi, '$11d');
}

/** Get weapon suffix from a skill name (trailing 'a' or 'b') */
function getWeaponSuffix(name) {
  if (/[ab]$/.test(name) && name.length > 1) return name.slice(-1);
  return '';
}

// ============================================================
//  Combat skill classification — derived from the COC skill table
//  (logstat&enAll.c 战斗类技能)
// ============================================================

/** All combat-class skills (战斗类技能) from the COC skill table */
const ALL_COMBAT_SKILLS = [
  '格斗', '斗殴', '斧', '链锯', '连枷', '绞索', '矛', '剑', '鞭',
  '射击', '射击:弓', '射击:手枪', '射击:重武器', '射击:火焰喷射器',
  '射击:机枪', '射击:步霰', '射击:冲锋枪',
  '投掷', '爆破', '炮术',
];

/** Melee combat skills (近战战斗类技能) — used for default counter-attack selection */
const MELEE_COMBAT_SKILLS = [
  '格斗', '斗殴', '斧', '链锯', '连枷', '绞索', '矛', '剑', '鞭',
];

/** Ranged combat skills (远程/射击/投掷/爆破/炮术) — cannot be reacted to */
const RANGED_COMBAT_SKILLS = [
  '射击', '射击:弓', '射击:手枪', '射击:重武器', '射击:火焰喷射器',
  '射击:机枪', '射击:步霰', '射击:冲锋枪',
  '投掷', '爆破', '炮术',
];

/** Common aliases for ranged skills (without "射击:" prefix) */
const RANGED_ALIASES = [
  '手枪', '弓', '弓箭', '弓术', '重武器', '火焰喷射器',
  '机枪', '步枪', '霰弹枪', '散弹枪', '步霰', '冲锋枪',
  '炮术', '火炮', '火器', '枪械',
];

/** Check if a skill name refers to a ranged weapon (cannot be dodged/countered) */
function isRangedSkill(name) {
  if (RANGED_COMBAT_SKILLS.includes(name)) return true;
  if (RANGED_ALIASES.includes(name)) return true;
  if (/^射击/.test(name)) return true;  // "射击:xxx" or bare "射击"
  return false;
}

/** Find the highest-valued melee combat skill on a character card.
 *  Returns { name, value } — fallback to 斗殴/25 if nothing found.
 */
function getBestMeleeSkill(ctx) {
  let bestSkill = '斗殴';
  let bestVal = 0;
  for (const ms of MELEE_COMBAT_SKILLS) {
    const sv = getAttr(ctx, ms);
    if (sv > bestVal) { bestVal = sv; bestSkill = ms; }
  }
  return { name: bestSkill, value: Math.max(bestVal, 25) };
}

/** Parse a dice expression into signed terms like ["1d6", "+2", "-1d4"].
 *  Simple match-based approach — no exec() loop, no g-flag issues.
 */
function parseDiceTerms(diceExpr) {
  if (!diceExpr) return [];
  // Match: optional sign, optional whitespace, then either NdS or a plain number
  const terms = diceExpr.match(/[+-]?\s*\d*d\d+|[+-]?\s*\d+/gi);
  return terms || [];
}

/** Calculate expected (average) damage. */
function avgDamage(diceExpr) {
  if (!diceExpr) return 0;
  let total = 0;
  const terms = parseDiceTerms(diceExpr);
  for (const term of terms) {
    const sign = term.trim()[0] === '-' ? -1 : 1;
    const clean = term.replace(/[+-]\s*/, '');
    const m = clean.match(/^(\d*)d(\d+)$/i);
    if (m) {
      const cnt = m[1] ? parseInt(m[1], 10) : 1;
      const sides = parseInt(m[2], 10);
      total += sign * cnt * (sides + 1) / 2;
    } else {
      total += sign * (parseInt(clean, 10) || 0);
    }
  }
  return total;
}

/** Calculate maximum possible damage. */
function maxDamage(diceExpr) {
  if (!diceExpr) return 0;
  let total = 0;
  const terms = parseDiceTerms(diceExpr);
  for (const term of terms) {
    const sign = term.trim()[0] === '-' ? -1 : 1;
    const clean = term.replace(/[+-]\s*/, '');
    const m = clean.match(/^(\d*)d(\d+)$/i);
    if (m) {
      const cnt = m[1] ? parseInt(m[1], 10) : 1;
      total += sign * cnt * parseInt(m[2], 10);
    } else {
      total += sign * (parseInt(clean, 10) || 0);
    }
  }
  return Math.max(0, total);
}

/** Roll damage normally */
function rollDmgNormal(ctx, diceExpr) {
  const val = rollDice(ctx, diceExpr);
  return { value: val, detail: `${diceExpr}=${val}` };
}

/** Roll damage with advantage (twice, take higher) */
function rollDmgAdv(ctx, diceExpr) {
  const r1 = rollDice(ctx, diceExpr);
  const r2 = rollDice(ctx, diceExpr);
  return { value: Math.max(r1, r2), detail: `优势(${diceExpr}=${r1}, ${r2}) → ${Math.max(r1, r2)}` };
}

/** Roll damage with disadvantage (twice, take lower) */
function rollDmgDisadv(ctx, diceExpr) {
  const r1 = rollDice(ctx, diceExpr);
  const r2 = rollDice(ctx, diceExpr);
  return { value: Math.min(r1, r2), detail: `劣势(${diceExpr}=${r1}, ${r2}) → ${Math.min(r1, r2)}` };
}

/** Get DB string from build value */
function dbFromBuild(build) {
  const table = { '-2': '-2', '-1': '-1d4', '0': '0', '1': '1d4', '2': '1d6', '3': '2d6', '4': '3d6', '5': '4d6' };
  return table[String(build)] || '0';
}

/** Determine if a context represents an NPC (has no character card attributes). */
function isNPCContext(ctx) {
  const keyAttrs = ['力量', '体质', '敏捷', '智力', '意志', '外貌', '教育', '体型', '幸运'];
  const aliasAttrs = ['hp', 'san', 'mp', 'str', 'con', 'dex', 'int', 'pow', 'app', 'siz', 'edu', 'luc'];
  let found = 0;
  for (const a of keyAttrs) {
    const vr = seal.vars.intGet(ctx, a);
    if (vr[1] && vr[0] > 0) found++;
  }
  for (const a of aliasAttrs) {
    const vr = seal.vars.intGet(ctx, a);
    if (vr[1] && vr[0] > 0) found++;
  }
  return found < 2;
}

// ============================================================
//  Combat HP temp store — defers HP changes until .unh
// ============================================================
function combatHPKey(groupId) { return `combat_hp_${groupId}`; }
function getCombatHP(groupId) {
  const raw = ext.storageGet(combatHPKey(groupId));
  if (!raw) return {};
  try { return JSON.parse(raw); } catch (e) { return {}; }
}
function setCombatHP(groupId, data) {
  ext.storageSet(combatHPKey(groupId), JSON.stringify(data));
}

/** Initialize combat HP for both parties if not already tracked.
 *  .st changes are synced via the onCommandReceived hook. */
function initCombatHP(groupId, atkUserId, atkCtx, defUserId, defCtx) {
  const hp = getCombatHP(groupId);
  if (hp[atkUserId] === undefined) {
    const v = seal.vars.intGet(atkCtx, '体力');
    hp[atkUserId] = v[1] ? v[0] : 10;
  }
  if (hp[defUserId] === undefined) {
    const v = seal.vars.intGet(defCtx, '体力');
    hp[defUserId] = v[1] ? v[0] : 10;
  }
  setCombatHP(groupId, hp);
}

/** Write combat HP back to character card on .unh */
function flushCombatHP(groupId, userId, ctx) {
  const hp = getCombatHP(groupId);
  if (hp[userId] !== undefined) {
    seal.vars.intSet(ctx, '体力', hp[userId]);
    delete hp[userId];
    setCombatHP(groupId, hp);
  }
}

// ============================================================
//  Damage value calculator — rolls dice, applies to combat HP store,
//  returns the numeric damage dealt (without building output text).
// ============================================================
function calcDamageValue(diceCtx, loserUserId, winnerUserId, groupId,
                         winnerRank, winnerRoll, dmgDice, pen, leth,
                         dmgAdv, dmgDis) {
  const dice = dmgDice || '1d4';
  const mx = maxDamage(dice);
  let dmgValue = 0;

  switch (winnerRank) {
    case 2: { const r = rollDmgAdv(diceCtx, dmgDice); dmgValue = r.value; break; }
    case 3: {
      if (pen) { const extra = rollDmgNormal(diceCtx, dmgDice); dmgValue = mx + extra.value; }
      else { dmgValue = mx; }
      break;
    }
    case 4: {
      if (winnerRoll === 1) { dmgValue = mx * 2; }
      else if (pen) { dmgValue = mx * 2; }
      else { const extra = rollDmgNormal(diceCtx, dmgDice); dmgValue = mx + extra.value; }
      break;
    }
    default: {
      if (dmgAdv) { const r = rollDmgAdv(diceCtx, dmgDice); dmgValue = r.value; }
      else if (dmgDis) { const r = rollDmgDisadv(diceCtx, dmgDice); dmgValue = r.value; }
      else { const r = rollDmgNormal(diceCtx, dmgDice); dmgValue = r.value; }
      break;
    }
  }

  // Apply to combat HP store
  const hpStore = getCombatHP(groupId);
  let curHP = hpStore[loserUserId];
  if (curHP === undefined) curHP = 10;

  const expDmg = avgDamage(dice);
  if (leth && expDmg > 6) {
    const lethDie = Math.max(2, curHP * 2);
    const lethRoll = parseInt(seal.format(diceCtx, `{1d${lethDie}}`), 10) || 0;
    const lethThreshold = Math.floor(expDmg);
    if (lethRoll <= lethThreshold) {
      curHP = 0;
    } else {
      curHP = Math.max(0, Math.floor(curHP - dmgValue));
    }
  } else {
    curHP = Math.max(0, Math.floor(curHP - dmgValue));
  }

  hpStore[loserUserId] = curHP;
  setCombatHP(groupId, hpStore);
  return dmgValue;
}

/** Same as calcDamageValue but also writes the new HP back to the loser's card.
 *  loserCtx must be the loser's own context (for seal.vars.intSet). */
function calcDamageAndSyncCard(loserCtx, diceCtx, loserUserId, winnerUserId, groupId,
                                winnerRank, winnerRoll, dmgDice, pen, leth, dmgAdv, dmgDis) {
  const dmg = calcDamageValue(diceCtx, loserUserId, winnerUserId, groupId,
    winnerRank, winnerRoll, dmgDice, pen, leth, dmgAdv, dmgDis);
  // Sync store→card so .st reads correct current HP
  const hpStore = getCombatHP(groupId);
  const curHP = hpStore[loserUserId];
  if (curHP !== undefined && loserCtx && loserCtx.player) {
    seal.vars.intSet(loserCtx, '体力', curHP);
  }
  return dmg;
}

// ============================================================
//  Unified damage resolution — uses combat HP store (with output text)
// ============================================================
function resolveDamage(diceCtx, loserUserId, winnerUserId, groupId,
                       winnerRank, winnerRoll, dmgDice, pen, leth, dmgAdv, dmgDis,
                       loserName, winnerName) {
  let out = '';
  let dmgValue = 0, dmgDetail = '';
  const dice = dmgDice || '1d4';
  const mx = maxDamage(dice);

  switch (winnerRank) {
    case 2: { const r = rollDmgAdv(diceCtx, dmgDice); dmgValue = r.value; dmgDetail = r.detail; break; }
    case 3: {
      if (pen) { const extra = rollDmgNormal(diceCtx, dmgDice); dmgValue = mx + extra.value; dmgDetail = `贯穿！满值${mx}+${dmgDice}=${extra.value} = ${dmgValue}`; }
      else { dmgValue = mx; dmgDetail = `${dmgDice}满值=${mx}`; }
      break;
    }
    case 4: {
      if (winnerRoll === 1) { dmgValue = mx * 2; dmgDetail = `大成功！${dmgDice}满值${mx}×2=${dmgValue}`; }
      else if (pen) { dmgValue = mx * 2; dmgDetail = `贯穿！${dmgDice}满值${mx}×2=${dmgValue}`; }
      else { const extra = rollDmgNormal(diceCtx, dmgDice); dmgValue = mx + extra.value; dmgDetail = `${dmgDice}满值${mx}+${extra.value} = ${dmgValue}`; }
      break;
    }
    default: {
      if (dmgAdv) { const r = rollDmgAdv(diceCtx, dmgDice); dmgValue = r.value; dmgDetail = r.detail; }
      else if (dmgDis) { const r = rollDmgDisadv(diceCtx, dmgDice); dmgValue = r.value; dmgDetail = r.detail; }
      else { const r = rollDmgNormal(diceCtx, dmgDice); dmgValue = r.value; dmgDetail = r.detail; }
      break;
    }
  }

  out += `${loserName} 受到伤害为：\n`;
  out += `${dmgDetail} = ${dmgValue}\n`;

  // Read HP from combat store
  const hpStore = getCombatHP(groupId);
  let curHP = hpStore[loserUserId];
  if (curHP === undefined) curHP = 10;

  // Lethality check (no NPC restriction)
  const expDmg = avgDamage(dice);
  if (leth && expDmg > 6) {
    const lethDie = Math.max(2, curHP * 2);
    const lethRoll = parseInt(seal.format(diceCtx, `{1d${lethDie}}`), 10) || 0;
    const lethThreshold = Math.floor(expDmg);
    out += `\n致死骰情况为：1d${lethDie} = ${lethRoll} `;
    if (lethRoll <= lethThreshold) {
      out += `<= ${lethThreshold}，成功，战斗结束\n`;
      curHP = 0;
    } else {
      out += `> ${lethThreshold}，失败，战斗继续\n`;
      curHP = Math.max(0, Math.floor(curHP - dmgValue));
    }
  } else {
    curHP = Math.max(0, Math.floor(curHP - dmgValue));
  }

  // Write HP back to combat store
  hpStore[loserUserId] = curHP;
  setCombatHP(groupId, hpStore);

  // Display both parties' HP
  const winnerHP = hpStore[winnerUserId];
  out += `${loserName}的剩余生命值为：${curHP}\n`;
  if (winnerHP !== undefined) {
    out += `${winnerName}的当前生命值为：${winnerHP}\n`;
  }

  return out;
}

// ============================================================
//  .setab <0|1>  — 切换自动化程度
// ============================================================
const cmdSetab = seal.ext.newCmdItemInfo();
cmdSetab.name = 'setab';
cmdSetab.help =
  '.setab 0 // 最小自动化模式（仅单次攻击-反应-结算 + 变身/解除）\n' +
  '.setab 1 // 完全自动化模式（默认，含地图、回合制等）';
cmdSetab.solve = (ctx, msg, cmdArgs) => {
  const val = cmdArgs.getArgN(1);
  switch (val) {
    case '0':
      seal.vars.intSet(ctx, '$gAutoBattleMode', 0);
      seal.replyToSender(ctx, msg,
        '已切换至【半自动战斗·最小自动化模式】(.setab 0)\n' +
        '支持指令：.bta start(战斗前同步) .bta(攻击) .e(反应) .bta end(战斗后同步) .hs(变身) .unh(解除变身) .setrestim(公布时机)');
      break;
    case '1':
      seal.vars.intSet(ctx, '$gAutoBattleMode', 1);
      seal.replyToSender(ctx, msg,
        '已切换至【半自动战斗·完全自动化模式】(.setab 1)\n' +
        '（完全自动化模式尚在开发中）');
      break;
    case '':
    case 'help': {
      const ret = seal.ext.newCmdExecuteResult(true);
      ret.showHelp = true;
      return ret;
    }
    default:
      seal.replyToSender(ctx, msg, '用法：.setab 0（最小自动化） 或 .setab 1（完全自动化）');
  }
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  .setrestim <0|1>  — 检定结果公布时机
// ============================================================
const cmdSetrestim = seal.ext.newCmdItemInfo();
cmdSetrestim.name = 'setrestim';
cmdSetrestim.help =
  '.setrestim 0 // 攻击时立即公布检定结果（默认）\n' +
  '.setrestim 1 // 反应动作后才一并公布双方检定结果';
cmdSetrestim.solve = (ctx, msg, cmdArgs) => {
  const val = cmdArgs.getArgN(1);
  switch (val) {
    case '0':
      seal.vars.intSet(ctx, '$gRestimMode', 0);
      seal.replyToSender(ctx, msg, '已切换：攻击时立即公布检定结果。');
      break;
    case '1':
      seal.vars.intSet(ctx, '$gRestimMode', 1);
      seal.replyToSender(ctx, msg, '已切换：反应动作后才一并公布双方检定结果。');
      break;
    default:
      seal.replyToSender(ctx, msg, '用法：.setrestim 0（立即公布） 或 .setrestim 1（延迟公布）');
  }
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  .bta start  — 战斗开始前同步属性快照
//  Saves a snapshot of all combat-relevant attributes and skills,
//  marks combat as active so .st changes are tracked in real time.
// ============================================================
const cmdBtaStart = seal.ext.newCmdItemInfo();
cmdBtaStart.name = 'bta start';
cmdBtaStart.help =
  '.bta start // 战斗前同步全部战斗属性快照\n' +
  '保存当前所有战斗类技能与属性的值，标记战斗进行中。\n' +
  '战斗期间 .st 修改的属性将实时反映至战斗内。';
cmdBtaStart.solve = (ctx, msg, cmdArgs) => {
  const mctx = seal.getCtxProxyFirst(ctx, cmdArgs) || ctx;

  // Collect all combat-relevant attributes & skills
  const snapshot = {};

  // Base attributes
  const baseAttrs = ['力量','体型','体质','敏捷','外貌','教育','智力','意志','幸运'];
  for (const a of baseAttrs) {
    const v = seal.vars.intGet(mctx, a);
    snapshot[a] = v[1] ? v[0] : 0;
  }

  // All combat skills
  for (const s of ALL_COMBAT_SKILLS) {
    const v = seal.vars.intGet(mctx, s);
    snapshot[s] = v[1] ? v[0] : 0;
  }

  // Extra combat-relevant stats
  snapshot['闪避'] = getAttr(mctx, '闪避');
  snapshot['体格'] = getAttr(mctx, '体格', 0);
  snapshot['行动力'] = getAttr(mctx, '行动力') || getAttr(mctx, 'mov', 8);
  snapshot['体力'] = getAttr(mctx, '体力', 10);
  snapshot['体力上限'] = getAttr(mctx, '体力上限', 10);
  snapshot['魔力'] = getAttr(mctx, '魔力') || getAttr(mctx, 'mp', 10);
  snapshot['魔力上限'] = getAttr(mctx, '魔力上限') || getAttr(mctx, 'mp', 10);
  snapshot['理智'] = getAttr(mctx, '理智') || getAttr(mctx, 'san', 50);
  snapshot['伤害值'] = getStrAttr(mctx, '伤害值');
  snapshot['伤害贯穿'] = (seal.vars.intGet(mctx, '伤害贯穿'))[1] ? (seal.vars.intGet(mctx, '伤害贯穿'))[0] : undefined;
  snapshot['致死骰'] = (seal.vars.intGet(mctx, '致死骰'))[1] ? (seal.vars.intGet(mctx, '致死骰'))[0] : undefined;

  const key = `bta_snapshot_${mctx.player.userId}`;
  ext.storageSet(key, JSON.stringify(snapshot));

  // Mark combat as active
  seal.vars.intSet(mctx, '$gCombatActive', 1);

  // Init combat HP
  const groupId = mctx.group ? mctx.group.groupId : 'private';
  initCombatHP(groupId, mctx.player.userId, mctx, mctx.player.userId, mctx);

  const pn = seal.format(mctx, '{$t玩家}');
  let out = `${pn} 的战斗属性已同步！\n`;
  out += `战斗标记已开启，.st 修改的属性将实时生效。\n`;
  out += `已同步属性：\n`;
  out += `力量${snapshot['力量']} 体型${snapshot['体型']} 体质${snapshot['体质']} 敏捷${snapshot['敏捷']}\n`;
  out += `斗殴${snapshot['斗殴']} 闪避${snapshot['闪避']} 格斗${snapshot['格斗']}\n`;
  out += `HP ${snapshot['体力']}/${snapshot['体力上限']}  MP ${snapshot['魔力']}/${snapshot['魔力上限']}  SAN ${snapshot['理智']}`;
  seal.replyToSender(ctx, msg, out);
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  .bta end  — 战斗结束后完成同步
//  Flushes combat HP, clears pending attacks, restores state.
// ============================================================
const cmdBtaEnd = seal.ext.newCmdItemInfo();
cmdBtaEnd.name = 'bta end';
cmdBtaEnd.help =
  '.bta end // 战斗结束后完成属性同步\n' +
  '将战斗HP写回人物卡，清除待处理攻击，关闭战斗标记。';
cmdBtaEnd.solve = (ctx, msg, cmdArgs) => {
  const mctx = seal.getCtxProxyFirst(ctx, cmdArgs) || ctx;

  // Flush combat HP back to character card
  const groupId = mctx.group ? mctx.group.groupId : 'private';
  flushCombatHP(groupId, mctx.player.userId, mctx);

  // Clear pending attack
  const pendingKey = `pending_atk_${groupId}`;
  ext.storageSet(pendingKey, '');

  // Clear snapshot
  const snapKey = `bta_snapshot_${mctx.player.userId}`;
  ext.storageSet(snapKey, '');

  // Mark combat as inactive
  seal.vars.intSet(mctx, '$gCombatActive', 0);

  const pn = seal.format(mctx, '{$t玩家}');
  seal.replyToSender(ctx, msg, `${pn} 的战斗已结束，属性已同步回人物卡。`);
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  .stb <+/-value> @target  — 战斗内修改HP
//  Reads current combat HP, applies delta, writes back.
//  Examples: .stb -5 @target  /  .stb 10 @target  /  .stb +3
// ============================================================
const cmdStb = seal.ext.newCmdItemInfo();
cmdStb.name = 'stb';
cmdStb.help =
  '.stb <值> @目标 // 战斗内直接修改HP\n' +
  '.stb +5  // 回复5点HP\n' +
  '.stb -3  // 扣除3点HP\n' +
  '.stb 10  // 将HP设为10';
cmdStb.allowDelegate = true;
cmdStb.solve = (ctx, msg, cmdArgs) => {
  const mctx = seal.getCtxProxyFirst(ctx, cmdArgs) || ctx;
  const args = cmdArgs.cleanArgs.split(/\s+/).filter(a => a.length > 0);
  if (args.length < 1) {
    seal.replyToSender(ctx, msg, '用法：.stb <值> 或 .stb +<值> 或 .stb -<值> @目标');
    return seal.ext.newCmdExecuteResult(true);
  }

  const valStr = args[0];
  const groupId = mctx.group ? mctx.group.groupId : 'private';
  const hpStore = getCombatHP(groupId);
  let curHP = hpStore[mctx.player.userId];
  if (curHP === undefined) {
    // Not in combat store yet — init from card
    const cv = seal.vars.intGet(mctx, '体力');
    curHP = cv[1] ? cv[0] : 10;
  }

  let newHP;
  if (valStr.startsWith('+')) {
    newHP = curHP + (parseInt(valStr.slice(1)) || 0);
  } else if (valStr.startsWith('-')) {
    newHP = curHP - (parseInt(valStr.slice(1)) || 0);
  } else {
    newHP = parseInt(valStr) || curHP;
  }
  newHP = Math.max(0, newHP);

  hpStore[mctx.player.userId] = newHP;
  setCombatHP(groupId, hpStore);

  const pn = seal.format(mctx, '{$t玩家}');
  const delta = newHP - curHP;
  const deltaStr = delta >= 0 ? `+${delta}` : `${delta}`;
  seal.replyToSender(ctx, msg,
    `${pn} 战斗HP: ${curHP} → ${newHP} (${deltaStr})`);
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  .bta / .btab / .btap  — 攻击指令
//  Syntax: .bta [skill] [damage_dice] [penetration 0/1] [lethality 0/1] @target [/a/b/c]
// ============================================================
function makeBtaCmd(baseName) {
  const cmd = seal.ext.newCmdItemInfo();
  cmd.name = baseName;
  cmd.help =
    `.bta <技能> [伤害骰] [贯穿0/1] [致死0/1] [n#] @目标 [/a/b/c]\n` +
    `n# 表示攻击次数（如 3# = 连击3次），可放在任意位置\n` +
    `近战技能 → 等待目标 .e 反应（一次反应应对全部攻击）；远程技能 → 直接结算\n` +
    `.btab ...  // 奖励骰\n` +
    `.btap ...  // 惩罚骰\n` +
    `.btab2 ... // 2个奖励骰（以此类推）`;
  cmd.allowDelegate = true;  // mctx=@对象, ctx=自身
  cmd.solve = (ctx, msg, cmdArgs) => {
    // ctx = 自身(攻击者), mctx = 对方(目标, 第一个@的人)
    const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);

    if (cmdArgs.at.length === 0) {
      seal.replyToSender(ctx, msg,
        '错误：.bta 必须 @ 一个目标！\n' +
        '格式：.bta <技能> [伤害骰] [贯穿] [致死] @目标');
      return seal.ext.newCmdExecuteResult(true);
    }

    // Parse bonus/penalty suffix from command name
    const cmdName = cmdArgs.command.toLowerCase();
    let bpSuffix = '';
    if (cmdName.startsWith('btab')) bpSuffix = 'b' + (cmdName.substring(4) || '');
    else if (cmdName.startsWith('btap')) bpSuffix = 'p' + (cmdName.substring(4) || '');

    // Parse positional arguments
    let args = cmdArgs.cleanArgs.split(/\s+/).filter(a => a.length > 0);

    // --- Extract n# count from args (any position) ---
    let atkCount = 1;
    args = args.filter(a => {
      const m = a.match(/^(\d+)#$/);
      if (m) { atkCount = Math.max(1, Math.min(20, parseInt(m[1]))); return false; }
      return true;
    });

    let skillName, skillValue, displaySkillName, effectiveSkill;
    let weaponSuffix = '';
    let damageDice = '';
    let ai = 0;            // index into args for remaining params
    let usedDiceAsSkill = false;

    // --- Determine skill ---
    if (args.length < 1) {
      const best = getBestMeleeSkill(ctx);
      skillName = best.name;
      skillValue = best.value;
      displaySkillName = best.name;
      effectiveSkill = best.value;
    }
    else if (/^\d*d\d+/i.test(args[0]) &&
             (args.length < 2 || !/\d*d\d+/i.test(args[1]))) {
      damageDice = normalizeDice(args[0]);
      const best = getBestMeleeSkill(ctx);
      skillName = best.name;
      skillValue = best.value;
      displaySkillName = best.name;
      effectiveSkill = best.value;
      usedDiceAsSkill = true;
    }
    else {
      skillName = args[0];
      weaponSuffix = getWeaponSuffix(skillName);
      const skillParsed = parseSkillValue(ctx, skillName);
      skillValue = skillParsed.value;
      displaySkillName = skillParsed.name;
      if (!skillParsed.isRaw && skillValue <= 0) {
        seal.replyToSender(ctx, msg, `警告：未找到技能【${skillName}】的值，将使用默认值50`);
      }
      effectiveSkill = skillParsed.isRaw ? skillValue : Math.max(skillValue, 1);
    }

    // Parse optional: damage_dice, penetration, lethality
    ai = usedDiceAsSkill ? 1 : (args.length >= 1 ? 1 : 0);
    let penetration = -1;
    let lethality = -1;
    let dmgAdvantage = false;
    let dmgDisadvantage = false;

    if (ai < args.length) {
      let cand = args[ai];
      if (!/^\/[a-c]$/.test(cand)) {
        if (cand.endsWith('优势')) { dmgAdvantage = true; cand = cand.slice(0, -2); }
        else if (cand.endsWith('劣势')) { dmgDisadvantage = true; cand = cand.slice(0, -2); }

        if (/d/i.test(cand)) { damageDice = normalizeDice(cand); ai++; }
        else if (/^\d+$/.test(cand)) { damageDice = cand; ai++; }
        else { damageDice = cand; ai++; }
      }
    }
    if (ai < args.length && /^[01]$/.test(args[ai])) { penetration = parseInt(args[ai]); ai++; }
    if (ai < args.length && /^[01]$/.test(args[ai])) { lethality = parseInt(args[ai]); ai++; }

    // Parse a/b/c sub-target designation
    let subTarget = '';
    if (ai < args.length && /^\/[a-c]$/.test(args[ai])) {
      subTarget = args[ai].slice(1); ai++;
    }

    // Fill defaults from attacker's character card (ctx)
    const dmgAttr = weaponSuffix ? `伤害值${weaponSuffix}` : '伤害值';
    if (!damageDice || damageDice === '伤害值') {
      let dmgStr = getStrAttr(ctx, dmgAttr);
      if (!dmgStr && weaponSuffix) dmgStr = getStrAttr(ctx, '伤害值');
      damageDice = dmgStr ? normalizeDice(dmgStr) : '1d4';
    }
    if (!/\d/.test(damageDice)) {
      const lookedUp = getStrAttr(ctx, damageDice);
      if (lookedUp && /\d/.test(lookedUp)) damageDice = normalizeDice(lookedUp);
      else { const rolled = rollDice(ctx, damageDice); damageDice = rolled > 0 ? String(rolled) : '1d4'; }
    }
    damageDice = normalizeDice(damageDice);

    const penAttr = weaponSuffix ? `伤害贯穿${weaponSuffix}` : '伤害贯穿';
    if (penetration === -1) {
      const pv = seal.vars.intGet(ctx, penAttr);
      penetration = pv[1] ? (pv[0] ? 1 : 0) : 1;
    }
    const lethAttr = weaponSuffix ? `致死骰${weaponSuffix}` : '致死骰';
    if (lethality === -1) {
      const lv = seal.vars.intGet(ctx, lethAttr);
      lethality = lv[1] ? (lv[0] ? 1 : 0) : 1;
    }

    // Roll attack(s) — one D100 per attack
    const attackerName = seal.format(ctx, '{$t玩家}');
    const targetName = seal.format(mctx, '{$t玩家}');
    const groupId = ctx.group ? ctx.group.groupId : 'private';
    initCombatHP(groupId, ctx.player.userId, ctx, mctx.player.userId, mctx);

    const atkResults = [];
    for (let n = 0; n < atkCount; n++) {
      const rollInfo = rollD100(ctx, bpSuffix);
      const roll = rollInfo.result;
      const rank = successRank(roll, effectiveSkill);
      atkResults.push({ roll, rank, detail: rollInfo.detail });
    }

    // Build combined result line
    let atkResultLine = `${attackerName}的【${displaySkillName}】`;
    if (atkCount > 1) atkResultLine += ` ×${atkCount}`;
    atkResultLine += ` 检定结果为：\n`;
    for (let n = 0; n < atkCount; n++) {
      const ar = atkResults[n];
      const bpD = ar.detail ? `, ${ar.detail}` : '';
      atkResultLine += `  #${n+1}: D100=${ar.roll}/${effectiveSkill}` +
        (bpD ? ` (${ar.roll}[D100=${ar.roll}${bpD}])` : '') +
        ` ${rankText(ctx, ar.rank)}\n`;
    }

    // Ranged: direct damage resolution per attack (no reaction possible)
    if (isRangedSkill(displaySkillName)) {
      let rangedOut = atkResultLine + `\n`;
      rangedOut += `（远程攻击，目标无法闪避/反击，直接结算伤害）\n\n`;
      let totalDmg = 0, hits = 0;
      for (let n = 0; n < atkCount; n++) {
        const ar = atkResults[n];
        if (ar.rank <= 0) { rangedOut += `#${n+1} ${rankText(ctx, ar.rank)}，不命中\n`; continue; }
        hits++;
        const crit = ar.rank >= 4 ? '大成功' : '';
        rangedOut += `#${n+1} 命中 ${rankText(ctx, ar.rank)}${crit ? ' '+crit : ''}\n`;
        const dmgVal = calcDamageAndSyncCard(mctx, ctx, mctx.player.userId, ctx.player.userId, groupId,
          ar.rank, ar.roll, damageDice, penetration, lethality,
          dmgAdvantage, dmgDisadvantage);
        totalDmg += dmgVal;
      }
      if (hits === 0) {
        rangedOut += `\n全部落空！`;
      } else {
        const hpStore = getCombatHP(groupId);
        rangedOut += `\n命中 ${hits}/${atkCount} 次，总伤害 ${totalDmg}`;
        rangedOut += `\n${targetName}剩余HP: ${hpStore[mctx.player.userId]}`;
      }
      seal.replyToSender(ctx, msg, rangedOut);
      return seal.ext.newCmdExecuteResult(true);
    }

    // Melee: store pending attacks array (even fumbles — defender may counter)
    const pendingKey = `pending_atk_${ctx.group ? ctx.group.groupId : 'private'}`;
    const restimV = seal.vars.intGet(ctx, '$gRestimMode');
    const attackerRestimMode = restimV[1] ? restimV[0] : 0;
    ext.storageSet(pendingKey, JSON.stringify({
      attackerName, attackerUserId: ctx.player.userId,
      skillName: displaySkillName, skillValue: effectiveSkill,
      atkResults, atkCount,
      damageDice, penetration, lethality,
      bpSuffix, dmgAdvantage, dmgDisadvantage,
      targetName, targetUserId: mctx.player.userId,
      groupId, subTarget, atkResultLine,
      attackerRestimMode: attackerRestimMode,
      ts: Date.now()
    }));

    // Output based on restim mode
    const restimMode = attackerRestimMode;
    const hasFumble = atkResults.some(a => a.rank === -2);
    const fumbleNote = hasFumble ? '（攻击方有大失败！反击等级+1）\n' : '';

    if (restimMode === 1) {
      const subLabel = subTarget ? `/${subTarget}` : '';
      seal.replyToSender(ctx, msg,
        `@${targetName}${subLabel} 请做出反应：\n` +
        fumbleNote +
        `.e 闪避 / .e d\n` +
        `.e 反击 [技能名=最高近战] [伤害骰] [贯穿gc/ngc] [致死] / .e c [...]`);
    } else {
      const subLabel = subTarget ? `${subTarget}的` : '';
      seal.replyToSender(ctx, msg,
        atkResultLine + `\n` +
        fumbleNote +
        `@${targetName} 请输入${subLabel}反应：\n` +
        `.e 闪避 / .e d\n` +
        `.e 反击 [技能名=最高近战] [伤害骰] [贯穿gc/ngc] [致死] / .e c [...]`);
    }
    return seal.ext.newCmdExecuteResult(true);
  };
  return cmd;
}

// ============================================================
//  .e / .eb / .ep  — 反应指令（闪避 / 反击）
//  Syntax: .e 闪避   OR   .e 反击 [skill] [dmg] [贯穿/非贯穿/gc/ngc] [致死]
//  Suffix: .e 闪避a / .e 反击a 斗殴a ...  (use character a's skills)
// ============================================================
function makeECmd(baseName) {
  const cmd = seal.ext.newCmdItemInfo();
  cmd.name = baseName;
  cmd.help =
    '.e 闪避 / .e d  // 闪避（成功等级稀释攻击方）\n' +
    '.e 反击 [技能=最高近战技能] [伤害骰] [贯穿gc/ngc] [致死]  /  .e c [...]  // 反击\n' +
    '.eb / .ep // 奖惩骰变体';
  cmd.allowDelegate = true;
  cmd.solve = (ctx, msg, cmdArgs) => {
    // ctx = 自身(反应者)
    const defCtx = ctx;

    // Load pending attack
    const pendingKey = `pending_atk_${ctx.group ? ctx.group.groupId : 'private'}`;
    const raw = ext.storageGet(pendingKey);
    if (!raw) {
      seal.replyToSender(ctx, msg, '当前没有待处理的攻击！请先由攻击方使用 .bta 发起攻击。');
      return seal.ext.newCmdExecuteResult(true);
    }
    let pending;
    try { pending = JSON.parse(raw); } catch (e) {
      seal.replyToSender(ctx, msg, '待处理攻击数据损坏，请重新 .bta。');
      ext.storageSet(pendingKey, '');
      return seal.ext.newCmdExecuteResult(true);
    }

    // Identity check: only the targeted player can respond
    if (pending.targetUserId && ctx.player.userId !== pending.targetUserId) {
      seal.replyToSender(ctx, msg, `该攻击的目标是 ${pending.targetName}，不是你！`);
      return seal.ext.newCmdExecuteResult(true);
    }

    // Parse bonus/penalty
    const cmdName = cmdArgs.command.toLowerCase();
    let bpSuffix = '';
    if (cmdName.startsWith('eb')) bpSuffix = 'b' + (cmdName.substring(2) || '');
    else if (cmdName.startsWith('ep')) bpSuffix = 'p' + (cmdName.substring(2) || '');

    // Parse reaction type
    const args = cmdArgs.cleanArgs.split(/\s+/).filter(a => a.length > 0);
    if (args.length < 1) {
      seal.replyToSender(ctx, msg, '请指定反应类型：\n.e 闪避 或 .e d\n.e 反击 [技能名] 或 .e c [技能名]');
      return seal.ext.newCmdExecuteResult(true);
    }

    const reactType = args[0];
    const isDodge = reactType === '闪避' || reactType === 'd' || reactType === '闪' || reactType === 'dodge';
    const isCounter = reactType === '反击' || reactType === 'c' || reactType === 'counter' || reactType === '反';

    if (!isDodge && !isCounter) {
      seal.replyToSender(ctx, msg, '不支持的反应类型。请使用：闪避/d 或 反击/c');
      return seal.ext.newCmdExecuteResult(true);
    }

    // Gather reaction parameters
    let reactSkillName, reactSkillValue;
    let reactDmgDice = '';
    let reactPen = pending.penetration;
    let reactLeth = pending.lethality;

    if (isDodge) {
      reactSkillName = '闪避';
      reactSkillValue = getAttr(defCtx, reactSkillName);
      if (reactSkillValue <= 0) {
        const dex = getAttr(defCtx, '敏捷', 50);
        reactSkillValue = Math.floor(dex / 2);
        if (reactSkillValue <= 0) reactSkillValue = 25;
      }
    } else {
      // Counter-attack: default to highest-value melee combat skill
      let argIdx = 1;

      // Find the highest melee combat skill on the defender's card
      const best = getBestMeleeSkill(defCtx);
      reactSkillName = best.name;
      reactSkillValue = best.value;

      if (argIdx < args.length) {
        const cand = args[argIdx];
        // Skip pen/leth keywords (pure numbers handled below)
        const isPenKW = (cand === '贯穿' || cand === '非贯穿' || cand === 'gc' || cand === 'ngc');

        // Pure number → raw skill value (e.g. ".e c 70")
        if (/^\d+$/.test(cand)) {
          reactSkillName = cand;
          reactSkillValue = parseInt(cand);
          argIdx++;
        }
        // Contains 'd' → damage dice (e.g. ".e c 3d6"), keep highest melee as skill
        else if (/d/i.test(cand)) {
          // skill stays as best melee; damage parsed below
        }
        // Non-numeric word that isn't a pen keyword → skill name
        else if (!isPenKW) {
          reactSkillName = cand;
          argIdx++;
          // Read skill value from card
          const sv = getAttr(defCtx, reactSkillName);
          if (sv > 0) reactSkillValue = sv;
          else {
            const p = parseSkillValue(defCtx, reactSkillName);
            reactSkillName = p.name;
            reactSkillValue = Math.max(p.value, 50);
          }
        }
      }

      // Damage dice for counter — only dice expressions (containing 'd')
      if (argIdx < args.length && /d/i.test(args[argIdx])) {
        reactDmgDice = normalizeDice(args[argIdx]); argIdx++;
      }
      // Default: defender's own 伤害值
      if (!reactDmgDice) reactDmgDice = getStrAttr(defCtx, '伤害值');
      if (!reactDmgDice) reactDmgDice = pending.damageDice;
      reactDmgDice = normalizeDice(reactDmgDice);

      // Penetration
      if (argIdx < args.length) {
        const pa = args[argIdx];
        if (pa === '贯穿' || pa === 'gc') { reactPen = 1; argIdx++; }
        else if (pa === '非贯穿' || pa === 'ngc') { reactPen = 0; argIdx++; }
        else if (pa === '0') { reactPen = 0; argIdx++; }
        else if (pa === '1') { reactPen = 1; argIdx++; }
      }
      if (argIdx < args.length && /^[01]$/.test(args[argIdx])) { reactLeth = parseInt(args[argIdx]); }
    }

    // --- Multi-attack resolution: each attack gets its own reaction roll ---
    const atkResults = pending.atkResults || [{ roll: pending.attackRoll, rank: pending.attackRank, detail: pending.bpDetail || '' }];
    const atkCount = pending.atkCount || 1;
    const gid = pending.groupId || (ctx.group ? ctx.group.groupId : 'private');
    const attackerName = pending.attackerName;
    const defenderName = seal.format(defCtx, '{$t玩家}');

    let out = '';
    const attackerRestim = pending.attackerRestimMode || 0;
    if (attackerRestim === 1) {
      out += pending.atkResultLine + '\n\n';
    }

    const reactLabel = isDodge ? '闪避' : `反击:${reactSkillName}`;
    out += `对手 ${defenderName}的反应：【${reactLabel}】×${atkCount}：\n`;

    // Roll one reaction per attack, resolve independently
    let atkHits = 0, atkTotalDmg = 0, defHits = 0, defTotalDmg = 0;
    for (let n = 0; n < atkCount; n++) {
      const ar = atkResults[n];

      // Roll reaction for this attack
      const reactRollInfo = rollD100(defCtx, bpSuffix);
      const reactRoll = reactRollInfo.result;
      const rawReactRank = successRank(reactRoll, reactSkillValue);
      const reactBpDetail = reactRollInfo.detail ? `, ${reactRollInfo.detail}` : '';

      let effAtk = ar.rank;
      let effReact = rawReactRank;

      // Reaction modifiers
      if (isDodge) {
        if (rawReactRank > 1) effAtk -= (rawReactRank - 1);
        if (rawReactRank === -2) effAtk += (effAtk === -1) ? 2 : 1;
      }
      if (isCounter) {
        if (rawReactRank === -2) effAtk += (effAtk === -1) ? 2 : 1;
        if (effAtk === -2) effReact = Math.min(4, effReact + 1);
      }
      effAtk = Math.max(-2, Math.min(4, effAtk));

      // Determine winner for this attack
      const atkPass = effAtk > 0;
      const defPass = effReact > 0;
      let winner = 0;
      if (atkPass && defPass) {
        if (effAtk > effReact) winner = 1;
        else if (effAtk < effReact) winner = 2;
        else winner = isDodge ? 2 : 1;
      } else if (atkPass && !defPass) winner = 1;
      else if (!atkPass && defPass) winner = 2;

      out += `  #${n+1}: 攻${rankText(ctx, ar.rank)} vs 防D100=${reactRoll}/${reactSkillValue}` +
        (reactBpDetail ? ` (${reactRoll}[D100=${reactRoll}${reactBpDetail}])` : '') +
        ` ${rankText(ctx, rawReactRank)} → `;

      if (winner === 1) {
        atkHits++;
        const dmg = calcDamageAndSyncCard(ctx, ctx, pending.targetUserId, pending.attackerUserId, gid,
          effAtk, ar.roll, pending.damageDice, pending.penetration, pending.lethality,
          pending.dmgAdvantage, pending.dmgDisadvantage);
        atkTotalDmg += dmg;
        out += `攻方命中！(+${dmg})\n`;
      } else if (winner === 2 && isCounter) {
        defHits++;
        const dmg = calcDamageValue(ctx, pending.attackerUserId, pending.targetUserId, gid,
          effReact, reactRoll, reactDmgDice, reactPen, reactLeth,
          false, false);
        defTotalDmg += dmg;
        out += `反击命中！(+${dmg})\n`;
      } else if (winner === 2 && isDodge) {
        out += `闪避成功\n`;
      } else {
        out += `未通过\n`;
      }
    }

    // Summary
    out += `\n`;
    if (atkHits > 0) {
      out += `${attackerName} 命中 ${atkHits}/${atkCount} 次，总伤害 ${atkTotalDmg}`;
      const hpStore = getCombatHP(gid);
      if (hpStore[pending.targetUserId] !== undefined) {
        out += `\n${pending.targetName}剩余HP: ${hpStore[pending.targetUserId]}`;
      }
    }
    if (defHits > 0) {
      if (atkHits > 0) out += `\n`;
      out += `${defenderName} 反击命中 ${defHits}/${atkCount} 次，总伤害 ${defTotalDmg}`;
      const hpStore = getCombatHP(gid);
      if (hpStore[pending.attackerUserId] !== undefined) {
        out += `\n${attackerName}剩余HP: ${hpStore[pending.attackerUserId]}`;
      }
    }
    if (atkHits === 0 && defHits === 0) {
      out += `无人得手！`;
    }

    ext.storageSet(pendingKey, '');
    seal.replyToSender(ctx, msg, out);
    return seal.ext.newCmdExecuteResult(true);
  };
  return cmd;
}

// ============================================================
//  .hs  — 魔法少女变身
//  变身后所有战斗类技能（近战+射击+投掷+爆破+炮术）只要
//  人物卡属性表中存在，均 +20。
// ============================================================
const cmdHs = seal.ext.newCmdItemInfo();
cmdHs.name = 'hs';
cmdHs.help =
  '.hs // 魔法少女变身（自动 .btastart）\n' +
  'HP ×(5+level)  MP ×(2+0.5×level)  APP+60(上限80)\n' +
  '全部战斗类技能（只要属性表有值）+20  体格+1  行动力+2\n' +
  '变身同时自动开启战斗同步（等同于 .btastart）';
cmdHs.allowDelegate = true;
cmdHs.solve = (ctx, msg, cmdArgs) => {
  const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);

  const alreadyV = seal.vars.intGet(mctx, '$gHsTransformed');
  if (alreadyV[1] && alreadyV[0]) {
    seal.replyToSender(ctx, msg, '已经处于变身状态！请先 .unh 解除变身。');
    return seal.ext.newCmdExecuteResult(true);
  }

  const lvV = seal.vars.intGet(mctx, '等级');
  const level = (lvV[1] && lvV[0]) ? lvV[0] : 1;

  const origHP  = getAttr(mctx, '体力上限') || getAttr(mctx, 'hp') || 10;
  const origMP  = getAttr(mctx, '魔力上限') || getAttr(mctx, '魔力') || getAttr(mctx, 'mp') || 10;
  const origAPP = getAttr(mctx, '外貌') || getAttr(mctx, 'app') || 50;
  const origDodge    = getAttr(mctx, '闪避', 25);
  const origBuild = getAttr(mctx, '体格', 0);
  const origMOV   = getAttr(mctx, '行动力') || getAttr(mctx, 'mov', 8);
  const origSAN   = getAttr(mctx, '理智') || getAttr(mctx, 'san', 50);
  const origCON   = getAttr(mctx, '体质') || getAttr(mctx, 'con', 50);
  const origSIZ   = getAttr(mctx, '体型') || getAttr(mctx, 'siz', 50);
  const origCM    = getAttr(mctx, 'cm') || getAttr(mctx, '克苏鲁神话', 0);

  const curHP = getAttr(mctx, '体力', origHP);
  const curMP = getAttr(mctx, '魔力', origMP);

  // Collect original values for ALL combat skills that exist on the character card
  const origCombatSkills = {};
  const boostedSkills = [];   // for display
  for (const s of ALL_COMBAT_SKILLS) {
    const v = seal.vars.intGet(mctx, s);
    if (v[1]) {
      origCombatSkills[s] = v[0];
      const newVal = v[0] + 20;
      if (newVal !== v[0]) boostedSkills.push({ name: s, orig: v[0], now: newVal });
    }
  }

  // Also save orig dodge separately (not in ALL_COMBAT_SKILLS)
  // 闪避 is handled separately

  const key = `hs_orig_${mctx.player.userId}`;
  ext.storageSet(key, JSON.stringify({
    hpMax: origHP, mpMax: origMP, app: origAPP,
    dodge: origDodge,
    build: origBuild, mov: origMOV, san: origSAN, con: origCON,
    siz: origSIZ, cm: origCM,
    curHP: curHP, curMP: curMP, level: level,
    combatSkills: origCombatSkills
  }));

  const newHPmax = Math.floor(origHP * (5 + level));
  const newMPmax = Math.floor(origMP * (2 + 0.5 * level));
  const newAPP = Math.min(origAPP + 60, 80);
  const newDodge = Math.min(origDodge + 20, 80);
  const newBuild = origBuild + 1;
  const newMOV   = origMOV + 2;
  const newDB = dbFromBuild(newBuild);

  seal.vars.intSet(mctx, '体力上限', newHPmax);
  seal.vars.intSet(mctx, '体力', newHPmax);
  seal.vars.intSet(mctx, '魔力上限', newMPmax);
  seal.vars.intSet(mctx, '魔力', newMPmax);
  seal.vars.intSet(mctx, '外貌', newAPP);
  seal.vars.intSet(mctx, '闪避', newDodge);
  seal.vars.intSet(mctx, '体格', newBuild);
  seal.vars.intSet(mctx, '行动力', newMOV);
  seal.vars.intSet(mctx, '$gHsTransformed', 1);
  seal.vars.intSet(mctx, '$gHsSpellCount', 0);
  seal.vars.intSet(mctx, '$gHsCombatFlag', 0);

  // Apply +20 (max 80) to ALL combat skills that exist in attr table
  for (const b of boostedSkills) {
    seal.vars.intSet(mctx, b.name, b.now);
  }

  // Auto .btastart: mark combat active, init combat HP
  seal.vars.intSet(mctx, '$gCombatActive', 1);
  const hsGid = mctx.group ? mctx.group.groupId : 'private';
  initCombatHP(hsGid, mctx.player.userId, mctx, mctx.player.userId, mctx);

  const pn = seal.format(mctx, '{$t玩家}');
  let out = `${pn} 进行了魔法少女变身！\n\n`;
  out += `HP : ${origHP} → ${newHPmax}  (×${(5+level)})\n`;
  out += `MP : ${origMP} → ${newMPmax}  (×${(2+0.5*level).toFixed(1)})\n`;
  out += `APP: ${origAPP} → ${newAPP}  (+60, max80)\n`;
  out += `闪避: ${origDodge} → ${newDodge}  (+20, max80)\n`;
  out += `体格: ${origBuild} → ${newBuild}  (+1, DB→${newDB})\n`;
  out += `行动力: ${origMOV} → ${newMOV}  (+2)\n`;
  out += `\n（战斗同步已自动开启，.st 修改属性将实时生效）\n`;
  if (boostedSkills.length > 0) {
    out += `\n【战斗技能】（+20）:\n`;
    // Split into lines: ~6 skills per line for readability
    const names = boostedSkills.map(b => `${b.name}: ${b.orig}→${b.now}`);
    for (let i = 0; i < names.length; i += 4) {
      out += names.slice(i, i + 4).join('  ') + '\n';
    }
  }
  seal.replyToSender(ctx, msg, out);
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  .unh  — 解除变身（.setab 0 模式：不自动结算成长）
// ============================================================
const cmdUnh = seal.ext.newCmdItemInfo();
cmdUnh.name = 'unh';
cmdUnh.help =
  '.unh // 解除魔法少女变身\n' +
  '恢复原始属性。根据SAN等级触发不同SC与CON检定。\n' +
  '（.setab 0 模式下不自动结算升级）';
cmdUnh.allowDelegate = true;
cmdUnh.solve = (ctx, msg, cmdArgs) => {
  const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);

  const alreadyV = seal.vars.intGet(mctx, '$gHsTransformed');
  if (!alreadyV[1] || !alreadyV[0]) {
    seal.replyToSender(ctx, msg, '当前未处于变身状态！');
    return seal.ext.newCmdExecuteResult(true);
  }

  const key = `hs_orig_${mctx.player.userId}`;
  const raw = ext.storageGet(key);
  if (!raw) {
    seal.replyToSender(ctx, msg, '未找到变身前的数据记录，将仅清除变身标记。');
    seal.vars.intSet(mctx, '$gHsTransformed', 0);
    return seal.ext.newCmdExecuteResult(true);
  }

  let orig;
  try { orig = JSON.parse(raw); } catch (e) {
    seal.replyToSender(ctx, msg, '变身数据损坏。');
    seal.vars.intSet(mctx, '$gHsTransformed', 0);
    return seal.ext.newCmdExecuteResult(true);
  }

  const curMPV = seal.vars.intGet(mctx, '魔力');
  const curMP = curMPV[1] ? curMPV[0] : orig.mpMax;

  // Prefer combat HP (战斗内HP) over card HP for post-transform calculation
  const gid = mctx.group ? mctx.group.groupId : 'private';
  const combatHP = getCombatHP(gid);
  const combatCurHP = combatHP[mctx.player.userId];
  const cardHPV = seal.vars.intGet(mctx, '体力');
  let curHP;
  if (combatCurHP !== undefined) {
    curHP = combatCurHP;
  } else {
    curHP = cardHPV[1] ? cardHPV[0] : orig.hpMax;
  }

  const restoredHP = Math.min(Math.ceil(curHP / (orig.level + 5)) + 2, orig.hpMax);
  const restoredMP = Math.min(curMP, orig.mpMax);

  // SC & CON check with full SAN tiers
  const spellCountV = seal.vars.intGet(mctx, '$gHsSpellCount');
  const combatFlagV = seal.vars.intGet(mctx, '$gHsCombatFlag');
  const spellCount = spellCountV[1] ? spellCountV[0] : 0;
  const combatFlag = combatFlagV[1] ? combatFlagV[0] : 0;
  let scOut = '';

  if ((spellCount > 2) || (combatFlag > 0)) {
    const curSAN = getAttr(mctx, '理智') || orig.san || 50;
    const curCON = getAttr(mctx, '体质') || orig.con || 50;
    const curCM  = getAttr(mctx, 'cm') || getAttr(mctx, '克苏鲁神话') || orig.cm || 0;

    let scSuccessExpr, scFailExpr, conFailExpr, conSuccessExpr;
    let halveLosses = false;

    if (curSAN < (curCM || 0) && curCM > 0) halveLosses = true;

    if (curSAN < 20) {
      scSuccessExpr = '1d3'; scFailExpr = '1d8';
      conFailExpr = '1d6'; conSuccessExpr = '1d3';
    } else if (curSAN < 30) {
      scSuccessExpr = '1'; scFailExpr = '1d6';
      conFailExpr = '1d3+1'; conSuccessExpr = '0';
    } else {
      scSuccessExpr = '0'; scFailExpr = '1d5';
      conFailExpr = '1d3'; conSuccessExpr = '0';
    }

    const sanCheck = rollDice(mctx, '1d100');
    if (sanCheck > curSAN) {
      let sanLoss = rollDice(mctx, scFailExpr);
      if (halveLosses) sanLoss = Math.floor(sanLoss / 2);
      seal.vars.intSet(mctx, '理智', Math.max(0, curSAN - sanLoss));
      scOut += `\nSC检定：D100=${sanCheck}/${curSAN} 失败，扣除理智 ${sanLoss} 点（${curSAN}→${Math.max(0, curSAN - sanLoss)}）。`;
    } else {
      let sanLoss = rollDice(mctx, scSuccessExpr);
      if (halveLosses) sanLoss = Math.floor(sanLoss / 2);
      if (sanLoss > 0) {
        seal.vars.intSet(mctx, '理智', Math.max(0, curSAN - sanLoss));
        scOut += `\nSC检定：D100=${sanCheck}/${curSAN} 成功，仍扣除理智 ${sanLoss} 点（${curSAN}→${Math.max(0, curSAN - sanLoss)}）。`;
      } else {
        scOut += `\nSC检定：D100=${sanCheck}/${curSAN} 成功，无需扣除理智。`;
      }
    }

    const conCheck = rollDice(mctx, '1d100');
    if (conCheck > curCON) {
      let conLoss = rollDice(mctx, conFailExpr);
      if (halveLosses) conLoss = Math.floor(conLoss / 2);
      const newCON = Math.max(0, curCON - conLoss);
      seal.vars.intSet(mctx, '体质', newCON);
      scOut += `\n体质检定：D100=${conCheck}/${curCON} 失败，永久减少体质${conLoss}点（${curCON}→${newCON}）。`;

      const curSIZ = getAttr(mctx, '体型') || orig.siz || 50;
      const newHPMax = Math.floor((newCON + curSIZ) / 10);
      seal.vars.intSet(mctx, '体力上限', newHPMax);
      const curHpAfter = seal.vars.intGet(mctx, '体力');
      if (curHpAfter[1] && curHpAfter[0] > newHPMax) {
        seal.vars.intSet(mctx, '体力', newHPMax);
        scOut += `\n最大生命值重算：(CON${newCON}+SIZ${curSIZ})/10=${newHPMax}。`;
      }
    } else {
      let conLoss = rollDice(mctx, conSuccessExpr);
      if (halveLosses) conLoss = Math.floor(conLoss / 2);
      if (conLoss > 0) {
        const newCON = Math.max(0, curCON - conLoss);
        seal.vars.intSet(mctx, '体质', newCON);
        scOut += `\n体质检定：D100=${conCheck}/${curCON} 成功，仍扣除体质${conLoss}点（${curCON}→${newCON}）。`;
        const curSIZ = getAttr(mctx, '体型') || orig.siz || 50;
        const newHPMax = Math.floor((newCON + curSIZ) / 10);
        seal.vars.intSet(mctx, '体力上限', newHPMax);
        const curHpAfter = seal.vars.intGet(mctx, '体力');
        if (curHpAfter[1] && curHpAfter[0] > newHPMax) {
          seal.vars.intSet(mctx, '体力', newHPMax);
          scOut += `\n最大生命值重算：(CON${newCON}+SIZ${curSIZ})/10=${newHPMax}。`;
        }
      } else {
        scOut += `\n体质检定：D100=${conCheck}/${curCON} 成功。`;
      }
    }
  }

  // Flush combat HP back to character card + auto .bta end
  flushCombatHP(gid, mctx.player.userId, mctx);
  // Auto .bta end: clear pending attack & combat flag
  const pendingKey = `pending_atk_${gid}`;
  ext.storageSet(pendingKey, '');
  seal.vars.intSet(mctx, '$gCombatActive', 0);

  // Restore original attributes
  seal.vars.intSet(mctx, '体力上限', orig.hpMax);
  seal.vars.intSet(mctx, '体力', restoredHP);
  seal.vars.intSet(mctx, '魔力上限', orig.mpMax);
  seal.vars.intSet(mctx, '魔力', restoredMP);
  seal.vars.intSet(mctx, '外貌', orig.app);
  seal.vars.intSet(mctx, '闪避', orig.dodge);
  seal.vars.intSet(mctx, '体格', orig.build);
  seal.vars.intSet(mctx, '行动力', orig.mov);
  seal.vars.intSet(mctx, '$gHsTransformed', 0);
  seal.vars.intSet(mctx, '$gHsSpellCount', 0);
  seal.vars.intSet(mctx, '$gHsCombatFlag', 0);

  // Restore ALL combat skills to their original values
  if (orig.combatSkills) {
    for (const s of ALL_COMBAT_SKILLS) {
      if (orig.combatSkills[s] !== undefined) {
        seal.vars.intSet(mctx, s, orig.combatSkills[s]);
      }
    }
  } else {
    // Backward compatibility: old storage format
    if (orig.brawl !== undefined) seal.vars.intSet(mctx, '斗殴', orig.brawl);
    if (orig.firearms !== undefined) seal.vars.intSet(mctx, '射击', orig.firearms);
  }

  ext.storageSet(key, '');

  const pn = seal.format(mctx, '{$t玩家}');
  let unhsOut = `${pn} 解除了魔法少女变身！\n\n` +
    `HP: ${curHP} → ${restoredHP}\n` +
    `MP: ${curMP} → ${restoredMP}\n` +
    `属性已恢复至变身前状态。` + scOut;
  seal.replyToSender(ctx, msg, unhsOut);
  return seal.ext.newCmdExecuteResult(true);
};

// ============================================================
//  Register all commands
// ============================================================
ext.cmdMap['setab']     = cmdSetab;
ext.cmdMap['setrestim'] = cmdSetrestim;
ext.cmdMap['bta']       = makeBtaCmd('bta');
ext.cmdMap['btab']      = makeBtaCmd('btab');
ext.cmdMap['btap']      = makeBtaCmd('btap');
ext.cmdMap['btab2']     = makeBtaCmd('btab2');
ext.cmdMap['btab3']     = makeBtaCmd('btab3');
ext.cmdMap['btap2']     = makeBtaCmd('btap2');
ext.cmdMap['btap3']     = makeBtaCmd('btap3');
ext.cmdMap['e']         = makeECmd('e');
ext.cmdMap['eb']        = makeECmd('eb');
ext.cmdMap['ep']        = makeECmd('ep');
ext.cmdMap['eb2']       = makeECmd('eb2');
ext.cmdMap['eb3']       = makeECmd('eb3');
ext.cmdMap['ep2']       = makeECmd('ep2');
ext.cmdMap['ep3']       = makeECmd('ep3');
ext.cmdMap['hs']        = cmdHs;
ext.cmdMap['unh']       = cmdUnh;
ext.cmdMap['btastart'] = cmdBtaStart;
ext.cmdMap['btaend']   = cmdBtaEnd;
ext.cmdMap['stb']      = cmdStb;

// Hook: track spell count / combat flag during transformation,
//       and real-time .st attribute sync during combat
ext.onCommandReceived = (ctx, msg, cmdArgs) => {
  // Use mctx (the @mentioned target) to read transformed/combat state,
  // because .hs / .bta start set flags on mctx, not ctx
  const mctx = seal.getCtxProxyFirst(ctx, cmdArgs);
  const cmd = cmdArgs.command.toLowerCase();

  // --- Transformed state tracking ---
  const transformedV = seal.vars.intGet(mctx, '$gHsTransformed');
  if (transformedV[1] && transformedV[0]) {
    if (cmd === 'bta' || cmd === 'btab' || cmd === 'btap' ||
        cmd === 'btab2' || cmd === 'btab3' || cmd === 'btap2' || cmd === 'btap3' ||
        cmd === 'e' || cmd === 'eb' || cmd === 'ep' ||
        cmd === 'eb2' || cmd === 'eb3' || cmd === 'ep2' || cmd === 'ep3') {
      const flagV = seal.vars.intGet(mctx, '$gHsCombatFlag');
      seal.vars.intSet(mctx, '$gHsCombatFlag', (flagV[1] ? flagV[0] : 0) + 1);
    }
    if (/^s\d/i.test(cmd) || cmd === 'cast' || cmd === 'spell') {
      const cntV = seal.vars.intGet(mctx, '$gHsSpellCount');
      seal.vars.intSet(mctx, '$gHsSpellCount', (cntV[1] ? cntV[0] : 0) + 1);
    }
  }

  // --- Real-time .st attribute sync during active combat ---
  const combatV = seal.vars.intGet(mctx, '$gCombatActive');
  if (combatV[1] && combatV[0] && mctx && mctx.player) {
    if (cmd === 'st') {
      const args = (cmdArgs.cleanArgs || '').trim();
      if (args) {
        const groupId = mctx.group ? mctx.group.groupId : 'private';
        // Match .st formats: "体力 5", "体力:5", "体力+2", "体力-3"
        let match = args.match(/^(.+?)[：:\s]+([+-]?\d+)$/);
        if (match) {
          const attrName = match[1].trim();
          const isHP = /^(体力|hp|HP)$/i.test(attrName);
          const isMP = /^(魔力|mp|MP)$/i.test(attrName);
          const isSAN = /^(理智|san|SAN)$/i.test(attrName);
          if (isHP || isMP || isSAN) {
            const delta = parseInt(match[2]);
            const hpStore = getCombatHP(groupId);
            const uid = mctx.player.userId;
            // Determine store key and current store value
            let storeKey, curVal;
            if (isHP) { storeKey = uid; curVal = hpStore[uid]; }
            else if (isMP) { storeKey = `mp_${uid}`; curVal = hpStore[storeKey]; }
            else { storeKey = `san_${uid}`; curVal = hpStore[storeKey]; }
            if (curVal === undefined) {
              // Not in store yet — read from card
              const cv = seal.vars.intGet(mctx, attrName);
              curVal = cv[1] ? cv[0] : (isSAN ? 50 : 10);
            }
            // If the arg starts with + or -, it's a relative change
            if (match[2].startsWith('+') || match[2].startsWith('-')) {
              hpStore[storeKey] = Math.max(0, curVal + delta);
            } else {
              hpStore[storeKey] = delta; // absolute set
            }
            setCombatHP(groupId, hpStore);
          }
        }
      }
    }
  }
};

console.log('[autocombat] 半自动战斗扩展 v0.4.0 已加载');
console.log('[autocombat] 指令: .setab .setrestim .btastart/.btaend .bta/.btab/.btap .e/.eb/.ep .hs .unh .stb');
