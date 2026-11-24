import {
  AUTOCHESS_ROLE_LABELS,
  pollRoom,
  sendAutoChessAction,
  sendRoomAction,
  type AutoChessAccount,
  type AutoChessCatalog,
  type AutoChessCombatUnit,
  type AutoChessMatchState,
  type AutoChessOwnedUnit,
  type AutoChessRoomState,
} from '../net/autochessApi';
import { LongPoller } from '../net/poller';
import { ApiError } from '../net/transport';
import {
  PALETTE,
  Stage,
  confirmAction,
  costColor,
  drawButton,
  drawClippedText,
  drawEmblemBadge,
  drawPill,
  drawProgressBar,
  drawWrappedText,
  fillRoundRect,
  strokeRoundRect,
  tierColor,
} from '../engine/ui';
import { VfxEngine } from '../engine/vfx';
import { WikiModal } from '../engine/wikiModal';

export interface MatchHost {
  stage: Stage;
  getAccount(): AutoChessAccount | null;
  setAccount(acc: AutoChessAccount | null): void;
  getCatalog(): AutoChessCatalog | null;
  backToLobby(): void;
}

function parseCoord(coord: string): [number, number] {
  const m = /^([A-Z])(\d+)$/.exec(coord);
  return m ? [m[1].charCodeAt(0) - 65, Number(m[2]) - 1] : [-1, -1];
}

function formatCoord(col: number, row: number): string {
  return String.fromCharCode(65 + col) + String(row + 1);
}

const STANCE_LABELS: Record<string, string> = {
  aggressive: '激进',
  balanced: '均衡',
  defensive: '防御',
};

const STANCE_ORDER: Array<'aggressive' | 'balanced' | 'defensive'> = [
  'aggressive',
  'balanced',
  'defensive',
];

export class MatchScene {
  private readonly host: MatchHost;
  private match: AutoChessMatchState | null = null;
  private room: AutoChessRoomState | null = null;
  private spectateCid: string | null = null;
  private roomVersion = -1;
  private roomPoller: LongPoller | null = null;
  private combatTimer: number | null = null;
  private prepTimer: number | null = null;
  private roundResultTimer: number | null = null;
  private roundResultFallbackDeadline = 0;
  private combatSpeed2x = false;
  private busy = false;
  private selectedUnitId: string | null = null;
  private hideRoundResult = false;
  private lastFrameCount = 0;
  private readonly vfx = new VfxEngine();
  private readonly wikiModal = new WikiModal();

  constructor(host: MatchHost) {
    this.host = host;
  }

  onEnter(match: AutoChessMatchState, room?: AutoChessRoomState): void {
    this.match = match;
    this.room = room || null;
    this.spectateCid = null;
    this.roomVersion = -1;
    this.selectedUnitId = null;
    this.hideRoundResult = false;
    this.lastFrameCount = match.combat_frames?.length || 0;
    this.roundResultFallbackDeadline = match.phase === 'round_result' ? Date.now() / 1000 + 15 : 0;
    this.vfx.clear();
    this.wikiModal.close();
    this.stopTimers();

    if (this.room) {
      this.startRoomPoller(this.room.code);
    } else if (match.phase === 'prep') {
      this.schedulePrepAutoStart();
    } else if (match.phase === 'combat') {
      this.scheduleCombatStep();
    } else if (match.phase === 'round_result') {
      this.scheduleRoundResultAutoNext();
    }
  }

  onLeave(): void {
    this.stopTimers();
    this.vfx.clear();
    this.wikiModal.close();
  }

  setForeground(active: boolean): void {
    this.roomPoller?.setForeground(active);
    if (active && this.match && !this.room) {
      if (this.match.phase === 'prep') {
        this.schedulePrepAutoStart();
      } else if (this.match.phase === 'combat') {
        this.scheduleCombatStep();
      } else if (this.match.phase === 'round_result') {
        this.scheduleRoundResultAutoNext();
      }
    } else if (!active) {
      this.clearPrepTimer();
      this.clearRoundResultTimer();
      if (this.combatTimer !== null) {
        clearTimeout(this.combatTimer);
        this.combatTimer = null;
      }
    }
  }

  private clearPrepTimer(): void {
    if (this.prepTimer !== null) {
      clearTimeout(this.prepTimer);
      this.prepTimer = null;
    }
  }

  private clearRoundResultTimer(): void {
    if (this.roundResultTimer !== null) {
      clearTimeout(this.roundResultTimer);
      this.roundResultTimer = null;
    }
  }

  private stopTimers(): void {
    if (this.roomPoller) {
      this.roomPoller.stop();
      this.roomPoller = null;
    }
    if (this.combatTimer !== null) {
      clearTimeout(this.combatTimer);
      this.combatTimer = null;
    }
    this.clearPrepTimer();
    this.clearRoundResultTimer();
  }

  private getRoundResultRemainingSec(m: AutoChessMatchState): number | null {
    if (m.phase !== 'round_result') return null;
    const deadline =
      typeof m.round_result_deadline === 'number' && Number.isFinite(m.round_result_deadline) && m.round_result_deadline > 0
        ? m.round_result_deadline
        : this.roundResultFallbackDeadline;
    if (!(deadline > 0)) return null;
    return Math.max(0, Math.ceil(deadline - Date.now() / 1000));
  }

  private scheduleRoundResultAutoNext(minDelayMs = 250): void {
    this.clearRoundResultTimer();
    if (this.room || !this.match || this.match.phase !== 'round_result') return;
    if (
      !(typeof this.match.round_result_deadline === 'number' && Number.isFinite(this.match.round_result_deadline) && this.match.round_result_deadline > 0) &&
      this.roundResultFallbackDeadline <= 0
    ) {
      this.roundResultFallbackDeadline = Date.now() / 1000 + 15;
    }
    const deadline =
      typeof this.match.round_result_deadline === 'number' && Number.isFinite(this.match.round_result_deadline) && this.match.round_result_deadline > 0
        ? this.match.round_result_deadline
        : this.roundResultFallbackDeadline;

    const delay = Math.max(minDelayMs, deadline * 1000 - Date.now() + 250);
    this.roundResultTimer = setTimeout(() => {
      this.roundResultTimer = null;
      const cur = this.match;
      if (!cur || cur.phase !== 'round_result' || this.room) return;
      if (this.busy) {
        this.scheduleRoundResultAutoNext(300);
        return;
      }
      const curDeadline =
        typeof cur.round_result_deadline === 'number' && Number.isFinite(cur.round_result_deadline) && cur.round_result_deadline > 0
          ? cur.round_result_deadline
          : this.roundResultFallbackDeadline;
      if (curDeadline * 1000 - Date.now() > 50) {
        this.scheduleRoundResultAutoNext(250);
        return;
      }
      this.host.stage.showToast('结算倒计时结束，自动进入下一回合');
      void this.dispatchAction('next_round', {}, true);
    }, delay) as unknown as number;
  }

  private getPrepRemainingSec(m: AutoChessMatchState): number | null {
    if (m.phase !== 'prep' || typeof m.prep_deadline !== 'number' || !Number.isFinite(m.prep_deadline) || m.prep_deadline <= 0) {
      return null;
    }
    return Math.max(0, Math.ceil(m.prep_deadline - Date.now() / 1000));
  }

