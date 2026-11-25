import { Stage } from './engine/ui';
import {
  fetchAutoChessCatalog,
  joinRoom,
  type AutoChessAccount,
  type AutoChessCatalog,
  type AutoChessMatchState,
  type AutoChessRuleset,
  type AutoChessRoomState,
} from './net/autochessApi';
import { ensureCloudInitialized } from './net/transport';
import { LobbyScene } from './scenes/LobbyScene';
import { MatchScene } from './scenes/MatchScene';
import { RoomScene } from './scenes/RoomScene';

type ActiveSceneName = 'lobby' | 'rooms' | 'match';

class MiniGameApp {
  readonly stage: Stage;
  private account: AutoChessAccount | null = null;
  private readonly catalogs = new Map<AutoChessRuleset, AutoChessCatalog>();
  private activeName: ActiveSceneName = 'lobby';
  private shareRoomCode: string | null = null;

  private readonly lobby: LobbyScene;
  private readonly rooms: RoomScene;
  private readonly match: MatchScene;

  constructor() {
    ensureCloudInitialized();
    this.stage = new Stage();

    this.lobby = new LobbyScene({
      stage: this.stage,
      getAccount: () => this.account,
      setAccount: acc => {
        this.account = acc;
      },
      getCatalog: (ruleset = 'standard') => this.catalogs.get(ruleset) ?? null,
      setCatalog: cat => {
        this.catalogs.set(cat.ruleset ?? 'standard', cat);
      },
      openMatch: match => this.switchToMatch(match),
      openRooms: () => this.switchToRooms(),
    });

    this.rooms = new RoomScene({
      stage: this.stage,
      getCatalog: () => this.catalogs.get('standard') ?? null,
      backToLobby: () => this.switchToLobby(),
      enterRoomMatch: room => {
        if (room.match) {
          this.switchToMatch(room.match, room);
        }
      },
      setShareRoomCode: code => {
        this.shareRoomCode = code;
      },
    });

    this.match = new MatchScene({
      stage: this.stage,
      getAccount: () => this.account,
      setAccount: acc => {
        this.account = acc;
      },
      getCatalog: (ruleset = 'standard') => this.catalogs.get(ruleset) ?? null,
      backToLobby: () => this.switchToLobby(),
    });

    this.setupLifecycle();
    this.setupShare();
    this.lobby.onEnter();

    const launch = wx.getLaunchOptionsSync();
    if (launch.query?.room) {
      void this.tryJoinInviteRoom(launch.query.room);
    }

    this.startLoop();
  }

  private switchToLobby(): void {
    this.leaveCurrent();
    this.activeName = 'lobby';
    this.lobby.onEnter();
  }

  private switchToRooms(initialCode?: string): void {
    this.leaveCurrent();
    this.activeName = 'rooms';
    this.rooms.onEnter(initialCode);
  }

  private switchToMatch(match: AutoChessMatchState, room?: AutoChessRoomState): void {
    this.leaveCurrent();
    this.activeName = 'match';
    this.match.onEnter(match, room);
    const ruleset = match.ruleset ?? 'standard';
    if (!this.catalogs.has(ruleset)) {
      void fetchAutoChessCatalog(ruleset).then(catalog => {
        this.catalogs.set(ruleset, catalog);
      }).catch(err => {
        if (this.activeName === 'match') this.stage.showToast(err instanceof Error ? err.message : String(err));
      });
    }
  }

  private leaveCurrent(): void {
    if (this.activeName === 'lobby') this.lobby.onLeave();
    else if (this.activeName === 'rooms') this.rooms.onLeave();
    else if (this.activeName === 'match') this.match.onLeave();
  }

  private async tryJoinInviteRoom(code: string): Promise<void> {
    try {
      await this.lobby.refreshAll();
      if (!this.account) {
        this.stage.showToast(`收到房间邀请 ${code}，请先登录账号`);
        return;
      }
      const room = await joinRoom(code);
      if (room.status === 'playing' && room.match) {
        this.switchToMatch(room.match, room);
      } else {
        this.switchToRooms(code);
      }
    } catch (err) {
      this.stage.showToast(err instanceof Error ? err.message : `加入房间 ${code} 失败`);
    }
  }

  private setupLifecycle(): void {
    wx.onWindowResize?.(() => this.stage.resize());
    wx.onShow(res => {
      this.stage.resize();
      if (this.activeName === 'rooms') this.rooms.setForeground(true);
      if (this.activeName === 'match') this.match.setForeground(true);
      if (res?.query?.room) {
        void this.tryJoinInviteRoom(res.query.room);
      }
    });
    wx.onHide(() => {
      if (this.activeName === 'rooms') this.rooms.setForeground(false);
      if (this.activeName === 'match') this.match.setForeground(false);
    });
  }

  private setupShare(): void {
    wx.showShareMenu?.({
      withShareTicket: true,
      menus: ['shareAppMessage', 'shareTimeline'],
    });
    wx.onShareAppMessage?.(() => {
      if (this.shareRoomCode) {
        return {
          title: `来星序自走棋开黑！房间码 ${this.shareRoomCode}`,
          query: `room=${this.shareRoomCode}`,
        };
      }
      return {
        title: '星序自走棋 — 魔法少女战术对决',
        query: '',
      };
    });
  }

  private startLoop(): void {
    const tick = () => {
      this.stage.beginFrame();
      if (this.activeName === 'lobby') this.lobby.render();
      else if (this.activeName === 'rooms') this.rooms.render();
      else if (this.activeName === 'match') this.match.render();
      this.stage.endFrame();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}

new MiniGameApp();
