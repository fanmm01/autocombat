import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  Award,
  BookOpen,
  Check,
  CircleHelp,
  Coins,
  Compass,
  Copy,
  Crown,
  Eye,
  FastForward,
  Heart,
  Image as ImageIcon,
  Lock,
  Pause,
  Play,
  RefreshCw,
  Shield,
  Sparkles,
  Swords,
  Trash2,
  Trophy,
  Unlock,
  Users,
  Wand2,
  X,
} from 'lucide-react';
import {
  controlRoom,
  createAutoChessMatch,
  createRankedMatch,
  createRoom,
  deleteAutoChessMatch,
  fetchAutoChessCatalog,
  getAutoChessMatch,
  getRoom,
  joinRoom,
  listAutoChessMatches,
  listRooms,
  roomEventsUrl,
  sendAutoChessAction,
  sendRoomAction,
} from './api';
import { AutoChessRankedSummaryModal } from './AutoChessRankedSummaryModal';
import { AutoChessVfxLayer } from './AutoChessVfxLayer';
import { AutoChessWikiModal } from './AutoChessWikiModal';
import { AutoChessWikiPopover } from './AutoChessWikiPopover';
import './autochess.css';
import {
  AUTOCHESS_ROLE_LABELS,
  type AutoChessAccount,
  type AutoChessCatalog,
  type AutoChessCombatUnit,
  type AutoChessMatchState,
  type AutoChessMatchSummary,
  type AutoChessOwnedUnit,
  type AutoChessRankedSettlement,
  type AutoChessRoomState,
  type AutoChessRoomSummary,
  type AutoChessUnitMeta,
  type AutoChessWikiTarget,
} from './types';
import { useHoverWiki } from './useHoverWiki';

const ROLE_LABELS = AUTOCHESS_ROLE_LABELS;

const STANCE_LABELS: Record<string, string> = {
  balanced: '均衡',
  aggressive: '激进',
  defensive: '稳健',
};

function parseCoordStr(coord: string): [number, number] | null {
  const m = /^([A-Z])(\d+)$/i.exec(coord.trim());
  if (!m) return null;
  return [m[1].toUpperCase().charCodeAt(0) - 65, Number(m[2]) - 1];
}

function formatCoord(col: number, row: number): string {
  return String.fromCharCode(65 + col) + String(row + 1);
}

function sellValue(cost: number, star: number): number {
  if (star <= 1) return cost;
  return Math.max(cost, Math.round(cost * 3 ** (star - 1) * 0.7));
}

interface AutoChessPageProps {
  playerName: string;
  account: AutoChessAccount | null;
  guestTokens: Record<string, string>;
  onAccountUpdate?: (acc: AutoChessAccount | null) => void;
  onCatalogLoaded?: (cat: AutoChessCatalog) => void;
  onOpenAuth?: (mode?: 'login' | 'register', prompt?: string) => void;
  onOpenTokenEditor?: (serial?: string) => void;
  onOpenLeaderboard?: () => void;
  onPlayerNameChange?: (name: string) => Promise<void> | void;
  wikiOpenNonce?: number;
  onError: (msg: string) => void;
}