  private schedulePrepAutoStart(minDelayMs = 250): void {
    this.clearPrepTimer();
    if (this.room || !this.match || this.match.phase !== 'prep') return;
    const deadline = this.match.prep_deadline;
    if (typeof deadline !== 'number' || !Number.isFinite(deadline) || deadline <= 0) return;

    const delay = Math.max(minDelayMs, deadline * 1000 - Date.now() + 250);
    this.prepTimer = setTimeout(() => {
      this.prepTimer = null;
      const cur = this.match;
      if (!cur || cur.phase !== 'prep' || this.room) return;
      if (this.busy) {
        this.schedulePrepAutoStart(300);
        return;
      }
      if (typeof cur.prep_deadline === 'number' && cur.prep_deadline * 1000 - Date.now() > 50) {
        this.schedulePrepAutoStart(250);
        return;
      }
      const firstAugment = cur.player.pending_augments?.[0];
      if (firstAugment) {
        void this.dispatchAction('pick_augment', { augment_id: firstAugment.id }, true);
      } else {
        this.host.stage.showToast('备战倒计时结束，自动进入战斗');
        void this.dispatchAction('start_combat', {}, true);
      }
    }, delay) as unknown as number;
  }

  private startRoomPoller(code: string): void {
    if (this.roomPoller) this.roomPoller.stop();
    this.roomPoller = new LongPoller(
      async () => {
        const res = await pollRoom(code, this.roomVersion, 8, this.spectateCid);
        this.roomVersion = res.version;
        if (res.changed && res.room) {
          this.applyRoomUpdate(res.room);
          return 'changed';
        }
        return 'timeout';
      },
      err => {
        if (err instanceof ApiError && (err.status === 404 || (err.status === 403 && err.message.includes('房间')))) {
          this.stopTimers();
          this.host.stage.showToast('联机房间已不存在，请点击左上角返回大厅');
          return;
        }
        this.host.stage.showToast(`联机同步重试中：${err.message}`);
      },
    );
    this.roomPoller.start();
  }

  private applyRoomUpdate(room: AutoChessRoomState): void {
    this.room = room;
    if (room.match) {
      this.applyMatchUpdate(room.match);
    }
  }

  private applyMatchUpdate(next: AutoChessMatchState): void {
    const prevPhase = this.match?.phase;
    const prevFrames = this.lastFrameCount;
    this.match = next;

    const frames = next.combat_frames || [];
    if (frames.length > prevFrames) {
      const latest = frames[frames.length - 1];
      this.vfx.trigger(latest.vfx_events);
    }
    this.lastFrameCount = frames.length;

    if (prevPhase !== 'round_result' && next.phase === 'round_result') {
      this.hideRoundResult = false;
      this.roundResultFallbackDeadline = Date.now() / 1000 + 15;
    }
    if (next.phase !== 'round_result') {
      this.roundResultFallbackDeadline = 0;
      this.clearRoundResultTimer();
    } else if (!this.room) {
      this.scheduleRoundResultAutoNext();
    }
    if (next.phase !== 'prep') {
      this.selectedUnitId = null;
    }

    if (!this.room && next.phase === 'prep') {
      this.schedulePrepAutoStart();
    } else if (next.phase !== 'prep') {
      this.clearPrepTimer();
    }

    if (!this.room && next.phase === 'combat') {
      this.scheduleCombatStep();
    } else if (next.phase !== 'combat' && this.combatTimer !== null) {
      clearTimeout(this.combatTimer);
      this.combatTimer = null;
    }
  }

  private scheduleCombatStep(): void {
    if (this.room || !this.match || this.match.phase !== 'combat') return;
    if (this.combatTimer !== null) return;
    const delay = this.combatSpeed2x ? 260 : 520;
    this.combatTimer = setTimeout(() => {
      this.combatTimer = null;
      if (!this.match || this.match.phase !== 'combat' || this.room) return;
      if (this.busy) {
        this.scheduleCombatStep();
        return;
      }
      void this.dispatchAction('step_combat', { steps: this.combatSpeed2x ? 2 : 1 }, true);
    }, delay) as unknown as number;
  }

  private async dispatchAction(
    action: string,
    payload: Record<string, unknown> = {},
    silentSuccess = false,
  ): Promise<void> {
    if (!this.match || this.busy) return;
    this.busy = true;
    let shouldBackoff = false;
    try {
      if (this.room) {
        const res = await sendRoomAction(this.room.code, action, payload, this.spectateCid);
        this.applyRoomUpdate(res.room);
        if (!res.ok) shouldBackoff = true;
        if (!res.ok || !silentSuccess) {
          if (res.message) this.host.stage.showToast(res.message);
        }
      } else {
        const res = await sendAutoChessAction(this.match.id, action, payload);
        if (res.account) {
          this.host.setAccount(res.account);
        }
        if (res.ranked_settlement) {
          res.match.ranked_settlement = res.ranked_settlement;
        }
        this.applyMatchUpdate(res.match);
        if (!res.ok) shouldBackoff = true;
        if (!res.ok || !silentSuccess) {
          if (res.message) this.host.stage.showToast(res.message);
        }
      }
    } catch (err) {
      shouldBackoff = true;
      if (this.room && err instanceof ApiError && err.status === 404) {
        this.stopTimers();
      }
      this.host.stage.showToast(err instanceof Error ? err.message : String(err));
    } finally {
      this.busy = false;
      if (!this.room && this.match?.phase === 'combat') {
        this.scheduleCombatStep();
      } else if (!this.room && this.match?.phase === 'prep') {
        this.schedulePrepAutoStart(shouldBackoff ? 2500 : 250);
      } else if (!this.room && this.match?.phase === 'round_result') {
        this.scheduleRoundResultAutoNext(shouldBackoff ? 2500 : 250);
      }
    }
  }

  private unitAccent(serial: string): string {
    const meta = this.host.getCatalog()?.units.find(u => u.serial === serial);
    return meta?.accent || costColor(meta?.cost || 1);
  }

  private unitEmblem(serial: string, isSummon = false): string {
    const meta = this.host.getCatalog()?.units.find(u => u.serial === serial);
    if (meta?.emblem) return meta.emblem;
    return isSummon ? 'star' : 'flame';
  }

  private unitCustomImage(serial: string, team: 'Y' | 'X', inCombat: boolean, m: AutoChessMatchState): WxImage | null {
    const url = inCombat
      ? m.bout_token_overrides?.[team]?.[serial]
      : this.host.getAccount()?.token_overrides?.[serial];
    return this.host.stage.getCachedImage(url);
  }

  private allOwnedUnits(m: AutoChessMatchState): AutoChessOwnedUnit[] {
    return [...m.player.board, ...m.player.bench];
  }

  private selectedOwnedUnit(m: AutoChessMatchState): AutoChessOwnedUnit | null {
    if (!this.selectedUnitId) return null;
    return this.allOwnedUnits(m).find(u => u.id === this.selectedUnitId) || null;
  }

  private isPlayerEliminated(m: AutoChessMatchState): boolean {
    const me = (m.commanders || []).find(c => c.id === m.player.id);
    return Boolean(me?.eliminated || m.player.hp <= 0);
  }

  private handleTapUnit(unit: AutoChessOwnedUnit): void {
    const m = this.match;
    if (!m || m.phase !== 'prep') return;
    if (!this.selectedUnitId) {
      this.selectedUnitId = unit.id;
      return;
    }
    if (this.selectedUnitId === unit.id) {
      this.selectedUnitId = null;
      return;
    }
    const fromId = this.selectedUnitId;
    this.selectedUnitId = null;
    void this.dispatchAction('swap', { unit_a: fromId, unit_b: unit.id }, true);
  }

