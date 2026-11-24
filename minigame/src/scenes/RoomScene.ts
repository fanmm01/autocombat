import {
  controlRoom,
  createRoom,
  getRoom,
  joinRoom,
  listRooms,
  pollRoom,
  type AutoChessCatalog,
  type AutoChessMatchState,
  type AutoChessRoomState,
  type AutoChessRoomSummary,
} from '../net/autochessApi';
import { LongPoller } from '../net/poller';
import {
  PALETTE,
  Stage,
  drawButton,
  drawClippedText,
  drawPill,
  drawWrappedText,
  fillRoundRect,
  promptInput,
  strokeRoundRect,
} from '../engine/ui';

export interface RoomHost {
  stage: Stage;
  getCatalog(): AutoChessCatalog | null;
  backToLobby(): void;
  enterRoomMatch(room: AutoChessRoomState): void;
  setShareRoomCode(code: string | null): void;
}

export class RoomScene {
  private readonly host: RoomHost;
  private rooms: AutoChessRoomSummary[] = [];
  private activeRoom: AutoChessRoomState | null = null;
  private version = -1;
  private poller: LongPoller | null = null;
  private busy = false;
  private listScroll = 0;

  constructor(host: RoomHost) {
    this.host = host;
  }

  onEnter(initialCode?: string): void {
    this.activeRoom = null;
    this.version = -1;
    this.host.setShareRoomCode(null);
    if (initialCode) {
      void this.handleJoinCode(initialCode);
    } else {
      void this.refreshList();
    }
  }

  onLeave(): void {
    this.stopPoller();
    this.host.setShareRoomCode(null);
  }

  setForeground(active: boolean): void {
    this.poller?.setForeground(active);
  }

  private stopPoller(): void {
    if (this.poller) {
      this.poller.stop();
      this.poller = null;
    }
  }

  private startPoller(code: string): void {
    this.stopPoller();
    this.poller = new LongPoller(async () => {
      const res = await pollRoom(code, this.version, 8);
      this.version = res.version;
      if (res.changed && res.room) {
        this.applyRoom(res.room);
        if (res.room.status === 'playing' && res.room.match) {
          return 'stop';
        }
        return 'changed';
      }
      return 'timeout';
    });
    this.poller.start();
  }

