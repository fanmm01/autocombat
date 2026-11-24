import {
  AUTOCHESS_ROLE_LABELS,
  fetchAutoChessStories,
  fetchAutoChessStoryDetail,
  resolveUnitWiki,
  type AutoChessAugment,
  type AutoChessCatalog,
  type AutoChessStoryDetail,
  type AutoChessStoryIndexItem,
  type AutoChessStoryParagraph,
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
  type Rect,
} from './ui';

export type WikiTab = 'units' | 'synergies' | 'augments' | 'stories';

interface CachedStoryLine {
  y: number;
  text: string;
  color: string;
  font: string;
  speakerPrefix?: string;
  speakerWidth?: number;
  isDivider?: boolean;
  isNoteBg?: boolean;
  lineHeight: number;
}

interface CachedStoryLayout {
  totalHeight: number;
  lines: CachedStoryLine[];
}

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

function drawClippedScrollButton(
  stage: Stage,
  ctx: WxCanvasRenderingContext2D,
  clipTop: number,
  clipBottom: number,
  rect: Rect,
  label: string,
  onTap: () => void,
  opts: { bg?: string; border?: string; color?: string; fontSize?: number } = {},
): void {
  const bg = opts.bg || PALETTE.violetDark;
  const border = opts.border || '#bba7ff';
  const color = opts.color || PALETTE.textMain;
  const fontSize = opts.fontSize ?? 13;

  fillRoundRect(ctx, rect.x, rect.y, rect.w, rect.h, 8, bg);
  strokeRoundRect(ctx, rect.x, rect.y, rect.w, rect.h, 8, border, 1.3);
  drawClippedText(
    ctx,
    label,
    rect.x + rect.w / 2,
    rect.y + rect.h / 2 + 0.5,
    rect.w - 14,
    color,
    `700 ${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`,
    'center',
    'middle',
  );

  const visTop = Math.max(clipTop, rect.y);
  const visBottom = Math.min(clipBottom, rect.y + rect.h);
  if (visBottom > visTop) {
    stage.addHitRegion({
      x: rect.x,
      y: visTop,
      w: rect.w,
      h: visBottom - visTop,
      onTap,
    });
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

  // Story reader state
  private selectedStoryId: string | null = null;
  private selectedChapterId: string | null = null;
  private storyDetail: AutoChessStoryDetail | null = null;
  private storyLoadingKey = '';
  private storyLoading = false;
  private storyError = '';
  private storyFontSize: 13 | 15 | 17 = 15;
  private fallbackStories: AutoChessStoryIndexItem[] | null = null;
  private fallbackLoading = false;
  private storyLayoutCache = new Map<string, CachedStoryLayout>();

  open(tab: WikiTab = 'units', unitSerial?: string, storyId?: string): void {
    this.opened = true;
    this.tab = tab;
    this.listScroll = 0;
    this.detailScroll = 0;
    this.selectedUnitSerial = unitSerial || null;
    this.selectedSynergyId = null;
    this.selectedAugmentId = null;
    this.selectedStoryId = storyId || null;
    this.selectedChapterId = null;
    this.storyError = '';
    if (storyId) {
      this.tab = 'stories';
      this.requestStoryLoad(storyId);
    }
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
    this.selectedStoryId = null;
    this.selectedChapterId = null;
    this.detailScroll = 0;
  }

  private resolveStories(cat: AutoChessCatalog): AutoChessStoryIndexItem[] {
    if (cat.story_index && cat.story_index.length > 0) {
      return cat.story_index;
    }
    if (this.fallbackStories) {
      return this.fallbackStories;
    }
    if (!this.fallbackLoading) {
      this.fallbackLoading = true;
      fetchAutoChessStories()
        .then(list => {
          this.fallbackStories = list;
        })
        .catch(() => {
          this.fallbackStories = [];
        })
        .finally(() => {
          this.fallbackLoading = false;
        });
    }
    return [];
  }

  private requestStoryLoad(storyId: string, chapterId?: string): void {
    const key = `${storyId}::${chapterId || ''}`;
    if (this.storyLoadingKey === key && this.storyLoading) return;
    if (
      this.storyDetail &&
      this.storyDetail.id === storyId &&
      (!chapterId || this.storyDetail.active_chapter_id === chapterId)
    ) {
      const ch = this.storyDetail.chapters.find(c => c.id === (chapterId || this.storyDetail!.active_chapter_id));
      if (ch && ch.paragraphs) return;
    }

    this.storyLoadingKey = key;
    this.storyLoading = true;
    this.storyError = '';
    fetchAutoChessStoryDetail(storyId, chapterId)
      .then(detail => {
        if (this.storyLoadingKey !== key) return;
        this.storyDetail = detail;
        this.selectedChapterId = detail.active_chapter_id;
        this.storyLoading = false;
      })
      .catch(err => {
        if (this.storyLoadingKey !== key) return;
        this.storyLoading = false;
        this.storyError = err instanceof Error ? err.message : '加载故事失败';
      });
  }

  private openStory(storyId: string, chapterId?: string): void {
    this.tab = 'stories';
    this.selectedUnitSerial = null;
    this.selectedSynergyId = null;
    this.selectedAugmentId = null;
    this.selectedStoryId = storyId;
    this.selectedChapterId = chapterId || null;
    this.detailScroll = 0;
    this.requestStoryLoad(storyId, chapterId);
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
      this.selectedUnitSerial ||
        this.selectedSynergyId ||
        this.selectedAugmentId ||
        this.selectedStoryId,
    );

    if (hasDetail) {
      drawButton(stage, ctx, { x: mx + 24, y: my + 14, w: 112, h: 34 }, '← 返回列表', () => {
        this.clearDetail();
      }, { fontSize: 13 });
      drawClippedText(
        ctx,
        this.selectedStoryId ? '纯文字故事阅读' : '星序自走棋百科 · 详情',
        mx + 150,
        my + 31,
        560,
        PALETTE.textMain,
        '700 18px "PingFang SC", sans-serif',
      );
    } else {
      drawClippedText(
        ctx,
        '星序自走棋百科与故事阅读（点击条目查看）',
        mx + 24,
        my + 32,
        620,
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

    if (this.selectedStoryId) {
      this.renderStoryReader(stage, catalog, this.selectedStoryId, mx + 24, my + 60, mw - 48, mh - 76);
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
    const stories = this.resolveStories(cat);
    const tabs: Array<[WikiTab, string]> = [
      ['units', `棋子图鉴 (${cat.units.length})`],
      ['synergies', `羁绊效果 (${cat.synergies.length})`],
      ['augments', `星序海克斯 (${cat.augments.length})`],
      ['stories', `故事阅读 (${stories.length})`],
    ];
    tabs.forEach(([id, label], i) => {
      const active = this.tab === id;
      drawButton(stage, ctx, { x: mx + 24 + i * 164, y: my + 62, w: 154, h: 34 }, label, () => {
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
          : this.tab === 'augments'
            ? cat.augments.length
            : stories.length;
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
      } else if (this.tab === 'augments') {
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
      } else {
        const st = stories[i];
        const catColor =
          st.category === 'opening'
            ? PALETTE.gold
            : st.category === 'prequel'
              ? PALETTE.cyan
              : PALETTE.violet;
        drawPill(ctx, listRect.x + 16, y + 12, 92, 22, `${catColor}22`, catColor, st.category_label, catColor, 11);
        drawClippedText(ctx, st.title, listRect.x + 120, y + 23, 520, PALETTE.textMain, '700 15px "PingFang SC", sans-serif');
        const meta = `${st.chapter_count > 1 ? `${st.chapter_count}节 · ` : ''}${st.word_count.toLocaleString()}字`;
        drawClippedText(ctx, `${meta}  阅读 →`, listRect.x + listRect.w - 18, y + 23, 220, PALETTE.cyan, '700 13px "PingFang SC", sans-serif', 'right', 'middle');
        drawClippedText(ctx, st.summary || st.subtitle || '', listRect.x + 16, y + 52, listRect.w - 34, PALETTE.textSub, '13px "PingFang SC", sans-serif');
        if (visBottom > visTop) {
          stage.addHitRegion({
            x: listRect.x,
            y: visTop,
            w: listRect.w,
            h: visBottom - visTop,
            onTap: () => this.openStory(st.id),
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

    // Precompute lore block layout height
    const lore = u.lore;
    const loreFieldBlocks = (lore?.profile_fields || []).map(f => ({
      label: f.label,
      lines: wrapTextLines(ctx, `${f.label}：${f.value}`, contentW - 36, textFont),
    }));
    const loreInlineLines =
      lore?.story_mode === 'inline' && lore.story_text
        ? wrapTextLines(ctx, lore.story_text, contentW - 36, textFont)
        : [];
    const loreExcerptLines =
      lore?.story_mode === 'jump' && lore.story_excerpt
        ? wrapTextLines(ctx, lore.story_excerpt, contentW - 36, textFont)
        : [];
    const extraStories = lore?.extra_stories || [];

    let loreH = 0;
    if (lore) {
      loreH = 42;
      for (const fb of loreFieldBlocks) {
        loreH += fb.lines.length * 19 + 5;
      }
      if (lore.story_mode === 'inline' && loreInlineLines.length > 0) {
        loreH += 14 + 24 + loreInlineLines.length * 19 + 42;
      } else if (lore.story_mode === 'jump' && lore.story_id) {
        loreH += 14 + 24 + loreExcerptLines.length * 19 + 44 + extraStories.length * 40;
      } else if (lore.story_mode === 'none') {
        loreH += 28;
      }
      loreH += 12;
    }

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
      (loreH > 0 ? loreH + 12 : 0) +
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
      `基础面板：MOV ${u.mov} · 战术移动 ${u.tactical_move} 格 · 主动作 ${u.main_actions} · 敏捷 ${u.dex} · 闪避 ${u.dodge} · 射程 ${u.range}${u.flying ? ' · 飞行' : ''}${u.can_block ? ` · 格挡(${u.block_val})` : ''}`,
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

    // 6. Character lore profile & story (inline or jump)
    if (lore && loreH > 0) {
      fillRoundRect(ctx, x, curY, contentW, loreH, 12, PALETTE.bgCard);
      strokeRoundRect(ctx, x, curY, contentW, loreH, 12, PALETTE.violet, 1.2);
      drawClippedText(ctx, '角色档案与背景故事', x + 18, curY + 20, 280, PALETTE.violet, '700 14px "PingFang SC", sans-serif');
      let ly = curY + 40;
      for (const fb of loreFieldBlocks) {
        drawLines(ctx, fb.lines, x + 18, ly, 19, PALETTE.textSub, textFont);
        ly += fb.lines.length * 19 + 5;
      }

      if (lore.story_mode === 'inline' && loreInlineLines.length > 0) {
        ly += 8;
        ctx.fillStyle = PALETTE.border;
        ctx.fillRect(x + 18, ly, contentW - 36, 1);
        ly += 10;
        drawClippedText(ctx, '背景故事', x + 18, ly + 8, 220, PALETTE.gold, '700 13px "PingFang SC", sans-serif');
        ly += 22;
        drawLines(ctx, loreInlineLines, x + 18, ly, 19, PALETTE.textMain, textFont);
        ly += loreInlineLines.length * 19 + 8;
        if (lore.story_id) {
          drawClippedScrollButton(
            stage,
            ctx,
            y,
            y + h,
            { x: x + 18, y: ly, w: 200, h: 30 },
            '在故事阅读中打开 →',
            () => this.openStory(lore.story_id!),
            { bg: '#20294c', border: PALETTE.cyan, color: PALETTE.cyan, fontSize: 12 },
          );
        }
      } else if (lore.story_mode === 'jump' && lore.story_id) {
        ly += 8;
        ctx.fillStyle = PALETTE.border;
        ctx.fillRect(x + 18, ly, contentW - 36, 1);
        ly += 10;
        drawClippedText(ctx, '背景故事（长篇）', x + 18, ly + 8, 260, PALETTE.gold, '700 13px "PingFang SC", sans-serif');
        ly += 22;
        drawLines(ctx, loreExcerptLines, x + 18, ly, 19, PALETTE.textSub, textFont);
        ly += loreExcerptLines.length * 19 + 8;
        drawClippedScrollButton(
          stage,
          ctx,
          y,
          y + h,
          { x: x + 18, y: ly, w: 256, h: 32 },
          '前往故事阅读查看完整故事 →',
          () => this.openStory(lore.story_id!),
        );
        ly += 40;
        for (const ex of extraStories) {
          drawClippedScrollButton(
            stage,
            ctx,
            y,
            y + h,
            { x: x + 18, y: ly, w: 340, h: 32 },
            `阅读单列前传：${ex.title} →`,
            () => this.openStory(ex.id),
            { bg: '#1d2747', border: PALETTE.cyan, color: PALETTE.cyan, fontSize: 12 },
          );
          ly += 40;
        }
      } else if (lore.story_mode === 'none') {
        ly += 4;
        drawClippedText(ctx, '该角色详细背景故事暂未公开', x + 18, ly + 8, 360, PALETTE.textMuted, '12px "PingFang SC", sans-serif');
      }
      curY += loreH + 12;
    }

    // 7. Skills
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

  private getStoryLayout(
    ctx: WxCanvasRenderingContext2D,
    storyId: string,
    chapterId: string,
    paragraphs: AutoChessStoryParagraph[],
    contentW: number,
  ): CachedStoryLayout {
    const cacheKey = `${storyId}::${chapterId}::${this.storyFontSize}::${contentW}`;
    const cached = this.storyLayoutCache.get(cacheKey);
    if (cached) return cached;

    const fs = this.storyFontSize;
    const lh = fs + 9;
    const baseFont = `${fs}px "PingFang SC", "Microsoft YaHei", sans-serif`;
    const boldFont = `700 ${fs}px "PingFang SC", "Microsoft YaHei", sans-serif`;
    const headFont = `700 ${fs + 1}px "PingFang SC", "Microsoft YaHei", sans-serif`;
    const noteFont = `${Math.max(12, fs - 1)}px "PingFang SC", "Microsoft YaHei", sans-serif`;

    const lines: CachedStoryLine[] = [];
    let curY = 8;

    for (const p of paragraphs) {
      if (p.kind === 'divider') {
        lines.push({
          y: curY,
          text: '',
          color: PALETTE.border,
          font: baseFont,
          isDivider: true,
          lineHeight: lh,
        });
        curY += 18;
        continue;
      }

      if (p.kind === 'heading') {
        const wrapped = wrapTextLines(ctx, p.text, contentW - 16, headFont);
        for (const wLine of wrapped) {
          lines.push({
            y: curY,
            text: wLine,
            color: PALETTE.gold,
            font: headFont,
            lineHeight: lh,
          });
          curY += lh;
        }
        curY += 8;
        continue;
      }

      if (p.kind === 'dialogue' && p.speaker) {
        const prefix = `${p.speaker}：`;
        ctx.font = boldFont;
        const prefixW = ctx.measureText(prefix).width;
        const full = `${prefix}${p.text}`;
        const wrapped = wrapTextLines(ctx, full, contentW - 8, baseFont);
        wrapped.forEach((wLine, idx) => {
          if (idx === 0 && wLine.startsWith(prefix)) {
            lines.push({
              y: curY,
              text: wLine.slice(prefix.length),
              speakerPrefix: prefix,
              speakerWidth: prefixW,
              color: PALETTE.textMain,
              font: baseFont,
              lineHeight: lh,
            });
          } else {
            lines.push({
              y: curY,
              text: wLine,
              color: PALETTE.textMain,
              font: baseFont,
              lineHeight: lh,
            });
          }
          curY += lh;
        });
        curY += 8;
        continue;
      }

      if (p.kind === 'note') {
        const txt = `[${p.speaker || '判定'}] ${p.text}`;
        const wrapped = wrapTextLines(ctx, txt, contentW - 24, noteFont);
        for (const wLine of wrapped) {
          lines.push({
            y: curY,
            text: wLine,
            color: PALETTE.textMuted,
            font: noteFont,
            isNoteBg: true,
            lineHeight: lh - 2,
          });
          curY += lh - 2;
        }
        curY += 8;
        continue;
      }

      const color = p.kind === 'quote' ? PALETTE.cyan : PALETTE.textSub;
      const wrapped = wrapTextLines(ctx, p.text, contentW - 8, baseFont);
      for (const wLine of wrapped) {
        lines.push({
          y: curY,
          text: wLine,
          color,
          font: baseFont,
          lineHeight: lh,
        });
        curY += lh;
      }
      curY += 10;
    }

    const layout: CachedStoryLayout = { totalHeight: curY + 24, lines };
    this.storyLayoutCache.set(cacheKey, layout);
    return layout;
  }

  private renderStoryReader(
    stage: Stage,
    cat: AutoChessCatalog,
    storyId: string,
    x: number,
    y: number,
    w: number,
    h: number,
  ): void {
    const ctx = stage.ctx;
    const stories = this.resolveStories(cat);
    const meta = stories.find(s => s.id === storyId);
    const activeChapterId = this.selectedChapterId || meta?.chapters[0]?.id;

    this.requestStoryLoad(storyId, activeChapterId);

    // Top reader control strip (42px)
    const barH = 42;
    fillRoundRect(ctx, x, y, w, barH, 10, PALETTE.bgCard);
    strokeRoundRect(ctx, x, y, w, barH, 10, PALETTE.border, 1);

    const detail = this.storyDetail?.id === storyId ? this.storyDetail : null;
    const chapters = detail?.chapters || meta?.chapters || [];
    const curChId = detail?.active_chapter_id || activeChapterId || '';
    const chIdx = Math.max(0, chapters.findIndex(c => c.id === curChId));
    const activeChapter = detail?.chapters?.[chIdx];

    drawClippedText(
      ctx,
      meta?.title || detail?.title || storyId,
      x + 14,
      y + 21,
      360,
      PALETTE.gold,
      '700 15px "PingFang SC", sans-serif',
    );

    let rightX = x + w - 10;

    if (meta?.serial) {
      rightX -= 104;
      const targetSerial = meta.serial;
      drawButton(stage, ctx, { x: rightX, y: y + 6, w: 100, h: 30 }, `查看 ${targetSerial} →`, () => {
        this.selectedStoryId = null;
        this.selectedChapterId = null;
        this.tab = 'units';
        this.selectedUnitSerial = targetSerial;
        this.detailScroll = 0;
      }, { fontSize: 12, bg: '#1d2747', border: PALETTE.cyan, color: PALETTE.cyan });
      rightX -= 6;
    }

    // Font size controls
    rightX -= 38;
    drawButton(stage, ctx, { x: rightX, y: y + 6, w: 36, h: 30 }, 'A+', () => {
      this.storyFontSize = this.storyFontSize === 13 ? 15 : 17;
    }, { fontSize: 12, disabled: this.storyFontSize === 17 });
    rightX -= 42;
    drawButton(stage, ctx, { x: rightX, y: y + 6, w: 36, h: 30 }, 'A-', () => {
      this.storyFontSize = this.storyFontSize === 17 ? 15 : 13;
    }, { fontSize: 12, disabled: this.storyFontSize === 13 });

    // Chapter prev / next controls when multi-chapter
    if (chapters.length > 1) {
      rightX -= 76;
      drawButton(stage, ctx, { x: rightX, y: y + 6, w: 70, h: 30 }, '下一节 ›', () => {
        if (chIdx < chapters.length - 1) {
          this.detailScroll = 0;
          this.selectedChapterId = chapters[chIdx + 1].id;
          this.requestStoryLoad(storyId, this.selectedChapterId);
        }
      }, { fontSize: 12, disabled: chIdx >= chapters.length - 1 });

      rightX -= 76;
      drawButton(stage, ctx, { x: rightX, y: y + 6, w: 70, h: 30 }, '‹ 上一节', () => {
        if (chIdx > 0) {
          this.detailScroll = 0;
          this.selectedChapterId = chapters[chIdx - 1].id;
          this.requestStoryLoad(storyId, this.selectedChapterId);
        }
      }, { fontSize: 12, disabled: chIdx <= 0 });

      const chTitleText = `${chIdx + 1}/${chapters.length} ${activeChapter?.title || chapters[chIdx]?.title || ''}`;
      const chMaxW = Math.max(80, rightX - (x + 382));
      if (chMaxW > 90) {
        drawClippedText(ctx, chTitleText, x + 382, y + 21, chMaxW, PALETTE.textSub, '12px "PingFang SC", sans-serif');
      }
    }

    const bodyY = y + barH + 10;
    const bodyH = h - barH - 10;
    const contentW = w - 24;

    fillRoundRect(ctx, x, bodyY, w, bodyH, 12, '#12162b');
    strokeRoundRect(ctx, x, bodyY, w, bodyH, 12, PALETTE.border, 1);

    if (this.storyLoading && (!activeChapter || !activeChapter.paragraphs)) {
      drawClippedText(ctx, '正在加载纯文字正文…', x + w / 2, bodyY + bodyH / 2, w - 40, PALETTE.textMuted, '15px "PingFang SC", sans-serif', 'center', 'middle');
      return;
    }

    if (this.storyError && (!activeChapter || !activeChapter.paragraphs)) {
      drawClippedText(ctx, this.storyError, x + w / 2, bodyY + bodyH / 2 - 20, w - 40, PALETTE.rose, '14px "PingFang SC", sans-serif', 'center', 'middle');
      drawButton(stage, ctx, { x: x + w / 2 - 50, y: bodyY + bodyH / 2 + 8, w: 100, h: 32 }, '重新加载', () => {
        this.storyLoadingKey = '';
        this.requestStoryLoad(storyId, activeChapterId);
      }, { fontSize: 13 });
      return;
    }

    const paragraphs = activeChapter?.paragraphs || [];
    if (paragraphs.length === 0) {
      drawClippedText(ctx, '暂无正文内容', x + w / 2, bodyY + bodyH / 2, w - 40, PALETTE.textMuted, '14px "PingFang SC", sans-serif', 'center', 'middle');
      return;
    }

    const layout = this.getStoryLayout(ctx, storyId, curChId, paragraphs, contentW);

    stage.addScrollZone({
      x,
      y: bodyY,
      w,
      h: bodyH,
      key: `wiki-story-reader-${storyId}-${curChId}`,
      contentHeight: layout.totalHeight + 24,
      getOffset: () => this.detailScroll,
      onScroll: v => {
        this.detailScroll = v;
      },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(x + 2, bodyY + 2, w - 4, bodyH - 4);
    ctx.clip();

    const baseTop = bodyY + 12 - this.detailScroll;
    const minVis = bodyY - 36;
    const maxVis = bodyY + bodyH + 12;

    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';

    for (const item of layout.lines) {
      const drawY = baseTop + item.y;
      if (drawY < minVis || drawY > maxVis) continue;

      if (item.isDivider) {
        ctx.fillStyle = PALETTE.border;
        ctx.fillRect(x + 24, drawY + 6, contentW - 24, 1);
        continue;
      }

      if (item.isNoteBg) {
        fillRoundRect(ctx, x + 14, drawY - 1, contentW - 8, item.lineHeight + 2, 4, 'rgba(156, 134, 236, 0.08)');
      }

      if (item.speakerPrefix && item.speakerWidth) {
        ctx.font = `700 ${this.storyFontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`;
        ctx.fillStyle = PALETTE.cyan;
        ctx.fillText(item.speakerPrefix, x + 16, drawY);
        ctx.font = item.font;
        ctx.fillStyle = item.color;
        ctx.fillText(item.text, x + 16 + item.speakerWidth, drawY);
      } else {
        ctx.font = item.font;
        ctx.fillStyle = item.color;
        ctx.fillText(item.text, x + 16, drawY);
      }
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
