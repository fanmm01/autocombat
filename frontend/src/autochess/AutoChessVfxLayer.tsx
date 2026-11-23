import type { CSSProperties } from 'react';
import type { AutoChessVfxEvent } from './types';

interface Props {
  events: AutoChessVfxEvent[];
  frameKey: number;
  cellCenter: (coord: string) => { x: number; y: number } | null;
}

const VFX_COLORS: Record<string, { main: string; glow: string; sub: string }> = {
  fire: { main: '#ff6d2e', glow: '#ffb84d', sub: '#ff3614' },
  frost: { main: '#6fe3ff', glow: '#d8f8ff', sub: '#2f9dff' },
  star: { main: '#ffd95e', glow: '#fff6b3', sub: '#f59e0b' },
  blood: { main: '#ff385c', glow: '#ff96a8', sub: '#9e112b' },
  heal: { main: '#42e395', glow: '#b8ffd9', sub: '#17b978' },
  summon: { main: '#b978ff', glow: '#ead2ff', sub: '#7a3df2' },
  slash: { main: '#f3f6ff', glow: '#a9c7ff', sub: '#ffd27a' },
};

export function AutoChessVfxLayer({ events, frameKey, cellCenter }: Props) {
  if (!events || events.length === 0) return null;

  return (
    <g className="ac-vfx-layer" pointerEvents="none">
      {events.map((ev, idx) => {
        if (ev.type === 'move') {
          const pts = (ev.path || [])
            .map(c => cellCenter(c))
            .filter((p): p is { x: number; y: number } => Boolean(p));
          if (pts.length < 2) return null;
          const start = pts[0];
          const end = pts[pts.length - 1];
          const midX = (start.x + end.x) / 2;
          const midY = (start.y + end.y) / 2 - (ev.flying ? 26 : 6);
          const d =
            pts.length === 2
              ? `M ${start.x} ${start.y} Q ${midX} ${midY} ${end.x} ${end.y}`
              : `M ${pts.map(p => `${p.x} ${p.y}`).join(' L ')}`;

          return (
            <g key={`mv-${frameKey}-${idx}`} className={ev.flying ? 'ac-vfx-move-fly' : 'ac-vfx-move-walk'}>
              <path
                d={d}
                fill="none"
                stroke={ev.flying ? '#b78cff' : '#6be8d6'}
                strokeWidth={ev.flying ? 3 : 2.5}
                strokeLinecap="round"
                strokeDasharray="6 5"
                className="ac-vfx-trail-path"
              />
              <circle cx={start.x} cy={start.y} r={10} fill="none" stroke={ev.flying ? '#b78cff' : '#6be8d6'} strokeWidth={1.6} opacity={0.55} />
              <circle cx={end.x} cy={end.y} r={14} fill="none" stroke={ev.flying ? '#e1c9ff' : '#9cf7ea'} strokeWidth={2} className="ac-vfx-ring" />
            </g>
          );
        }

        const kind = ev.vfx_kind || 'slash';
        const palette = VFX_COLORS[kind] || VFX_COLORS.slash;
        const src = ev.from_coord ? cellCenter(ev.from_coord) : null;
        const targets = (ev.to_coords || [])
          .map(c => ({ coord: c, pt: cellCenter(c) }))
          .filter((item): item is { coord: string; pt: { x: number; y: number } } => Boolean(item.pt));

        return (
          <g key={`act-${frameKey}-${idx}`} className={`ac-vfx-action ac-vfx-kind-${kind}`}>
            {src &&
              targets.map((t, ti) => {
                const dist = Math.hypot(t.pt.x - src.x, t.pt.y - src.y);
                if (dist < 6) return null;
                return (
                  <line
                    key={`beam-${ti}`}
                    x1={src.x}
                    y1={src.y}
                    x2={t.pt.x}
                    y2={t.pt.y}
                    stroke={palette.main}
                    strokeWidth={kind === 'star' || kind === 'fire' ? 3.5 : 2.5}
                    strokeLinecap="round"
                    className="ac-vfx-beam"
                    style={{ '--beam-glow': palette.glow } as CSSProperties}
                  />
                );
              })}

            {targets.map((t, ti) => {
              const { x, y } = t.pt;
              return (
                <g key={`burst-${ti}`} transform={`translate(${x}, ${y})`}>
                  <circle cx={0} cy={0} r={24} fill={palette.main} opacity={0.18} className="ac-vfx-flash" />
                  <circle cx={0} cy={0} r={22} fill="none" stroke={palette.glow} strokeWidth={2.5} className="ac-vfx-ring" />
                  {kind === 'fire' && (
                    <g className="ac-vfx-spin">
                      <polygon points="0,-24 6,-6 24,0 6,6 0,24 -6,6 -24,0 -6,-6" fill={palette.glow} opacity={0.85} />
                    </g>
                  )}
                  {kind === 'frost' && (
                    <g className="ac-vfx-spin">
                      <path d="M-20,0 L20,0 M0,-20 L0,20 M-14,-14 L14,14 M-14,14 L14,-14" stroke={palette.glow} strokeWidth={2.4} strokeLinecap="round" />
                      <circle cx={0} cy={0} r={15} fill="none" stroke={palette.main} strokeWidth={1.6} strokeDasharray="3 4" />
                    </g>
                  )}
                  {kind === 'star' && (
                    <g className="ac-vfx-spin">
                      <polygon points="0,-26 5,-5 26,0 5,5 0,26 -5,5 -26,0 -5,-5" fill={palette.glow} />
                      <circle cx={0} cy={0} r={18} fill="none" stroke={palette.main} strokeWidth={1.5} />
                    </g>
                  )}
                  {kind === 'blood' && (
                    <g>
                      <path d="M-19,-15 Q0,-2 19,17" fill="none" stroke={palette.main} strokeWidth={3.5} strokeLinecap="round" />
                      <path d="M18,-16 Q0,0 -18,16" fill="none" stroke={palette.glow} strokeWidth={2.2} strokeLinecap="round" />
                    </g>
                  )}
                  {kind === 'heal' && (
                    <g className="ac-vfx-float">
                      <path d="M-9,0 L9,0 M0,-9 L0,9" stroke={palette.glow} strokeWidth={3.5} strokeLinecap="round" />
                    </g>
                  )}
                  {kind === 'summon' && (
                    <g className="ac-vfx-spin">
                      <polygon points="0,-22 19,11 -19,11" fill="none" stroke={palette.glow} strokeWidth={2} />
                      <circle cx={0} cy={0} r={20} fill="none" stroke={palette.main} strokeWidth={1.8} strokeDasharray="5 4" />
                    </g>
                  )}
                  {kind === 'slash' && (
                    <g>
                      <path d="M-20,12 Q-2,-16 21,-10" fill="none" stroke={palette.glow} strokeWidth={3.2} strokeLinecap="round" />
                    </g>
                  )}
                </g>
              );
            })}

            {src && ev.skill_name && (
              <g transform={`translate(${src.x}, ${src.y - 30})`} className="ac-vfx-callout">
                <rect x={-44} y={-10} width={88} height={18} rx={9} fill="rgba(16, 18, 30, 0.88)" stroke={palette.main} strokeWidth={1.1} />
                <text x={0} y={2} textAnchor="middle" fontSize="9.5" fontWeight={700} fill={palette.glow}>
                  {ev.skill_name.slice(0, 12)}
                </text>
              </g>
            )}

            {(ev.popups || []).map((p, pi) => {
              const pt = cellCenter(p.coord);
              if (!pt) return null;
              return (
                <text
                  key={`pop-${pi}`}
                  x={pt.x + (pi % 2 === 0 ? 0 : 12)}
                  y={pt.y - 16 - Math.floor(pi / 2) * 12}
                  textAnchor="middle"
                  className={`ac-vfx-popup ac-vfx-popup-${p.kind}`}
                >
                  {p.text}
                </text>
              );
            })}
          </g>
        );
      })}
    </g>
  );
}
