import { useLayoutEffect, useRef, useState } from 'react';
import { ArrowRight, BookOpen, Shield, Sparkles, Wind, X } from 'lucide-react';
import {
  AUTOCHESS_ROLE_LABELS,
  resolveUnitWiki,
  type AutoChessCatalog,
  type AutoChessWikiTarget,
} from './types';
import type { HoverAnchorRect } from './useHoverWiki';

export function AutoChessWikiPopover({
  catalog,
  serial,
  star,
  anchorRect,
  onMouseEnter,
  onMouseLeave,
  onClose,
  onOpenFullWiki,
}: {
  catalog: AutoChessCatalog | null;
  serial: string;
  star: number;
  anchorRect: HoverAnchorRect;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onClose: () => void;
  onOpenFullWiki: (target: AutoChessWikiTarget) => void;
}) {
  const unit = resolveUnitWiki(catalog, serial);
  const popRef = useRef<HTMLElement | null>(null);
  const [coords, setCoords] = useState<{ left: number; top: number; width: number; maxHeight: number }>({
    left: Math.max(8, anchorRect.left),
    top: Math.max(8, anchorRect.top),
    width: 332,
    maxHeight: 460,
  });

  useLayoutEffect(() => {
    if (typeof window === 'undefined') return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const width = Math.min(340, Math.max(240, vw - 16));
    const measuredH = popRef.current?.offsetHeight || 360;
    const maxHeight = Math.max(200, vh - 16);
    const gap = 10;

    let left: number;
    let top: number;

    if (anchorRect.right + gap + width <= vw - 8) {
      left = anchorRect.right + gap;
      top = Math.max(8, Math.min(vh - measuredH - 8, anchorRect.top - 10));
    } else if (anchorRect.left - gap - width >= 8) {
      left = anchorRect.left - gap - width;
      top = Math.max(8, Math.min(vh - measuredH - 8, anchorRect.top - 10));
    } else {
      left = Math.max(8, Math.min(vw - width - 8, anchorRect.left + anchorRect.width / 2 - width / 2));
      if (anchorRect.bottom + gap + measuredH <= vh - 8) {
        top = anchorRect.bottom + gap;
      } else if (anchorRect.top - gap - measuredH >= 8) {
        top = anchorRect.top - gap - measuredH;
      } else {
        top = Math.max(8, vh - Math.min(measuredH, maxHeight) - 8);
      }
    }

    setCoords({ left, top, width, maxHeight });
  }, [anchorRect, serial, star]);

  if (!unit) return null;

  const starKey = String(Math.max(1, Math.min(3, star || 1)));
  const sStat = unit.star_stats[starKey] || unit.star_stats['1'];
  const synById = Object.fromEntries((catalog?.synergies || []).map(s => [s.id, s]));
  const previewSkills = unit.skills
    .filter(sk => sk.phase === 0 || sk.phase === 1)
    .slice(0, 3);
  const shownSkills = previewSkills.length ? previewSkills : unit.skills.slice(0, 3);

  return (
    <aside
      ref={popRef}
      role="dialog"
      aria-label={`${unit.name} 自走棋百科速览`}
      className={`ac-wiki-popover cost-${unit.cost}`}
      style={{
        left: `${coords.left}px`,
        top: `${coords.top}px`,
        width: `${coords.width}px`,
        maxHeight: `${coords.maxHeight}px`,
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="ac-wiki-pop-head">
        <div className="ac-wiki-pop-title">
          <span className="ac-wiki-serial">{unit.serial}</span>
          <strong>{unit.name}</strong>
          <span className="ac-wiki-stars" title="当前展示星级">{'★'.repeat(sStat.star)}</span>
        </div>
        <div className="ac-wiki-pop-badges">
          <span className={`ac-wiki-cost cost-${unit.cost}`}>{unit.cost}费</span>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭速览"
            title="关闭"
            onClick={onClose}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="ac-wiki-pop-sub">
        <span>{AUTOCHESS_ROLE_LABELS[unit.role] || unit.role} · {unit.tag}</span>
        <span>牌库 {unit.pool_count} 张</span>
      </div>

      <p className="ac-wiki-pop-lead">{unit.blurb}</p>

      <div className="ac-wiki-stat-pills">
        <span><b>HP</b> {sStat.hp}</span>
        <span><b>MP</b> {sStat.mp}</span>
        <span><b>射程</b> {unit.range}格</span>
        <span><b>移速</b> {unit.tactical_move}格</span>
        <span><b>主动作</b> {unit.main_actions}</span>
        <span><b>闪避</b> {sStat.dodge}%</span>
        {unit.flying && <span className="tag"><Wind size={11} /> 飞行越障</span>}
        {unit.can_block && <span className="tag"><Shield size={11} /> 持盾{unit.block_val}</span>}
      </div>

      <div className="ac-wiki-trait-links">
        {unit.traits.map(tr => {
          const syn = synById[tr];
          return (
            <button
              key={tr}
              type="button"
              className="ac-wiki-trait-btn"
              title={syn?.desc || tr}
              onClick={() => {
                onClose();
                onOpenFullWiki({ tab: 'synergies', synergyId: tr });
              }}
            >
              <span>{syn?.icon || '✧'}</span> {tr}
            </button>
          );
        })}
        {unit.tuning_notes.length > 0 && (
          <span className="ac-wiki-tune-pill" title={unit.tuning_notes.join('；')}>
            {unit.tuning_notes[0]}
          </span>
        )}
      </div>

      <div className="ac-wiki-pop-skills">
        <div className="ac-wiki-pop-sec">
          <Sparkles size={12} /> 普攻：{unit.basic_attack.skill_name} ({unit.basic_attack.skill_val}%) · {unit.basic_attack.dice}
        </div>
        {shownSkills.map((sk, idx) => (
          <div key={`${sk.name}_${idx}`} className="ac-wiki-pop-skill">
            <div className="ac-wiki-pop-skill-top">
              <strong>{sk.name}</strong>
              <span>
                {sk.mp_cost !== 0 && sk.mp_cost !== '' ? `${sk.mp_cost} MP` : '0 MP'}
                {sk.range ? ` · ${sk.range}格` : ''}
                {sk.cooldown > 0 ? ` · CD${sk.cooldown}` : ''}
              </span>
            </div>
            <div className="ac-wiki-pop-skill-desc">{sk.summary}</div>
          </div>
        ))}
        {unit.skills.length > shownSkills.length && (
          <div className="muted" style={{ fontSize: '0.72rem' }}>
            还有 {unit.skills.length - shownSkills.length} 个自走棋技能（见完整词条）
          </div>
        )}
      </div>

      <button
        type="button"
        className="ac-wiki-pop-more"
        onClick={() => {
          onClose();
          onOpenFullWiki({ tab: 'units', serial: unit.serial });
        }}
      >
        <span><BookOpen size={13} /> 在自走棋百科中展开完整词条</span>
        <ArrowRight size={13} />
      </button>
    </aside>
  );
}
