import type { AutoChessVfxEvent } from '../net/autochessApi';

const VFX_COLORS: Record<string, { main: string; glow: string }> = {
  fire: { main: '#ff6d2e', glow: '#ffb84d' },
  frost: { main: '#6fe3ff', glow: '#d8f8ff' },
  star: { main: '#ffd95e', glow: '#fff6b3' },
  blood: { main: '#ff385c', glow: '#ff96a8' },
  heal: { main: '#42e395', glow: '#b8ffd9' },
  summon: { main: '#b978ff', glow: '#ead2ff' },
  slash: { main: '#f3f6ff', glow: '#ffd27a' },
};

const POPUP_COLORS: Record<string, string> = {
  dmg: '#ff708d',
  heal: '#4be39a',
  shield: '#6ec5ff',
  summon: '#caa0ff',
  miss: '#9aa4c8',
};

interface ActiveVfxBatch {
  startedAt: number;
  durationMs: number;
  events: AutoChessVfxEvent[];
}

export class VfxEngine {
  private batches: ActiveVfxBatch[] = [];

  trigger(events: AutoChessVfxEvent[] | undefined): void {
    if (!events || events.length === 0) return;
    this.batches.push({
      startedAt: Date.now(),
      durationMs: 700,
      events,
    });
    if (this.batches.length > 6) {
      this.batches.shift();
    }
  }

  clear(): void {
    this.batches = [];
  }

  render(
    ctx: WxCanvasRenderingContext2D,
    cellCenter: (coord: string) => { x: number; y: number } | null,
  ): void {
    const now = Date.now();
    this.batches = this.batches.filter(b => now - b.startedAt < b.durationMs);
    if (this.batches.length === 0) return;

    for (const batch of this.batches) {
      const t = Math.max(0, Math.min(1, (now - batch.startedAt) / batch.durationMs));
      const fade = 1 - Math.pow(t, 1.8);

      for (const ev of batch.events) {
        if (ev.type === 'move') {
          const pts = (ev.path || [])
            .map(c => cellCenter(c))
            .filter((p): p is { x: number; y: number } => Boolean(p));
          if (pts.length >= 2) {
            const start = pts[0];
            const end = pts[pts.length - 1];
            const color = ev.flying ? '#b78cff' : '#6be8d6';
            ctx.save();
            ctx.globalAlpha = fade * 0.9;
            ctx.strokeStyle = color;
            ctx.lineWidth = ev.flying ? 3 : 2.5;
            ctx.setLineDash([6, 5]);
            ctx.beginPath();
            ctx.moveTo(start.x, start.y);
            if (pts.length === 2) {
              const mx = (start.x + end.x) / 2;
              const my = (start.y + end.y) / 2 - (ev.flying ? 26 : 6);
              ctx.quadraticCurveTo(mx, my, end.x, end.y);
            } else {
              for (let i = 1; i < pts.length; i += 1) {
                ctx.lineTo(pts[i].x, pts[i].y);
              }
            }
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.arc(end.x, end.y, 10 + t * 14, 0, Math.PI * 2);
            ctx.stroke();
            ctx.restore();
          }
          continue;
        }

        const kind = ev.vfx_kind || 'slash';
        const palette = VFX_COLORS[kind] || VFX_COLORS.slash;
        const src = ev.from_coord ? cellCenter(ev.from_coord) : null;
        const targets = (ev.to_coords || [])
          .map(c => ({ coord: c, pt: cellCenter(c) }))
          .filter((item): item is { coord: string; pt: { x: number; y: number } } => Boolean(item.pt));

        ctx.save();
        ctx.globalAlpha = fade;
        if (src) {
          for (const target of targets) {
            const dist = Math.hypot(target.pt.x - src.x, target.pt.y - src.y);
            if (dist < 6) continue;
            ctx.strokeStyle = palette.main;
            ctx.lineWidth = kind === 'star' || kind === 'fire' ? 3.5 : 2.5;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(src.x, src.y);
            ctx.lineTo(target.pt.x, target.pt.y);
            ctx.stroke();
          }
        }

        for (const target of targets) {
          const { x, y } = target.pt;
          ctx.fillStyle = palette.main;
          ctx.globalAlpha = fade * 0.22;
          ctx.beginPath();
          ctx.arc(x, y, 22 + t * 8, 0, Math.PI * 2);
          ctx.fill();

          ctx.globalAlpha = fade;
          ctx.strokeStyle = palette.glow;
          ctx.lineWidth = 2.4;
          ctx.beginPath();
          ctx.arc(x, y, 12 + t * 18, 0, Math.PI * 2);
          ctx.stroke();
        }

        for (const popup of ev.popups || []) {
          const pt = cellCenter(popup.coord);
          if (!pt) continue;
          const color = POPUP_COLORS[popup.kind] || '#ffffff';
          ctx.fillStyle = color;
          ctx.font = '700 15px "PingFang SC", "Microsoft YaHei", sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(popup.text, pt.x, pt.y - 18 - t * 24);
        }
        ctx.restore();
      }
    }
  }
}
