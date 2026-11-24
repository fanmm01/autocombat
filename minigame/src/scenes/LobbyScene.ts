import {
  bindWeChatAccount,
  createAutoChessMatch,
  createRankedMatch,
  deleteAutoChessMatch,
  ensureSession,
  fetchAutoChessCatalog,
  fetchRankedLeaderboard,
  getAuthMe,
  getAutoChessMatch,
  listAutoChessMatches,
  loginAccount,
  loginWithWeChat,
  logoutAccount,
  registerAccount,
  type AutoChessAccount,
  type AutoChessArenaPreset,
  type AutoChessCatalog,
  type AutoChessLeaderboardResponse,
  type AutoChessMatchState,
  type AutoChessMatchSummary,
} from '../net/autochessApi';
import { getSavedPlayerName, setSavedPlayerName } from '../net/transport';
import {
  PALETTE,
  Stage,
  confirmAction,
  drawButton,
  drawClippedText,
  drawPill,
  drawWrappedText,
  fillRoundRect,
  promptInput,
  strokeRoundRect,
  tierColor,
} from '../engine/ui';
import { WikiModal } from '../engine/wikiModal';

export interface LobbyHost {
  stage: Stage;
  getAccount(): AutoChessAccount | null;
  setAccount(acc: AutoChessAccount | null): void;
  getCatalog(): AutoChessCatalog | null;
  setCatalog(cat: AutoChessCatalog): void;
  openMatch(match: AutoChessMatchState): void;
  openRooms(): void;
}

type ModalState = 'none' | 'auth' | 'leaderboard';

export class LobbyScene {
  private readonly host: LobbyHost;
  private connected = false;
  private loading = true;
  private busy = false;
  private statusText = '正在连接星序云端引擎…';
  private matches: AutoChessMatchSummary[] = [];
  private selectedArena = 'autochess_standard';
  private modal: ModalState = 'none';
  private leaderboard: AutoChessLeaderboardResponse | null = null;
  private lbTier = 'all';
  private lbScroll = 0;
  private matchScroll = 0;
  private readonly wikiModal = new WikiModal();

  constructor(host: LobbyHost) {
    this.host = host;
  }

  onEnter(): void {
    void this.refreshAll();
  }

  onLeave(): void {
    this.modal = 'none';
    this.wikiModal.close();
  }

  async refreshAll(): Promise<void> {
    this.loading = true;
    try {
      const name = getSavedPlayerName();
      await ensureSession(name);
      this.connected = true;
      const [cat, auth, savedMatches] = await Promise.all([
        this.host.getCatalog() ? Promise.resolve(this.host.getCatalog()!) : fetchAutoChessCatalog(),
        getAuthMe().catch(() => ({ authenticated: false, account: null })),
        listAutoChessMatches(name).catch(() => []),
      ]);
      this.host.setCatalog(cat);
      if (cat.arenas.length > 0 && !cat.arenas.some(a => a.id === this.selectedArena)) {
        this.selectedArena = cat.arenas[0].id;
      }
      this.host.setAccount(auth.authenticated ? auth.account : null);
      this.matches = savedMatches;
      this.statusText = '星序引擎已就绪';
    } catch (err) {
      this.connected = false;
      this.statusText = err instanceof Error ? err.message : '连接引擎失败';
    } finally {
      this.loading = false;
    }
  }

