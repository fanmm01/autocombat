import { useEffect, useState } from 'react';
import { MapPin, X } from 'lucide-react';
import { api, type Skill, type Snapshot } from './types';
import './cellSkillPicker.css';

type CellSkill = { index: number; target: string };

export function CellSkillPicker({ code, revision, coord, snapshot, busy, onPick, onClose }: {
  code: string; revision: number; coord: string; snapshot: Snapshot; busy: boolean;
  onPick: (skill: Skill, target: string) => void; onClose: () => void;
}) {
  const [options, setOptions] = useState<CellSkill[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    api<{ skills: CellSkill[] }>(`/rooms/${code}/options`, { command: 'cell_skills', coord, revision })
      .then(({ skills }) => { if (!cancelled) setOptions(skills); })
      .catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [code, revision, coord]);

  const skills = (options ?? []).flatMap(({ index, target }) => {
    const skill = snapshot.turn?.skills.find(s => s.index === index);
    const unit = snapshot.units.find(u => u.uid === target);
    const grave = snapshot.graveyard.find(g => g.uid === target);
    const name = unit?.name ?? grave?.name ?? target;
    const targetLabel = grave && !unit ? `${name}（已阵亡）` : unit?.group_count && unit.group_count > 1 ? `${name} · ${unit.hp} HP` : name;
    return skill ? [{ skill, target, targetLabel }] : [];
  });

  return <section className="cell-skill-picker" aria-label={`${coord} 格可用技能`}>
    <header>
      <h3><MapPin size={16}/>{coord} 格可用技能</h3>
      <button type="button" className="icon-button" aria-label="关闭格子技能" onClick={onClose}><X size={16}/></button>
    </header>
    {skills.length ? <ul className="cell-skill-list">{skills.map(({ skill, target, targetLabel }) =>
      <li key={`${skill.index}:${target}`}><button type="button" className="button" disabled={busy} onClick={() => onPick(skill, target)}>
        <strong>{skill.name}</strong><small>{targetLabel}</small>
      </button></li>,
    )}</ul> : <p role="status">{error || (options ? '当前没有可对这格使用的技能' : '正在查询可用技能…')}</p>}
  </section>;
}
