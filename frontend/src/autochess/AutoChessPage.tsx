import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  Award,
  BookOpen,
  CircleHelp,
  Coins,
  Compass,
  FastForward,
  Heart,
  Lock,
  Pause,
  Play,
  RefreshCw,
  Sparkles,
  Swords,
  Trash2,
  Unlock,
  Wand2,
  X,
} from 'lucide-react';
import {
  createAutoChessMatch,
  deleteAutoChessMatch,
  fetchAutoChessCatalog,
  getAutoChessMatch,
  listAutoChessMatches,
  sendAutoChessAction,
} from './api';
import { AutoChessWikiModal } from './AutoChessWikiModal';
import { AutoChessWikiPopover } from './AutoChessWikiPopover';
import './autochess.css';
import {
  AUTOCHESS_ROLE_LABELS,
  type AutoChessCatalog,
  type AutoChessCombatUnit,
  type AutoChessMatchState,
  type AutoChessMatchSummary,
  type AutoChessOwnedUnit,
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
  return `${String.fromCharCode(65 + col)}${row + 1}`;
}

function sellValue(cost: number, star: number): number {
  if (star <= 1) return cost;
  return Math.max(cost, Math.round(cost * 3 ** (star - 1) * 0.7));
}

export function AutoChessPage({
  playerName,
  onPlayerNameChange,
  wikiOpenNonce = 0,
  onError,
}: {
  playerName: string;
  onPlayerNameChange?: (name: string) => Promise<void> | void;
  wikiOpenNonce?: number;
  onError: (msg: string) => void;
}) {
  const [catalog, setCatalog] = useState<AutoChessCatalog | null>(null);
  const [matches, setMatches] = useState<AutoChessMatchSummary[]>([]);
  const [match, setMatch] = useState<AutoChessMatchState | null>(null);
  const [mode, setMode] = useState<'lobby4' | 'pve12'>('lobby4');
  const [arenaPreset, setArenaPreset] = useState<string>('autochess_standard');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [autoPlay, setAutoPlay] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [now, setNow] = useState(Date.now);
  const [wikiTarget, setWikiTarget] = useState<AutoChessWikiTarget | null>(null);
  const [nameDraft, setNameDraft] = useState(playerName);
  const hoverWiki = useHoverWiki();
  const inFlight = useRef(false);
  const resolveAfterStep = useRef(false);

  useEffect(() => {
    setNameDraft(playerName);
  }, [playerName]);

  useEffect(() => {
    hoverWiki.closeNow();
  }, [match?.id, match?.phase, match?.round_num, hoverWiki.closeNow]);
  // Older servers omit the deadline. Keep one local deadline throughout preparation.
  const prepDeadline = useMemo(() => {
    if (match?.phase !== 'prep') return null;
    const deadline = match.prep_deadline;
    return typeof deadline === 'number' && Number.isFinite(deadline) && deadline > 0
      ? deadline * 1000
      : Date.now() + 30_000;
  }, [match?.id, match?.round_num, match?.phase, match?.prep_deadline]);
  const remaining = prepDeadline === null ? 0 : Math.min(30, Math.max(0, Math.ceil((prepDeadline - now) / 1000)));

  const refreshLobby = async () => {
    try {
      const [cat, list] = await Promise.all([
        catalog ? Promise.resolve(catalog) : fetchAutoChessCatalog(),
        listAutoChessMatches(playerName),
      ]);
      setCatalog(cat);
      setMatches(list);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  useEffect(() => {
    void refreshLobby();
  }, []);

  useEffect(() => {
    if (match?.phase !== 'prep') return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [match?.id, match?.round_num, match?.phase]);

  useEffect(() => {
    if (!match || busy) return;
    let action: string;
    let delay: number;
    let payload: Record<string, unknown> = {};
    if (match.phase === 'prep' && remaining === 0) {
      const firstAugment = match.player.pending_augments[0];
      action = firstAugment ? 'pick_augment' : 'start_combat';
      if (firstAugment) payload = { augment_id: firstAugment.id };
      delay = 250;
    } else if (match.phase === 'combat' && autoPlay) {
      action = 'step_combat';
      delay = 520 / speed;
    } else if (match.phase === 'round_result') {
      action = 'next_round';
      delay = 15_000;
    } else return;
    const timer = window.setTimeout(() => void act(action, payload, true), delay);
    return () => window.clearTimeout(timer);
  }, [match, busy, remaining, autoPlay, speed]);

  const act = async (action: string, payload: Record<string, unknown> = {}, silent = false) => {
    if (!match || inFlight.current) return;
    inFlight.current = true;
    if (action !== 'step_combat') setBusy(true);
    try {
      let res = await sendAutoChessAction(match.id, action, payload, playerName);
      if (action === 'step_combat' && resolveAfterStep.current && res.match.phase === 'combat') {
        res = await sendAutoChessAction(match.id, 'resolve_combat', {}, playerName);
      }
      setMatch(current => current?.id === match.id ? res.match : current);
      if (res.message && (!silent || !res.ok)) setNotice(res.message);
      if (res.match.phase !== 'combat' || match.phase !== 'combat') setAutoPlay(true);
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
      setMatch(created);
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

  const handleLoad = async (id: string) => {
    setBusy(true);
    try {
      const loaded = await getAutoChessMatch(id, playerName);
      setMatch(loaded);
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

  const selectedOwned: AutoChessOwnedUnit | null = useMemo(() => {
    if (!match || !selectedId) return null;
    return (
      match.player.board.find(u => u.id === selectedId) ||
      match.player.bench.find(u => u.id === selectedId) ||
      null
    );
  }, [match, selectedId]);

  useEffect(() => {
    if (!wikiOpenNonce) return;
    hoverWiki.closeNow();
    setWikiTarget({
      tab: 'units',
      serial: selectedOwned?.serial || catalog?.units[0]?.serial || 'Y1',
    });
  }, [wikiOpenNonce]);

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

  if (!match) {
    return (
      <div className="page ac-page">
        <div className="page-intro">
          <div>
            <div className="eyebrow">STARLIGHT AUTO-CHESS · SPATIAL EDITION</div>
            <h1>星序自走棋</h1>
            <p>
              独立空间自走棋工作台：对称地形、切比雪夫真射程、BFS 地形卡位、经济利息与三合一升星。
            </p>
          </div>
          <div className="ac-lobby-actions">
            {onPlayerNameChange && (
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
                  placeholder="指挥官称呼"
                  onChange={e => setNameDraft(e.target.value)}
                />
                <button type="submit" className="button subtle compact-button" disabled={busy || !nameDraft.trim()}>
                  改名
                </button>
              </form>
            )}
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

        <div className="ac-lobby-grid">
          <section className="panel" style={{ padding: 16 }}>
            <h3>创建新对局</h3>
            <div className="ac-mode-pills">
              <button
                type="button"
                className={'ac-mode-pill ' + (mode === 'lobby4' ? 'active' : '')}
                onClick={() => setMode('lobby4')}
              >
                <strong>4 人 AI 锦标大厅</strong>
                <small>与 3 名策略各异的 AI 指挥官争夺第一名，第 4/8 回合可选星序祝福</small>
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
              <Sparkles size={16} /> 开启自走棋对局
            </button>
          </section>

          <section className="panel" style={{ padding: 16 }}>
            <div className="ac-section-head" style={{ marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>SQLite 存档对局</h3>
              <button className="button subtle" onClick={() => void refreshLobby()}>
                <RefreshCw size={14} /> 刷新
              </button>
            </div>
            {!matches.length ? (
              <p className="muted">暂无已保存对局，左侧创建后将自动持久化保存，支持刷新重连。</p>
            ) : (
              <div className="ac-saved-list">
                {matches.map(m => (
                  <div key={m.id} className="ac-saved-item">
                    <div>
                      <strong>{m.mode === 'lobby4' ? '4人锦标大厅' : '12波试炼'}</strong>
                      <div className="muted" style={{ fontSize: '0.78rem' }}>
                        第 {m.round_num} 回合 · HP {m.hp} · {m.phase === 'finished' ? '已结束' : '进行中'} · {m.arena_preset}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="button subtle" disabled={busy} onClick={() => void handleLoad(m.id)}>
                        继续
                      </button>
                      <button className="button subtle" title="删除存档" disabled={busy} onClick={() => void handleDelete(m.id)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {wikiOverlays}
      </div>
    );
  }

  const p = match.player;
  const boardW = match.live_snapshot?.width || match.map.width;
  const boardH = match.live_snapshot?.height || match.map.height;
  const terrain = match.live_snapshot?.terrain || match.map.terrain || {};
  const deployColsY = new Set((match.live_snapshot?.deploy_cols || match.map.deploy_cols)?.Y || []);
  const latestFrame = match.combat_frames[match.combat_frames.length - 1] || null;
  const curInterest = Math.min(p.max_interest, Math.floor(p.gold / 10));
  const selectedCoord = selectedOwned?.location === 'board' ? selectedOwned.coord : null;
  const selectedOrigin = selectedCoord ? parseCoordStr(selectedCoord) : null;

  const cellSize = boardW >= 12 ? 50 : boardW >= 10 ? 58 : 64;
  const padL = 26;
  const padT = 22;
  const svgW = padL + boardW * cellSize + 10;
  const svgH = padT + boardH * cellSize + 12;

  const onBoardCellClick = (coord: string, unitAtCoord: AutoChessOwnedUnit | undefined) => {
    if (match.phase !== 'prep') return;
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
    cx: number,
    cy: number,
    label: string,
    team: 'Y' | 'X',
    star: number,
    hpPct: number,
    shield: number,
    flying: boolean,
    isSelected: boolean,
    isDying: boolean,
    isSummon: boolean,
  ) => {
    const fill = team === 'Y' ? '#6d4aff' : '#e05b47';
    const r = isSummon ? cellSize * 0.28 : cellSize * 0.34;
    return (
      <g style={{ cursor: match.phase === 'prep' ? 'pointer' : 'default' }}>
        {isSelected && (
          <circle cx={cx} cy={cy} r={r + 5} fill="none" stroke="#f59e0b" strokeWidth={3} strokeDasharray="4 2" />
        )}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill={isDying ? '#6b7280' : fill}
          fillOpacity={isSummon ? 0.82 : 0.94}
          stroke={star >= 3 ? '#facc15' : star === 2 ? '#e0e7ff' : '#fff'}
          strokeWidth={star >= 2 ? 2.5 : 1.5}
        />
        <text x={cx} y={cy + 4} textAnchor="middle" fill="#fff" fontSize={isSummon ? 10 : 11} fontWeight={700}>
          {label.slice(0, 4)}
        </text>
        {star > 1 && (
          <text x={cx} y={cy - r - 2} textAnchor="middle" fill="#b45309" fontSize={10} fontWeight={800}>
            {'★'.repeat(star)}
          </text>
        )}
        {flying && (
          <text x={cx + r - 2} y={cy - r + 8} textAnchor="middle" fill="#0284c7" fontSize={10} fontWeight={700}>
            ✈
          </text>
        )}
        {/* HP & Shield bar */}
        <rect x={cx - r} y={cy + r + 2} width={r * 2} height={5} rx={2} fill="#e5e7eb" />
        <rect
          x={cx - r}
          y={cy + r + 2}
          width={Math.max(0, Math.min(1, hpPct)) * r * 2}
          height={5}
          rx={2}
          fill={team === 'Y' ? '#22c55e' : '#ef4444'}
        />
        {shield > 0 && (
          <rect
            x={cx - r}
            y={cy + r + 2}
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

  return (
    <div className="page ac-page">
      {/* Top HUD */}
      <section className="panel ac-hud">
        <div className="ac-hud-group">
          <button className="button subtle" onClick={() => { setMatch(null); void refreshLobby(); }}>
            ← 大厅/换局
          </button>
          <span className="ac-stat-chip">
            <Compass size={14} /> 第 {match.round_num}{match.max_waves ? `/${match.max_waves}` : ''} 回合 ·{' '}
            {match.phase === 'prep'
              ? '备战布阵'
              : match.phase === 'combat'
              ? '战斗演算'
              : match.phase === 'round_result'
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
          <span className="muted" style={{ fontSize: '0.8rem' }}>
            {match.arena_name} · 公共牌库余 {match.pool_remaining} 张
          </span>
          <button className="button subtle" onClick={() => setWikiTarget({ tab: 'rules' })}>
            <CircleHelp size={15} /> 规则说明
          </button>
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

      <div className="ac-workspace">
        {/* Left column: Synergies + Standings + Logs */}
        <aside className="ac-left-col">
          <section className="panel" style={{ padding: 12 }}>
            <h4 style={{ margin: '0 0 8px' }}>羁绊共鸣 ({p.board.length} 棋子)</h4>
            <div className="ac-syn-list">
              {p.synergies.length === 0 ? (
                <p className="muted" style={{ fontSize: '0.8rem', margin: 0 }}>上阵棋子即可激活对应双轴羁绊。</p>
              ) : (
                [...p.synergies]
                  .sort((a, b) => (b.active_tier ? 1 : 0) - (a.active_tier ? 1 : 0) || b.count - a.count)
                  .map(s => (
                    <div key={s.id} className={'ac-syn-row ' + (s.active_tier ? 'lit' : '')} title={s.desc}>
                      <div className="ac-syn-head">
                        <span>{s.icon} {s.name}</span>
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

          <section className="panel" style={{ padding: 12 }}>
            <h4 style={{ margin: '0 0 8px' }}>
              {match.mode === 'lobby4' ? '4人战绩榜' : '指挥官状态'}
            </h4>
            <div className="ac-standings">
              {match.commanders.map(c => (
                <div
                  key={c.id}
                  className={
                    'ac-cmd-row ' +
                    (c.is_human ? 'me ' : '') +
                    (c.eliminated ? 'dead' : '')
                  }
                >
                  <div className="ac-cmd-top">
                    <span>
                      {c.placement ? `#${c.placement} ` : ''}
                      {c.name}
                    </span>
                    <span>{c.hp} HP</span>
                  </div>
                  <div className="ac-cmd-sub">
                    <span>Lv.{c.level} ({c.board_count}/{c.max_pop}) · {c.gold}G</span>
                    <span>{c.wins}胜 {c.losses}负</span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel" style={{ padding: 12 }}>
            <h4 style={{ margin: '0 0 6px' }}>对局纪要</h4>
            <div className="ac-logs">
              {[...match.logs].reverse().map((ln, idx) => (
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
                <span><i style={{ background: '#ede9fe', border: '1px solid #8b5cf6' }} /> 我方部署区</span>
                <span><i style={{ background: '#4b5563' }} /> 墙体障碍(飞行可越)</span>
                <span><i style={{ background: '#d1fae5', border: '1px solid #10b981' }} /> 掩体(远减15%/耗2移)</span>
                <span><i style={{ background: '#e0f2fe', border: '1px solid #0284c7' }} /> 灵脉(轮首+1MP)</span>
              </div>
              <div className="ac-hud-group">
                {match.phase === 'prep' && (
                  <>
                    <span>布局剩余 {remaining} 秒</span>
                    <button className="button subtle" disabled={busy || !p.board.length} onClick={() => void act('auto_arrange')}>
                      <Wand2 size={14} /> 一键布阵
                    </button>
                    <button
                      className="button primary"
                      disabled={busy || (p.board.length === 0 && p.bench.length === 0)}
                      onClick={() => void act('start_combat')}
                    >
                      <Swords size={15} /> 开战！
                    </button>
                  </>
                )}
                {match.phase === 'combat' && (
                  <>
                    <button className="button subtle" onClick={() => setSpeed(v => v === 8 ? 1 : v * 2)}>
                      <FastForward size={14} /> 倍率调节 {speed}x
                    </button>
                    <button className="button subtle" onClick={() => setAutoPlay(v => !v)}>
                      {autoPlay ? <><Pause size={14} /> 暂停</> : <><Play size={14} /> 自动播放</>}
                    </button>
                    <button className="button primary" disabled={busy} onClick={resolveCombat}>
                      <FastForward size={14} /> 直接结算
                    </button>
                  </>
                )}
                {match.phase === 'round_result' && (
                  <button className="button primary" disabled={busy} onClick={() => void act('next_round')}>
                    跳过结算，进入第 {match.round_num + 1} 回合 →
                  </button>
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
                  const isDeployY = match.phase === 'prep' && deployColsY.has(c) && t !== 'wall';
                  const inSelectedRange =
                    match.phase === 'prep' &&
                    selectedOrigin !== null &&
                    selectedOwned !== null &&
                    Math.max(Math.abs(selectedOrigin[0] - c), Math.abs(selectedOrigin[1] - r)) <=
                      (selectedOwned.range || 2);

                  let fill = (c + r) % 2 === 0 ? '#faf9ff' : '#f3f1fb';
                  if (t === 'wall') fill = '#4b5563';
                  else if (t === 'cover') fill = '#d1fae5';
                  else if (t === 'leyline') fill = '#e0f2fe';
                  else if (isDeployY) fill = (c + r) % 2 === 0 ? '#f3efff' : '#ebe4ff';

                  const prepUnit = match.phase === 'prep' ? p.board.find(u => u.coord === coord) : undefined;
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

              {/* Prep phase player pieces */}
              {match.phase === 'prep' &&
                p.board.map(u => {
                  const pt = u.coord ? parseCoordStr(u.coord) : null;
                  if (!pt) return null;
                  const cx = padL + pt[0] * cellSize + cellSize / 2;
                  const cy = padT + pt[1] * cellSize + cellSize / 2;
                  return (
                    <g
                      key={u.id}
                      className="ac-board-unit"
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
                        cx,
                        cy,
                        u.name,
                        'Y',
                        u.star,
                        1,
                        0,
                        u.serial === 'Y5' || u.serial === 'Y13',
                        selectedId === u.id,
                        false,
                        false,
                      )}
                    </g>
                  );
                })}

              {/* Combat / Round-Result snapshot units */}
              {match.phase !== 'prep' &&
                match.live_snapshot?.units.map((u: AutoChessCombatUnit) => {
                  const pt = u.coord ? parseCoordStr(u.coord) : null;
                  if (!pt || (u.hp <= 0 && !u.dying)) return null;
                  const cx = padL + pt[0] * cellSize + cellSize / 2;
                  const cy = padT + pt[1] * cellSize + cellSize / 2;
                  const starCount = u.name.match(/★/g)?.length || 1;
                  const canWiki = !u.is_summon && Boolean(u.serial);
                  return (
                    <g
                      key={u.uid}
                      className={canWiki ? 'ac-board-unit' : undefined}
                      data-ac-serial={canWiki ? u.serial : undefined}
                      onMouseEnter={
                        canWiki
                          ? e => hoverWiki.startHover(u.serial, starCount, e.currentTarget)
                          : undefined
                      }
                      onMouseLeave={canWiki ? hoverWiki.leaveTarget : undefined}
                    >
                      <title>{`${u.name} (${u.coord}) HP ${u.hp}/${u.max_hp} 护盾 ${u.shield} MP ${u.mp}`}</title>
                      {renderUnitToken(
                        cx,
                        cy,
                        u.name.replace(/★+/g, ''),
                        u.team,
                        starCount,
                        u.hp / Math.max(1, u.max_hp),
                        u.shield,
                        u.flying,
                        latestFrame?.actor_uid === u.uid,
                        u.dying,
                        u.is_summon,
                      )}
                    </g>
                  );
                })}
            </svg>
            </div>

            {/* AI Intent / Battle playback banner */}
            {match.phase !== 'prep' && latestFrame && (
              <div className="ac-intent-bar">
                <div>
                  <strong>
                    [R{latestFrame.round} · {latestFrame.actor_name}]
                  </strong>{' '}
                  {latestFrame.reason || latestFrame.lines[0] || '行动演算'}
                </div>
                {match.live_snapshot && match.live_snapshot.round >= match.live_snapshot.overtime_start_round && (
                  <span className="ac-stat-chip hp">⚡ 加时决战：伤害升级 / 治疗衰减</span>
                )}
              </div>
            )}

            {/* Prep Selected Unit Inspector */}
            {match.phase === 'prep' && selectedOwned && (
              <div className="ac-inspector">
                <div>
                  <strong>
                    {selectedOwned.name} ({'★'.repeat(selectedOwned.star)})
                  </strong>{' '}
                  · {selectedOwned.cost}费 · {ROLE_LABELS[selectedOwned.role] || selectedOwned.role} · 射程{' '}
                  {selectedOwned.range} · [{selectedOwned.traits.join(' / ')}]
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
                  <select aria-label="替换成员" value="" disabled={busy || !(selectedOwned.location === 'board' ? p.bench : p.board).length}
                    onChange={e => void act('swap', { unit_a: selectedOwned.id, unit_b: e.target.value })}>
                    <option value="" disabled>替换成员</option>
                    {(selectedOwned.location === 'board' ? p.bench : p.board).map(u =>
                      <option key={u.id} value={u.id}>{u.name} {'★'.repeat(u.star)} · {u.coord || `备战席 ${(u.bench_idx ?? 0) + 1}`}</option>
                    )}
                  </select>
                  {selectedOwned.location === 'board' ? (
                    <button className="button subtle" disabled={busy} onClick={() => { void act('recall', { unit_id: selectedOwned.id }); setSelectedId(null); }}>
                      撤回备战席
                    </button>
                  ) : (
                    <button className="button subtle" disabled={busy} onClick={() => { void act('deploy', { unit_id: selectedOwned.id }); setSelectedId(null); }}>
                      上阵到空位
                    </button>
                  )}
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
          {match.last_round_report && (match.phase === 'round_result' || match.phase === 'finished') && (
            <section className="panel" style={{ padding: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <h4 style={{ margin: 0 }}>
                  {match.phase === 'finished'
                    ? `🏆 对局总结 · 第 ${p.placement || 1} 名`
                    : `第 ${match.last_round_report.round} 回合战报：${
                        match.last_round_report.won ? '✅ 胜利' : `❌ 落败 (-${match.last_round_report.hp_damage} HP)`
                      } · 对阵 ${match.last_round_report.opponent_name} (${match.last_round_report.battle_rounds}轮)`}
                </h4>
                {match.last_round_report.mvp && (
                  <span className="ac-stat-chip gold">
                    <Award size={14} /> MVP：{match.last_round_report.mvp.name}（伤害 {match.last_round_report.mvp.dmg_dealt} / 治疗 {match.last_round_report.mvp.heal_done}）
                  </span>
                )}
              </div>
              <div className="ac-report-grid">
                {(() => {
                  const rows = match.last_round_report.telemetry;
                  const maxVal = Math.max(1, ...rows.map(r => Math.max(r.dmg_dealt, r.dmg_taken, r.heal_done)));
                  return rows.map(r => (
                    <div key={r.uid} className="ac-tel-card">
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700 }}>
                        <span>{r.team === 'Y' ? '🟦' : '🟥'} {r.name}</span>
                        <span>{r.kills > 0 ? `${r.kills}击杀` : r.alive ? '存活' : '阵亡'}</span>
                      </div>
                      <div className="muted" style={{ fontSize: '0.74rem' }}>
                        输出 {r.dmg_dealt} · 治疗 {r.heal_done} · 承伤 {r.dmg_taken}
                      </div>
                      <div className="ac-tel-bar-wrap">
                        <div className="ac-tel-bar" style={{ width: `${(r.dmg_dealt / maxVal) * 100}%`, background: '#ef4444' }} />
                      </div>
                      <div className="ac-tel-bar-wrap">
                        <div className="ac-tel-bar" style={{ width: `${(r.heal_done / maxVal) * 100}%`, background: '#22c55e' }} />
                      </div>
                    </div>
                  ));
                })()}
              </div>
            </section>
          )}

          {/* Bench (6 slots) */}
          <section className="panel" style={{ padding: 12 }}>
            <div className="ac-section-head" style={{ marginBottom: 6 }}>
              <strong>备战席 ({p.bench.length}/{benchCapacity})</strong>
              <span className="muted" style={{ fontSize: '0.78rem' }}>点击棋子后点击紫色部署区即可上阵；同类3枚自动合成高星</span>
            </div>
            <div className="ac-bench-row">
              {benchSlots.map((u, idx) =>
                u ? (
                  <button
                    key={u.id}
                    type="button"
                    data-ac-serial={u.serial}
                    className={'ac-bench-slot filled ' + (selectedId === u.id ? 'selected' : '')}
                    onMouseEnter={e => hoverWiki.startHover(u.serial, u.star, e.currentTarget)}
                    onMouseLeave={hoverWiki.leaveTarget}
                    onClick={() => {
                      hoverWiki.closeNow();
                      setSelectedId(selectedId === u.id ? null : u.id);
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', fontWeight: 700 }}>
                      <span>{u.name}</span>
                      <span>{'★'.repeat(u.star)}</span>
                    </div>
                    <small className="muted">
                      {u.cost}费 · {ROLE_LABELS[u.role] || u.role} · 射程{u.range}
                    </small>
                    <small className="muted">{u.traits.join(' / ')}</small>
                  </button>
                ) : idx >= benchCapacity ? (
                  <div key={`locked_${idx}`} className="ac-bench-slot locked" title="栏位未解锁" aria-label={`备战席 ${idx + 1} 未解锁`}>
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
          <section className="panel" style={{ padding: 12 }}>
            <div className="ac-shop-controls">
              <strong>星序招募商店</strong>
              <div className="ac-hud-group">
                <button
                  className="button subtle"
                  disabled={busy || match.phase !== 'prep' || p.xp_to_next <= 0 || p.gold < 4}
                  onClick={() => void act('buy_xp')}
                >
                  购买经验 +4XP (4G)
                </button>
                <button
                  className="button subtle"
                  disabled={busy || match.phase !== 'prep' || (p.gold < 2 && p.free_rerolls <= 0)}
                  onClick={() => void act('reroll')}
                >
                  <RefreshCw size={14} /> {p.free_rerolls > 0 ? `免费刷新 (${p.free_rerolls})` : '刷新商店 (2G)'}
                </button>
                <button
                  className="button subtle"
                  disabled={busy || match.phase !== 'prep'}
                  onClick={() => void act('lock_shop')}
                >
                  {p.shop_locked ? <><Lock size={14} /> 已锁定</> : <><Unlock size={14} /> 锁定商店</>}
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
                      disabled={busy || match.phase !== 'prep' || slot.bought || p.gold < slot.cost}
                      className={`ac-shop-card cost-${slot.cost} ${slot.bought ? 'bought' : ''}`}
                      onClick={() => {
                        hoverWiki.closeNow();
                        void act('buy', { slot_index: slot.slot_index });
                      }}
                    >
                      {slot.hint && !slot.bought && <span className="ac-shop-hint">{slot.hint}</span>}
                      <div className="ac-shop-top">
                        <span>{slot.name}</span>
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
          </section>
        </main>
      </div>

      {/* Round 4 / Round 8 Augment 3-Choose-1 Modal */}
      {p.pending_augments.length > 0 && (
        <div className="modal-scrim">
          <section className="modal wide" role="dialog" aria-modal="true" aria-label="星序祝福三选一">
            <header>
              <h2>🌟 第 {match.round_num} 回合 · 选择星序祝福</h2>
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
                  <div style={{ fontSize: '0.76rem', color: '#6d4aff', fontWeight: 700 }}>{aug.tier || '星序祝福'}</div>
                  <strong style={{ display: 'block', margin: '4px 0', fontSize: '1rem' }}>{aug.name}</strong>
                  <p style={{ margin: 0, fontSize: '0.84rem', color: '#374151', lineHeight: 1.4 }}>{aug.desc}</p>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      {wikiOverlays}
    </div>
  );
}