  private async runBusy(fn: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      await fn();
    } catch (err) {
      this.host.stage.showToast(err instanceof Error ? err.message : String(err));
    } finally {
      this.busy = false;
    }
  }

  private currentArena(): AutoChessArenaPreset | null {
    const arenas = this.host.getCatalog()?.arenas || [];
    return arenas.find(a => a.id === this.selectedArena) || arenas[0] || null;
  }

  private cycleArena(): void {
    const arenas = this.host.getCatalog()?.arenas || [];
    if (arenas.length <= 1) return;
    const idx = arenas.findIndex(a => a.id === this.selectedArena);
    this.selectedArena = arenas[(idx + 1) % arenas.length].id;
  }

  private async startMatch(mode: 'pve12' | 'lobby4' | 'ranked'): Promise<void> {
    await this.runBusy(async () => {
      if (mode === 'ranked') {
        if (!this.host.getAccount()) {
          this.modal = 'auth';
          this.host.stage.showToast('请先微信一键登录或登录账号再参加排位赛');
          return;
        }
        const res = await createRankedMatch({ arena_preset: this.selectedArena });
        if (res.resumed) {
          this.host.stage.showToast('已为你恢复进行中的 8 人排位赛');
        }
        this.host.openMatch(res.match);
        return;
      }
      const acc = this.host.getAccount();
      const playerName = acc?.display_name || getSavedPlayerName();
      const match = await createAutoChessMatch({
        mode,
        arena_preset: this.selectedArena,
        player_name: playerName,
      });
      this.host.openMatch(match);
    });
  }

  private async handleWeChatLogin(): Promise<void> {
    await this.runBusy(async () => {
      const res = await loginWithWeChat();
      if (res.authenticated && res.account) {
        this.host.setAccount(res.account);
        setSavedPlayerName(res.account.display_name);
        this.matches = await listAutoChessMatches(res.account.display_name).catch(() => []);
        this.host.stage.showToast(res.created ? '已通过微信创建星序棋手账号' : '微信登录成功');
        this.modal = 'none';
      }
    });
  }

  private async handlePasswordLogin(isRegister: boolean, isBind: boolean): Promise<void> {
    const username = await promptInput(
      isBind ? '绑定已有账号 - 用户名' : isRegister ? '注册账号 - 用户名' : '账号登录 - 用户名',
      '3-20 位字母/数字/中文',
    );
    if (!username) return;
    const password = await promptInput('请输入密码', '至少 6 位字符');
    if (!password) return;

    await this.runBusy(async () => {
      let res;
      if (isBind) {
        res = await bindWeChatAccount({ username, password });
        this.host.stage.showToast('已成功将当前微信绑定到原有账号');
      } else if (isRegister) {
        const displayName = await promptInput('设置游戏昵称（可选）', '留空则默认用户名', username);
        res = await registerAccount({ username, password, display_name: displayName || undefined });
        this.host.stage.showToast('注册并登录成功');
      } else {
        res = await loginAccount({ username, password });
        this.host.stage.showToast('登录成功');
      }
      if (res.authenticated && res.account) {
        this.host.setAccount(res.account);
        setSavedPlayerName(res.account.display_name);
        this.matches = await listAutoChessMatches(res.account.display_name).catch(() => []);
        this.modal = 'none';
      }
    });
  }

  private async loadLeaderboard(tier = this.lbTier): Promise<void> {
    this.lbTier = tier;
    this.lbScroll = 0;
    this.modal = 'leaderboard';
    await this.runBusy(async () => {
      this.leaderboard = await fetchRankedLeaderboard(tier, 50);
    });
  }

  render(): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const acc = this.host.getAccount();
    const padX = Math.max(24, stage.safeLeft);
    const rightX = 1280 - Math.max(24, stage.safeRight);

    // Subtle starry header glow
    const grad = ctx.createLinearGradient(0, 0, 1280, 720);
    grad.addColorStop(0, '#12162d');
    grad.addColorStop(1, '#0b0e1b');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 1280, 720);

    // Top bar
    fillRoundRect(ctx, 0, 0, 1280, 68, 0, 'rgba(19, 24, 46, 0.94)');
    ctx.fillStyle = PALETTE.border;
    ctx.fillRect(0, 67, 1280, 1);

    stage.drawLogo(ctx, padX, 13, 42);
    drawClippedText(ctx, '星序自走棋', padX + 54, 26, 160, PALETTE.textMain, '700 20px "PingFang SC", sans-serif');
    drawClippedText(ctx, 'STARLIGHT AUTO-CHESS', padX + 54, 48, 160, PALETTE.textMuted, '600 11px sans-serif');

    // Connection pill
    drawPill(
      ctx,
      padX + 220,
      20,
      132,
      28,
      this.connected ? 'rgba(72, 214, 141, 0.14)' : 'rgba(241, 108, 141, 0.16)',
      this.connected ? PALETTE.emerald : PALETTE.rose,
      this.connected ? '● 引擎已连接' : '○ 未连接后端',
      this.connected ? PALETTE.emerald : PALETTE.rose,
      12,
    );

    // Right actions (anchored clear of WeChat capsule + "更多游戏" floating pill)
    let rx = stage.topbarRightEdge;
    rx -= 96;
    drawButton(stage, ctx, { x: rx, y: 15, w: 96, h: 38 }, '百科图鉴', () => {
      this.modal = 'none';
      this.wikiModal.open('units');
    }, { fontSize: 14 });

    rx -= 96;
    drawButton(stage, ctx, { x: rx, y: 15, w: 88, h: 38 }, '排行榜', () => {
      void this.loadLeaderboard('all');
    }, { fontSize: 14, border: PALETTE.goldSoft, color: PALETTE.gold, disabled: !this.connected || this.busy });

    rx -= 164;
    const accLabel = acc ? `${acc.display_name}${acc.wx_bound ? ' [微信]' : ''}` : '登录 / 绑定';
    drawButton(stage, ctx, { x: rx, y: 15, w: 156, h: 38 }, accLabel, () => {
      this.modal = 'auth';
    }, {
      fontSize: 14,
      bg: acc ? '#20294c' : PALETTE.violetDark,
      border: acc ? PALETTE.violet : '#a995ff',
      disabled: !this.connected || this.busy,
    });

    if (acc?.ranked) {
      rx -= 154;
      const rk = acc.ranked.rank_info;
      if (rx > padX + 360) {
        drawButton(stage, ctx, { x: rx, y: 15, w: 146, h: 38 }, `${rk.full_label} · ${acc.ranked.coins}币`, () => {
          void this.loadLeaderboard('all');
        }, {
          fontSize: 12,
          bg: '#1c223b',
          border: tierColor(rk.tier_id),
          color: tierColor(rk.tier_id),
        });
      }
    }

    // Left Column: Mode Cards + Arena Selector
    const leftW = 736;
    const colY = 88;

    // Arena bar
    const arena = this.currentArena();
    fillRoundRect(ctx, padX, colY, leftW, 56, 12, PALETTE.bgPanel);
    strokeRoundRect(ctx, padX, colY, leftW, 56, 12, PALETTE.border, 1.2);
    drawClippedText(ctx, `战场棋盘：${arena ? arena.name : this.selectedArena}`, padX + 18, colY + 20, 420, PALETTE.textMain, '700 16px "PingFang SC", sans-serif');
    drawClippedText(ctx, arena?.description || this.statusText, padX + 18, colY + 41, 520, PALETTE.textSub, '12px "PingFang SC", sans-serif');
    drawButton(stage, ctx, { x: padX + leftW - 140, y: colY + 10, w: 126, h: 36 }, '切换棋盘', () => this.cycleArena(), {
      fontSize: 14,
      disabled: (this.host.getCatalog()?.arenas.length || 0) <= 1,
    });

    // 2x2 Mode Grid
    const cardW = (leftW - 16) / 2;
    const cardH = 198;
    const cardTop = colY + 72;
    const modes: Array<{
      title: string;
      en: string;
      desc: string;
      badge: string;
      color: string;
      onTap: () => void;
    }> = [
      {
        title: 'PvE 星界试炼（12 关）',
        en: 'PVE 12 WAVES',
        desc: '单人迎战 12 波递增星序幻象阵容，每波可调试羁绊与站位，通关计入胜场。',
        badge: '单人闯关',
        color: PALETTE.cyan,
        onTap: () => void this.startMatch('pve12'),
      },
      {
        title: '4 人标准演习局',
        en: '4-PLAYER LOBBY',
        desc: '1 名人类指挥官 + 3 名不同流派 AI 同台竞技，快速检验经济运营与追三星策略。',
        badge: '快速对战',
        color: PALETTE.violet,
        onTap: () => void this.startMatch('lobby4'),
      },
      {
        title: '8 人排位混战',
        en: 'RANKED 8-PLAYER',
        desc: '冲刺青铜到王者段位，支持保段卡与局外星币结算，需登录账号参与。',
        badge: '段位积分',
        color: PALETTE.gold,
        onTap: () => void this.startMatch('ranked'),
      },
      {
        title: '好友联机房间',
        en: 'MULTIPLAYER ROOM',
        desc: '创建或输入 6 位房间码联机开黑，支持微信好友卡片直接邀战、AI 补位与观战。',
        badge: '多人联机',
        color: PALETTE.rose,
        onTap: () => {
          if (!this.host.getAccount()) {
            this.modal = 'auth';
            this.host.stage.showToast('多人联机需要先登录或微信一键登录');
            return;
          }
          this.host.openRooms();
        },
      },
    ];

    modes.forEach((m, idx) => {
      const col = idx % 2;
      const row = Math.floor(idx / 2);
      const x = padX + col * (cardW + 16);
      const y = cardTop + row * (cardH + 16);
      fillRoundRect(ctx, x, y, cardW, cardH, 14, PALETTE.bgPanel);
      strokeRoundRect(ctx, x, y, cardW, cardH, 14, m.color, 1.5);
      drawPill(ctx, x + 18, y + 18, 92, 24, `${m.color}22`, m.color, m.badge, m.color, 12);
      drawClippedText(ctx, m.en, x + cardW - 18, y + 30, 180, PALETTE.textMuted, '700 11px sans-serif', 'right', 'middle');
      drawClippedText(ctx, m.title, x + 18, y + 66, cardW - 36, PALETTE.textMain, '700 20px "PingFang SC", sans-serif');
      drawWrappedText(ctx, m.desc, x + 18, y + 88, cardW - 36, 22, PALETTE.textSub, '14px "PingFang SC", sans-serif', 3);
      drawClippedText(ctx, '点击进入 →', x + cardW - 18, y + cardH - 22, 120, m.color, '700 14px "PingFang SC", sans-serif', 'right', 'middle');
      stage.addHitRegion({ x, y, w: cardW, h: cardH, onTap: m.onTap });
    });

    // Right Column: Account Summary + Saved Matches
    const rightColX = padX + leftW + 20;
    const rightColW = rightX - rightColX;
    const panelY = colY;
    const panelH = 602;
    fillRoundRect(ctx, rightColX, panelY, rightColW, panelH, 14, PALETTE.bgPanel);
    strokeRoundRect(ctx, rightColX, panelY, rightColW, panelH, 14, PALETTE.border, 1.2);

    // Account card inside right column
    fillRoundRect(ctx, rightColX + 14, panelY + 14, rightColW - 28, 124, 10, PALETTE.bgCard);
    if (acc) {
      drawClippedText(ctx, acc.display_name, rightColX + 28, panelY + 38, rightColW - 130, PALETTE.textMain, '700 18px "PingFang SC", sans-serif');
      drawClippedText(ctx, `@${acc.username}`, rightColX + 28, panelY + 60, rightColW - 130, PALETTE.textMuted, '12px sans-serif');
      const st = acc.stats;
      drawClippedText(
        ctx,
        `对局 ${st.games} · 吃鸡 ${st.wins} · 前二 ${st.top2} · PvE通关 ${st.pve_clears}`,
        rightColX + 28,
        panelY + 88,
        rightColW - 56,
        PALETTE.textSub,
        '13px "PingFang SC", sans-serif',
      );
      if (acc.ranked) {
        const rk = acc.ranked.rank_info;
        drawClippedText(
          ctx,
          `排位 ${rk.full_label} (${acc.ranked.total_lp} LP) · 保段卡 ${acc.ranked.shield_cards}`,
          rightColX + 28,
          panelY + 114,
          rightColW - 56,
          tierColor(rk.tier_id),
          '700 13px "PingFang SC", sans-serif',
        );
      }
      drawButton(stage, ctx, { x: rightColX + rightColW - 104, y: panelY + 24, w: 78, h: 30 }, '账号', () => {
        this.modal = 'auth';
      }, { fontSize: 12 });
    } else {
      drawClippedText(ctx, `访客：${getSavedPlayerName()}`, rightColX + 28, panelY + 38, rightColW - 56, PALETTE.textMain, '700 17px "PingFang SC", sans-serif');
      drawWrappedText(ctx, '点击右侧「微信一键登录」即可保存排位段位、解锁好友联机房，也可绑定原有 Web 账号。', rightColX + 28, panelY + 56, rightColW - 56, 18, PALETTE.textSub, '12px "PingFang SC", sans-serif', 2);
      drawButton(stage, ctx, { x: rightColX + 28, y: panelY + 98, w: rightColW - 56, h: 30 }, '微信一键登录 / 绑定账号', () => {
        this.modal = 'auth';
      }, { fontSize: 13, bg: PALETTE.violetDark, border: '#a995ff' });
    }

    // Saved matches list
    const listHeaderY = panelY + 154;
    drawClippedText(ctx, `存档战局 (${this.matches.length})`, rightColX + 18, listHeaderY + 12, 220, PALETTE.textMain, '700 16px "PingFang SC", sans-serif');
    drawButton(stage, ctx, { x: rightColX + rightColW - 88, y: listHeaderY - 2, w: 72, h: 28 }, '刷新', () => {
      void this.refreshAll();
    }, { fontSize: 12, disabled: this.loading || this.busy });

    const listRect = {
      x: rightColX + 14,
      y: listHeaderY + 34,
      w: rightColW - 28,
      h: panelY + panelH - (listHeaderY + 48),
    };
    const itemH = 74;
    const itemGap = 10;
    const totalH = this.matches.length * (itemH + itemGap);
    stage.addScrollZone({
      ...listRect,
      key: 'lobby-matches',
      contentHeight: totalH,
      getOffset: () => this.matchScroll,
      onScroll: next => {
        this.matchScroll = next;
      },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(listRect.x, listRect.y, listRect.w, listRect.h);
    ctx.clip();

    if (this.loading) {
      drawClippedText(ctx, '正在加载存档…', listRect.x + listRect.w / 2, listRect.y + 60, listRect.w, PALETTE.textMuted, '14px "PingFang SC", sans-serif', 'center', 'middle');
    } else if (this.matches.length === 0) {
      drawWrappedText(ctx, '暂无未结束或已保存的单人战局。\n点击左侧模式卡即可开启新对局。', listRect.x + 12, listRect.y + 24, listRect.w - 24, 22, PALETTE.textMuted, '13px "PingFang SC", sans-serif', 3);
    } else {
      this.matches.forEach((m, idx) => {
        const iy = listRect.y + idx * (itemH + itemGap) - this.matchScroll;
        if (iy + itemH < listRect.y || iy > listRect.y + listRect.h) return;
        fillRoundRect(ctx, listRect.x, iy, listRect.w, itemH, 10, PALETTE.bgCard);
        strokeRoundRect(ctx, listRect.x, iy, listRect.w, itemH, 10, PALETTE.border, 1);
        const modeTitle = m.mode === 'ranked' ? '8人排位' : m.mode === 'pve12' ? 'PvE 12关' : '4人标准局';
        drawClippedText(ctx, `${modeTitle} · R${m.round_num}`, listRect.x + 14, iy + 24, listRect.w - 150, PALETTE.textMain, '700 15px "PingFang SC", sans-serif');
        drawClippedText(ctx, `阶段 ${m.phase} · HP ${m.hp}`, listRect.x + 14, iy + 50, listRect.w - 150, PALETTE.textSub, '12px "PingFang SC", sans-serif');
        drawButton(stage, ctx, { x: listRect.x + listRect.w - 134, y: iy + 19, w: 64, h: 34 }, '继续', () => {
          void this.runBusy(async () => {
            const full = await getAutoChessMatch(m.id);
            this.host.openMatch(full);
          });
        }, { fontSize: 13, bg: PALETTE.violetDark, border: PALETTE.violet, disabled: this.busy });

        if (m.mode !== 'ranked' || m.phase === 'finished') {
          drawButton(stage, ctx, { x: listRect.x + listRect.w - 64, y: iy + 19, w: 54, h: 34 }, '删', () => {
            void this.runBusy(async () => {
              if (await confirmAction('删除战局', '确定删除这条战局记录吗？')) {
                await deleteAutoChessMatch(m.id);
                this.matches = this.matches.filter(x => x.id !== m.id);
              }
            });
          }, { fontSize: 13, border: PALETTE.rose, color: PALETTE.rose, disabled: this.busy });
        }
      });
    }
    ctx.restore();

    if (this.modal === 'auth') {
      this.renderAuthModal();
    } else if (this.modal === 'leaderboard') {
      this.renderLeaderboardModal();
    }
    this.wikiModal.render(stage, this.host.getCatalog());
  }

  private renderAuthModal(): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const acc = this.host.getAccount();
    fillRoundRect(ctx, 0, 0, 1280, 720, 0, 'rgba(6, 8, 16, 0.78)');
    stage.addHitRegion({ x: 0, y: 0, w: 1280, h: 720, onTap: () => { this.modal = 'none'; } });

    const mw = 600;
    const mh = 430;
    const mx = (1280 - mw) / 2;
    const my = (720 - mh) / 2;
    fillRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.bgPanel);
    strokeRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.violet, 1.8);
    stage.addHitRegion({ x: mx, y: my, w: mw, h: mh, onTap: () => {} });

    drawClippedText(ctx, '星序账号与微信登录', mx + 26, my + 34, 420, PALETTE.textMain, '700 20px "PingFang SC", sans-serif');
    drawButton(stage, ctx, { x: mx + mw - 58, y: my + 16, w: 40, h: 34 }, '✕', () => { this.modal = 'none'; }, { fontSize: 16 });

    if (acc) {
      drawClippedText(ctx, `当前已登录：${acc.display_name} (@${acc.username})`, mx + 26, my + 82, mw - 52, PALETTE.emerald, '700 16px "PingFang SC", sans-serif');
      drawClippedText(ctx, acc.wx_bound ? '微信绑定状态：已绑定当前微信 OpenID' : '微信绑定状态：尚未绑定微信', mx + 26, my + 112, mw - 52, PALETTE.textSub, '14px "PingFang SC", sans-serif');

      if (!acc.wx_bound) {
        drawButton(stage, ctx, { x: mx + 26, y: my + 150, w: mw - 52, h: 48 }, '将当前账号与微信绑定', () => {
          void this.handlePasswordLogin(false, true);
        }, { bg: PALETTE.violetDark, border: '#b39eff', fontSize: 16, disabled: this.busy });
      }
      drawButton(stage, ctx, { x: mx + 26, y: my + 216, w: mw - 52, h: 46 }, '切换账号（密码登录）', () => {
        void this.handlePasswordLogin(false, false);
      }, { fontSize: 15, disabled: this.busy });
      drawButton(stage, ctx, { x: mx + 26, y: my + 280, w: mw - 52, h: 46 }, '退出当前账号', () => {
        void this.runBusy(async () => {
          await logoutAccount();
          this.host.setAccount(null);
          this.matches = await listAutoChessMatches().catch(() => []);
          this.host.stage.showToast('已退出登录');
        });
      }, { border: PALETTE.rose, color: PALETTE.rose, fontSize: 15, disabled: this.busy });
    } else {
      drawWrappedText(ctx, '使用微信一键登录可自动创建云端棋手档案并同步排位战绩；如果你已有 Web 端星序账号，点击「微信绑定已有账号」即可打通双端数据。', mx + 26, my + 74, mw - 52, 22, PALETTE.textSub, '14px "PingFang SC", sans-serif', 3);

      drawButton(stage, ctx, { x: mx + 26, y: my + 154, w: mw - 52, h: 52 }, '微信一键登录 / 自动建号', () => {
        void this.handleWeChatLogin();
      }, { bg: '#1a6b4e', border: PALETTE.emerald, fontSize: 17, disabled: this.busy });

      drawButton(stage, ctx, { x: mx + 26, y: my + 222, w: mw - 52, h: 48 }, '微信绑定已有 Web 端账号', () => {
        void this.handlePasswordLogin(false, true);
      }, { bg: PALETTE.violetDark, border: '#b39eff', fontSize: 16, disabled: this.busy });

      drawButton(stage, ctx, { x: mx + 26, y: my + 288, w: (mw - 68) / 2, h: 44 }, '用户名密码登录', () => {
        void this.handlePasswordLogin(false, false);
      }, { fontSize: 15, disabled: this.busy });

      drawButton(stage, ctx, { x: mx + 42 + (mw - 68) / 2, y: my + 288, w: (mw - 68) / 2, h: 44 }, '注册新账号', () => {
        void this.handlePasswordLogin(true, false);
      }, { fontSize: 15, disabled: this.busy });

      drawButton(stage, ctx, { x: mx + 26, y: my + 350, w: mw - 52, h: 40 }, `修改访客昵称（当前：${getSavedPlayerName()}）`, () => {
        void (async () => {
          const next = await promptInput('修改访客称呼', '最多 20 字', getSavedPlayerName());
          if (next) {
            setSavedPlayerName(next);
            await ensureSession(next).catch(() => {});
            this.host.stage.showToast(`访客称呼已改为 ${next}`);
          }
        })();
      }, { fontSize: 13 });
    }
  }

  private renderLeaderboardModal(): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    fillRoundRect(ctx, 0, 0, 1280, 720, 0, 'rgba(6, 8, 16, 0.78)');
    stage.addHitRegion({ x: 0, y: 0, w: 1280, h: 720, onTap: () => { this.modal = 'none'; } });

    const mw = 960;
    const mh = 580;
    const mx = (1280 - mw) / 2;
    const my = (720 - mh) / 2;
    fillRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.bgPanel);
    strokeRoundRect(ctx, mx, my, mw, mh, 16, PALETTE.goldSoft, 1.8);
    stage.addHitRegion({ x: mx, y: my, w: mw, h: mh, onTap: () => {} });

    drawClippedText(ctx, '全服 8 人排位段位排行榜', mx + 24, my + 32, 420, PALETTE.gold, '700 20px "PingFang SC", sans-serif');
    drawButton(stage, ctx, { x: mx + mw - 56, y: my + 14, w: 40, h: 34 }, '✕', () => { this.modal = 'none'; }, { fontSize: 16 });

    const tiers = [
      ['all', '全部'],
      ['king', '王者'],
      ['diamond', '钻石'],
      ['platinum', '铂金'],
      ['gold', '黄金'],
      ['silver', '白银'],
      ['bronze', '青铜'],
    ];
    tiers.forEach(([id, label], i) => {
      const tx = mx + 24 + i * 94;
      const active = this.lbTier === id;
      drawButton(stage, ctx, { x: tx, y: my + 64, w: 86, h: 32 }, label, () => {
        void this.loadLeaderboard(id);
      }, {
        fontSize: 13,
        bg: active ? PALETTE.violetDark : PALETTE.bgCard,
        border: active ? PALETTE.gold : PALETTE.border,
      });
    });

    const entries = this.leaderboard?.entries || [];
    const listRect = { x: mx + 24, y: my + 110, w: mw - 48, h: mh - 134 };
    const rowH = 46;
    stage.addScrollZone({
      ...listRect,
      key: 'lb-scroll',
      contentHeight: entries.length * (rowH + 8),
      getOffset: () => this.lbScroll,
      onScroll: v => { this.lbScroll = v; },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(listRect.x, listRect.y, listRect.w, listRect.h);
    ctx.clip();
    if (entries.length === 0) {
      drawClippedText(ctx, '暂无排位记录，快去开启首局 8 人排位吧！', listRect.x + listRect.w / 2, listRect.y + 80, listRect.w, PALETTE.textMuted, '15px "PingFang SC", sans-serif', 'center', 'middle');
    } else {
      entries.forEach((e, i) => {
        const y = listRect.y + i * (rowH + 8) - this.lbScroll;
        if (y + rowH < listRect.y || y > listRect.y + listRect.h) return;
        fillRoundRect(ctx, listRect.x, y, listRect.w, rowH, 8, PALETTE.bgCard);
        drawClippedText(ctx, `#${e.rank}`, listRect.x + 18, y + 23, 52, i < 3 ? PALETTE.gold : PALETTE.textSub, '700 15px sans-serif');
        drawClippedText(ctx, e.display_name, listRect.x + 76, y + 23, 210, PALETTE.textMain, '700 15px "PingFang SC", sans-serif');
        drawClippedText(ctx, e.rank_info.full_label, listRect.x + 310, y + 23, 160, tierColor(e.rank_info.tier_id), '700 14px "PingFang SC", sans-serif');
        drawClippedText(ctx, `${e.total_lp} LP`, listRect.x + 490, y + 23, 110, PALETTE.textMain, '600 14px sans-serif');
        drawClippedText(ctx, `胜率 ${Math.round(e.win_rate * 100)}% (${e.wins}/${e.games})`, listRect.x + 620, y + 23, 200, PALETTE.textSub, '13px "PingFang SC", sans-serif');
      });
    }
    ctx.restore();
  }
}
