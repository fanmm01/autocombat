import { useEffect, useMemo, useRef, useState } from 'react';
import { BookOpen, Compass, Search, Shield, Sparkles, Star, Trophy, Wind, X } from 'lucide-react';
import {
  AUTOCHESS_ROLE_LABELS,
  resolveUnitWiki,
  type AutoChessCatalog,
  type AutoChessWikiTab,
  type AutoChessWikiTarget,
} from './types';

export function AutoChessWikiModal({
  catalog,
  initialTarget,
  onClose,
}: {
  catalog: AutoChessCatalog | null;
  initialTarget?: AutoChessWikiTarget | null;
  onClose: () => void;
}) {
  const units = catalog?.units || [];
  const synergies = catalog?.synergies || [];
  const augments = catalog?.augments || [];
  const arenas = catalog?.arenas || [];
  const levels = catalog?.levels || {};
  const terrains = catalog?.terrains || {};

  const [tab, setTab] = useState<AutoChessWikiTab>(initialTarget?.tab || 'units');
  const [activeSerial, setActiveSerial] = useState<string>(initialTarget?.serial || units[0]?.serial || 'Y1');
  const [activeSynergy, setActiveSynergy] = useState<string>(initialTarget?.synergyId || '');
  const [costFilter, setCostFilter] = useState<number>(0);
  const [traitFilter, setTraitFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [phaseFilter, setPhaseFilter] = useState<string>('all');
  const [augFilter, setAugFilter] = useState<string>('');
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLElement | null>(null);
  const articleRef = useRef<HTMLElement | null>(null);

  const selectUnit = (serial: string) => {
    setActiveSerial(serial);
    window.requestAnimationFrame(() => {
      const article = articleRef.current;
      const body = bodyRef.current;
      const list = listRef.current;
      if (!article) return;
      article.scrollTop = 0;
      if (body && list && article.offsetTop >= list.offsetTop + list.offsetHeight - 4) {
        body.scrollTo({ top: Math.max(0, article.offsetTop - body.offsetTop), behavior: 'smooth' });
      }
    });
  };

  useEffect(() => {
    if (!initialTarget) return;
    setTab(initialTarget.tab || 'units');
    if (initialTarget.serial) setActiveSerial(initialTarget.serial);
    if (initialTarget.synergyId !== undefined) setActiveSynergy(initialTarget.synergyId);
    setPhaseFilter('all');
  }, [initialTarget]);

  useEffect(() => {
    setPhaseFilter('all');
  }, [activeSerial]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const filteredUnits = useMemo(() => {
    const q = search.trim().toLowerCase();
    return units.filter(u => {
      if (costFilter && u.cost !== costFilter) return false;
      if (traitFilter && !u.traits.includes(traitFilter)) return false;
      if (!q) return true;
      const wiki = resolveUnitWiki(catalog, u.serial);
      const hay = [
        u.serial,
        u.name,
        u.tag,
        u.blurb,
        AUTOCHESS_ROLE_LABELS[u.role] || u.role,
        ...u.traits,
        ...(wiki?.skills.map(s => s.name) || []),
      ]
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [units, costFilter, traitFilter, search, catalog]);

  const currentUnit = useMemo(() => {
    const pick =
      filteredUnits.find(u => u.serial === activeSerial) ||
      units.find(u => u.serial === activeSerial) ||
      filteredUnits[0] ||
      units[0];
    return pick ? resolveUnitWiki(catalog, pick.serial) : null;
  }, [catalog, units, filteredUnits, activeSerial]);

  const synById = useMemo(() => Object.fromEntries(synergies.map(s => [s.id, s])), [synergies]);

  const phaseOptions = useMemo(() => {
    if (!currentUnit) return [];
    const seen = new Map<string, string>();
    for (const sk of currentUnit.skills) {
      if (sk.phase_label && !seen.has(String(sk.phase))) {
        seen.set(String(sk.phase), sk.phase_label);
      }
    }
    return Array.from(seen.entries());
  }, [currentUnit]);

  const shownSkills = useMemo(() => {
    if (!currentUnit) return [];
    if (phaseFilter === 'all') return currentUnit.skills;
    return currentUnit.skills.filter(s => String(s.phase) === phaseFilter);
  }, [currentUnit, phaseFilter]);

  const filteredAugments = useMemo(() => {
    const q = augFilter.trim().toLowerCase();
    if (!q) return augments;
    return augments.filter(a => `${a.name} ${a.tier || ''} ${a.desc || ''}`.toLowerCase().includes(q));
  }, [augments, augFilter]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <section
        className="modal wide ac-wiki-modal"
        role="dialog"
        aria-modal="true"
        aria-label="星序自走棋独立百科"
        onClick={e => e.stopPropagation()}
      >
        <header className="ac-wiki-modal-head">
          <div>
            <h2><BookOpen size={18} /> 星序自走棋百科</h2>
            <small className="muted">自走棋独立词典 · 全部数值、射程与星级成长均仅对应本模式（与本体百科不互通）</small>
          </div>
          <button type="button" className="icon-button" aria-label="关闭百科" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <nav className="ac-wiki-tabs" aria-label="自走棋百科分类">
          {(
            [
              ['units', `棋子图鉴 (${units.length})`],
              ['synergies', `8 大羁绊 (${synergies.length})`],
              ['augments', `星序祝福 (${augments.length})`],
              ['rules', '地形与机制'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={'ac-wiki-tab ' + (tab === id ? 'active' : '')}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>

        {tab === 'units' && (
          <div className="ac-wiki-body" ref={bodyRef}>
            <div className="ac-wiki-filters">
              <div className="ac-wiki-search-wrap">
                <Search size={14} />
                <input
                  aria-label="搜索自走棋棋子"
                  placeholder="搜索编号、名称、特质或技能…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
              <div className="ac-wiki-filter-pills">
                {[0, 1, 2, 3, 4, 5, 6].map(c => (
                  <button
                    key={c}
                    type="button"
                    className={'ac-wiki-chip ' + (costFilter === c ? 'active' : '')}
                    onClick={() => setCostFilter(c)}
                  >
                    {c === 0 ? '全费' : `${c}费`}
                  </button>
                ))}
                <select
                  aria-label="按羁绊筛选"
                  value={traitFilter}
                  onChange={e => setTraitFilter(e.target.value)}
                >
                  <option value="">全部羁绊</option>
                  {synergies.map(s => (
                    <option key={s.id} value={s.id}>{s.icon} {s.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="ac-wiki-split">
              <aside className="ac-wiki-list" ref={listRef} aria-label="自走棋棋子目录">
                {!filteredUnits.length ? (
                  <div className="muted" style={{ padding: 12, fontSize: '0.84rem' }}>没有匹配的棋子词条</div>
                ) : (
                  filteredUnits.map(u => (
                    <button
                      key={u.serial}
                      type="button"
                      className={`ac-wiki-list-item cost-${u.cost} ${currentUnit?.serial === u.serial ? 'active' : ''}`}
                      onClick={() => selectUnit(u.serial)}
                    >
                      <div className="ac-wiki-list-top">
                        <span><b>{u.serial}</b> {u.name}</span>
                        <span>{u.cost}G</span>
                      </div>
                      <small className="muted">{u.traits.join(' / ')} · {AUTOCHESS_ROLE_LABELS[u.role] || u.role}</small>
                    </button>
                  ))
                )}
              </aside>

              <article className="ac-wiki-article" ref={articleRef}>
                {currentUnit && (
                  <>
                    <div className={`ac-wiki-infobox cost-${currentUnit.cost}`}>
                      <div className="ac-wiki-info-head">
                        <div>
                          <span className="ac-wiki-serial">{currentUnit.serial}</span>
                          <h3>{currentUnit.name}</h3>
                          <span className={`ac-wiki-cost cost-${currentUnit.cost}`}>{currentUnit.cost}费</span>
                        </div>
                        <div className="ac-wiki-info-meta">
                          <span>{AUTOCHESS_ROLE_LABELS[currentUnit.role] || currentUnit.role}</span>
                          <span>{currentUnit.tag}</span>
                          <span>牌库 {currentUnit.pool_count} 张</span>
                          {currentUnit.flying && <span><Wind size={12} /> 飞行越障</span>}
                          {currentUnit.can_block && <span><Shield size={12} /> 格挡 {currentUnit.block_val}</span>}
                        </div>
                      </div>
                      <p className="ac-wiki-lead">{currentUnit.blurb}</p>
                      <div className="ac-wiki-stat-pills">
                        <span><b>真射程</b> {currentUnit.range} 格</span>
                        <span><b>行动力</b> {currentUnit.mov} → 战术移动 {currentUnit.tactical_move} 格/轮</span>
                        <span><b>主动作</b> {currentUnit.main_actions} 次/轮</span>
                        <span><b>敏捷</b> {currentUnit.dex}</span>
                        <span><b>基础闪避</b> {currentUnit.dodge}%</span>
                        {currentUnit.tuning_notes.map(note => (
                          <span key={note} className="ac-wiki-tune-pill">{note}</span>
                        ))}
                      </div>
                    </div>

                    <section className="ac-wiki-section">
                      <h4>双轴羁绊与共鸣搭档（点击内部跳转）</h4>
                      <div className="ac-wiki-syn-cards">
                        {currentUnit.traits.map(tr => {
                          const syn = synById[tr];
                          const partners = units.filter(u => u.serial !== currentUnit.serial && u.traits.includes(tr));
                          return (
                            <div key={tr} className="ac-wiki-syn-card">
                              <div className="ac-wiki-syn-card-head">
                                <button
                                  type="button"
                                  className="ac-wiki-trait-btn"
                                  onClick={() => {
                                    setActiveSynergy(tr);
                                    setTab('synergies');
                                  }}
                                >
                                  <span>{syn?.icon || '✧'}</span> {tr} →
                                </button>
                                <small className="muted">{syn?.tiers.map(t => `${t.count}:${t.label}`).join('；')}</small>
                              </div>
                              <div className="ac-wiki-partner-row">
                                {partners.map(pt => (
                                  <button
                                    key={pt.serial}
                                    type="button"
                                    className="ac-wiki-chip"
                                    onClick={() => selectUnit(pt.serial)}
                                  >
                                    {pt.name} ({pt.cost}G)
                                  </button>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>

                    <section className="ac-wiki-section">
                      <h4>星级成长数值表（1★ → 2★ → 3★）</h4>
                      <div className="ac-wiki-table-wrap">
                        <table className="ac-wiki-table">
                          <thead>
                            <tr>
                              <th>星级</th>
                              <th>体力 HP</th>
                              <th>魔力 MP</th>
                              <th>技能检定</th>
                              <th>附加伤害</th>
                              <th>固定减伤</th>
                              <th>闪避</th>
                              <th>召唤物(HP/技)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(['1', '2', '3'] as const).map(sk => {
                              const st = currentUnit.star_stats[sk];
                              if (!st) return null;
                              return (
                                <tr key={sk}>
                                  <td><b>{'★'.repeat(st.star)}</b></td>
                                  <td>{st.hp}</td>
                                  <td>{st.mp}</td>
                                  <td>+{st.skill_bonus}</td>
                                  <td>+{st.flat_dmg}</td>
                                  <td>+{st.flat_dr}</td>
                                  <td>{st.dodge}%</td>
                                  <td>×{st.summon_hp_mult} / +{st.summon_skill_bonus}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </section>

                    <section className="ac-wiki-section">
                      <h4>普攻与专属被动</h4>
                      <div className="ac-wiki-basic-box">
                        <strong>普通攻击：</strong>
                        {currentUnit.basic_attack.skill_name}（基础 {currentUnit.basic_attack.skill_val}%） · 伤害骰{' '}
                        <code>{currentUnit.basic_attack.dice}</code> ·{' '}
                        {currentUnit.basic_attack.pierce ? '贯穿减伤' : '非贯穿'}
                      </div>
                      {currentUnit.passives.length > 0 && (
                        <ul className="ac-wiki-passives">
                          {currentUnit.passives.map((pText, idx) => (
                            <li key={idx}>{pText}</li>
                          ))}
                        </ul>
                      )}
                    </section>

                    <section className="ac-wiki-section">
                      <div className="ac-section-head" style={{ marginBottom: 6 }}>
                        <h4 style={{ margin: 0 }}>自走棋技能列表（真实射程）</h4>
                        {phaseOptions.length > 1 && (
                          <div className="ac-wiki-filter-pills">
                            <button
                              type="button"
                              className={'ac-wiki-chip ' + (phaseFilter === 'all' ? 'active' : '')}
                              onClick={() => setPhaseFilter('all')}
                            >
                              全部 ({currentUnit.skills.length})
                            </button>
                            {phaseOptions.map(([ph, lbl]) => (
                              <button
                                key={ph}
                                type="button"
                                className={'ac-wiki-chip ' + (phaseFilter === ph ? 'active' : '')}
                                onClick={() => setPhaseFilter(ph)}
                              >
                                {lbl}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="ac-wiki-skill-list">
                        {shownSkills.map((sk, idx) => (
                          <div key={`${sk.name}_${idx}`} className="ac-wiki-skill-row">
                            <div className="ac-wiki-skill-head">
                              <strong>
                                {sk.name}
                                {sk.phase_label && <small className="ac-wiki-phase">[{sk.phase_label}]</small>}
                              </strong>
                              <div className="ac-wiki-skill-tags">
                                <span>{sk.timing}</span>
                                <span>{sk.mp_cost !== 0 && sk.mp_cost !== '' ? `${sk.mp_cost} MP` : '0 MP'}</span>
                                <span>{sk.range ? `射程 ${sk.range} 格` : '自身/无限制'}</span>
                                {sk.cooldown > 0 && <span>冷却 {sk.cooldown} 轮</span>}
                              </div>
                            </div>
                            <p>{sk.summary}</p>
                          </div>
                        ))}
                      </div>
                    </section>
                  </>
                )}
              </article>
            </div>
          </div>
        )}

        {tab === 'synergies' && (
          <div className="ac-wiki-body">
            <div className="ac-wiki-syn-grid">
              {synergies.map(syn => {
                const members = units.filter(u => u.traits.includes(syn.id));
                const isSelected = activeSynergy === syn.id;
                return (
                  <section
                    key={syn.id}
                    className={'ac-wiki-syn-panel ' + (isSelected ? 'selected' : '')}
                  >
                    <div className="ac-wiki-syn-panel-head">
                      <strong>{syn.icon} {syn.name}</strong>
                      <span className="muted">{members.length} 位棋子</span>
                    </div>
                    <p className="muted" style={{ margin: '4px 0 8px', fontSize: '0.82rem' }}>{syn.desc}</p>
                    <ul className="ac-wiki-tiers">
                      {syn.tiers.map(t => (
                        <li key={t.count}><b>{t.count} 羁绊：</b>{t.label}</li>
                      ))}
                    </ul>
                    <div className="ac-wiki-partner-row">
                      {members.map(m => (
                        <button
                          key={m.serial}
                          type="button"
                          className={`ac-wiki-chip cost-${m.cost}`}
                          onClick={() => {
                            setActiveSerial(m.serial);
                            setTab('units');
                          }}
                        >
                          {m.serial} {m.name} ({m.cost}G)
                        </button>
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          </div>
        )}

        {tab === 'augments' && (
          <div className="ac-wiki-body">
            <div className="ac-wiki-search-wrap" style={{ marginBottom: 10 }}>
              <Search size={14} />
              <input
                aria-label="搜索星序祝福"
                placeholder="筛选祝福名称、定位或效果（第 4、8、12 回合三选一）…"
                value={augFilter}
                onChange={e => setAugFilter(e.target.value)}
              />
            </div>
            <div className="ac-wiki-aug-grid">
              {filteredAugments.map(aug => (
                <div key={aug.id} className="ac-wiki-aug-card">
                  <div className="ac-wiki-aug-tier"><Star size={12} /> {aug.tier || '星序祝福'}</div>
                  <strong>{aug.name}</strong>
                  <p>{aug.desc}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === 'rules' && (
          <div className="ac-wiki-body ac-wiki-rules">
            <section className="ac-wiki-rule-card">
              <h4><Shield size={15} /> 1. 独立模式边界与主动作公式</h4>
              <p>星序自走棋完全独立于经典模式与本体百科：仅收录 <code>Y1–Y19</code> 共 19 位魔法少女。每轮主动作次数仍严格沿用经典 CoC 公式 <code>max(1, (有效MOV+1)//5 + 额外行动数)</code>；仅将战术移动力缩放为 2–8 格，且回合末保留站位不再弹回锚点。</p>
            </section>

            <section className="ac-wiki-rule-card">
              <h4><Compass size={15} /> 2. 地形效果与 4 张对称战场</h4>
              <ul>
                {Object.entries(terrains).map(([k, v]) => (
                  <li key={k}>
                    <b>{k === 'wall' ? '墙体 (墙)' : k === 'cover' ? '掩体 (掩)' : k === 'leyline' ? '灵脉 (灵)' : k}：</b>
                    {typeof v === 'string' ? v : v.summary || v.name}
                  </li>
                ))}
              </ul>
              <div className="ac-wiki-arena-list">
                {arenas.map(a => (
                  <div key={a.id} className="ac-wiki-arena-item">
                    <strong>{a.name.includes('×') ? a.name : `${a.name} (${a.width}×${a.height})`}</strong>
                    <small className="muted">{a.description}</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="ac-wiki-rule-card">
              <h4><Sparkles size={15} /> 3. 经济、升星、刷新概率与加时</h4>
              <p>每 10 金币每轮 +1 利息（基础上限 +5G，星辉投资可提至 +7G），连胜/连败达 2/3/5+ 轮分别额外 +1/+2/+3 金币；每轮结算自动获得 +2 XP，单回合战胜对手额外奖励 +1G 与 +1 XP（即胜场累计 +3 XP、败场 +2 XP）。同类同星 3 枚自动合成 1★ → 2★ → 3★；第 4、8、12 回合触发星序祝福 3 选 1；1v1 第 12 轮 / 多人第 15 轮起进入加时决战（每轮伤递增 +15%、治疗最低降至 25%）。</p>
              <div className="ac-wiki-table-wrap">
                <table className="ac-wiki-table">
                  <thead>
                    <tr>
                      <th>指挥官等级</th>
                      <th>可上阵人口</th>
                      <th>升级所需 XP</th>
                      <th>1费概率</th>
                      <th>2费概率</th>
                      <th>3费概率</th>
                      <th>4费概率</th>
                      <th>5费概率</th>
                      <th>6费概率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(levels)
                      .sort(([a], [b]) => Number(a) - Number(b))
                      .map(([lv, info]) => (
                      <tr key={lv}>
                        <td><b>Lv.{lv}</b></td>
                        <td>{info.max_pop} 人</td>
                        <td>{info.xp_to_next > 0 ? `${info.xp_to_next} XP` : '满级'}</td>
                        <td>{info.odds['1'] ?? 0}%</td>
                        <td>{info.odds['2'] ?? 0}%</td>
                        <td>{info.odds['3'] ?? 0}%</td>
                        <td>{info.odds['4'] ?? 0}%</td>
                        <td>{info.odds['5'] ?? 0}%</td>
                        <td>{info.odds['6'] ?? 0}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ margin: '6px 0 0', fontSize: '0.8rem' }}>
                注：当前已开启 5–6 费体系，其中 5 费档位架构预留（刷新概率 0%），6 费为唯一彩卡档位（<code>Y12 斯瑞提卡</code>），于 Lv.5 起逐步出现、Lv.6–Lv.7 主力刷新。
              </p>
            </section>

            <section className="ac-wiki-rule-card">
              <h4><Trophy size={15} /> 4. 8 人排位模式、段位积分与局外金币</h4>
              <p>
                排位模式需登录自走棋账号后方可参与，每局共 8 名指挥官混战（1 名玩家 + 7 名随机命名且策略各异的同段位 AI），使用扩容版 8 人共享牌库（1–6 费分别为{' '}
                <code>
                  {catalog?.pool_counts_8p
                    ? `${catalog.pool_counts_8p['1']}/${catalog.pool_counts_8p['2']}/${catalog.pool_counts_8p['3']}/${catalog.pool_counts_8p['4']}/${catalog.pool_counts_8p['5'] ?? 11}/${catalog.pool_counts_8p['6'] ?? 9}`
                    : '29/22/18/14/11/9'}
                </code>{' '}
                张）。前 4 名记为排位胜利并积累连胜与局外「金币」（暂未设兑换出口），第 5–8 名记为战败；每小段需 <b>100 分</b>，晋级白银后永久解锁<b>不会跌回青铜</b>硬保底；3 连胜必得 1 张<b>保段卡</b>（上限 5 张），掉段时自动消耗抵扣全部扣分。
              </p>
              {catalog?.ranked_rules?.tiers && (
                <div className="ac-wiki-table-wrap" style={{ marginTop: 8 }}>
                  <table className="ac-wiki-table">
                    <thead>
                      <tr>
                        <th>段位 (小段数)</th>
                        <th>#1</th>
                        <th>#2</th>
                        <th>#3</th>
                        <th>#4</th>
                        <th>#5</th>
                        <th>#6</th>
                        <th>#7</th>
                        <th>#8</th>
                      </tr>
                    </thead>
                    <tbody>
                      {catalog.ranked_rules.tiers.map(t => (
                        <tr key={t.id}>
                          <td>
                            <b>{t.name}</b> ({t.divisions ?? '无限'})
                          </td>
                          {t.lp_table.map((v, i) => (
                            <td key={i}>{v > 0 ? `+${v}` : v}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
      </section>
    </div>
  );
}