  private handleTapBoardCell(coord: string, unitOnCell: AutoChessOwnedUnit | undefined): void {
    const m = this.match;
    if (!m || m.phase !== 'prep') return;
    if (unitOnCell) {
      this.handleTapUnit(unitOnCell);
      return;
    }
    if (!this.selectedUnitId) return;
    const terrain = m.map.terrain[coord];
    if (terrain === 'wall') {
      this.host.stage.showToast('墙体地形不可布阵');
      return;
    }
    const [col] = parseCoord(coord);
    const allowedCols = m.map.deploy_cols?.Y || [];
    if (allowedCols.length > 0 && !allowedCols.includes(col)) {
      this.host.stage.showToast('仅可在己方蓝色部署区布阵');
      return;
    }
    const uid = this.selectedUnitId;
    this.selectedUnitId = null;
    void this.dispatchAction('deploy', { unit_id: uid, coord }, true);
  }

  render(): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const m = this.match;
    if (!m) return;

    ctx.fillStyle = PALETTE.bgDeep;
    ctx.fillRect(0, 0, 1280, 720);

    const padX = Math.max(16, stage.safeLeft);
    const rightX = 1280 - Math.max(16, stage.safeRight);

    this.renderTopHud(padX, rightX, m);
    this.renderLeftSidebar(padX, 66, 206, 456, m);
    this.renderCommandersStrip(rightX - 216, 66, 216, 456, m);
    this.renderBoardArea(padX + 216, 66, rightX - padX - 442, 456, m);
    this.renderBottomDock(padX, rightX, 532, 178, m);

