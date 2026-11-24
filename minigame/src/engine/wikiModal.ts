import {
  AUTOCHESS_ROLE_LABELS,
  resolveUnitWiki,
  type AutoChessAugment,
  type AutoChessCatalog,
  type AutoChessSynergyDef,
  type AutoChessUnitWiki,
} from '../net/autochessApi';
import {
  PALETTE,
  Stage,
  costColor,
  drawButton,
  drawClippedText,
  drawEmblemBadge,
  drawPill,
  fillRoundRect,
  strokeRoundRect,
} from './ui';

export type WikiTab = 'units' | 'synergies' | 'augments';

function wrapTextLines(
  ctx: WxCanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  font: string,
): string[] {
  ctx.font = font;
  const paragraphs = String(text || '').split('\n');
  const lines: string[] = [];
  for (const para of paragraphs) {
    if (!para) {
      lines.push('');
      continue;
    }
    let line = '';
    for (let i = 0; i < para.length; i += 1) {
      const ch = para[i];
      const test = line + ch;
      if (ctx.measureText(test).width > maxWidth && line.length > 0) {
        lines.push(line);
        line = ch;
      } else {
        line = test;
      }
    }
    if (line.length > 0) lines.push(line);
  }
  return lines;
}

function drawLines(
  ctx: WxCanvasRenderingContext2D,
  lines: string[],
  x: number,
  y: number,
  lineHeight: number,
  color: string,
  font: string,
): void {
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  for (let i = 0; i < lines.length; i += 1) {
    ctx.fillText(lines[i], x, y + i * lineHeight);
  }
}

export class WikiModal {
  private opened = false;
  private tab: WikiTab = 'units';
  private listScroll = 0;
  private detailScroll = 0;
  private selectedUnitSerial: string | null = null;
  private selectedSynergyId: string | null = null;
  private selectedAugmentId: string | null = null;

  open(tab: WikiTab = 'units', unitSerial?: string): void {
    this.opened = true;
    this.tab = tab;
    this.listScroll = 0;
    this.detailScroll = 0;
    this.selectedUnitSerial = unitSerial || null;
    this.selectedSynergyId = null;
    this.selectedAugmentId = null;
  }

  close(): void {
    this.opened = false;
  }

  isOpen(): boolean {
    return this.opened;
  }

  private clearDetail(): void {
    this.selectedUnitSerial = null;
    this.selectedSynergyId = null;
    this.selectedAugmentId = null;
    this.detailScroll = 0;
  }