  private applyRoom(room: AutoChessRoomState): void {
    this.activeRoom = room;
    this.host.setShareRoomCode(room.code);
    if (room.status === 'playing' && room.match) {
      this.stopPoller();
      this.host.enterRoomMatch(room);
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

  async refreshList(): Promise<void> {
    await this.runBusy(async () => {
      this.rooms = await listRooms();
    });
  }

  async handleCreateRoom(): Promise<void> {
    const arenas = this.host.getCatalog()?.arenas || [];
    const arenaId = arenas[0]?.id || 'autochess_standard';
    await this.runBusy(async () => {
      const room = await createRoom({
        arena_preset: arenaId,
        max_players: 4,
        fill_bots: true,
        prep_duration: 30,
      });
      this.version = -1;
      this.applyRoom(room);
      this.startPoller(room.code);
    });
  }

  async handleJoinCode(codeInput?: string): Promise<void> {
    const code = codeInput || (await promptInput('加入联机房间', '输入 6 位房间码'));
    if (!code) return;
    await this.runBusy(async () => {
      const room = await joinRoom(code);
      this.version = -1;
      this.applyRoom(room);
      if (room.status === 'waiting') {
        this.startPoller(room.code);
      }
    });
  }

  private async handleControl(op: 'ready' | 'config' | 'leave' | 'start', payload: Record<string, unknown> = {}): Promise<void> {
    if (!this.activeRoom) return;
    const code = this.activeRoom.code;
    await this.runBusy(async () => {
      const res = await controlRoom(code, op, payload);
      if (op === 'leave' || res.disbanded) {
        this.stopPoller();
        this.activeRoom = null;
        this.host.setShareRoomCode(null);
        this.rooms = await listRooms();
        return;
      }
      if (res.room) {
        this.applyRoom(res.room);
      }
    });
  }

  render(): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const padX = Math.max(24, stage.safeLeft);
    const rightX = 1280 - Math.max(24, stage.safeRight);

    ctx.fillStyle = PALETTE.bgDeep;
    ctx.fillRect(0, 0, 1280, 720);

    // Header
    fillRoundRect(ctx, 0, 0, 1280, 68, 0, PALETTE.bgPanel);
    ctx.fillStyle = PALETTE.border;
    ctx.fillRect(0, 67, 1280, 1);

    drawButton(stage, ctx, { x: padX, y: 15, w: 112, h: 38 }, '← 返回大厅', () => {
      if (this.activeRoom && this.activeRoom.status === 'waiting') {
        void this.handleControl('leave');
      } else {
        this.host.backToLobby();
      }
    }, { fontSize: 14 });

    drawClippedText(
      ctx,
      this.activeRoom ? `联机候战室 · ${this.activeRoom.name}` : '好友联机房间大厅',
      padX + 132,
      34,
      540,
      PALETTE.textMain,
      '700 20px "PingFang SC", sans-serif',
    );

    if (!this.activeRoom) {
      drawButton(stage, ctx, { x: rightX - 280, y: 15, w: 132, h: 38 }, '房间码加入', () => {
        void this.handleJoinCode();
      }, { fontSize: 14 });
      drawButton(stage, ctx, { x: rightX - 134, y: 15, w: 134, h: 38 }, '+ 创建房间', () => {
        void this.handleCreateRoom();
      }, { fontSize: 14, bg: PALETTE.violetDark, border: '#b39eff' });

      this.renderRoomList(padX, 92, rightX - padX, 598);
    } else {
      this.renderWaitingRoom(padX, 92, rightX - padX, 598, this.activeRoom);
    }
  }

  private renderRoomList(x: number, y: number, w: number, h: number): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;

    fillRoundRect(ctx, x, y, w, h, 14, PALETTE.bgPanel);
    strokeRoundRect(ctx, x, y, w, h, 14, PALETTE.border, 1.2);
    drawClippedText(ctx, `开放与已加入房间 (${this.rooms.length})`, x + 22, y + 28, 360, PALETTE.textMain, '700 17px "PingFang SC", sans-serif');
    drawButton(stage, ctx, { x: x + w - 104, y: y + 12, w: 84, h: 32 }, '刷新', () => {
      void this.refreshList();
    }, { fontSize: 13 });

    const listRect = { x: x + 18, y: y + 58, w: w - 36, h: h - 76 };
    const rowH = 74;
    stage.addScrollZone({
      ...listRect,
      key: 'rooms-scroll',
      contentHeight: this.rooms.length * (rowH + 10),
      getOffset: () => this.listScroll,
      onScroll: v => { this.listScroll = v; },
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(listRect.x, listRect.y, listRect.w, listRect.h);
    ctx.clip();

    if (this.rooms.length === 0) {
      drawClippedText(ctx, '当前没有等待中的联机房间，点击右上角「+ 创建房间」即可开房邀请好友！', listRect.x + listRect.w / 2, listRect.y + 120, listRect.w - 40, PALETTE.textMuted, '16px "PingFang SC", sans-serif', 'center', 'middle');
    } else {
      this.rooms.forEach((rm, idx) => {
        const ry = listRect.y + idx * (rowH + 10) - this.listScroll;
        if (ry + rowH < listRect.y || ry > listRect.y + listRect.h) return;
        fillRoundRect(ctx, listRect.x, ry, listRect.w, rowH, 10, PALETTE.bgCard);
        strokeRoundRect(ctx, listRect.x, ry, listRect.w, rowH, 10, PALETTE.border, 1);

        drawPill(ctx, listRect.x + 16, ry + 22, 86, 30, 'rgba(156,134,236,0.18)', PALETTE.violet, rm.code, PALETTE.violet, 14);
        drawClippedText(ctx, rm.name, listRect.x + 118, ry + 26, 360, PALETTE.textMain, '700 16px "PingFang SC", sans-serif');
        drawClippedText(
          ctx,
          `房主 ${rm.host_name || '未知'} · ${rm.member_count}/${rm.max_players} 人 · 备战 ${rm.prep_duration}s · ${rm.fill_bots ? 'AI补位' : '纯玩家'}`,
          listRect.x + 118,
          ry + 50,
          540,
          PALETTE.textSub,
          '13px "PingFang SC", sans-serif',
        );

        drawButton(stage, ctx, { x: listRect.x + listRect.w - 134, y: ry + 18, w: 116, h: 38 }, rm.is_member ? '进入房间' : '加入房间', () => {
          void this.handleJoinCode(rm.code);
        }, { fontSize: 14, bg: PALETTE.violetDark, border: '#b39eff' });
      });
    }
    ctx.restore();
  }

  private renderWaitingRoom(x: number, y: number, w: number, h: number, room: AutoChessRoomState): void {
    const stage = this.host.stage;
    const ctx = stage.ctx;
    const leftW = Math.round(w * 0.62);
    const rightX = x + leftW + 18;
    const rightW = w - leftW - 18;

    // Left: Members
    fillRoundRect(ctx, x, y, leftW, h, 14, PALETTE.bgPanel);
    strokeRoundRect(ctx, x, y, leftW, h, 14, PALETTE.border, 1.2);
    drawClippedText(ctx, `房间成员 (${room.members.length}/${room.max_players})`, x + 22, y + 28, 320, PALETTE.textMain, '700 18px "PingFang SC", sans-serif');
    drawPill(ctx, x + leftW - 140, y + 14, 120, 30, 'rgba(244,200,106,0.14)', PALETTE.gold, `房间码 ${room.code}`, PALETTE.gold, 14);

    room.members.forEach((m, idx) => {
      const my = y + 66 + idx * 78;
      fillRoundRect(ctx, x + 20, my, leftW - 40, 64, 10, PALETTE.bgCard);
      strokeRoundRect(ctx, x + 20, my, leftW - 40, 64, 10, m.ready ? PALETTE.emerald : PALETTE.border, 1.2);
      drawClippedText(
        ctx,
        `${m.display_name}${m.is_host ? ' [房主]' : ''}`,
        x + 38,
        my + 24,
        360,
        PALETTE.textMain,
        '700 16px "PingFang SC", sans-serif',
      );
      drawClippedText(ctx, `@${m.username}`, x + 38, my + 46, 300, PALETTE.textMuted, '12px sans-serif');
      drawPill(
        ctx,
        x + leftW - 134,
        my + 18,
        96,
        28,
        m.ready ? 'rgba(72,214,141,0.18)' : 'rgba(115,126,166,0.18)',
        m.ready ? PALETTE.emerald : PALETTE.textMuted,
        m.is_host ? '房主就绪' : m.ready ? '已准备' : '未准备',
        m.ready ? PALETTE.emerald : PALETTE.textSub,
        13,
      );
    });

    // Right: Room Config & Controls
    fillRoundRect(ctx, rightX, y, rightW, h, 14, PALETTE.bgPanel);
    strokeRoundRect(ctx, rightX, y, rightW, h, 14, PALETTE.border, 1.2);
    drawClippedText(ctx, '房间规则与邀战', rightX + 22, y + 28, rightW - 44, PALETTE.textMain, '700 18px "PingFang SC", sans-serif');

    const arenas = this.host.getCatalog()?.arenas || [];
    const arenaName = arenas.find(a => a.id === room.arena_preset)?.name || room.arena_preset;
    drawWrappedText(
      ctx,
      `棋盘：${arenaName}\n人数上限：${room.max_players} 人\nAI 补位：${room.fill_bots ? '开启（自动补足 4 人）' : '关闭'}\n备战时长：${room.prep_duration} 秒`,
      rightX + 22,
      y + 62,
      rightW - 44,
      26,
      PALETTE.textSub,
      '14px "PingFang SC", sans-serif',
      5,
    );

    if (room.is_host) {
      drawButton(stage, ctx, { x: rightX + 22, y: y + 190, w: (rightW - 54) / 2, h: 38 }, room.fill_bots ? 'AI 补位：开' : 'AI 补位：关', () => {
        void this.handleControl('config', { fill_bots: !room.fill_bots });
      }, { fontSize: 13 });

      drawButton(stage, ctx, { x: rightX + 32 + (rightW - 54) / 2, y: y + 190, w: (rightW - 54) / 2, h: 38 }, `备战 ${room.prep_duration}s`, () => {
        const nextDur = room.prep_duration >= 60 ? 20 : room.prep_duration + 15;
        void this.handleControl('config', { prep_duration: nextDur });
      }, { fontSize: 13 });

      drawButton(stage, ctx, { x: rightX + 22, y: y + 242, w: rightW - 44, h: 38 }, '切换棋盘预设', () => {
        if (arenas.length > 1) {
          const idx = arenas.findIndex(a => a.id === room.arena_preset);
          const next = arenas[(idx + 1) % arenas.length].id;
          void this.handleControl('config', { arena_preset: next });
        }
      }, { fontSize: 13 });
    }

    drawButton(stage, ctx, { x: rightX + 22, y: y + h - 184, w: rightW - 44, h: 44 }, '分享给微信好友 (直达本房)', () => {
      if (wx.shareAppMessage) {
        wx.shareAppMessage({
          title: `来星序自走棋开黑！房间码 ${room.code}`,
          query: `room=${room.code}`,
        });
      } else {
        this.host.stage.showToast(`请点击右上角「···」转发，房间码：${room.code}`);
      }
    }, { bg: '#1b5e47', border: PALETTE.emerald, fontSize: 14 });

    if (room.is_host) {
      drawButton(stage, ctx, { x: rightX + 22, y: y + h - 126, w: rightW - 44, h: 48 }, '开始多人对局', () => {
        void this.handleControl('start');
      }, { bg: PALETTE.violetDark, border: PALETTE.gold, fontSize: 16 });
    } else {
      const me = room.members.find(m => m.account_id === room.my_account_id);
      const isReady = Boolean(me?.ready);
      drawButton(stage, ctx, { x: rightX + 22, y: y + h - 126, w: rightW - 44, h: 48 }, isReady ? '取消准备' : '准备就绪', () => {
        void this.handleControl('ready', { ready: !isReady });
      }, {
        bg: isReady ? '#2d375c' : '#1b5e47',
        border: isReady ? PALETTE.borderBright : PALETTE.emerald,
        fontSize: 16,
      });
    }

    drawButton(stage, ctx, { x: rightX + 22, y: y + h - 66, w: rightW - 44, h: 40 }, '离开房间', () => {
      void this.handleControl('leave');
    }, { border: PALETTE.rose, color: PALETTE.rose, fontSize: 14 });

    void getRoom;
    void (null as AutoChessMatchState | null);
  }
}