export function AutoChessPage({
  playerName,
  account,
  guestTokens,
  onAccountUpdate,
  onCatalogLoaded,
  onOpenAuth,
  onOpenTokenEditor,
  onOpenLeaderboard,
  onPlayerNameChange,
  wikiOpenNonce = 0,
  onError,
}: AutoChessPageProps) {
  const [catalog, setCatalog] = useState<AutoChessCatalog | null>(null);
  const [matches, setMatches] = useState<AutoChessMatchSummary[]>([]);
  const [match, setMatch] = useState<AutoChessMatchState | null>(null);
  const [mode, setMode] = useState<'lobby4' | 'pve12'>('lobby4');
  const [arenaPreset, setArenaPreset] = useState<string>('autochess_standard');
  const [rankedArena, setRankedArena] = useState<string>('autochess_standard');
  const [rankedSettlement, setRankedSettlement] = useState<AutoChessRankedSettlement | null>(null);
  const [confirmSurrender, setConfirmSurrender] = useState(false);
  const [leftRailTab, setLeftRailTab] = useState<'synergies' | 'standings' | 'logs'>('synergies');
  const [lobbyMobileTab, setLobbyMobileTab] = useState<'ranked' | 'pve' | 'pvp'>('ranked');
  const [showTelemetryMobile, setShowTelemetryMobile] = useState(false);

  // Multiplayer room state
  const [room, setRoom] = useState<AutoChessRoomState | null>(null);
  const [rooms, setRooms] = useState<AutoChessRoomSummary[]>([]);
  const [roomName, setRoomName] = useState('');
  const [roomArena, setRoomArena] = useState<string>('autochess_standard');
  const [roomMaxPlayers, setRoomMaxPlayers] = useState<2 | 3 | 4>(4);
  const [roomFillBots, setRoomFillBots] = useState(true);
  const [roomPrepSec, setRoomPrepSec] = useState(30);
  const [joinCode, setJoinCode] = useState(() => {
    try {
      const code = new URLSearchParams(window.location.search).get('room') || '';
      return code.trim().toUpperCase().slice(0, 8);
    } catch {
      return '';
    }
  });
  const [pendingRoomCode] = useState<string | null>(() => {
    try {
      const code = new URLSearchParams(window.location.search).get('room') || '';
      return code.trim().toUpperCase().slice(0, 8) || null;
    } catch {
      return null;
    }
  });
  const autoJoinedRef = useRef(false);
  const [spectateCid, setSpectateCid] = useState<string | null>(null);
  const [copiedUrl, setCopiedUrl] = useState('');

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [autoPlay, setAutoPlay] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [now, setNow] = useState(Date.now);
  const [wikiTarget, setWikiTarget] = useState<AutoChessWikiTarget | null>(null);
  const [nameDraft, setNameDraft] = useState(playerName);
  const [frameSeq, setFrameSeq] = useState(1);
  const [starUpIds, setStarUpIds] = useState<Record<string, boolean>>({});
  const prevStarsRef = useRef<Record<string, number>>({});
  const lastFrameSigRef = useRef('');

  const hoverWiki = useHoverWiki();
  const inFlight = useRef(false);
  const resolveAfterStep = useRef(false);

  const activeMatch = room?.match ?? match;
  const isPvpRoom = Boolean(room);

  const catalogBySerial = useMemo(() => {
    const map: Record<string, AutoChessUnitMeta> = {};
    for (const u of catalog?.units || []) {
      map[u.serial] = u;
    }
    return map;
  }, [catalog]);

  useEffect(() => {
    setNameDraft(playerName);
  }, [playerName]);

  useEffect(() => {
    hoverWiki.closeNow();
  }, [activeMatch?.id, activeMatch?.phase, activeMatch?.round_num, hoverWiki.closeNow]);

  const prepDeadline = useMemo(() => {
    if (activeMatch?.phase !== 'prep') return null;
    const deadline = activeMatch.prep_deadline;
    return typeof deadline === 'number' && Number.isFinite(deadline) && deadline > 0
      ? deadline * 1000
      : Date.now() + 30_000;
  }, [activeMatch?.id, activeMatch?.round_num, activeMatch?.phase, activeMatch?.prep_deadline]);

  const remaining = prepDeadline === null ? 0 : Math.max(0, Math.ceil((prepDeadline - now) / 1000));

  const refreshLobby = useCallback(async () => {
    try {
      const catPromise = catalog ? Promise.resolve(catalog) : fetchAutoChessCatalog();
      const matchPromise = listAutoChessMatches(playerName);
      const roomsPromise = account ? listRooms().catch(() => [] as AutoChessRoomSummary[]) : Promise.resolve([] as AutoChessRoomSummary[]);
      const [cat, list, roomListRes] = await Promise.all([catPromise, matchPromise, roomsPromise]);
      setCatalog(cat);
      onCatalogLoaded?.(cat);
      setMatches(list);
      setRooms(roomListRes);
    } catch (e) {
      onError((e as Error).message);
    }
  }, [account, catalog, onCatalogLoaded, onError, playerName]);

  useEffect(() => {
    void refreshLobby();
  }, [account?.id]);

  // If URL had ?room=CODE and user is authenticated, auto-join once cleanly
  useEffect(() => {
    if (!account || !pendingRoomCode || room || autoJoinedRef.current) return;
    autoJoinedRef.current = true;
    void handleJoinRoom(pendingRoomCode);
  }, [account, pendingRoomCode]);

  // Clear multiplayer room if logged out
  useEffect(() => {
    if (!account) {
      setRoom(null);
      setRooms([]);
      setSpectateCid(null);
    }
  }, [account]);

  // Countdown tick during prep
  useEffect(() => {
    if (activeMatch?.phase !== 'prep') return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [activeMatch?.id, activeMatch?.round_num, activeMatch?.phase]);

  // SSE subscription for active multiplayer room (waiting / playing)
  useEffect(() => {
    if (!account || !room?.code) return;
    const url = roomEventsUrl(room.code, spectateCid);
    const es = new EventSource(url);
    es.addEventListener('room', ev => {
      try {
        const nextRoom = JSON.parse((ev as MessageEvent<string>).data) as AutoChessRoomState;
        setRoom(prev => {
          if (prev?.status === 'waiting' && nextRoom.status === 'playing') {
            setNotice('多人联机对局已开启！');
          }
          return nextRoom;
        });
      } catch {
        // ignore malformed event payload
      }
    });
    return () => {
      es.close();
    };
  }, [account?.id, room?.code, spectateCid]);

  // Track frame progression & star-up bursts
  useEffect(() => {
    if (!activeMatch) return;
    const frames = activeMatch.combat_frames || [];
    const last = frames[frames.length - 1];
    const sig = last
      ? `${activeMatch.id}-${activeMatch.round_num}-${frames.length}-${last.actor_uid || ''}-${last.cmd}`
      : `${activeMatch.id}-${activeMatch.round_num}-none`;
    if (sig !== lastFrameSigRef.current) {
      lastFrameSigRef.current = sig;
      setFrameSeq(s => s + 1);
    }

    // Star-up highlight in prep
    const allUnits = [...activeMatch.player.board, ...activeMatch.player.bench];
    const upgraded: string[] = [];
    const nextStars: Record<string, number> = {};
    for (const u of allUnits) {
      nextStars[u.id] = u.star;
      const old = prevStarsRef.current[u.id];
      if (old !== undefined && u.star > old) {
        upgraded.push(u.id);
      }
    }
    prevStarsRef.current = nextStars;
    if (upgraded.length > 0) {
      setStarUpIds(prev => {
        const copy = { ...prev };
        for (const id of upgraded) copy[id] = true;
        return copy;
      });
      const timer = window.setTimeout(() => {
        setStarUpIds(prev => {
          const copy = { ...prev };
          for (const id of upgraded) delete copy[id];
          return copy;
        });
      }, 950);
      return () => window.clearTimeout(timer);
    }
  }, [activeMatch]);

  // Single-player client auto-stepper (PvP room combat is paced by backend stepper over SSE)
  useEffect(() => {
    if (!activeMatch || busy || isPvpRoom) return;
    let action: string;
    let delay: number;
    let payload: Record<string, unknown> = {};
    if (activeMatch.phase === 'prep' && remaining === 0) {
      const firstAugment = activeMatch.player.pending_augments[0];
      action = firstAugment ? 'pick_augment' : 'start_combat';
      if (firstAugment) payload = { augment_id: firstAugment.id };
      delay = 250;
    } else if (activeMatch.phase === 'combat' && autoPlay) {
      action = 'step_combat';
      delay = 520 / speed;
    } else if (activeMatch.phase === 'round_result') {
      action = 'next_round';
      delay = 15_000;
    } else return;
    const timer = window.setTimeout(() => void act(action, payload, true), delay);
    return () => window.clearTimeout(timer);
  }, [activeMatch, busy, remaining, autoPlay, speed, isPvpRoom]);

  const act = async (action: string, payload: Record<string, unknown> = {}, silent = false) => {
    if (!activeMatch || inFlight.current) return;
    inFlight.current = true;
    if (action !== 'step_combat') setBusy(true);
    try {
      if (room) {
        const res = await sendRoomAction(room.code, action, payload, spectateCid);
        setRoom(res.room);
        if (res.message && (!silent || !res.ok)) setNotice(res.message);
      } else if (match) {
        let res = await sendAutoChessAction(match.id, action, payload, playerName);
        if (action === 'step_combat' && resolveAfterStep.current && res.match.phase === 'combat') {
          res = await sendAutoChessAction(match.id, 'resolve_combat', {}, playerName);
        }
        setMatch(current => (current?.id === match.id ? res.match : current));
        if (res.account) onAccountUpdate?.(res.account);
        if (res.ranked_settlement) {
          setRankedSettlement(res.ranked_settlement);
        }
        if (res.match.phase === 'finished') setConfirmSurrender(false);
        if (res.message && (!silent || !res.ok)) setNotice(res.message);
        if (res.match.phase !== 'combat' || match.phase !== 'combat') setAutoPlay(true);
      }
    } catch (e) {
      onError((e as Error).message);
      setAutoPlay(false);
    } finally {
      resolveAfterStep.current = false;
      inFlight.current = false;
      setBusy(false);
    }
  };

  const resolveCombat = () => {
    if (busy) return;
    if (inFlight.current) {
      resolveAfterStep.current = true;
      setBusy(true);
      return;
    }
    void act('resolve_combat');
  };

  const handleCreate = async () => {
    setBusy(true);
    try {
      const created = await createAutoChessMatch({
        mode,
        arena_preset: arenaPreset,
        player_name: playerName || '指挥官',
      });
      setRoom(null);
      setMatch(created);
      setRankedSettlement(null);
      setConfirmSurrender(false);
      setAutoPlay(true);
      setSelectedId(null);
      setNotice('对局创建成功，请购买并布置你的魔法少女小队！');
      await refreshLobby();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateRanked = async () => {
    if (!account) {
      onOpenAuth?.('login', '请先登录自走棋账号后再参与 8 人排位模式');
      return;
    }
    setBusy(true);
    try {
      const res = await createRankedMatch({ arena_preset: rankedArena });
      setRoom(null);
      setMatch(res.match);
      setRankedSettlement(null);
      setConfirmSurrender(false);
      setAutoPlay(true);
      setSelectedId(null);
      setNotice(res.resumed ? '已为你重连至当前进行中的 8 人排位赛！' : '8 人排位赛已开启，共有 7 位同段位策略 AI 与你角逐排名！');
      await refreshLobby();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleLoad = async (id: string) => {
    setBusy(true);
    try {
      const loaded = await getAutoChessMatch(id, playerName);
      setRoom(null);
      setMatch(loaded);
      setRankedSettlement(null);
      setConfirmSurrender(false);
      setSelectedId(null);
      setAutoPlay(true);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: string) => {
    setBusy(true);
    try {
      await deleteAutoChessMatch(id, playerName);
      if (match?.id === id) setMatch(null);
      await refreshLobby();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateRoom = async () => {
    if (!account) {
      onOpenAuth?.('login', '请先登录自走棋账号后再创建多人联机房间');
      return;
    }
    setBusy(true);
    try {
      const created = await createRoom({
        name: roomName.trim() || undefined,
        arena_preset: roomArena,
        max_players: roomMaxPlayers,
        fill_bots: roomFillBots,
        prep_duration: roomPrepSec,
      });
      setMatch(null);
      setSpectateCid(null);
      setRoom(created);
      setSelectedId(null);
      setNotice(`联机房间 ${created.code} 已创建！分享房间号或链接给好友即可加入。`);
      await refreshLobby();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleJoinRoom = async (targetCode?: string) => {
    const code = (targetCode ?? joinCode).trim().toUpperCase();
    if (!code) return;
    if (!account) {
      onOpenAuth?.('login', `请先登录自走棋账号，再加入联机房间 ${code}`);
      return;
    }
    setBusy(true);
    try {
      const joined = await joinRoom(code);
      setMatch(null);
      setSpectateCid(null);
      setRoom(joined);
      setSelectedId(null);
      setNotice(joined.status === 'waiting' ? `已加入联机房间 ${joined.code}` : `已重连至联机对局 ${joined.code}`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleRoomControl = async (op: 'ready' | 'config' | 'leave' | 'start', payload: Record<string, unknown> = {}) => {
    if (!room) return;
    setBusy(true);
    try {
      const res = await controlRoom(room.code, op, payload);
      if (op === 'leave' || res.disbanded) {
        setRoom(null);
        setNotice(res.disbanded ? '房间已解散' : '已离开房间');
        await refreshLobby();
      } else if (res.room) {
        setRoom(res.room);
        if (res.message) setNotice(res.message);
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleSpectate = async (cid: string | null) => {
    if (!room) return;
    const target = cid === room.my_commander_id ? null : cid;
    setSpectateCid(target);
    try {
      const nextRoom = await getRoom(room.code, target);
      setRoom(nextRoom);
    } catch {
      // SSE will update shortly
    }
  };

  const copyText = async (txt: string) => {
    try {
      await navigator.clipboard.writeText(txt);
      setCopiedUrl(txt);
      window.setTimeout(() => setCopiedUrl(cur => (cur === txt ? '' : cur)), 1800);
    } catch {
      setNotice(`请手动复制：${txt}`);
    }
  };

  const selectedOwned: AutoChessOwnedUnit | null = useMemo(() => {
    if (!activeMatch || !selectedId) return null;
    return (
      activeMatch.player.board.find(u => u.id === selectedId) ||
      activeMatch.player.bench.find(u => u.id === selectedId) ||
      null
    );
  }, [activeMatch, selectedId]);

  useEffect(() => {
    if (!wikiOpenNonce) return;
    hoverWiki.closeNow();
    setWikiTarget({
      tab: 'units',
      serial: selectedOwned?.serial || catalog?.units[0]?.serial || 'Y1',
    });
  }, [wikiOpenNonce]);

  const resolveTokenUrl = useCallback(
    (serial: string, team: 'Y' | 'X', inCombat: boolean): { url: string; accent: string; isSvg: boolean } => {
      const meta = catalogBySerial[serial];
      let url = '';
      if (inCombat && activeMatch?.bout_token_overrides?.[team]?.[serial]) {
        url = activeMatch.bout_token_overrides[team][serial];
      } else if (team === 'Y') {
        const mine = account ? account.token_overrides : guestTokens;
        if (mine?.[serial]) url = mine[serial];
      }
      if (!url) {
        url = meta?.emblem_url || '/ui/icons/flame.svg';
      }
      return {
        url,
        accent: meta?.accent || (team === 'Y' ? '#8b7dff' : '#ff7b6b'),
        isSvg: url.toLowerCase().endsWith('.svg'),
      };
    },
    [account, activeMatch?.bout_token_overrides, catalogBySerial, guestTokens],
  );

  const renderMiniToken = (serial: string, name: string, team: 'Y' | 'X' = 'Y') => {
    const resolved = resolveTokenUrl(serial, team, false);
    const ring = team === 'Y' ? '#5b46e8' : '#df4e3b';
    return (
      <span className="ac-mini-token" style={{ borderColor: ring }} title={name}>
        {resolved.isSvg ? (
          <span
            className="ac-mini-token-emblem"
            style={{
              backgroundColor: resolved.accent,
              WebkitMaskImage: `url(${resolved.url})`,
              maskImage: `url(${resolved.url})`,
            }}
          />
        ) : (
          <img src={resolved.url} alt={name} className="ac-mini-token-img" />
        )}
      </span>
    );
  };

  const wikiOverlays = (
    <>
      {hoverWiki.preview && (
        <AutoChessWikiPopover
          catalog={catalog}
          serial={hoverWiki.preview.serial}
          star={hoverWiki.preview.star}
          anchorRect={hoverWiki.preview.rect}
          onMouseEnter={hoverWiki.enterPopover}
          onMouseLeave={hoverWiki.leavePopover}
          onClose={hoverWiki.closeNow}
          onOpenFullWiki={target => {
            hoverWiki.closeNow();
            setWikiTarget(target);
          }}
        />
      )}
      {wikiTarget && (
        <AutoChessWikiModal
          catalog={catalog}
          initialTarget={wikiTarget}
          onClose={() => setWikiTarget(null)}
        />
      )}
    </>
  );

  const saveName = async () => {
    const cleaned = nameDraft.trim().slice(0, 20);
    if (!cleaned || cleaned === playerName || !onPlayerNameChange) {
      setNameDraft(playerName);
      return;
    }
    try {
      await onPlayerNameChange(cleaned);
      setNotice(`指挥官称呼已更新为「${cleaned}」`);
    } catch (e) {
      onError((e as Error).message);
      setNameDraft(playerName);
    }
  };

  // ── Waiting Room Screen ──────────────────────────────────────────────────
  if (room && (!room.match || room.status === 'waiting')) {
    const myMember = room.members.find(m => m.account_id === room.my_account_id);
    const nonHostUnready = room.members.filter(m => !m.is_host && !m.ready);
    const canStart =
      room.is_host &&
      nonHostUnready.length === 0 &&
      (room.fill_bots || room.members.length >= 2);
    const arenaInfo = catalog?.arenas.find(a => a.id === room.arena_preset);

    return (
      <div className="page ac-page">
        {notice && (
          <div className="ac-intent-bar">
            <span>{notice}</span>
            <button className="icon-button" onClick={() => setNotice('')}>
              <X size={14} />
            </button>
          </div>
        )}

        <section className="panel ac-room-wait-card">
          <div className="ac-room-wait-head">
            <div>
              <div className="eyebrow">MULTIPLAYER WAITING LOBBY</div>
              <h2>{room.name}</h2>
              <div className="ac-room-code-bar">
                <span>
                  房间号：<strong className="ac-room-code-badge">{room.code}</strong>
                </span>
                <button type="button" className="button subtle compact-button" onClick={() => void copyText(room.code)}>
                  {copiedUrl === room.code ? <Check size={14} /> : <Copy size={14} />}
                  <span>{copiedUrl === room.code ? '已复制房间号' : '复制房间号'}</span>
                </button>
              </div>
            </div>
            <div className="ac-hud-group">
              <button type="button" className="button subtle" onClick={() => onOpenTokenEditor?.()}>
                <ImageIcon size={15} /> 定制出战头图
              </button>
              <button
                type="button"
                className="button subtle"
                disabled={busy}
                onClick={() => void handleRoomControl('leave')}
              >
                退出房间
              </button>
            </div>
          </div>

          <div className="ac-room-invite-box">
            <strong>局域网 / 在线邀请链接：</strong>
            <div className="ac-room-invite-links">
              {room.invite_urls.map(u => (
                <div key={u} className="ac-invite-url-row">
                  <code>{u}</code>
                  <button type="button" className="button subtle compact-button" onClick={() => void copyText(u)}>
                    {copiedUrl === u ? <Check size={13} /> : <Copy size={13} />}
                    <span>{copiedUrl === u ? '已复制' : '复制链接'}</span>
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="ac-room-split">
            <div className="ac-room-seats-panel">
              <h3>
                玩家席位 ({room.members.length}/{room.max_players} 人)
              </h3>
              <div className="ac-seat-grid">
                {Array.from({ length: room.max_players }, (_, idx) => {
                  const m = room.members[idx];
                  if (m) {
                    return (
                      <div key={m.account_id} className={`ac-seat-card filled ${m.ready ? 'ready' : ''}`}>
                        <div className="ac-seat-top">
                          <strong>
                            {m.is_host && <Crown size={14} className="ac-host-icon" />} {m.display_name}
                          </strong>
                          <span className={`ac-ready-pill ${m.ready ? 'ok' : ''}`}>
                            {m.is_host ? '房主' : m.ready ? '已准备' : '未准备'}
                          </span>
                        </div>
                        <small className="muted">@{m.username}</small>
                      </div>
                    );
                  }
                  return (
                    <div key={`empty-${idx}`} className="ac-seat-card empty">
                      <strong>{room.fill_bots ? 'AI 代理空位' : '等待好友加入'}</strong>
                      <small className="muted">
                        {room.fill_bots ? '开局若未满人将由 AI 替补至 4 人' : '发送上方房间号或邀请链接'}
                      </small>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="ac-room-config-panel">
              <h3>房间战场设置 {room.is_host ? '(房主可调)' : '(仅房主可改)'}</h3>
              <div className="ac-room-config-list">
                <label className="ac-field">
                  <span>对称棋盘形制</span>
                  <select
                    disabled={!room.is_host || busy}
                    value={room.arena_preset}
                    onChange={e => void handleRoomControl('config', { arena_preset: e.target.value })}
                  >
                    {(catalog?.arenas || []).map(ar => (
                      <option key={ar.id} value={ar.id}>
                        {ar.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="ac-field">
                  <span>真人玩家上限</span>
                  <select
                    disabled={!room.is_host || busy}
                    value={room.max_players}
                    onChange={e => void handleRoomControl('config', { max_players: Number(e.target.value) })}
                  >
                    {[2, 3, 4].map(n => (
                      <option key={n} value={n} disabled={n < room.members.length}>
                        {n} 人联机
                      </option>
                    ))}
                  </select>
                </label>

                <label className="ac-field">
                  <span>每回合备战时间</span>
                  <select
                    disabled={!room.is_host || busy}
                    value={room.prep_duration}
                    onChange={e => void handleRoomControl('config', { prep_duration: Number(e.target.value) })}
                  >
                    {[20, 30, 45, 60].map(sec => (
                      <option key={sec} value={sec}>
                        {sec} 秒
                      </option>
                    ))}
                  </select>
                </label>

                <label className="ac-checkbox-row">
                  <input
                    type="checkbox"
                    disabled={!room.is_host || busy}
                    checked={room.fill_bots}
                    onChange={e => void handleRoomControl('config', { fill_bots: e.target.checked })}
                  />
                  <span>人数不足 4 人时由 AI 指挥官补足</span>
                </label>

                {arenaInfo && <p className="muted" style={{ fontSize: '0.78rem', margin: '4px 0 0' }}>{arenaInfo.description}</p>}
              </div>

              <div className="ac-room-wait-actions">
                {!room.is_host && (
                  <button
                    type="button"
                    className={`button ${myMember?.ready ? 'subtle' : 'primary'}`}
                    disabled={busy}
                    onClick={() => void handleRoomControl('ready', { ready: !myMember?.ready })}
                  >
                    {myMember?.ready ? '取消准备' : '准备就绪'}
                  </button>
                )}

                {room.is_host && (
                  <button
                    type="button"
                    className="button primary"
                    disabled={busy || !canStart}
                    onClick={() => void handleRoomControl('start')}
                  >
                    <Swords size={15} />{' '}
                    {!room.fill_bots && room.members.length < 2
                      ? '至少需要 2 名真人（或开启 AI 补位）'
                      : nonHostUnready.length > 0
                      ? `等待玩家准备 (${nonHostUnready.map(m => m.display_name).join('、')})`
                      : '开启多人自走棋！'}
                  </button>
                )}
              </div>
            </div>
          </div>
        </section>

        {wikiOverlays}
      </div>
    );
  }

  // ── Lobby Screen ─────────────────────────────────────────────────────────
  if (!activeMatch) {
    return (
      <div className="page ac-page ac-page-lobby">
        <div className="page-intro">
          <div>
            <div className="eyebrow">STARLIGHT AUTO-CHESS · SPATIAL EDITION</div>
            <h1>星序自走棋</h1>
            <p>
              独立空间自走棋工作台：对称地形、切比雪夫真射程、BFS 地形卡位、经济利息、可定制棋子 Token 与多人联机。
            </p>
          </div>
          <div className="ac-lobby-actions">
            {onPlayerNameChange && !account && (
              <form
                className="ac-name-form"
                onSubmit={e => {
                  e.preventDefault();
                  void saveName();
                }}
              >
                <input
                  aria-label="指挥官称呼"
                  maxLength={20}
                  value={nameDraft}
                  placeholder="游客称呼"
                  onChange={e => setNameDraft(e.target.value)}
                />
                <button type="submit" className="button subtle compact-button" disabled={busy || !nameDraft.trim()}>
                  改名
                </button>
              </form>
            )}
            <button
              className="button subtle compact-button"
              onClick={() => onOpenTokenEditor?.(catalog?.units[0]?.serial)}
            >
              <ImageIcon size={16} /> 定制棋子头图
            </button>
            <button
              className="button subtle compact-button"
              onClick={() => setWikiTarget({ tab: 'units', serial: catalog?.units[0]?.serial })}
            >
              <BookOpen size={16} /> 自走棋百科
            </button>
            <button
              className="button subtle compact-button"
              onClick={() => setWikiTarget({ tab: 'rules' })}
            >
              <CircleHelp size={16} /> 规则说明
            </button>
          </div>
        </div>

        {notice && (
          <div className="ac-intent-bar">
            <span>{notice}</span>
            <button className="icon-button" onClick={() => setNotice('')}>
              <X size={14} />
            </button>
          </div>
        )}

        <div className="ac-landscape-lobby-tabs" role="tablist" aria-label="手机横屏大厅模式切换">
          <button
            type="button"
            role="tab"
            aria-selected={lobbyMobileTab === 'ranked'}
            className={lobbyMobileTab === 'ranked' ? 'active' : ''}
            onClick={() => setLobbyMobileTab('ranked')}
          >
            🏆 8人排位
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={lobbyMobileTab === 'pve'}
            className={lobbyMobileTab === 'pve' ? 'active' : ''}
            onClick={() => setLobbyMobileTab('pve')}
          >
            ⚔️ 单人 / PvE
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={lobbyMobileTab === 'pvp'}
            className={lobbyMobileTab === 'pvp' ? 'active' : ''}
            onClick={() => setLobbyMobileTab('pvp')}
          >
            👥 多人联机
          </button>
        </div>

        {/* Top Full-Width Ranked Mode Hero */}
        {(() => {
          const rankedProfile = account?.ranked;
          const activeRankedSave = matches.find(m => m.mode === 'ranked' && m.phase !== 'finished');
          const tierNames = [
            { id: 'bronze', label: '青铜 3段 (+100~0)' },
            { id: 'silver', label: '白银 4段 (+75~-25)' },
            { id: 'gold', label: '黄金 5段 (+50~-40)' },
            { id: 'platinum', label: '铂金 5段 (+50~-50)' },
            { id: 'diamond', label: '钻石 5段 (+35~-55)' },
            { id: 'king', label: '王者 无限 (+20~-60)' },
          ];
          return (
            <section className={'panel ac-ranked-hero ac-lobby-tab-pane ' + (lobbyMobileTab === 'ranked' ? 'ac-lobby-tab-active' : '')}>
              <div className="ac-section-head" style={{ marginBottom: 10 }}>
                <div>
                  <h3 style={{ margin: 0 }}>
                    <Trophy size={18} style={{ verticalAlign: '-3px', marginRight: 6, color: '#d97706' }} />
                    8 人混战排位模式 · 全服段位天梯
                  </h3>
                  <small className="muted">
                    7 位随机命名、每段位 12 套差异化策略 AI 混战 · 前 4 上分得金币，白银永不降青铜
                  </small>
                </div>
                <span className={account ? 'ac-badge-unlocked' : 'ac-badge-locked'}>
                  {account && rankedProfile ? rankedProfile.rank_info.full_label : '需账号登录'}
                </span>
              </div>

              {!account || !rankedProfile ? (
                <div className="ac-ranked-locked-box">
                  <div className="ac-ranked-tiers-strip">
                    {tierNames.map(t => (
                      <span key={t.id} className={`ac-tier-badge ac-tier-${t.id}`}>
                        {t.label}
                      </span>
                    ))}
                  </div>
                  <p className="muted" style={{ margin: '6px 0 0', fontSize: '0.84rem', lineHeight: 1.5 }}>
                    登录后即可参与 8 人排位混战！每小段 100 分，连胜可额外加分并概率/必得<b>保段卡</b>，晋级白银后永久不会因战败降回青铜；前 4 胜利还可获得局外<b>金币</b>资源并参与全服积分排名。
                  </p>
                  <div className="ac-hud-group" style={{ marginTop: 10 }}>
                    <button
                      type="button"
                      className="button primary"
                      onClick={() => onOpenAuth?.('login', '请先登录自走棋账号后再参与排位赛')}
                    >
                      登录参与排位
                    </button>
                    <button type="button" className="button subtle" onClick={() => onOpenAuth?.('register')}>
                      注册账号
                    </button>
                    <button type="button" className="button subtle" onClick={() => onOpenLeaderboard?.()}>
                      <Trophy size={15} /> 全服排位排行榜
                    </button>
                  </div>
                </div>
              ) : (
                <div className="ac-ranked-hero-grid">
                  <div className="ac-ranked-profile-card">
                    <div className="ac-ranked-profile-top">
                      <div>
                        <span className={`ac-tier-badge ac-tier-${rankedProfile.rank_info.tier_id}`}>
                          {rankedProfile.rank_info.full_label}
                        </span>
                        <strong className="ac-ranked-lp-num">{rankedProfile.total_lp} 积分</strong>
                      </div>
                      <span className="ac-ranked-coins-pill" title="局外金币（排位胜利奖励，暂未设消耗出口）">
                        <Coins size={14} /> {rankedProfile.coins} 金币
                      </span>
                    </div>

                    <div className="ac-lp-progress-wrap">
                      <div className="ac-lp-progress-bar">
                        <div
                          className="ac-lp-progress-fill"
                          style={{
                            width: `${Math.min(100, Math.max(0, rankedProfile.rank_info.division_lp))}%`,
                            backgroundColor: rankedProfile.rank_info.tier_color,
                          }}
                        />
                      </div>
                      <div className="ac-lp-progress-labels">
                        <span>本小段进度 {rankedProfile.rank_info.division_lp}/100</span>
                        <span>
                          {rankedProfile.silver_floor_unlocked
                            ? '✅ 已激活白银永不降青铜保护'
                            : '升至白银(300分)后永不降青铜'}
                        </span>
                      </div>
                    </div>

                    <div className="ac-ranked-mini-stats">
                      <span>
                        <Award size={13} /> 前4胜 {rankedProfile.wins}/{rankedProfile.games} 局 ({rankedProfile.firsts}吃鸡)
                      </span>
                      <span>
                        <Sparkles size={13} /> 连胜 {rankedProfile.win_streak} (最高 {rankedProfile.best_win_streak})
                      </span>
                      <span>
                        <Shield size={13} /> 保段卡 {rankedProfile.shield_cards}/{rankedProfile.shield_card_cap}
                      </span>
                    </div>

                    {rankedProfile.history.length > 0 && (
                      <div className="ac-ranked-history-row">
                        <span className="muted" style={{ fontSize: '0.73rem' }}>近期战绩：</span>
                        {rankedProfile.history.slice(-4).reverse().map((h, i) => (
                          <span key={i} className={`ac-ranked-hist-chip ${h.placement <= 4 ? 'win' : 'loss'}`}>
                            #{h.placement} {h.net_delta >= 0 ? `+${h.net_delta}` : h.net_delta}分
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="ac-ranked-launch-box">
                    <label className="ac-field">
                      <span>排位赛对称战场</span>
                      <select value={rankedArena} onChange={e => setRankedArena(e.target.value)}>
                        {(catalog?.arenas || []).map(ar => (
                          <option key={ar.id} value={ar.id}>
                            {ar.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="ac-ranked-launch-actions">
                      <button
                        type="button"
                        className="button primary ac-ranked-start-btn"
                        disabled={busy}
                        onClick={() => void handleCreateRanked()}
                      >
                        <Swords size={16} />{' '}
                        {activeRankedSave
                          ? `继续排位赛 (第${activeRankedSave.round_num}回合 · HP ${activeRankedSave.hp})`
                          : '开启 8 人排位赛'}
                      </button>
                      <button
                        type="button"
                        className="button subtle"
                        onClick={() => onOpenLeaderboard?.()}
                      >
                        <Trophy size={15} /> 全服排行榜
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </section>
          );
        })()}

        <div className={'ac-lobby-grid ' + (lobbyMobileTab !== 'ranked' ? 'ac-lobby-grid-mobile-active' : '')}>
          {/* Left Panel: Singleplayer / PvE (Available to Guests & Logged-in Accounts) */}
          <section className={'panel ac-lobby-tab-pane ' + (lobbyMobileTab === 'pve' ? 'ac-lobby-tab-active' : '')} style={{ padding: 16 }}>
            <div className="ac-section-head" style={{ marginBottom: 8 }}>
              <h3 style={{ margin: 0 }}>单人模式 · PvE 试炼与 AI 练习</h3>
              <span className="ac-badge-free">{account ? '账号云同步中' : '游客免登录可用'}</span>
            </div>
            <div className="ac-mode-pills">
              <button
                type="button"
                className={'ac-mode-pill ' + (mode === 'lobby4' ? 'active' : '')}
                onClick={() => setMode('lobby4')}
              >
                <strong>4 人 AI 锦标大厅</strong>
                <small>与 3 名策略各异的 AI 指挥官争夺第一名，第 4、8、12 回合可选星序祝福</small>
              </button>
              <button
                type="button"
                className={'ac-mode-pill ' + (mode === 'pve12' ? 'active' : '')}
                onClick={() => setMode('pve12')}
              >
                <strong>12 波星序试炼 (PvE)</strong>
                <small>迎战 12 波逐步强化的主题守卫阵营，检验构筑上限</small>
              </button>
            </div>

            <h4 style={{ marginBottom: 8 }}>选择对称战场形制</h4>
            <div className="ac-arena-cards">
              {(catalog?.arenas || []).map(ar => (
                <button
                  key={ar.id}
                  type="button"
                  className={'ac-arena-card ' + (arenaPreset === ar.id ? 'active' : '')}
                  onClick={() => setArenaPreset(ar.id)}
                >
                  <strong>{ar.name}</strong>
                  <p>{ar.description}</p>
                </button>
              ))}
            </div>

            <button className="button primary" disabled={busy} onClick={handleCreate}>
              <Sparkles size={16} /> 开启单人 / PvE 对局
            </button>

            <div style={{ marginTop: 18 }}>
              <div className="ac-section-head" style={{ marginBottom: 8 }}>
                <h4 style={{ margin: 0 }}>
                  {account ? `我的存档对局 (@${account.username} 跨端互通)` : '本机游客存档对局'}
                </h4>
                <button className="button subtle compact-button" onClick={() => void refreshLobby()}>
                  <RefreshCw size={14} /> 刷新
                </button>
              </div>
              {!matches.length ? (
                <p className="muted" style={{ fontSize: '0.82rem' }}>
                  暂无已保存对局，开局后将自动持久化保存，支持刷新或跨设备重连。
                </p>
              ) : (
                <div className="ac-saved-list">
                  {matches.map(m => (
                    <div key={m.id} className="ac-saved-item">
                      <div>
                        <strong>
                          {m.mode === 'ranked'
                            ? '8人排位赛'
                            : m.mode === 'lobby4'
                            ? '4人 AI 大厅'
                            : '12波 PvE 试炼'}
                        </strong>
                        <div className="muted" style={{ fontSize: '0.78rem' }}>
                          第 {m.round_num} 回合 · HP {m.hp} · {m.phase === 'finished' ? '已结束' : '进行中'} · {m.arena_preset}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="button subtle" disabled={busy} onClick={() => void handleLoad(m.id)}>
                          {m.phase === 'finished' ? '查看' : '继续'}
                        </button>
                        {!(m.mode === 'ranked' && m.phase !== 'finished') && (
                          <button className="button subtle" title="删除存档" disabled={busy} onClick={() => void handleDelete(m.id)}>
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* Right Panel: Multiplayer Room Mode (Login Required) */}
          <section className={'panel ac-pvp-panel ac-lobby-tab-pane ' + (lobbyMobileTab === 'pvp' ? 'ac-lobby-tab-active' : '')} style={{ padding: 16 }}>
            <div className="ac-section-head" style={{ marginBottom: 8 }}>
              <h3 style={{ margin: 0 }}>
                <Users size={17} style={{ verticalAlign: '-3px', marginRight: 6 }} />
                多人联机开房间 (PvP)
              </h3>
              <span className={account ? 'ac-badge-unlocked' : 'ac-badge-locked'}>
                {account ? `已登录 @${account.username}` : '需账号登录'}
              </span>
            </div>

            {!account ? (
              <div className="ac-pvp-locked-box">
                <Lock size={28} />
                <h4>登录后即可开启多人联机对战</h4>
                <p>
                  未登录时仅开放左侧单人 AI 大厅与 12 波 PvE 试炼；创建并登录自走棋账号后，可开设 2–4 人联机房间、生成局域网邀请码，并在同账号跨设备互通全部存档、战绩与定制棋子头图。
                </p>
                {pendingRoomCode && (
                  <div className="ac-banner ac-banner-warn" style={{ width: '100%', boxSizing: 'border-box' }}>
                    已检测到邀请房间号 <strong>{pendingRoomCode}</strong>，登录后即可加入对战！
                  </div>
                )}
                <div className="ac-hud-group" style={{ justifyContent: 'center' }}>
                  <button
                    type="button"
                    className="button primary"
                    onClick={() =>
                      onOpenAuth?.(
                        'login',
                        pendingRoomCode ? `请先登录账号，以加入联机房间 ${pendingRoomCode}` : undefined,
                      )
                    }
                  >
                    登录账号
                  </button>
                  <button
                    type="button"
                    className="button subtle"
                    onClick={() => onOpenAuth?.('register')}
                  >
                    注册新账号
                  </button>
                </div>
              </div>
            ) : (
              <div className="ac-pvp-body">
                <form
                  className="ac-join-room-bar"
                  onSubmit={e => {
                    e.preventDefault();
                    void handleJoinRoom();
                  }}
                >
                  <input
                    aria-label="输入 6 位房间码"
                    maxLength={8}
                    placeholder="输入 6 位房间号加入好友房间"
                    value={joinCode}
                    onChange={e => setJoinCode(e.target.value.toUpperCase())}
                  />
                  <button type="submit" className="button primary" disabled={busy || !joinCode.trim()}>
                    加入房间
                  </button>
                </form>

                <div className="ac-create-room-box">
                  <h4 style={{ margin: '0 0 8px' }}>创建多人联机房间</h4>
                  <div className="ac-create-room-grid">
                    <label className="ac-field">
                      <span>房间名称（可选）</span>
                      <input
                        maxLength={28}
                        placeholder={`${account.display_name}的房间`}
                        value={roomName}
                        onChange={e => setRoomName(e.target.value)}
                      />
                    </label>
                    <label className="ac-field">
                      <span>棋盘形制</span>
                      <select value={roomArena} onChange={e => setRoomArena(e.target.value)}>
                        {(catalog?.arenas || []).map(ar => (
                          <option key={ar.id} value={ar.id}>
                            {ar.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="ac-field">
                      <span>玩家人数</span>
                      <select
                        value={roomMaxPlayers}
                        onChange={e => setRoomMaxPlayers(Number(e.target.value) as 2 | 3 | 4)}
                      >
                        <option value={2}>2 人局</option>
                        <option value={3}>3 人局</option>
                        <option value={4}>4 人局</option>
                      </select>
                    </label>
                    <label className="ac-field">
                      <span>备战秒数</span>
                      <select value={roomPrepSec} onChange={e => setRoomPrepSec(Number(e.target.value))}>
                        <option value={20}>20 秒（快节奏）</option>
                        <option value={30}>30 秒（标准）</option>
                        <option value={45}>45 秒（宽裕）</option>
                        <option value={60}>60 秒（慢速）</option>
                      </select>
                    </label>
                  </div>
                  <label className="ac-checkbox-row" style={{ marginTop: 8 }}>
                    <input
                      type="checkbox"
                      checked={roomFillBots}
                      onChange={e => setRoomFillBots(e.target.checked)}
                    />
                    <span>开局不足 4 人时由 AI 补足空位</span>
                  </label>
                  <button
                    type="button"
                    className="button primary"
                    style={{ marginTop: 10 }}
                    disabled={busy}
                    onClick={() => void handleCreateRoom()}
                  >
                    <Users size={15} /> 创建房间并等待好友
                  </button>
                </div>

                <div>
                  <div className="ac-section-head" style={{ marginBottom: 8 }}>
                    <h4 style={{ margin: 0 }}>开放与进行中的联机房间</h4>
                    <button type="button" className="button subtle compact-button" onClick={() => void refreshLobby()}>
                      <RefreshCw size={14} /> 刷新列表
                    </button>
                  </div>
                  {!rooms.length ? (
                    <p className="muted" style={{ fontSize: '0.82rem' }}>
                      当前暂无公开候战房间，可点击上方创建或输入好友房间号。
                    </p>
                  ) : (
                    <div className="ac-saved-list">
                      {rooms.map(rm => (
                        <div key={rm.code} className="ac-saved-item">
                          <div>
                            <strong>
                              [{rm.code}] {rm.name}
                            </strong>
                            <div className="muted" style={{ fontSize: '0.78rem' }}>
                              房主：{rm.host_name || '玩家'} · {rm.member_count}/{rm.max_players}人 ·{' '}
                              {rm.status === 'waiting' ? '等待开局' : rm.status === 'playing' ? '对战中（可重连）' : '已结束'}
                            </div>
                          </div>
                          <button
                            type="button"
                            className="button primary compact-button"
                            disabled={busy}
                            onClick={() => void handleJoinRoom(rm.code)}
                          >
                            {rm.is_member && rm.status !== 'waiting' ? '重连对局' : '进入房间'}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>

        {wikiOverlays}
      </div>
    );
  }

  // ── Playing View (PvE / Lobby4 / PvP Room) ───────────────────────────────
  const p = activeMatch.player;
  const boardW = activeMatch.live_snapshot?.width || activeMatch.map.width;
  const boardH = activeMatch.live_snapshot?.height || activeMatch.map.height;
  const terrain = activeMatch.live_snapshot?.terrain || activeMatch.map.terrain || {};
  const deployColsY = new Set((activeMatch.live_snapshot?.deploy_cols || activeMatch.map.deploy_cols)?.Y || []);
  const latestFrame = activeMatch.combat_frames[activeMatch.combat_frames.length - 1] || null;
  const latestVfxEvents = latestFrame?.vfx_events || [];

  const actingUids = new Set<string>();
  const hitUids = new Set<string>();
  if (latestFrame?.actor_uid) actingUids.add(latestFrame.actor_uid);
  for (const ev of latestVfxEvents) {
    if (ev.type === 'action') {
      if (ev.actor_uid) actingUids.add(ev.actor_uid);
      for (const tu of ev.target_uids || []) hitUids.add(tu);
      for (const pop of ev.popups || []) {
        if (pop.kind === 'dmg') hitUids.add(pop.uid);
      }
    }
  }

  const curInterest = Math.min(p.max_interest, Math.floor(p.gold / 10));
  const selectedCoord = selectedOwned?.location === 'board' ? selectedOwned.coord : null;
  const selectedOrigin = selectedCoord ? parseCoordStr(selectedCoord) : null;

  const cellSize = boardW >= 12 ? 50 : boardW >= 10 ? 58 : 64;
  const padL = 26;
  const padT = 30;
  const svgW = padL + boardW * cellSize + 12;
  const svgH = padT + boardH * cellSize + 14;

  const cellCenter = (coord: string): { x: number; y: number } | null => {
    const pt = parseCoordStr(coord);
    if (!pt) return null;
    return {
      x: padL + pt[0] * cellSize + cellSize / 2,
      y: padT + pt[1] * cellSize + cellSize / 2,
    };
  };

  const onBoardCellClick = (coord: string, unitAtCoord: AutoChessOwnedUnit | undefined) => {
    if (activeMatch.phase !== 'prep') return;
    if (unitAtCoord) {
      if (selectedOwned && selectedOwned.id !== unitAtCoord.id) {
        void act('swap', { unit_a: selectedOwned.id, unit_b: unitAtCoord.id });
        setSelectedId(null);
      } else {
        setSelectedId(selectedOwned?.id === unitAtCoord.id ? null : unitAtCoord.id);
      }
      return;
    }
    if (selectedOwned) {
      void act('deploy', { unit_id: selectedOwned.id, coord });
      setSelectedId(null);
    }
  };

  const renderUnitToken = (
    serial: string,
    label: string,
    team: 'Y' | 'X',
    star: number,
    hpPct: number,
    shield: number,
    flying: boolean,
    isSelected: boolean,
    isDying: boolean,
    isSummon: boolean,
    motionClass = '',
  ) => {
    // Fixed team color rings: left/friendly always #5b46e8, right/enemy always #df4e3b
    const ringColor = team === 'Y' ? '#5b46e8' : '#df4e3b';
    const coreBg = team === 'Y' ? '#1e1940' : '#3d1514';
    const hpColor = team === 'Y' ? '#22c55e' : '#ef4444';
    const r = isSummon ? cellSize * 0.27 : cellSize * 0.33;
    const resolved = serial ? resolveTokenUrl(serial, team, activeMatch.phase !== 'prep') : null;
    const cleanLabel = label.replace(/★+|\s+/g, '');
    const shortLabel = cleanLabel.slice(0, 5);
    const pillW = Math.max(30, shortLabel.length * 10 + 10);

    return (
      <g style={{ cursor: activeMatch.phase === 'prep' ? 'pointer' : 'default' }}>
        <g className={motionClass}>
          {isSelected && (
            <circle cx={0} cy={0} r={r + 5.5} fill="none" stroke="#f59e0b" strokeWidth={2.8} strokeDasharray="4 2" />
          )}
          <circle
            cx={0}
            cy={0}
            r={r}
            fill={isDying ? '#4b5563' : coreBg}
            fillOpacity={isSummon ? 0.85 : 0.98}
            stroke={ringColor}
            strokeWidth={3.2}
          />
          {resolved && resolved.isSvg && (
            <>
              <circle cx={0} cy={0} r={Math.max(4, r - 3.5)} fill={resolved.accent} fillOpacity={0.28} />
              <image
                href={resolved.url}
                x={-(r - 5)}
                y={-(r - 5)}
                width={(r - 5) * 2}
                height={(r - 5) * 2}
                filter="url(#ac-emblem-light)"
              />
            </>
          )}
          {resolved && !resolved.isSvg && (
            <image
              href={resolved.url}
              x={-(r - 2)}
              y={-(r - 2)}
              width={(r - 2) * 2}
              height={(r - 2) * 2}
              preserveAspectRatio="xMidYMid slice"
              clipPath="url(#ac-clip-unit)"
            />
          )}
          {!resolved && (
            <text x={0} y={4} textAnchor="middle" fill="#fff" fontSize={10} fontWeight={700}>
              {label.slice(0, 2)}
            </text>
          )}
          {star > 1 && (
            <text x={0} y={r + 1} textAnchor="middle" fill="#facc15" stroke="#111827" strokeWidth={0.5} fontSize={9.5} fontWeight={800}>
              {'★'.repeat(star)}
            </text>
          )}
          {flying && (
            <text x={r + 1} y={-r + 5} textAnchor="middle" fill="#38bdf8" fontSize={10} fontWeight={800}>
              ✈
            </text>
          )}
        </g>

        {/* Character Name ABOVE Token */}
        <g transform={`translate(0, ${-r - 11})`} className="ac-name-pill">
          <rect
            x={-pillW / 2}
            y={-8}
            width={pillW}
            height={14.5}
            rx={7}
            fill="rgba(16, 18, 34, 0.9)"
            stroke={ringColor}
            strokeWidth={1.1}
          />
          <text x={0} y={2} textAnchor="middle" fill="#f8fafc" fontSize={9.2} fontWeight={700}>
            {shortLabel}
          </text>
        </g>

        {/* HP & Shield Bar BELOW Token */}
        <rect x={-r} y={r + 4} width={r * 2} height={4.8} rx={2} fill="#e5e7eb" />
        <rect
          x={-r}
          y={r + 4}
          width={Math.max(0, Math.min(1, hpPct)) * r * 2}
          height={4.8}
          rx={2}
          fill={hpColor}
        />
        {shield > 0 && (
          <rect
            x={-r}
            y={r + 4}
            width={Math.min(r * 2, Math.max(4, (shield / 15) * r * 2))}
            height={2.2}
            rx={1}
            fill="#38bdf8"
          />
        )}
      </g>
    );
  };

  const benchCapacity = p.bench_capacity ?? 6;
  const benchSlots: (AutoChessOwnedUnit | null)[] = Array.from({ length: 12 }, (_, i) =>
    p.bench.find(u => u.bench_idx === i) || null,
  );
  const watchingOther = Boolean(isPvpRoom && spectateCid && room?.my_commander_id && spectateCid !== room.my_commander_id);
  const watchingCommander = watchingOther
    ? activeMatch.commanders.find(c => c.id === spectateCid)
    : null;

  return (
    <div className="page ac-page ac-page-playing">
      {/* Top HUD */}
      <section className="panel ac-hud">
        <div className="ac-hud-group">
          <button
            className="button subtle"
            onClick={() => {
              setRoom(null);
              setMatch(null);
              setSpectateCid(null);
              void refreshLobby();
            }}
          >
            ← 大厅/换局
          </button>
          {room && <span className="ac-stat-chip ac-room-chip">联机房 {room.code}</span>}
          {activeMatch.mode === 'ranked' && (
            <span className={`ac-tier-badge ac-tier-${activeMatch.ranked_tier || 'bronze'}`}>
              8人排位 ·{' '}
              {
                (
                  {
                    bronze: '青铜局',
                    silver: '白银局',
                    gold: '黄金局',
                    platinum: '铂金局',
                    diamond: '钻石局',
                    king: '王者局',
                  } as Record<string, string>
                )[activeMatch.ranked_tier || 'bronze'] || '排位局'
              }
            </span>
          )}
          <span className="ac-stat-chip">
            <Compass size={14} /> 第 {activeMatch.round_num}
            {activeMatch.max_waves ? `/${activeMatch.max_waves}` : ''} 回合 ·{' '}
            {activeMatch.phase === 'prep'
              ? '备战布阵'
              : activeMatch.phase === 'combat'
              ? '战斗演算'
              : activeMatch.phase === 'round_result'
              ? '回合结算'
              : '对局结束'}
          </span>
          <span className="ac-stat-chip hp">
            <Heart size={14} /> {p.hp}/{p.max_hp}
          </span>
          <span className="ac-stat-chip gold" title={`当前利息 +${curInterest}G (上限+${p.max_interest}G)`}>
            <Coins size={14} /> {p.gold}G (利息+{curInterest})
          </span>
          <span className="ac-stat-chip">
            Lv.{p.level} · 人口 {p.board.length}/{p.max_pop}
            {p.xp_to_next > 0 ? ` · XP ${p.xp}/${p.xp_to_next}` : ' · 满级'}
          </span>
          {p.streak !== 0 && (
            <span className="ac-stat-chip">
              {p.streak > 0 ? `${p.streak} 连胜` : `${Math.abs(p.streak)} 连败`}
            </span>
          )}
        </div>
        <div className="ac-hud-group">
          {activeMatch.opponent_name && activeMatch.phase !== 'prep' && (
            <span className="ac-stat-chip">对手：{activeMatch.opponent_name}</span>
          )}
          <span className="muted" style={{ fontSize: '0.8rem' }}>
            {activeMatch.arena_name} · 牌库余 {activeMatch.pool_remaining}
          </span>
          <button className="button subtle" onClick={() => setWikiTarget({ tab: 'rules' })}>
            <CircleHelp size={15} /> 规则说明
          </button>
          {activeMatch.mode === 'ranked' && activeMatch.phase !== 'finished' && (
            confirmSurrender ? (
              <div className="ac-hud-group">
                <button
                  type="button"
                  className="button subtle ac-surrender-confirm-btn"
                  disabled={busy}
                  onClick={() => void act('surrender')}
                >
                  确认投降结算
                </button>
                <button
                  type="button"
                  className="button subtle"
                  disabled={busy}
                  onClick={() => setConfirmSurrender(false)}
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="button subtle"
                disabled={busy}
                onClick={() => setConfirmSurrender(true)}
              >
                投降结算
              </button>
            )
          )}
        </div>
      </section>

      {notice && (
        <div className="ac-intent-bar">
          <span>{notice}</span>
          <button className="icon-button" onClick={() => setNotice('')}>
            <X size={14} />
          </button>
        </div>
      )}

      {watchingOther && (
        <div className="ac-intent-bar">
          <span>
            <Eye size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
            正在观战其他席位：{watchingCommander?.name || spectateCid}
          </span>
          <button type="button" className="button primary compact-button" onClick={() => void handleSpectate(null)}>
            切回自己视角
          </button>
        </div>
      )}

      <div className="ac-workspace">
        {/* Left column: Synergies + Standings + Logs */}
        <aside className="ac-left-col">
          <div className="ac-landscape-rail-tabs" role="tablist" aria-label="手机横屏侧栏切换">
            <button
              type="button"
              role="tab"
              aria-selected={leftRailTab === 'synergies'}
              className={leftRailTab === 'synergies' ? 'active' : ''}
              onClick={() => setLeftRailTab('synergies')}
            >
              羁绊
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={leftRailTab === 'standings'}
              className={leftRailTab === 'standings' ? 'active' : ''}
              onClick={() => setLeftRailTab('standings')}
            >
              战绩
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={leftRailTab === 'logs'}
              className={leftRailTab === 'logs' ? 'active' : ''}
              onClick={() => setLeftRailTab('logs')}
            >
              纪要
            </button>
          </div>

          <section className={'panel ac-rail-panel ' + (leftRailTab === 'synergies' ? 'ac-rail-active' : '')} style={{ padding: 12 }}>
            <h4 style={{ margin: '0 0 8px' }}>羁绊共鸣 ({p.board.length} 棋子)</h4>
            <div className="ac-syn-list">
              {p.synergies.length === 0 ? (
                <p className="muted" style={{ fontSize: '0.8rem', margin: 0 }}>
                  上阵棋子即可激活对应双轴羁绊。
                </p>
              ) : (
                [...p.synergies]
                  .sort((a, b) => (b.active_tier ? 1 : 0) - (a.active_tier ? 1 : 0) || b.count - a.count)
                  .map(s => (
                    <div key={s.id} className={'ac-syn-row ' + (s.active_tier ? 'lit' : '')} title={s.desc}>
                      <div className="ac-syn-head">
                        <span>
                          {s.icon} {s.name}
                        </span>
                        <span>
                          {s.count}/{s.next_tier || s.max_tier}
                        </span>
                      </div>
                      <div className="ac-syn-desc">{s.active_tier ? s.active_tier.label : s.desc}</div>
                    </div>
                  ))
              )}
            </div>
            {p.augments.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <strong style={{ fontSize: '0.8rem' }}>已选星序祝福</strong>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {p.augments.map(a => (
                    <span key={a.id} className="ac-stat-chip" style={{ fontSize: '0.72rem' }} title={a.desc}>
                      🌟 {a.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className={'panel ac-rail-panel ' + (leftRailTab === 'standings' ? 'ac-rail-active' : '')} style={{ padding: 12 }}>
            <h4 style={{ margin: '0 0 8px' }}>
              {activeMatch.mode === 'pvp_room'
                ? '联机战绩榜 (点击观战)'
                : activeMatch.mode === 'ranked'
                ? '8人排位战绩榜'
                : activeMatch.mode === 'lobby4'
                ? '4人战绩榜'
                : '指挥官状态'}
            </h4>
            <div className={'ac-standings ' + (activeMatch.commanders.length > 4 ? 'ac-standings-8p' : '')}>
              {activeMatch.commanders.map(c => {
                const isMe = isPvpRoom ? c.id === room?.my_commander_id : c.is_human;
                const canSpectate = isPvpRoom && activeMatch.phase !== 'prep' && !c.eliminated;
                const activeWatch = activeMatch.watching_cid === c.id;
                return (
                  <div
                    key={c.id}
                    onClick={() => canSpectate && void handleSpectate(c.id)}
                    style={{ cursor: canSpectate ? 'pointer' : 'default' }}
                    className={
                      'ac-cmd-row ' +
                      (isMe ? 'me ' : '') +
                      (c.eliminated ? 'dead ' : '') +
                      (activeWatch ? 'watching' : '')
                    }
                  >
                    <div className="ac-cmd-top">
                      <span>
                        {c.placement ? `#${c.placement} ` : ''}
                        {c.name}
                        {c.is_human && activeMatch.phase === 'prep' && c.ready ? ' ✅' : ''}
                      </span>
                      <span>{c.hp} HP</span>
                    </div>
                    <div className="ac-cmd-sub">
                      <span>
                        Lv.{c.level} ({c.board_count}/{c.max_pop}) · {c.gold}G
                        {!c.is_human && c.ai_style_label && (c.eliminated || activeMatch.phase === 'finished')
                          ? ` · ${c.ai_style_label}`
                          : ''}
                      </span>
                      <span>
                        {c.wins}胜 {c.losses}负
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className={'panel ac-rail-panel ' + (leftRailTab === 'logs' ? 'ac-rail-active' : '')} style={{ padding: 12 }}>
            <h4 style={{ margin: '0 0 6px' }}>对局纪要</h4>
            <div className="ac-logs">
              {[...activeMatch.logs].reverse().map((ln, idx) => (
                <div key={idx}>{ln}</div>
              ))}
            </div>
          </section>
        </aside>

        {/* Center column: Board, Telemetry, Bench, Shop */}
        <main className="ac-center-col">
          <section className="panel ac-board-panel">
            <div className="ac-board-toolbar">
              <div className="ac-legend">
                <span>
                  <i style={{ background: '#5b46e8', border: '1px solid #8b7dff' }} /> 友方分队环(左侧)
                </span>
                <span>
                  <i style={{ background: '#df4e3b', border: '1px solid #ff7b6b' }} /> 敌方分队环(右侧)
                </span>
                <span>
                  <i style={{ background: '#4b5563' }} /> 墙体障碍
                </span>
                <span>
                  <i style={{ background: '#d1fae5', border: '1px solid #10b981' }} /> 掩体
                </span>
                <span>
                  <i style={{ background: '#e0f2fe', border: '1px solid #0284c7' }} /> 灵脉
                </span>
              </div>
              <div className="ac-hud-group">
                {activeMatch.phase === 'prep' && (
                  <>
                    <span>布局剩余 {remaining} 秒</span>
                    <button
                      className="button subtle"
                      disabled={busy || !p.board.length}
                      onClick={() => void act('auto_arrange')}
                    >
                      <Wand2 size={14} /> 一键布阵
                    </button>
                    {isPvpRoom ? (
                      <button
                        className={`button ${p.ready ? 'subtle' : 'primary'}`}
                        disabled={busy}
                        onClick={() => void act('ready_combat', { ready: !p.ready })}
                      >
                        <Swords size={15} /> {p.ready ? '已就绪 (点击取消)' : '锁定布阵准备开战'}
                      </button>
                    ) : (
                      <button
                        className="button primary"
                        disabled={busy || (p.board.length === 0 && p.bench.length === 0)}
                        onClick={() => void act('start_combat')}
                      >
                        <Swords size={15} /> 开战！
                      </button>
                    )}
                  </>
                )}
                {activeMatch.phase === 'combat' && !isPvpRoom && (
                  <>
                    <button className="button subtle" onClick={() => setSpeed(v => (v === 8 ? 1 : v * 2))}>
                      <FastForward size={14} /> 倍率调节 {speed}x
                    </button>
                    <button className="button subtle" onClick={() => setAutoPlay(v => !v)}>
                      {autoPlay ? (
                        <>
                          <Pause size={14} /> 暂停
                        </>
                      ) : (
                        <>
                          <Play size={14} /> 自动播放
                        </>
                      )}
                    </button>
                    <button className="button primary" disabled={busy} onClick={resolveCombat}>
                      <FastForward size={14} /> 直接结算
                    </button>
                  </>
                )}
                {activeMatch.phase === 'combat' && isPvpRoom && (
                  <>
                    <span className="muted" style={{ fontSize: '0.82rem' }}>
                      服务端同步演算中…
                    </span>
                    <button className="button subtle" disabled={busy} onClick={() => void act('resolve_combat')}>
                      <FastForward size={14} /> 跳过动画结算
                    </button>
                  </>
                )}
                {activeMatch.phase === 'round_result' && (
                  <>
                    <button
                      className={`button ${isPvpRoom && p.next_ready ? 'subtle' : 'primary'}`}
                      disabled={busy}
                      onClick={() =>
                        isPvpRoom
                          ? void act('ready_next', { ready: !p.next_ready })
                          : void act('next_round')
                      }
                    >
                      {isPvpRoom
                        ? p.next_ready
                          ? '已确认下一回合，等待其他玩家…'
                          : `准备进入第 ${activeMatch.round_num + 1} 回合 →`
                        : `跳过结算，进入第 ${activeMatch.round_num + 1} 回合 →`}
                    </button>
                    {activeMatch.last_round_report && (
                      <button
                        type="button"
                        className="button subtle ac-landscape-tel-toggle"
                        onClick={() => setShowTelemetryMobile(v => !v)}
                      >
                        {showTelemetryMobile ? '收起战报' : '本轮战报'}
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>

            <div className="ac-board-scroll">
              <svg
                className="ac-board-svg"
                style={{ '--ac-cols': boardW } as CSSProperties}
                viewBox={`0 0 ${svgW} ${svgH}`}
                role="img"
                aria-label="自走棋战场棋盘"
              >
                <defs>
                  <clipPath id="ac-clip-unit" clipPathUnits="objectBoundingBox">
                    <circle cx="0.5" cy="0.5" r="0.5" />
                  </clipPath>
                  <filter id="ac-emblem-light">
                    <feColorMatrix
                      type="matrix"
                      values="0 0 0 0 0.97  0 0 0 0 0.95  0 0 0 0 1  0 0 0 1 0"
                    />
                  </filter>
                </defs>

                {/* Column letters */}
                {Array.from({ length: boardW }, (_, c) => (
                  <text
                    key={`col_${c}`}
                    x={padL + c * cellSize + cellSize / 2}
                    y={15}
                    textAnchor="middle"
                    fontSize={11}
                    fill="#6b7280"
                    fontWeight={600}
                  >
                    {String.fromCharCode(65 + c)}
                  </text>
                ))}
                {/* Row numbers */}
                {Array.from({ length: boardH }, (_, r) => (
                  <text
                    key={`row_${r}`}
                    x={12}
                    y={padT + r * cellSize + cellSize / 2 + 4}
                    textAnchor="middle"
                    fontSize={11}
                    fill="#6b7280"
                    fontWeight={600}
                  >
                    {r + 1}
                  </text>
                ))}

                {/* Grid Cells */}
                {Array.from({ length: boardH }, (_, r) =>
                  Array.from({ length: boardW }, (_, c) => {
                    const coord = formatCoord(c, r);
                    const x = padL + c * cellSize;
                    const y = padT + r * cellSize;
                    const t = terrain[coord];
                    const isDeployY = activeMatch.phase === 'prep' && deployColsY.has(c) && t !== 'wall';
                    const inSelectedRange =
                      activeMatch.phase === 'prep' &&
                      selectedOrigin !== null &&
                      selectedOwned !== null &&
                      Math.max(Math.abs(selectedOrigin[0] - c), Math.abs(selectedOrigin[1] - r)) <=
                        (selectedOwned.range || 2);

                    let fill = (c + r) % 2 === 0 ? '#faf9ff' : '#f3f1fb';
                    if (t === 'wall') fill = '#4b5563';
                    else if (t === 'cover') fill = '#d1fae5';
                    else if (t === 'leyline') fill = '#e0f2fe';
                    else if (isDeployY) fill = (c + r) % 2 === 0 ? '#f3efff' : '#ebe4ff';

                    const prepUnit =
                      activeMatch.phase === 'prep' ? p.board.find(u => u.coord === coord) : undefined;
                    return (
                      <g
                        key={coord}
                        onClick={() => onBoardCellClick(coord, prepUnit)}
                        style={{ cursor: isDeployY || prepUnit ? 'pointer' : 'default' }}
                      >
                        <rect
                          x={x + 1}
                          y={y + 1}
                          width={cellSize - 2}
                          height={cellSize - 2}
                          rx={6}
                          fill={fill}
                          stroke={inSelectedRange ? '#f59e0b' : isDeployY ? '#c4b5fd' : '#e2dff0'}
                          strokeWidth={inSelectedRange ? 1.8 : 1}
                        />
                        {t && (
                          <text
                            x={x + 6}
                            y={y + 13}
                            fontSize={9}
                            fontWeight={700}
                            fill={t === 'wall' ? '#e5e7eb' : t === 'cover' ? '#047857' : '#0369a1'}
                          >
                            {t === 'wall' ? '墙' : t === 'cover' ? '掩' : '灵'}
                          </text>
                        )}
                      </g>
                    );
                  }),
                )}

                {/* Prep phase player pieces with smooth glide & star-up burst */}
                {activeMatch.phase === 'prep' &&
                  p.board.map(u => {
                    const pt = u.coord ? parseCoordStr(u.coord) : null;
                    if (!pt) return null;
                    const cx = padL + pt[0] * cellSize + cellSize / 2;
                    const cy = padT + pt[1] * cellSize + cellSize / 2;
                    return (
                      <g
                        key={u.id}
                        className="ac-board-unit ac-unit-group"
                        style={{ transform: `translate(${cx}px, ${cy}px)` }}
                        data-ac-serial={u.serial}
                        onMouseEnter={e => hoverWiki.startHover(u.serial, u.star, e.currentTarget)}
                        onMouseLeave={hoverWiki.leaveTarget}
                        onClick={e => {
                          e.stopPropagation();
                          hoverWiki.closeNow();
                          onBoardCellClick(u.coord!, u);
                        }}
                      >
                        {renderUnitToken(
                          u.serial,
                          u.name,
                          'Y',
                          u.star,
                          1,
                          0,
                          u.serial === 'Y5' || u.serial === 'Y13',
                          selectedId === u.id,
                          false,
                          false,
                          starUpIds[u.id] ? 'ac-token-starup' : '',
                        )}
                      </g>
                    );
                  })}

                {/* Combat / Round-Result snapshot units with smooth glide, attack lunge, hit shake */}
                {activeMatch.phase !== 'prep' &&
                  activeMatch.live_snapshot?.units.map((u: AutoChessCombatUnit) => {
                    const pt = u.coord ? parseCoordStr(u.coord) : null;
                    if (!pt || (u.hp <= 0 && !u.dying)) return null;
                    const cx = padL + pt[0] * cellSize + cellSize / 2;
                    const cy = padT + pt[1] * cellSize + cellSize / 2;
                    const starCount = u.name.match(/★/g)?.length || 1;
                    const canWiki = !u.is_summon && Boolean(u.serial);
                    const motionCls = actingUids.has(u.uid)
                      ? u.team === 'Y'
                        ? 'ac-token-lunge'
                        : 'ac-token-lunge-left'
                      : hitUids.has(u.uid)
                      ? 'ac-token-hit'
                      : '';
                    return (
                      <g
                        key={u.uid}
                        className={`${canWiki ? 'ac-board-unit ' : ''}ac-unit-group`}
                        style={{ transform: `translate(${cx}px, ${cy}px)` }}
                        data-ac-serial={canWiki ? u.serial : undefined}
                        onMouseEnter={
                          canWiki ? e => hoverWiki.startHover(u.serial, starCount, e.currentTarget) : undefined
                        }
                        onMouseLeave={canWiki ? hoverWiki.leaveTarget : undefined}
                      >
                        <title>{`${u.name} (${u.coord}) HP ${u.hp}/${u.max_hp} 护盾 ${u.shield} MP ${u.mp}`}</title>
                        {renderUnitToken(
                          u.serial,
                          u.name.replace(/★+/g, ''),
                          u.team,
                          starCount,
                          u.hp / Math.max(1, u.max_hp),
                          u.shield,
                          u.flying,
                          latestFrame?.actor_uid === u.uid,
                          u.dying,
                          u.is_summon,
                          motionCls,
                        )}
                      </g>
                    );
                  })}

                {/* Dynamic Skill VFX, Movement Trails & Floating Damage/Heal Popups */}
                {activeMatch.phase !== 'prep' && (
                  <AutoChessVfxLayer
                    events={latestVfxEvents}
                    frameKey={frameSeq}
                    cellCenter={cellCenter}
                  />
                )}
              </svg>
            </div>

            {/* AI Intent / Battle playback banner */}
            {activeMatch.phase !== 'prep' && latestFrame && (
              <div className="ac-intent-bar">
                <div>
                  <strong>
                    [R{latestFrame.round} · {latestFrame.actor_name}]
                  </strong>{' '}
                  {latestFrame.reason || latestFrame.lines[0] || '行动演算'}
                </div>
                {activeMatch.live_snapshot &&
                  activeMatch.live_snapshot.round >= activeMatch.live_snapshot.overtime_start_round && (
                    <span className="ac-stat-chip hp">⚡ 加时决战：伤害升级 / 治疗衰减</span>
                  )}
              </div>
            )}

            {/* Prep Selected Unit Inspector */}
            {activeMatch.phase === 'prep' && selectedOwned && (
              <div className="ac-inspector">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {renderMiniToken(selectedOwned.serial, selectedOwned.name, 'Y')}
                  <div>
                    <strong>
                      {selectedOwned.name} ({'★'.repeat(selectedOwned.star)})
                    </strong>{' '}
                    · {selectedOwned.cost}费 · {ROLE_LABELS[selectedOwned.role] || selectedOwned.role} · 射程{' '}
                    {selectedOwned.range} · [{selectedOwned.traits.join(' / ')}]
                  </div>
                </div>
                <div className="ac-hud-group">
                  {(['aggressive', 'balanced', 'defensive'] as const).map(st => (
                    <button
                      key={st}
                      className={'button ' + (selectedOwned.stance === st ? 'primary' : 'subtle')}
                      disabled={busy}
                      onClick={() => void act('set_stance', { unit_id: selectedOwned.id, stance: st })}
                    >
                      姿态:{STANCE_LABELS[st]}
                    </button>
                  ))}
                  <select
                    aria-label="替换成员"
                    value=""
                    disabled={busy || !(selectedOwned.location === 'board' ? p.bench : p.board).length}
                    onChange={e => void act('swap', { unit_a: selectedOwned.id, unit_b: e.target.value })}
                  >
                    <option value="" disabled>
                      替换成员
                    </option>
                    {(selectedOwned.location === 'board' ? p.bench : p.board).map(u => (
                      <option key={u.id} value={u.id}>
                        {u.name} {'★'.repeat(u.star)} · {u.coord || `备战席 ${(u.bench_idx ?? 0) + 1}`}
                      </option>
                    ))}
                  </select>
                  {selectedOwned.location === 'board' ? (
                    <button
                      className="button subtle"
                      disabled={busy}
                      onClick={() => {
                        void act('recall', { unit_id: selectedOwned.id });
                        setSelectedId(null);
                      }}
                    >
                      撤回备战席
                    </button>
                  ) : (
                    <button
                      className="button subtle"
                      disabled={busy}
                      onClick={() => {
                        void act('deploy', { unit_id: selectedOwned.id });
                        setSelectedId(null);
                      }}
                    >
                      上阵到空位
                    </button>
                  )}
                  <button
                    className="button subtle"
                    disabled={busy}
                    onClick={() => onOpenTokenEditor?.(selectedOwned.serial)}
                  >
                    <ImageIcon size={14} /> 换头图
                  </button>
                  <button
                    className="button subtle"
                    disabled={busy}
                    onClick={() => {
                      hoverWiki.closeNow();
                      setWikiTarget({ tab: 'units', serial: selectedOwned.serial });
                    }}
                  >
                    <BookOpen size={14} /> 查看百科
                  </button>
                  <button
                    className="button subtle"
                    disabled={busy}
                    onClick={() => {
                      void act('sell', { unit_id: selectedOwned.id });
                      setSelectedId(null);
                    }}
                  >
                    出售 (+{sellValue(selectedOwned.cost, selectedOwned.star)}G)
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* Post-Round Telemetry & MVP */}
          {activeMatch.last_round_report &&
            (activeMatch.phase === 'round_result' || activeMatch.phase === 'finished') && (
              <section
                className={
                  'panel ac-telemetry-panel ' +
                  (showTelemetryMobile ? 'ac-tel-mobile-open' : '')
                }
                style={{ padding: 12 }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: 8,
                  }}
                >
                  <h4 style={{ margin: 0 }}>
                    {activeMatch.phase === 'finished'
                      ? `🏆 对局总结 · 第 ${p.placement || 1} 名`
                      : `第 ${activeMatch.last_round_report.round} 回合战报：${
                          activeMatch.last_round_report.won
                            ? '✅ 胜利'
                            : `❌ 落败 (-${activeMatch.last_round_report.hp_damage} HP)`
                        } · 对阵 ${activeMatch.last_round_report.opponent_name} (${activeMatch.last_round_report.battle_rounds}轮)`}
                  </h4>
                  {activeMatch.phase === 'finished' && activeMatch.mode === 'ranked' && activeMatch.ranked_settlement && (
                    <button
                      type="button"
                      className="button primary compact-button"
                      onClick={() => setRankedSettlement(activeMatch.ranked_settlement || null)}
                    >
                      <Trophy size={14} /> 查看排位结算明细
                    </button>
                  )}
                  {activeMatch.last_round_report.mvp && (
                    <span className="ac-stat-chip gold">
                      <Award size={14} /> MVP：{activeMatch.last_round_report.mvp.name}（伤害{' '}
                      {activeMatch.last_round_report.mvp.dmg_dealt} / 治疗{' '}
                      {activeMatch.last_round_report.mvp.heal_done}）
                    </span>
                  )}
                </div>
                <div className="ac-report-grid">
                  {(() => {
                    const rows = activeMatch.last_round_report.telemetry;
                    const maxVal = Math.max(
                      1,
                      ...rows.map(r => Math.max(r.dmg_dealt, r.dmg_taken, r.heal_done)),
                    );
                    return rows.map(r => (
                      <div key={r.uid} className="ac-tel-card">
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700 }}>
                          <span>
                            {r.team === 'Y' ? '🟦' : '🟥'} {r.name}
                          </span>
                          <span>{r.kills > 0 ? `${r.kills}击杀` : r.alive ? '存活' : '阵亡'}</span>
                        </div>
                        <div className="muted" style={{ fontSize: '0.74rem' }}>
                          输出 {r.dmg_dealt} · 治疗 {r.heal_done} · 承伤 {r.dmg_taken}
                        </div>
                        <div className="ac-tel-bar-wrap">
                          <div
                            className="ac-tel-bar"
                            style={{ width: `${(r.dmg_dealt / maxVal) * 100}%`, background: '#ef4444' }}
                          />
                        </div>
                        <div className="ac-tel-bar-wrap">
                          <div
                            className="ac-tel-bar"
                            style={{ width: `${(r.heal_done / maxVal) * 100}%`, background: '#22c55e' }}
                          />
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              </section>
            )}

          {/* Bench */}
          <section className="panel ac-bench-panel" style={{ padding: 12 }}>
            <div className="ac-section-head" style={{ marginBottom: 6 }}>
              <strong>
                备战席 ({p.bench.length}/{benchCapacity})
              </strong>
              <span className="muted ac-bench-hint" style={{ fontSize: '0.78rem' }}>
                点击棋子后点击紫色部署区即可上阵；同类 3 枚自动合成高星
              </span>
            </div>
            <div className="ac-bench-row">
              {benchSlots.map((u, idx) =>
                u ? (
                  <button
                    key={u.id}
                    type="button"
                    data-ac-serial={u.serial}
                    className={
                      'ac-bench-slot filled ' +
                      (selectedId === u.id ? 'selected ' : '') +
                      (starUpIds[u.id] ? 'ac-token-starup' : '')
                    }
                    onMouseEnter={e => hoverWiki.startHover(u.serial, u.star, e.currentTarget)}
                    onMouseLeave={hoverWiki.leaveTarget}
                    onClick={() => {
                      hoverWiki.closeNow();
                      setSelectedId(selectedId === u.id ? null : u.id);
                    }}
                  >
                    <div className="ac-bench-head">
                      <span className="ac-bench-name">
                        {renderMiniToken(u.serial, u.name, 'Y')}
                        <span>{u.name}</span>
                      </span>
                      <span>{'★'.repeat(u.star)}</span>
                    </div>
                    <small className="muted">
                      {u.cost}费 · {ROLE_LABELS[u.role] || u.role} · 射程{u.range}
                    </small>
                    <small className="muted">{u.traits.join(' / ')}</small>
                  </button>
                ) : idx >= benchCapacity ? (
                  <div
                    key={`locked_${idx}`}
                    className="ac-bench-slot locked"
                    title="栏位未解锁"
                    aria-label={`备战席 ${idx + 1} 未解锁`}
                  >
                    <Lock size={16} aria-hidden="true" />
                  </div>
                ) : (
                  <div key={`empty_${idx}`} className="ac-bench-slot">
                    <span className="muted">空位 {idx + 1}</span>
                  </div>
                ),
              )}
            </div>
          </section>

          {/* Shop (5 slots) */}
          <section className="panel ac-shop-panel" style={{ padding: 12 }}>
            <div className="ac-shop-body">
              <div className="ac-shop-controls">
                <strong>星序招募商店</strong>
                <div className="ac-hud-group">
                  <button
                    className="button subtle"
                    disabled={busy || activeMatch.phase !== 'prep' || p.xp_to_next <= 0 || p.gold < 4}
                    onClick={() => void act('buy_xp')}
                  >
                    购买经验 +4XP (4G)
                  </button>
                  <button
                    className="button subtle"
                    disabled={busy || activeMatch.phase !== 'prep' || (p.gold < 2 && p.free_rerolls <= 0)}
                    onClick={() => void act('reroll')}
                  >
                    <RefreshCw size={14} /> {p.free_rerolls > 0 ? `免费刷新 (${p.free_rerolls})` : '刷新商店 (2G)'}
                  </button>
                  <button
                    className="button subtle"
                    disabled={busy || activeMatch.phase !== 'prep'}
                    onClick={() => void act('lock_shop')}
                  >
                    {p.shop_locked ? (
                      <>
                        <Lock size={14} /> 已锁定
                      </>
                    ) : (
                      <>
                        <Unlock size={14} /> 锁定商店
                      </>
                    )}
                  </button>
                </div>
              </div>

              <div className="ac-shop-row">
              {p.shop.map((slot, idx) =>
                slot ? (
                  <div
                    key={idx}
                    className="ac-shop-slot-wrap"
                    data-ac-serial={slot.serial}
                    onMouseEnter={e => {
                      if (!slot.bought) hoverWiki.startHover(slot.serial, 1, e.currentTarget);
                    }}
                    onMouseLeave={hoverWiki.leaveTarget}
                  >
                    <button
                      type="button"
                      disabled={busy || activeMatch.phase !== 'prep' || slot.bought || p.gold < slot.cost}
                      className={`ac-shop-card cost-${slot.cost} ${slot.bought ? 'bought' : ''}`}
                      onClick={() => {
                        hoverWiki.closeNow();
                        void act('buy', { slot_index: slot.slot_index });
                      }}
                    >
                      {slot.hint && !slot.bought && <span className="ac-shop-hint">{slot.hint}</span>}
                      <div className="ac-shop-top">
                        <span className="ac-shop-name-wrap">
                          {renderMiniToken(slot.serial, slot.name, 'Y')}
                          <span>{slot.name}</span>
                        </span>
                        <span>{slot.cost}G</span>
                      </div>
                      <div className="ac-shop-traits">
                        {slot.traits.map(t => (
                          <span key={t}>{t}</span>
                        ))}
                        <span>{ROLE_LABELS[slot.role] || slot.role}</span>
                      </div>
                      <small className="muted" style={{ fontSize: '0.73rem', lineHeight: 1.3 }}>
                        {slot.tag} · {slot.blurb}
                      </small>
                    </button>
                  </div>
                ) : (
                  <div key={idx} className="ac-shop-card bought">
                    <span className="muted">牌库已空</span>
                  </div>
                ),
              )}
              </div>
            </div>
          </section>
        </main>
      </div>

      {/* Round Augment 3-Choose-1 Modal */}
      {p.pending_augments.length > 0 && (
        <div className="modal-scrim">
          <section className="modal wide" role="dialog" aria-modal="true" aria-label="星序祝福三选一">
            <header>
              <h2>🌟 第 {activeMatch.round_num} 回合 · 选择星序祝福</h2>
            </header>
            <p className="muted">剩余 {remaining} 秒，超时自动选择第一项祝福。</p>
            <div className="ac-aug-choices">
              {p.pending_augments.map(aug => (
                <button
                  key={aug.id}
                  type="button"
                  className="ac-aug-card"
                  disabled={busy}
                  onClick={() => void act('pick_augment', { augment_id: aug.id })}
                >
                  <div style={{ fontSize: '0.76rem', color: '#6d4aff', fontWeight: 700 }}>
                    {aug.tier || '星序祝福'}
                  </div>
                  <strong style={{ display: 'block', margin: '4px 0', fontSize: '1rem' }}>{aug.name}</strong>
                  <p style={{ margin: 0, fontSize: '0.84rem', color: '#374151', lineHeight: 1.4 }}>{aug.desc}</p>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      {activeMatch.phase === 'finished' && activeMatch.mode === 'ranked' && !activeMatch.last_round_report && activeMatch.ranked_settlement && (
        <section className="panel" style={{ padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <strong>🏆 排位赛已结算 · 第 {p.placement || 8} 名（{activeMatch.ranked_settlement.net_delta >= 0 ? '+' : ''}{activeMatch.ranked_settlement.net_delta} 积分）</strong>
          <button
            type="button"
            className="button primary compact-button"
            onClick={() => setRankedSettlement(activeMatch.ranked_settlement || null)}
          >
            <Trophy size={14} /> 查看排位结算明细
          </button>
        </section>
      )}

      <AutoChessRankedSummaryModal
        settlement={rankedSettlement}
        onClose={() => setRankedSettlement(null)}
        onPlayAgain={() => {
          setRankedSettlement(null);
          void handleCreateRanked();
        }}
        onOpenLeaderboard={() => {
          setRankedSettlement(null);
          onOpenLeaderboard?.();
        }}
        onBackToLobby={() => {
          setRankedSettlement(null);
          setRoom(null);
          setMatch(null);
          void refreshLobby();
        }}
      />

      {wikiOverlays}
    </div>
  );
}