  render(stage: Stage, catalog: AutoChessCatalog | null): void {
    if (!this.opened) return;
    const ctx = stage.ctx;

    fillRoundRect(ctx, 0, 0, 1280, 720, 0, 'rgba(6, 8, 16, 0.82)');
    stage.addHitRegion({ x: 0, y: 0, w: 1280, h: 720, onTap: () => this.close() });

    const mw = 1040;
    const mh = 610;
    const mx = (1280 - mw) / 2;
    const my = (720 - mh) / 2;
    fillRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.bgPanel);
    strokeRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.violet, 1.8);
    stage.addHitRegion({ x: mx, y: my, w: mw, h: mh, onTap: () => {} });

    const hasDetail = Boolean(
      this.selectedUnitSerial || this.selectedSynergyId || this.selectedAugmentId,
    );

    if (hasDetail) {
      drawButton(stage, ctx, { x: mx + 24, y: my + 14, w: 112, h: 34 }, '← 返回列表', () => {
        this.clearDetail();
      }, { fontSize: 13 });
      drawClippedText(
        ctx,
        '星序自走棋百科 · 详情',
        mx + 150,
        my + 31,
        420,
        PALETTE.textMain,
        '700 18px "PingFang SC", sans-serif',
      );
    } else {
      drawClippedText(
        ctx,
        '星序自走棋百科图鉴（点击条目查看详情）',
        mx + 24,
        my + 32,
        560,
        PALETTE.textMain,
        '700 19px "PingFang SC", sans-serif',
      );
    }

    drawButton(stage, ctx, { x: mx + mw - 56, y: my + 14, w: 40, h: 34 }, '✕', () => this.close(), {
      fontSize: 16,
    });

    if (!catalog) {
      drawClippedText(ctx, '正在加载图鉴数据…', mx + mw / 2, my + mh / 2, mw, PALETTE.textMuted, '15px "PingFang SC", sans-serif', 'center', 'middle');
      return;
    }

    if (this.selectedUnitSerial) {
      const unitWiki = resolveUnitWiki(catalog, this.selectedUnitSerial);
      if (unitWiki) {
        this.renderUnitDetail(stage, catalog, unitWiki, mx + 24, my + 62, mw - 48, mh - 80);
        return;
      }
      this.selectedUnitSerial = null;
    }

    if (this.selectedSynergyId) {
      const syn = catalog.synergies.find(s => s.id === this.selectedSynergyId);
      if (syn) {
        this.renderSynergyDetail(stage, catalog, syn, mx + 24, my + 62, mw - 48, mh - 80);
        return;
      }
      this.selectedSynergyId = null;
    }

    if (this.selectedAugmentId) {
      const aug = catalog.augments.find(a => a.id === this.selectedAugmentId);
      if (aug) {
        this.renderAugmentDetail(stage, aug, mx + 24, my + 62, mw - 48, mh - 80);
        return;
      }
      this.selectedAugmentId = null;
    }

    this.renderList(stage, catalog, mx, my, mw, mh);
  }

  private renderList(
    stage: Stage,
    cat: AutoChessCatalog,
    mx: number,
    my: number,
    mw: number,
    mh: number,
  ): void {
    const ctx = stage.ctx;
    const tabs: Array<[WikiTab, string]> = [
      ['units', `棋子图鉴 (${cat.units.length})`],
      ['synergies', `羁绊效果 (${cat.synergies.length})`],
      ['augments', `星序海克斯 (${cat.augments.length})`],
    ];
    tabs.forEach(([id, label], i) => {
      const active = this.tab === id;
      drawButton(stage, ctx, { x: mx + 24 + i * 168, y: my + 62, w: 158, h: 34 }, label, () => {
        this.tab = id;
        this.listScroll = 0;
      }, {
        fontSize: 13,
        bg: active ? PALETTE.violetDark : PALETTE.bgCard,
        border: active ? '#bba7ff' : PALETTE.border,
      });
    });

    const listRect = { x: mx + 24, y: my + 110, w: mw - 48, h: mh - 130 };
    const rows =
      this.tab === 'units'
        ? cat.units.length
        : this.tab === 'synergies'
          ? cat.synergies.length
          : cat.augments.length;
    const rowH = this.tab === 'units' ? 84 : 78;
    stage.addScrollZone({
      ...listRect,
      key: 'wiki-list-scroll',
      contentHeight: rows * (rowH + 10),
      getOffset: () => this.listScroll,
      onScroll: v => {
        this.listScroll = v;
      },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(listRect.x, listRect.y, listRect.w, listRect.h);
    ctx.clip();

    for (let i = 0; i < rows; i += 1) {
      const y = listRect.y + i * (rowH + 10) - this.listScroll;
      if (y + rowH < listRect.y || y > listRect.y + listRect.h) continue;

      fillRoundRect(ctx, listRect.x, y, listRect.w, rowH, 10, PALETTE.bgCard);
      strokeRoundRect(ctx, listRect.x, y, listRect.w, rowH, 10, PALETTE.border, 1);

      const visTop = Math.max(listRect.y, y);
      const visBottom = Math.min(listRect.y + listRect.h, y + rowH);

      if (this.tab === 'units') {
        const u = cat.units[i];
        const col = u.accent || costColor(u.cost);
        drawEmblemBadge(ctx, listRect.x + 36, y + 42, 22, u.emblem || 'star', col);
        drawClippedText(ctx, `${u.name} · ${u.cost}费 [${AUTOCHESS_ROLE_LABELS[u.role] || u.role}]`, listRect.x + 72, y + 22, 420, costColor(u.cost), '700 16px "PingFang SC", sans-serif');
        drawClippedText(ctx, `羁绊：${u.traits.join(' / ')} · 射程 ${u.range}`, listRect.x + 510, y + 22, 340, PALETTE.textSub, '13px "PingFang SC", sans-serif');
        drawClippedText(ctx, '查看详情 →', listRect.x + listRect.w - 18, y + 22, 100, PALETTE.cyan, '700 13px "PingFang SC", sans-serif', 'right', 'middle');
        drawClippedText(ctx, `${u.tag} — ${u.blurb}`, listRect.x + 72, y + 54, listRect.w - 92, PALETTE.textSub, '13px "PingFang SC", sans-serif');
        if (visBottom > visTop) {
          stage.addHitRegion({
            x: listRect.x,
            y: visTop,
            w: listRect.w,
            h: visBottom - visTop,
            onTap: () => {
              this.detailScroll = 0;
              this.selectedUnitSerial = u.serial;
            },
          });
        }
      } else if (this.tab === 'synergies') {
        const s = cat.synergies[i];
        const tierLabel = s.tiers.map(t => `${t.count}:${t.label}`).join(' · ');
        drawClippedText(ctx, `${s.name}（${tierLabel}）`, listRect.x + 18, y + 22, listRect.w - 140, PALETTE.gold, '700 15px "PingFang SC", sans-serif');
        drawClippedText(ctx, '查看详情 →', listRect.x + listRect.w - 18, y + 22, 100, PALETTE.cyan, '700 13px "PingFang SC", sans-serif', 'right', 'middle');
        drawClippedText(ctx, s.desc, listRect.x + 18, y + 50, listRect.w - 36, PALETTE.textSub, '13px "PingFang SC", sans-serif');
        if (visBottom > visTop) {
          stage.addHitRegion({
            x: listRect.x,
            y: visTop,
            w: listRect.w,
            h: visBottom - visTop,
            onTap: () => {
              this.detailScroll = 0;
              this.selectedSynergyId = s.id;
            },
          });
        }
      } else {
        const a = cat.augments[i];
        drawClippedText(ctx, `${a.name}${a.tier ? ` [${a.tier}]` : ''}`, listRect.x + 18, y + 22, listRect.w - 140, PALETTE.cyan, '700 15px "PingFang SC", sans-serif');
        drawClippedText(ctx, '查看详情 →', listRect.x + listRect.w - 18, y + 22, 100, PALETTE.cyan, '700 13px "PingFang SC", sans-serif', 'right', 'middle');
        drawClippedText(ctx, a.desc || '', listRect.x + 18, y + 50, listRect.w - 36, PALETTE.textSub, '13px "PingFang SC", sans-serif');
        if (visBottom > visTop) {
          stage.addHitRegion({
            x: listRect.x,
            y: visTop,
            w: listRect.w,
            h: visBottom - visTop,
            onTap: () => {
              this.detailScroll = 0;
              this.selectedAugmentId = a.id;
            },
          });
        }
      }
    }
    ctx.restore();
  }

  private renderUnitDetail(
    stage: Stage,
    cat: AutoChessCatalog,
    u: AutoChessUnitWiki,
    x: number,
    y: number,
    w: number,
    h: number,
  ): void {
    const ctx = stage.ctx;
    const contentW = w - 20;
    const textFont = '13px "PingFang SC", "Microsoft YaHei", sans-serif';
    const blurbLines = wrapTextLines(ctx, `${u.tag} — ${u.blurb}`, contentW - 110, textFont);
    const headerH = Math.max(92, 54 + blurbLines.length * 19 + 12);

    const skillLayouts = u.skills.map(sk => {
      const lines = wrapTextLines(ctx, sk.summary || '无额外描述', contentW - 32, textFont);
      return { sk, lines, height: 46 + lines.length * 19 + 12 };
    });

    const passiveLineBlocks = u.passives.map(p => wrapTextLines(ctx, `• ${p}`, contentW - 32, textFont));
    const tuningLineBlocks = u.tuning_notes.map(t => wrapTextLines(ctx, `• ${t}`, contentW - 32, textFont));
    const passiveH =
      passiveLineBlocks.length > 0
        ? 40 + passiveLineBlocks.reduce((sum, ls) => sum + ls.length * 19 + 6, 0) + 10
        : 0;
    const tuningH =
      tuningLineBlocks.length > 0
        ? 40 + tuningLineBlocks.reduce((sum, ls) => sum + ls.length * 19 + 6, 0) + 10
        : 0;

    const baseStatsH = 90;
    const starKeys = ['1', '2', '3'].filter(k => u.star_stats[k]);
    const starTableH = 44 + Math.max(1, starKeys.length) * 30 + 14;

    const totalH =
      headerH +
      12 +
      baseStatsH +
      12 +
      starTableH +
      12 +
      (passiveH > 0 ? passiveH + 12 : 0) +
      (tuningH > 0 ? tuningH + 12 : 0) +
      36 +
      skillLayouts.reduce((sum, item) => sum + item.height + 10, 0) +
      20;

    stage.addScrollZone({
      x,
      y,
      w,
      h,
      key: 'wiki-unit-detail',
      contentHeight: totalH,
      getOffset: () => this.detailScroll,
      onScroll: v => {
        this.detailScroll = v;
      },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();

    let curY = y - this.detailScroll;
    const accent = u.accent || costColor(u.cost);

    // 1. Header summary card
    fillRoundRect(ctx, x, curY, contentW, headerH, 12, PALETTE.bgCard);
    strokeRoundRect(ctx, x, curY, contentW, headerH, 12, costColor(u.cost), 1.4);
    drawEmblemBadge(ctx, x + 46, curY + 46, 28, u.emblem || 'star', accent);
    drawClippedText(
      ctx,
      `${u.name}（${u.serial}）· ${u.cost}费 [${AUTOCHESS_ROLE_LABELS[u.role] || u.role}]`,
      x + 92,
      curY + 24,
      540,
      costColor(u.cost),
      '700 19px "PingFang SC", sans-serif',
    );
    drawClippedText(
      ctx,
      `羁绊：${u.traits.join(' / ')} · 卡池 ${u.pool_count || cat.pool_counts?.[String(u.cost)] || '-'} 张`,
      x + contentW - 18,
      curY + 24,
      300,
      PALETTE.gold,
      '700 13px "PingFang SC", sans-serif',
      'right',
      'middle',
    );
    drawLines(ctx, blurbLines, x + 92, curY + 46, 19, PALETTE.textSub, textFont);
    curY += headerH + 12;

    // 2. Base combat attributes & basic attack
    fillRoundRect(ctx, x, curY, contentW, baseStatsH, 12, PALETTE.bgCard);
    strokeRoundRect(ctx, x, curY, contentW, baseStatsH, 12, PALETTE.border, 1);
    drawClippedText(
      ctx,
      `基础面板：MOV ${u.mov} · 战术移动 ${u.tactical_move} · 主动作 ${u.main_actions} · 敏捷 ${u.dex} · 闪避 ${u.dodge} · 射程 ${u.range}${u.flying ? ' · 飞行单位' : ''}${u.can_block ? ` · 可格挡(${u.block_val})` : ''}`,
      x + 18,
      curY + 26,
      contentW - 36,
      PALETTE.textMain,
      '700 13px "PingFang SC", sans-serif',
    );
    drawClippedText(
      ctx,
      `普攻【${u.basic_attack.skill_name}】：成功率 ${u.basic_attack.skill_val}% · 伤害 ${u.basic_attack.dice}${u.basic_attack.pierce ? ' · 贯穿' : ''}`,
      x + 18,
      curY + 58,
      contentW - 36,
      PALETTE.cyan,
      '600 13px "PingFang SC", sans-serif',
    );
    curY += baseStatsH + 12;

    // 3. Star scaling table
    fillRoundRect(ctx, x, curY, contentW, starTableH, 12, PALETTE.bgCard);
    strokeRoundRect(ctx, x, curY, contentW, starTableH, 12, PALETTE.border, 1);
    drawClippedText(ctx, '星级成长（1★ / 2★ / 3★）', x + 18, curY + 22, 280, PALETTE.gold, '700 14px "PingFang SC", sans-serif');
    starKeys.forEach((k, idx) => {
      const st = u.star_stats[k];
      const ry = curY + 44 + idx * 30;
      fillRoundRect(ctx, x + 14, ry, contentW - 28, 25, 6, '#151a30');
      const summonPart =
        st.summon_hp_mult !== 1 || st.summon_skill_bonus !== 0
          ? ` · 召唤HP×${st.summon_hp_mult}/技能+${st.summon_skill_bonus}`
          : '';
      drawClippedText(
        ctx,
        `${'★'.repeat(st.star)}   HP ${st.hp}   MP ${st.mp}   技能 +${st.skill_bonus}%   增伤 +${st.flat_dmg}   减伤 +${st.flat_dr}   闪避 ${st.dodge}${summonPart}`,
        x + 24,
        ry + 13,
        contentW - 48,
        PALETTE.textMain,
        '600 13px "PingFang SC", sans-serif',
      );
    });
    curY += starTableH + 12;

    // 4. Passives
    if (passiveH > 0) {
      fillRoundRect(ctx, x, curY, contentW, passiveH, 12, PALETTE.bgCard);
      strokeRoundRect(ctx, x, curY, contentW, passiveH, 12, PALETTE.border, 1);
      drawClippedText(ctx, '固有被动', x + 18, curY + 20, 200, PALETTE.emerald, '700 14px "PingFang SC", sans-serif');
      let py = curY + 38;
      for (const ls of passiveLineBlocks) {
        drawLines(ctx, ls, x + 18, py, 19, PALETTE.textSub, textFont);
        py += ls.length * 19 + 6;
      }
      curY += passiveH + 12;
    }

    // 5. Tuning notes
    if (tuningH > 0) {
      fillRoundRect(ctx, x, curY, contentW, tuningH, 12, PALETTE.bgCard);
      strokeRoundRect(ctx, x, curY, contentW, tuningH, 12, PALETTE.border, 1);
      drawClippedText(ctx, '自走棋适配说明', x + 18, curY + 20, 240, PALETTE.amber, '700 14px "PingFang SC", sans-serif');
      let ty = curY + 38;
      for (const ls of tuningLineBlocks) {
        drawLines(ctx, ls, x + 18, ty, 19, PALETTE.textSub, textFont);
        ty += ls.length * 19 + 6;
      }
      curY += tuningH + 12;
    }

    // 6. Skills
    drawClippedText(ctx, `主动技能与形态技能 (${skillLayouts.length})`, x + 4, curY + 14, 340, PALETTE.violet, '700 15px "PingFang SC", sans-serif');
    curY += 34;

    for (const item of skillLayouts) {
      const { sk, lines, height } = item;
      fillRoundRect(ctx, x, curY, contentW, height, 10, PALETTE.bgCard);
      strokeRoundRect(ctx, x, curY, contentW, height, 10, PALETTE.border, 1);
      drawClippedText(ctx, sk.name, x + 16, curY + 20, 340, PALETTE.textMain, '700 15px "PingFang SC", sans-serif');
      const meta = [
        sk.phase_label || `阶段${sk.phase}`,
        sk.timing || '',
        `消耗 ${sk.mp_cost} MP`,
        sk.range !== null ? `射程 ${sk.range}` : '',
        sk.cooldown > 0 ? `冷却 ${sk.cooldown} 轮` : '',
      ]
        .filter(Boolean)
        .join(' · ');
      drawClippedText(ctx, meta, x + contentW - 16, curY + 20, 560, PALETTE.gold, '600 12px "PingFang SC", sans-serif', 'right', 'middle');
      drawLines(ctx, lines, x + 16, curY + 40, 19, PALETTE.textSub, textFont);
      curY += height + 10;
    }

    ctx.restore();
  }

  private renderSynergyDetail(
    stage: Stage,
    cat: AutoChessCatalog,
    syn: AutoChessSynergyDef,
    x: number,
    y: number,
    w: number,
    h: number,
  ): void {
    const ctx = stage.ctx;
    const contentW = w - 20;
    const textFont = '14px "PingFang SC", "Microsoft YaHei", sans-serif';
    const descLines = wrapTextLines(ctx, syn.desc, contentW - 36, textFont);
    const matchingUnits = cat.units.filter(u => u.traits.includes(syn.name) || u.traits.includes(syn.id));

    const headerH = 56 + descLines.length * 22 + 16;
    const tiersH = 44 + syn.tiers.length * 36 + 10;
    const totalH = headerH + 14 + tiersH + 14 + 34 + matchingUnits.length * 68 + 20;

    stage.addScrollZone({
      x,
      y,
      w,
      h,
      key: 'wiki-synergy-detail',
      contentHeight: totalH,
      getOffset: () => this.detailScroll,
      onScroll: v => {
        this.detailScroll = v;
      },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();

    let curY = y - this.detailScroll;
    fillRoundRect(ctx, x, curY, contentW, headerH, 12, PALETTE.bgCard);
    strokeRoundRect(ctx, x, curY, contentW, headerH, 12, PALETTE.goldSoft, 1.4);
    drawClippedText(ctx, `羁绊：${syn.name}`, x + 18, curY + 26, contentW - 36, PALETTE.gold, '700 20px "PingFang SC", sans-serif');
    drawLines(ctx, descLines, x + 18, curY + 50, 22, PALETTE.textSub, textFont);
    curY += headerH + 14;

    fillRoundRect(ctx, x, curY, contentW, tiersH, 12, PALETTE.bgCard);
    strokeRoundRect(ctx, x, curY, contentW, tiersH, 12, PALETTE.border, 1);
    drawClippedText(ctx, '激活档位', x + 18, curY + 22, 200, PALETTE.textMain, '700 15px "PingFang SC", sans-serif');
    syn.tiers.forEach((t, idx) => {
      const ty = curY + 42 + idx * 36;
      fillRoundRect(ctx, x + 14, ty, contentW - 28, 30, 8, '#151a30');
      drawPill(ctx, x + 22, ty + 4, 68, 22, 'rgba(244,200,106,0.16)', PALETTE.gold, `${t.count} 棋子`, PALETTE.gold, 11);
      drawClippedText(ctx, t.label, x + 104, ty + 15, contentW - 130, PALETTE.textMain, '600 13px "PingFang SC", sans-serif');
    });
    curY += tiersH + 14;

    drawClippedText(ctx, `关联棋子 (${matchingUnits.length}) · 点击查看棋子详情`, x + 4, curY + 14, 420, PALETTE.cyan, '700 15px "PingFang SC", sans-serif');
    curY += 34;

    for (const u of matchingUnits) {
      fillRoundRect(ctx, x, curY, contentW, 58, 10, PALETTE.bgCard);
      strokeRoundRect(ctx, x, curY, contentW, 58, 10, PALETTE.border, 1);
      drawEmblemBadge(ctx, x + 32, curY + 29, 18, u.emblem || 'star', u.accent || costColor(u.cost));
      drawClippedText(ctx, `${u.name} · ${u.cost}费 [${AUTOCHESS_ROLE_LABELS[u.role] || u.role}]`, x + 64, curY + 20, 380, costColor(u.cost), '700 14px "PingFang SC", sans-serif');
      drawClippedText(ctx, u.traits.join(' / '), x + 64, curY + 41, 380, PALETTE.textSub, '12px "PingFang SC", sans-serif');
      drawClippedText(ctx, '查看详情 →', x + contentW - 18, curY + 29, 100, PALETTE.cyan, '700 13px "PingFang SC", sans-serif', 'right', 'middle');

      const visTop = Math.max(y, curY);
      const visBottom = Math.min(y + h, curY + 58);
      if (visBottom > visTop) {
        stage.addHitRegion({
          x,
          y: visTop,
          w: contentW,
          h: visBottom - visTop,
          onTap: () => {
            this.detailScroll = 0;
            this.selectedSynergyId = null;
            this.selectedUnitSerial = u.serial;
          },
        });
      }
      curY += 68;
    }

    ctx.restore();
  }

  private renderAugmentDetail(
    stage: Stage,
    aug: AutoChessAugment,
    x: number,
    y: number,
    w: number,
    h: number,
  ): void {
    const ctx = stage.ctx;
    const textFont = '15px "PingFang SC", "Microsoft YaHei", sans-serif';
    const lines = wrapTextLines(ctx, aug.desc || '暂无描述', w - 48, textFont);
    const cardH = Math.min(h, Math.max(160, 88 + lines.length * 24 + 24));
    fillRoundRect(ctx, x, y, w, cardH, 14, PALETTE.bgCard);
    strokeRoundRect(ctx, x, y, w, cardH, 14, PALETTE.cyan, 1.5);
    drawPill(ctx, x + 22, y + 20, 104, 26, 'rgba(92,225,208,0.14)', PALETTE.cyan, aug.tier || '星序祝福', PALETTE.cyan, 12);
    drawClippedText(ctx, aug.name, x + 140, y + 33, w - 164, PALETTE.textMain, '700 20px "PingFang SC", sans-serif');
    drawLines(ctx, lines, x + 24, y + 72, 24, PALETTE.textSub, textFont);
    void stage;
  }
}