    // Overlays
    if (m.phase === 'prep' && m.player.pending_augments && m.player.pending_augments.length > 0) {
      this.renderAugmentModal(m);
    } else if (m.phase === 'round_result' && m.last_round_report && !this.hideRoundResult) {
      this.renderRoundResultModal(m);
    } else if (m.phase === 'finished') {
      this.renderFinishedModal(m);
    }
    this.wikiModal.render(stage, this.host.getCatalog());
  }

  private renderTopHud(padX: number, rightX: number, m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    fillRoundRect(ctx, 0, 0, 1280, 58, 0, 'rgba(18, 23, 44, 0.96)');
    ctx.fillStyle = PALETTE.border;
    ctx.fillRect(0, 57, 1280, 1);

    drawButton(stage, ctx, { x: padX, y: 11, w: 84, h: 36 }, '← 大厅', () => {
      this.host.backToLobby();
    }, { fontSize: 13 });

    const modeLabel =
      m.mode === 'pve12'
        ? 'PvE 12关'
        : m.mode === 'ranked'
          ? '8人排位'
          : m.mode === 'pvp_room'
            ? `联机房 ${this.room?.code || ''}`
            : '4人标准';
    const leftSec = this.getPrepRemainingSec(m);
    const resultLeftSec = this.getRoundResultRemainingSec(m);
    const urgentPrep = m.phase === 'prep' && leftSec !== null && leftSec <= 5;
    const urgentResult = m.phase === 'round_result' && resultLeftSec !== null && resultLeftSec <= 3;
    const urgentPhase = urgentPrep || urgentResult;
    const phaseLabel =
      m.phase === 'prep'
        ? leftSec !== null
          ? `备战 ${leftSec}s`
          : '备战布阵'
        : m.phase === 'combat'
          ? '战斗演算中'
          : m.phase === 'round_result'
            ? resultLeftSec !== null
              ? `结算 ${resultLeftSec}s`
              : '回合结算'
            : '已结束';

    drawPill(ctx, padX + 90, 15, 138, 28, 'rgba(156,134,236,0.16)', PALETTE.violet, `${modeLabel} · R${m.round_num}`, PALETTE.textMain, 12);
    drawPill(
      ctx,
      padX + 234,
      15,
      92,
      28,
      urgentPhase ? 'rgba(241, 108, 141, 0.18)' : 'rgba(92,225,208,0.12)',
      urgentPhase ? PALETTE.rose : PALETTE.cyan,
      phaseLabel,
      urgentPhase ? PALETTE.rose : PALETTE.cyan,
      12,
    );

    const isEliminated = this.isPlayerEliminated(m);
    const canPrepAct = m.phase === 'prep' && !isEliminated;

    let rx = stage.topbarRightEdge;
    if (m.phase !== 'finished') {
      rx -= 76;
      drawButton(stage, ctx, { x: rx, y: 11, w: 76, h: 36 }, '投降', () => {
        void (async () => {
          if (await confirmAction('确认投降', '确定放弃当前对局并直接结算排名吗？')) {
            await this.dispatchAction('surrender');
          }
        })();
      }, { fontSize: 13, border: PALETTE.rose, color: PALETTE.rose, disabled: isEliminated });
    }

    if (m.phase === 'prep') {
      rx -= 92;
      drawButton(stage, ctx, { x: rx, y: 11, w: 84, h: 36 }, '一键布阵', () => {
        void this.dispatchAction('auto_arrange', {}, true);
      }, { fontSize: 13, disabled: !canPrepAct || m.player.board.length === 0 });
    } else if (m.phase === 'combat') {
      if (!this.room) {
        rx -= 78;
        drawButton(stage, ctx, { x: rx, y: 11, w: 70, h: 36 }, '跳过', () => {
          void this.dispatchAction('resolve_combat', {}, true);
        }, { fontSize: 13, border: PALETTE.goldSoft, color: PALETTE.gold });
        rx -= 80;
        drawButton(stage, ctx, { x: rx, y: 11, w: 72, h: 36 }, this.combatSpeed2x ? '2x 速度' : '1x 速度', () => {
          this.combatSpeed2x = !this.combatSpeed2x;
        }, { fontSize: 13, border: PALETTE.cyan, color: PALETTE.cyan });
      } else {
        const aliveHumans = (m.commanders || []).filter(c => c.is_human && !c.eliminated);
        const skippedCount = aliveHumans.filter(c => c.skip_combat).length;
        const mySkipped = Boolean(m.player.skip_combat);
        const skipLabel = mySkipped
          ? `已跳过 ${skippedCount}/${Math.max(1, aliveHumans.length)}`
          : skippedCount > 0
            ? `跳过 (${skippedCount}/${Math.max(1, aliveHumans.length)})`
            : '跳过战斗';
        rx -= 120;
        drawButton(stage, ctx, { x: rx, y: 11, w: 112, h: 36 }, skipLabel, () => {
          void this.dispatchAction('skip_combat', { skip: !mySkipped }, true);
        }, {
          fontSize: 12,
          bg: mySkipped ? '#2d365a' : PALETTE.bgCard,
          border: mySkipped ? PALETTE.borderBright : PALETTE.goldSoft,
          color: mySkipped ? PALETTE.textSub : PALETTE.gold,
          disabled: isEliminated,
        });
      }
    }

    const p = m.player;
    const statsText = `HP ${p.hp}/${p.max_hp} · ${p.gold}G · Lv.${p.level}(${p.xp}/${p.xp_to_next}) · 人口 ${p.board.length}/${p.max_pop} · 连胜${p.streak}`;
    const statsX = padX + 336;
    const statsMaxW = Math.max(120, rx - statsX - 12);
    drawClippedText(ctx, statsText, statsX, 29, statsMaxW, PALETTE.gold, '700 13px "PingFang SC", sans-serif');
    void rightX;
  }

  private renderLeftSidebar(x: number, y: number, w: number, h: number, m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;

    fillRoundRect(ctx, x, y, w, h, 12, PALETTE.bgPanel);
    strokeRoundRect(ctx, x, y, w, h, 12, PALETTE.border, 1.2);
    drawClippedText(ctx, '当前羁绊', x + 14, y + 22, w - 28, PALETTE.textMain, '700 15px "PingFang SC", sans-serif');

    const synergies = m.player.synergies || [];
    const maxSynergyRows = 6;
    if (synergies.length === 0) {
      drawClippedText(ctx, '上阵棋子激活羁绊', x + 14, y + 54, w - 28, PALETTE.textMuted, '12px "PingFang SC", sans-serif');
    } else {
      synergies.slice(0, maxSynergyRows).forEach((s, idx) => {
        const sy = y + 40 + idx * 36;
        const active = Boolean(s.active_tier);
        fillRoundRect(ctx, x + 10, sy, w - 20, 30, 8, active ? 'rgba(244,200,106,0.14)' : PALETTE.bgCard);
        strokeRoundRect(ctx, x + 10, sy, w - 20, 30, 8, active ? PALETTE.goldSoft : PALETTE.border, 1);
        drawClippedText(
          ctx,
          `${s.name} ${s.count}${s.next_tier ? `/${s.next_tier}` : ''}`,
          x + 18,
          sy + 15,
          w - 36,
          active ? PALETTE.gold : PALETTE.textSub,
          '700 12px "PingFang SC", sans-serif',
        );
      });
    }

    // Selected unit inspector card at bottom of left sidebar
    const sel = this.selectedOwnedUnit(m);
    const cardY = y + h - 186;
    fillRoundRect(ctx, x + 10, cardY, w - 20, 176, 10, PALETTE.bgCard);
    strokeRoundRect(ctx, x + 10, cardY, w - 20, 176, 10, sel ? costColor(sel.cost) : PALETTE.border, 1.2);

    if (!sel) {
      drawWrappedText(
        ctx,
        '操作提示：\n• 点备战/棋盘棋子选中\n• 点蓝色部署格上阵\n• 点另一棋子互换位置',
        x + 20,
        cardY + 18,
        w - 40,
        22,
        PALETTE.textSub,
        '12px "PingFang SC", sans-serif',
        5,
      );
      return;
    }

    drawClippedText(ctx, `${sel.name} ${'★'.repeat(sel.star)}`, x + 20, cardY + 22, w - 92, costColor(sel.cost), '700 15px "PingFang SC", sans-serif');
    drawButton(stage, ctx, { x: x + w - 66, y: cardY + 10, w: 48, h: 24 }, '详情', () => {
      this.wikiModal.open('units', sel.serial);
    }, { fontSize: 11, border: PALETTE.cyan, color: PALETTE.cyan, radius: 6 });
    drawClippedText(
      ctx,
      `${AUTOCHESS_ROLE_LABELS[sel.role] || sel.role} · ${sel.traits.join('/')} · 射程${sel.range}`,
      x + 20,
      cardY + 44,
      w - 40,
      PALETTE.textSub,
      '12px "PingFang SC", sans-serif',
    );
    drawClippedText(
      ctx,
      `位置：${sel.location === 'board' ? sel.coord : `备战席#${(sel.bench_idx ?? 0) + 1}`}`,
      x + 20,
      cardY + 66,
      w - 40,
      PALETTE.textMuted,
      '12px "PingFang SC", sans-serif',
    );

    const isEliminated = this.isPlayerEliminated(m);
    const canPrepAct = m.phase === 'prep' && !isEliminated;
    const benchCap = Math.max(1, m.player.bench_capacity || 8);
    const benchFull = m.player.bench.length >= benchCap;

    const stanceLabel = STANCE_LABELS[sel.stance] || sel.stance;
    drawButton(stage, ctx, { x: x + 18, y: cardY + 84, w: w - 36, h: 36 }, `姿态：${stanceLabel} (切换)`, () => {
      const nextStance = STANCE_ORDER[(STANCE_ORDER.indexOf(sel.stance) + 1) % STANCE_ORDER.length];
      void this.dispatchAction('set_stance', { unit_id: sel.id, stance: nextStance }, true);
    }, { fontSize: 12, disabled: !canPrepAct });

    if (sel.location === 'board') {
      drawButton(stage, ctx, { x: x + 18, y: cardY + 128, w: (w - 42) / 2, h: 36 }, benchFull ? '备战已满' : '撤回席', () => {
        const uid = sel.id;
        this.selectedUnitId = null;
        void this.dispatchAction('recall', { unit_id: uid }, true);
      }, { fontSize: 12, disabled: !canPrepAct || benchFull });
      drawButton(stage, ctx, { x: x + 24 + (w - 42) / 2, y: cardY + 128, w: (w - 42) / 2, h: 36 }, '出售', () => {
        const uid = sel.id;
        this.selectedUnitId = null;
        void this.dispatchAction('sell', { unit_id: uid }, true);
      }, { fontSize: 12, border: PALETTE.rose, color: PALETTE.rose, disabled: !canPrepAct });
    } else {
      drawButton(stage, ctx, { x: x + 18, y: cardY + 128, w: w - 36, h: 36 }, '出售该棋子', () => {
        const uid = sel.id;
        this.selectedUnitId = null;
        void this.dispatchAction('sell', { unit_id: uid }, true);
      }, { fontSize: 12, border: PALETTE.rose, color: PALETTE.rose, disabled: !canPrepAct });
    }
  }

  private renderCommandersStrip(x: number, y: number, w: number, h: number, m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;

    fillRoundRect(ctx, x, y, w, h, 12, PALETTE.bgPanel);
    strokeRoundRect(ctx, x, y, w, h, 12, PALETTE.border, 1.2);
    drawClippedText(
      ctx,
      this.room ? '玩家排行 (点击观战)' : '全场指挥官排行',
      x + 14,
      y + 22,
      w - 28,
      PALETTE.textMain,
      '700 14px "PingFang SC", sans-serif',
    );

    const list = m.commanders || [];
    const maxRows = Math.min(8, list.length);
    const rowH = Math.min(48, Math.floor((h - 46) / Math.max(1, maxRows)) - 4);

    for (let i = 0; i < maxRows; i += 1) {
      const c = list[i];
      const ry = y + 38 + i * (rowH + 4);
      const isMe = c.id === m.player.id;
      const isSpectating = m.watching_cid === c.id;
      fillRoundRect(
        ctx,
        x + 10,
        ry,
        w - 20,
        rowH,
        8,
        isSpectating ? '#2b244e' : isMe ? '#1f2b48' : PALETTE.bgCard,
      );
      strokeRoundRect(
        ctx,
        x + 10,
        ry,
        w - 20,
        rowH,
        8,
        c.eliminated ? '#292c3e' : isSpectating ? PALETTE.gold : isMe ? PALETTE.cyan : PALETTE.border,
        1.1,
      );

      const labelColor = c.eliminated ? PALETTE.textMuted : isMe ? PALETTE.cyan : PALETTE.textMain;
      drawClippedText(
        ctx,
        `${c.name}${c.is_human && !isMe ? ' [人]' : ''}`,
        x + 18,
        ry + rowH * 0.34,
        w - 86,
        labelColor,
        '700 12px "PingFang SC", sans-serif',
      );
      drawClippedText(
        ctx,
        c.eliminated ? `#${c.placement || '-'}` : `${c.hp}HP`,
        x + w - 18,
        ry + rowH * 0.34,
        62,
        c.eliminated ? PALETTE.rose : PALETTE.emerald,
        '700 12px sans-serif',
        'right',
        'middle',
      );
      drawProgressBar(
        ctx,
        x + 18,
        ry + rowH - 10,
        w - 36,
        4,
        c.hp / Math.max(1, c.max_hp),
        '#111629',
        c.eliminated ? '#444b66' : isMe ? PALETTE.cyan : PALETTE.emerald,
        2,
      );

      if (this.room && !c.eliminated) {
        stage.addHitRegion({
          x: x + 10,
          y: ry,
          w: w - 20,
          h: rowH,
          onTap: () => {
            this.spectateCid = c.id === m.player.id ? null : c.id;
            this.roomVersion = -1;
            if (this.room) {
              this.startRoomPoller(this.room.code);
            }
          },
        });
      }
    }
  }

  private renderBoardArea(x: number, y: number, w: number, h: number, m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;

    fillRoundRect(ctx, x, y, w, h, 14, PALETTE.bgPanel);
    strokeRoundRect(ctx, x, y, w, h, 14, PALETTE.border, 1.2);

    const activeFrame =
      m.phase === 'combat' && m.combat_frames && m.combat_frames.length > 0
        ? m.combat_frames[m.combat_frames.length - 1]
        : null;
    const combatSnap = m.phase === 'combat' ? m.live_snapshot || activeFrame?.snapshot || null : null;

    const cols = combatSnap?.width || m.map.width;
    const rows = combatSnap?.height || m.map.height;
    const terrain = combatSnap?.terrain || m.map.terrain || {};
    const deployColsY = m.map.deploy_cols?.Y || [];

    const bannerH = 32;
    const cellSize = Math.floor(Math.min((w - 56) / cols, (h - bannerH - 42) / rows));
    const gridW = cols * cellSize;
    const gridH = rows * cellSize;
    const gx = x + Math.floor((w - gridW) / 2);
    const gy = y + bannerH + Math.floor((h - bannerH - gridH) / 2);

    // Top status banner inside board
    const bannerText =
      m.phase === 'combat'
        ? this.room && m.player.skip_combat
          ? '你已跳过本轮战斗，等待其他玩家结束或跳过…'
          : activeFrame
            ? `[第${activeFrame.round}轮] ${activeFrame.actor_name}：${activeFrame.lines?.[0] || activeFrame.reason || ''}`
            : `战斗中 · 对手：${m.opponent_name || '星序敌军'}`
        : `${m.arena_name} · ${this.selectedUnitId ? '点击己方蓝色格部署或点击棋子换位' : '点击棋子选中并调整站位'}`;
    drawClippedText(ctx, bannerText, x + w / 2, y + 18, w - 32, PALETTE.textSub, '600 13px "PingFang SC", sans-serif', 'center', 'middle');

    const boardUnitByCoord = new Map<string, AutoChessOwnedUnit>();
    if (m.phase !== 'combat') {
      for (const u of m.player.board) {
        if (u.coord) boardUnitByCoord.set(u.coord, u);
      }
    }

    // Draw cells
    for (let r = 0; r < rows; r += 1) {
      drawClippedText(ctx, String(r + 1), gx - 14, gy + r * cellSize + cellSize / 2, 16, PALETTE.textMuted, '600 11px sans-serif', 'center', 'middle');
      for (let c = 0; c < cols; c += 1) {
        if (r === 0) {
          drawClippedText(ctx, String.fromCharCode(65 + c), gx + c * cellSize + cellSize / 2, gy - 12, 18, PALETTE.textMuted, '600 11px sans-serif', 'center', 'middle');
        }
        const coord = formatCoord(c, r);
        const cx = gx + c * cellSize;
        const cy = gy + r * cellSize;
        const terr = terrain[coord];
        const isDeployY = m.phase === 'prep' && deployColsY.includes(c);

        let fill = (c + r) % 2 === 0 ? '#181e36' : '#14192e';
        if (terr === 'wall') fill = '#2e344d';
        else if (terr === 'cover') fill = '#1e3847';
        else if (terr === 'leyline') fill = '#2f2352';
        else if (isDeployY) fill = (c + r) % 2 === 0 ? '#1d2849' : '#192341';

        ctx.fillStyle = fill;
        ctx.fillRect(cx + 1, cy + 1, cellSize - 2, cellSize - 2);
        ctx.strokeStyle = isDeployY ? '#384c82' : '#262e4d';
        ctx.lineWidth = 1;
        ctx.strokeRect(cx + 1, cy + 1, cellSize - 2, cellSize - 2);

        if (terr) {
          const terrTag = terr === 'wall' ? '墙' : terr === 'cover' ? '掩' : '脉';
          drawClippedText(ctx, terrTag, cx + cellSize - 8, cy + 10, 14, 'rgba(255,255,255,0.28)', '600 10px sans-serif', 'center', 'middle');
        }

        if (m.phase === 'prep') {
          const u = boardUnitByCoord.get(coord);
          stage.addHitRegion({
            x: cx,
            y: cy,
            w: cellSize,
            h: cellSize,
            onTap: () => this.handleTapBoardCell(coord, u),
          });
        }
      }
    }

    const cellCenter = (coord: string) => {
      const [c, r] = parseCoord(coord);
      if (c < 0 || r < 0 || c >= cols || r >= rows) return null;
      return {
        x: gx + c * cellSize + cellSize / 2,
        y: gy + r * cellSize + cellSize / 2,
      };
    };

    // Draw units
    if (combatSnap) {
      this.renderCombatUnits(ctx, combatSnap.units, cellCenter, cellSize, m);
      this.vfx.render(ctx, cellCenter);
    } else {
      for (const u of m.player.board) {
        if (!u.coord) continue;
        const center = cellCenter(u.coord);
        if (!center) continue;
        const sel = this.selectedUnitId === u.id;
        const radius = Math.max(14, Math.floor(cellSize * 0.33));
        const accent = this.unitAccent(u.serial);
        if (sel) {
          ctx.save();
          ctx.strokeStyle = PALETTE.gold;
          ctx.lineWidth = 2.5;
          ctx.beginPath();
          ctx.arc(center.x, center.y, radius + 5, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
        drawEmblemBadge(
          ctx,
          center.x,
          center.y - 3,
          radius,
          this.unitEmblem(u.serial),
          accent,
          PALETTE.cyan,
          this.unitCustomImage(u.serial, 'Y', false, m),
        );
        drawClippedText(ctx, '★'.repeat(u.star), center.x, center.y - radius - 6, cellSize, PALETTE.gold, '700 10px sans-serif', 'center', 'middle');
        drawClippedText(ctx, u.name, center.x, center.y + radius + 5, cellSize + 6, PALETTE.textMain, '600 11px "PingFang SC", sans-serif', 'center', 'middle');
      }
    }
  }

  private renderCombatUnits(
    ctx: WxCanvasRenderingContext2D,
    units: AutoChessCombatUnit[],
    cellCenter: (coord: string) => { x: number; y: number } | null,
    cellSize: number,
    m: AutoChessMatchState,
  ): void {
    const radius = Math.max(13, Math.floor(cellSize * 0.31));
    for (const u of units) {
      if (u.hp <= 0 && u.dying) continue;
      const center = cellCenter(u.coord);
      if (!center) continue;
      const teamColor = u.team === 'Y' ? PALETTE.cyan : PALETTE.rose;
      const accent = this.unitAccent(u.serial);

      ctx.save();
      if (u.hp <= 0) ctx.globalAlpha = 0.32;
      drawEmblemBadge(
        ctx,
        center.x,
        center.y - 3,
        radius,
        this.unitEmblem(u.serial, u.is_summon),
        accent,
        teamColor,
        this.unitCustomImage(u.serial, u.team, true, m),
        u.is_summon,
      );
      const barW = Math.max(26, cellSize * 0.72);
      drawProgressBar(
        ctx,
        center.x - barW / 2,
        center.y + radius + 1,
        barW,
        5,
        u.hp / Math.max(1, u.max_hp),
        '#101424',
        u.team === 'Y' ? PALETTE.emerald : PALETTE.rose,
        2,
      );
      if (u.shield > 0) {
        drawProgressBar(
          ctx,
          center.x - barW / 2,
          center.y + radius + 7,
          barW,
          3,
          Math.min(1, u.shield / Math.max(1, u.max_hp)),
          '#101424',
          '#7cc8ff',
          1.5,
        );
      }
      drawClippedText(ctx, u.name, center.x, center.y - radius - 7, cellSize + 8, PALETTE.textMain, '600 10px "PingFang SC", sans-serif', 'center', 'middle');
      ctx.restore();
    }
  }

  private renderBottomDock(padX: number, rightX: number, y: number, h: number, m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const totalW = rightX - padX;
    const p = m.player;

    fillRoundRect(ctx, padX, y, totalW, h, 12, PALETTE.bgPanel);
    strokeRoundRect(ctx, padX, y, totalW, h, 12, PALETTE.border, 1.2);

    // Top row inside dock: Bench slots
    const benchCount = Math.max(8, p.bench_capacity || 8);
    const benchAreaW = totalW - 240;
    const slotGap = 8;
    const slotW = Math.floor((benchAreaW - (benchCount - 1) * slotGap) / benchCount);
    const slotH = 54;
    const bx0 = padX + 14;
    const by0 = y + 10;

    for (let i = 0; i < benchCount; i += 1) {
      const unit = p.bench.find(u => u.bench_idx === i);
      const sx = bx0 + i * (slotW + slotGap);
      const selected = Boolean(unit && this.selectedUnitId === unit.id);
      fillRoundRect(ctx, sx, by0, slotW, slotH, 8, unit ? PALETTE.bgCard : '#12172b');
      strokeRoundRect(
        ctx,
        sx,
        by0,
        slotW,
        slotH,
        8,
        selected ? PALETTE.gold : unit ? costColor(unit.cost) : '#252e4c',
        selected ? 2 : 1.1,
      );
      if (unit) {
        drawEmblemBadge(
          ctx,
          sx + 22,
          by0 + slotH / 2,
          15,
          this.unitEmblem(unit.serial),
          this.unitAccent(unit.serial),
          undefined,
          this.unitCustomImage(unit.serial, 'Y', false, m),
        );
        drawClippedText(ctx, unit.name, sx + 42, by0 + 18, slotW - 48, PALETTE.textMain, '700 12px "PingFang SC", sans-serif');
        drawClippedText(ctx, `${'★'.repeat(unit.star)} ${unit.cost}G`, sx + 42, by0 + 38, slotW - 48, PALETTE.gold, '600 11px sans-serif');
        stage.addHitRegion({
          x: sx,
          y: by0,
          w: slotW,
          h: slotH,
          onTap: () => this.handleTapUnit(unit),
        });
      } else {
        drawClippedText(ctx, `席${i + 1}`, sx + slotW / 2, by0 + slotH / 2, slotW - 8, '#3d476c', '11px sans-serif', 'center', 'middle');
      }
    }

    // Top right of dock: Primary Combat / Ready button
    const isEliminated = this.isPlayerEliminated(m);
    const canPrepAct = m.phase === 'prep' && !isEliminated;
    const hasPendingAugments = Boolean(p.pending_augments && p.pending_augments.length > 0);
    const readyBtnX = rightX - 210;
    if (m.phase === 'prep') {
      const label = isEliminated
        ? '已淘汰观战中'
        : this.room
          ? p.ready
            ? '已准备 (取消)'
            : '准备开战'
          : '开始战斗';
      drawButton(stage, ctx, { x: readyBtnX, y: by0, w: 196, h: slotH }, label, () => {
        void this.dispatchAction('ready_combat', this.room ? { ready: !p.ready } : {}, true);
      }, {
        bg: p.ready ? '#2d365a' : '#1b644a',
        border: p.ready ? PALETTE.borderBright : PALETTE.emerald,
        fontSize: 16,
        disabled: isEliminated || hasPendingAugments,
      });
    } else if (m.phase === 'round_result') {
      const nextLabel = isEliminated
        ? '已淘汰观战中'
        : this.room
          ? p.next_ready
            ? '已就绪 (取消)'
            : '准备下一回合'
          : '进入下一回合';
      drawButton(stage, ctx, { x: readyBtnX, y: by0, w: 196, h: slotH }, nextLabel, () => {
        void this.dispatchAction('ready_next', this.room ? { ready: !p.next_ready } : {}, true);
      }, {
        bg: p.next_ready ? '#2d365a' : PALETTE.violetDark,
        border: p.next_ready ? PALETTE.borderBright : PALETTE.gold,
        fontSize: 15,
        disabled: isEliminated,
      });
    } else {
      const combatWaitLabel =
        m.phase === 'combat'
          ? this.room && m.player.skip_combat
            ? '已跳过 · 等待结算'
            : '战斗演算中…'
          : '已结束';
      drawButton(stage, ctx, { x: readyBtnX, y: by0, w: 196, h: slotH }, combatWaitLabel, () => {}, {
        disabled: true,
        fontSize: 14,
      });
    }

    // Bottom row: Economy buttons + 5 Shop Cards
    const ctrlX = padX + 14;
    const shopY = y + 74;
    const ctrlH = 92;

    const xpMaxed = p.xp_to_next <= 0;
    const xpNoGold = !xpMaxed && p.gold < 4;
    const buyXpDisabled = !canPrepAct || xpMaxed || xpNoGold;
    drawButton(stage, ctx, { x: ctrlX, y: shopY, w: 126, h: 42 }, xpMaxed ? '已达满级' : '升级 +4XP', () => {
      void this.dispatchAction('buy_xp', {}, true);
    }, {
      sublabel: xpMaxed ? '满级' : xpNoGold && canPrepAct ? '4 金币 · 不足' : '4 金币',
      sublabelColor: xpNoGold && canPrepAct ? '#c8647e' : undefined,
      fontSize: 13,
      disabled: buyXpDisabled,
    });

    const hasFreeReroll = p.free_rerolls > 0;
    const rerollNoGold = !hasFreeReroll && p.gold < 2;
    const rerollDisabled = !canPrepAct || rerollNoGold;
    const rerollLabel = hasFreeReroll ? `刷新 (免费${p.free_rerolls})` : '刷新商店';
    drawButton(stage, ctx, { x: ctrlX, y: shopY + 48, w: 126, h: 44 }, rerollLabel, () => {
      void this.dispatchAction('reroll', {}, true);
    }, {
      sublabel: hasFreeReroll ? '0 金币' : rerollNoGold && canPrepAct ? '2 金币 · 不足' : '2 金币',
      sublabelColor: rerollNoGold && canPrepAct ? '#c8647e' : undefined,
      fontSize: 13,
      disabled: rerollDisabled,
    });

    drawButton(stage, ctx, { x: ctrlX + 134, y: shopY, w: 72, h: 92 }, p.shop_locked ? '已锁定' : '锁定', () => {
      void this.dispatchAction('lock_shop', {}, true);
    }, {
      sublabel: '商店',
      fontSize: 13,
      bg: p.shop_locked ? '#3c2e1c' : PALETTE.bgCard,
      border: p.shop_locked ? PALETTE.gold : PALETTE.borderBright,
      disabled: !canPrepAct,
    });

    const shopStartX = ctrlX + 216;
    const shopTotalW = rightX - 14 - shopStartX;
    const cardGap = 10;
    const cardW = Math.floor((shopTotalW - 4 * cardGap) / 5);

    const benchCap = Math.max(1, p.bench_capacity || 8);
    const benchFull = p.bench.length >= benchCap;
    const boardFull = p.board.length >= p.max_pop;
    const ownedAll = this.allOwnedUnits(m);

    for (let i = 0; i < 5; i += 1) {
      const slot = p.shop[i];
      const cx = shopStartX + i * (cardW + cardGap);
      if (!slot || slot.bought) {
        fillRoundRect(ctx, cx, shopY, cardW, ctrlH, 10, '#12172b');
        strokeRoundRect(ctx, cx, shopY, cardW, ctrlH, 10, '#232b47', 1);
        drawClippedText(ctx, slot?.bought ? '已购入' : '空槽', cx + cardW / 2, shopY + ctrlH / 2, cardW - 12, '#434d73', '13px "PingFang SC", sans-serif', 'center', 'middle');
        continue;
      }

      const cantAfford = p.gold < slot.cost;
      const willMerge = ownedAll.filter(u => u.serial === slot.serial && u.star === 1).length >= 2;
      const noSpace = benchFull && boardFull && !willMerge;
      const cardDisabled = !canPrepAct || cantAfford || noSpace;

      const cColor = costColor(slot.cost);
      if (cardDisabled) {
        fillRoundRect(ctx, cx, shopY, cardW, ctrlH, 10, '#121626');
        strokeRoundRect(ctx, cx, shopY, cardW, ctrlH, 10, '#252c44', 1);

        ctx.save();
        ctx.globalAlpha = 0.4;
        drawEmblemBadge(
          ctx,
          cx + 26,
          shopY + 28,
          16,
          this.unitEmblem(slot.serial),
          this.unitAccent(slot.serial),
          undefined,
          this.unitCustomImage(slot.serial, 'Y', false, m),
        );
        drawClippedText(ctx, slot.name, cx + 50, shopY + 22, cardW - 92, PALETTE.textMuted, '700 14px "PingFang SC", sans-serif');
        drawClippedText(ctx, slot.traits.join(' · '), cx + 12, shopY + 54, cardW - 24, PALETTE.textMuted, '12px "PingFang SC", sans-serif');
        ctx.restore();

        drawClippedText(
          ctx,
          `${slot.cost}G`,
          cx + cardW - 12,
          shopY + 22,
          42,
          canPrepAct && cantAfford ? '#d96480' : '#5b6482',
          '700 14px sans-serif',
          'right',
          'middle',
        );

        let bottomText: string;
        let bottomColor: string;
        if (canPrepAct && cantAfford) {
          bottomText = slot.hint ? `金币不足 · ${slot.hint}` : '金币不足';
          bottomColor = '#c8647e';
        } else if (canPrepAct && noSpace) {
          bottomText = '席位已满';
          bottomColor = '#c98c3a';
        } else {
          bottomText = slot.hint ? `▲ ${slot.hint}` : AUTOCHESS_ROLE_LABELS[slot.role] || slot.role;
          bottomColor = '#4d5673';
        }
        drawClippedText(
          ctx,
          bottomText,
          cx + 12,
          shopY + 76,
          cardW - 24,
          bottomColor,
          '700 11px "PingFang SC", sans-serif',
        );
      } else {
        fillRoundRect(ctx, cx, shopY, cardW, ctrlH, 10, PALETTE.bgCard);
        strokeRoundRect(ctx, cx, shopY, cardW, ctrlH, 10, slot.hint ? PALETTE.gold : cColor, slot.hint ? 2 : 1.3);

        drawEmblemBadge(
          ctx,
          cx + 26,
          shopY + 28,
          16,
          this.unitEmblem(slot.serial),
          this.unitAccent(slot.serial),
          undefined,
          this.unitCustomImage(slot.serial, 'Y', false, m),
        );
        drawClippedText(ctx, slot.name, cx + 50, shopY + 22, cardW - 92, PALETTE.textMain, '700 14px "PingFang SC", sans-serif');
        drawClippedText(ctx, `${slot.cost}G`, cx + cardW - 12, shopY + 22, 42, PALETTE.gold, '700 14px sans-serif', 'right', 'middle');
        drawClippedText(ctx, slot.traits.join(' · '), cx + 12, shopY + 54, cardW - 24, PALETTE.textSub, '12px "PingFang SC", sans-serif');
        drawClippedText(
          ctx,
          slot.hint ? `▲ ${slot.hint}` : AUTOCHESS_ROLE_LABELS[slot.role] || slot.role,
          cx + 12,
          shopY + 76,
          cardW - 24,
          slot.hint ? PALETTE.gold : PALETTE.textMuted,
          '700 11px "PingFang SC", sans-serif',
        );

        stage.addHitRegion({
          x: cx,
          y: shopY,
          w: cardW,
          h: ctrlH,
          onTap: () => void this.dispatchAction('buy', { slot_index: slot.slot_index }, true),
        });
      }
    }
  }

  private renderAugmentModal(m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const choices = m.player.pending_augments || [];
    fillRoundRect(ctx, 0, 0, 1280, 720, 0, 'rgba(6, 8, 16, 0.8)');
    stage.addHitRegion({ x: 0, y: 0, w: 1280, h: 720, onTap: () => {} });

    drawClippedText(ctx, '星序海克斯祝福 · 请选择一项强化', 640, 118, 600, PALETTE.gold, '700 24px "PingFang SC", sans-serif', 'center', 'middle');
    const leftSec = this.getPrepRemainingSec(m);
    if (leftSec !== null) {
      drawClippedText(
        ctx,
        `剩余 ${leftSec} 秒，超时自动选择第一项祝福并开战`,
        640,
        148,
        600,
        leftSec <= 5 ? PALETTE.rose : PALETTE.textSub,
        '600 13px "PingFang SC", sans-serif',
        'center',
        'middle',
      );
    }

    const cardW = 300;
    const cardH = 340;
    const gap = 28;
    const startX = (1280 - (choices.length * cardW + (choices.length - 1) * gap)) / 2;

    choices.forEach((aug, idx) => {
      const cx = startX + idx * (cardW + gap);
      const cy = 174;
      fillRoundRect(ctx, cx, cy, cardW, cardH, 16, PALETTE.bgPanel);
      strokeRoundRect(ctx, cx, cy, cardW, cardH, 16, PALETTE.gold, 1.8);
      drawPill(ctx, cx + 22, cy + 24, 90, 26, 'rgba(244,200,106,0.16)', PALETTE.gold, aug.tier || '星序祝福', PALETTE.gold, 12);
      drawClippedText(ctx, aug.name, cx + 22, cy + 78, cardW - 44, PALETTE.textMain, '700 20px "PingFang SC", sans-serif');
      drawWrappedText(ctx, aug.desc || '', cx + 22, cy + 112, cardW - 44, 24, PALETTE.textSub, '14px "PingFang SC", sans-serif', 6);
      drawButton(stage, ctx, { x: cx + 22, y: cy + cardH - 64, w: cardW - 44, h: 44 }, '选择此祝福', () => {
        void this.dispatchAction('pick_augment', { augment_id: aug.id });
      }, { bg: PALETTE.violetDark, border: PALETTE.gold, fontSize: 15 });
    });
  }

  private renderRoundResultModal(m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const rep = m.last_round_report;
    if (!rep) return;

    fillRoundRect(ctx, 0, 0, 1280, 720, 0, 'rgba(6, 8, 16, 0.72)');
    stage.addHitRegion({ x: 0, y: 0, w: 1280, h: 720, onTap: () => { this.hideRoundResult = true; } });

    const mw = 680;
    const mh = 430;
    const mx = (1280 - mw) / 2;
    const my = (720 - mh) / 2;
    fillRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.bgPanel);
    strokeRoundRect(ctx, mx, my, mw, mh, 16, rep.won ? PALETTE.emerald : PALETTE.rose, 1.8);
    stage.addHitRegion({ x: mx, y: my, w: mw, h: mh, onTap: () => {} });

    drawClippedText(
      ctx,
      `第 ${rep.round} 回合 · ${rep.won ? '胜利！' : '惜败'}（vs ${rep.opponent_name}）`,
      mx + 26,
      my + 36,
      mw - 100,
      rep.won ? PALETTE.emerald : PALETTE.rose,
      '700 20px "PingFang SC", sans-serif',
    );
    const resultLeftSec = this.getRoundResultRemainingSec(m);
    const resultCountdownNote = resultLeftSec !== null ? ` · ${resultLeftSec}s 后自动进入下回合` : '';
    drawClippedText(
      ctx,
      `激战 ${rep.battle_rounds} 轮${rep.timeout ? '（超时判定）' : ''} · 指挥官 HP 扣减 ${rep.hp_damage}${resultCountdownNote}`,
      mx + 26,
      my + 68,
      mw - 52,
      resultLeftSec !== null && resultLeftSec <= 3 ? PALETTE.rose : PALETTE.textSub,
      '14px "PingFang SC", sans-serif',
    );

    if (rep.mvp) {
      fillRoundRect(ctx, mx + 26, my + 92, mw - 52, 46, 10, '#232b4c');
      drawClippedText(
        ctx,
        `本轮 MVP：${rep.mvp.name} — 伤害 ${rep.mvp.dmg_dealt} · 治疗 ${rep.mvp.heal_done} · 击杀 ${rep.mvp.kills}`,
        mx + 42,
        my + 115,
        mw - 84,
        PALETTE.gold,
        '700 14px "PingFang SC", sans-serif',
      );
    }

    const topRows = [...(rep.telemetry || [])]
      .sort((a, b) => b.dmg_dealt - a.dmg_dealt)
      .slice(0, 5);
    topRows.forEach((row, i) => {
      const ry = my + 150 + i * 36;
      fillRoundRect(ctx, mx + 26, ry, mw - 52, 30, 6, PALETTE.bgCard);
      drawClippedText(ctx, `${row.team === 'Y' ? '[己]' : '[敌]'} ${row.name}`, mx + 38, ry + 15, 220, row.team === 'Y' ? PALETTE.cyan : PALETTE.rose, '600 13px "PingFang SC", sans-serif');
      drawClippedText(ctx, `输出 ${row.dmg_dealt} · 承伤 ${row.dmg_taken} · 治疗 ${row.heal_done}`, mx + mw - 38, ry + 15, 340, PALETTE.textSub, '12px "PingFang SC", sans-serif', 'right', 'middle');
    });

    drawButton(stage, ctx, { x: mx + 26, y: my + mh - 64, w: 180, h: 42 }, '查看棋盘', () => {
      this.hideRoundResult = true;
    }, { fontSize: 14 });

    const nextLabel = this.room
      ? m.player.next_ready
        ? '已就绪 (等待他人)'
        : '准备下一回合'
      : '进入下一回合';
    drawButton(stage, ctx, { x: mx + mw - 236, y: my + mh - 64, w: 210, h: 42 }, nextLabel, () => {
      void this.dispatchAction('ready_next', this.room ? { ready: !m.player.next_ready } : {}, true);
    }, { bg: PALETTE.violetDark, border: PALETTE.gold, fontSize: 15 });
  }

  private renderFinishedModal(m: AutoChessMatchState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    fillRoundRect(ctx, 0, 0, 1280, 720, 0, 'rgba(6, 8, 16, 0.8)');
    stage.addHitRegion({ x: 0, y: 0, w: 1280, h: 720, onTap: () => {} });

    const mw = 620;
    const mh = 390;
    const mx = (1280 - mw) / 2;
    const my = (720 - mh) / 2;
    fillRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.bgPanel);
    strokeRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.gold, 2);

    const place = m.player.placement || (m.winner_id === m.player.id ? 1 : 4);
    const won = place === 1;
    drawClippedText(
      ctx,
      won ? '★ 星序夺魁 · 第 1 名！' : `对局结束 · 第 ${place} 名`,
      mx + mw / 2,
      my + 52,
      mw - 48,
      won ? PALETTE.gold : PALETTE.textMain,
      '700 26px "PingFang SC", sans-serif',
      'center',
      'middle',
    );
    drawClippedText(
      ctx,
      `总回合 R${m.round_num} · 剩余 HP ${m.player.hp}`,
      mx + mw / 2,
      my + 92,
      mw - 48,
      PALETTE.textSub,
      '15px "PingFang SC", sans-serif',
      'center',
      'middle',
    );

    const rs = m.ranked_settlement;
    if (rs) {
      const boxY = my + 124;
      fillRoundRect(ctx, mx + 36, boxY, mw - 72, 148, 12, PALETTE.bgCard);
      strokeRoundRect(ctx, mx + 36, boxY, mw - 72, 148, 12, tierColor(rs.new_rank.tier_id), 1.4);
      const deltaStr = rs.net_delta >= 0 ? `+${rs.net_delta}` : String(rs.net_delta);
      drawClippedText(ctx, `排位结算：${rs.new_rank.full_label} (${rs.new_lp} LP，${deltaStr})`, mx + 54, boxY + 34, mw - 108, tierColor(rs.new_rank.tier_id), '700 17px "PingFang SC", sans-serif');
      drawClippedText(ctx, `局外星币 +${rs.coins_earned}（当前 ${rs.coins_after}） · 保段卡 ${rs.shield_cards_after}`, mx + 54, boxY + 70, mw - 108, PALETTE.gold, '14px "PingFang SC", sans-serif');
      if (rs.shield_card_used) {
        drawClippedText(ctx, '已触发保段卡护盾！', mx + 54, boxY + 104, mw - 108, PALETTE.cyan, '700 13px "PingFang SC", sans-serif');
      } else if (rs.promoted) {
        drawClippedText(ctx, '恭喜晋升更高段位！', mx + 54, boxY + 104, mw - 108, PALETTE.emerald, '700 13px "PingFang SC", sans-serif');
      }
    }

    drawButton(stage, ctx, { x: mx + 150, y: my + mh - 74, w: mw - 300, h: 48 }, '返回星序大厅', () => {
      this.host.backToLobby();
    }, { bg: PALETTE.violetDark, border: PALETTE.gold, fontSize: 16 });
  }
}
