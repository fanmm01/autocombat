export const VIRTUAL_W = 1280;
export const VIRTUAL_H = 720;

export const PALETTE = {
  bgDeep: '#0e1120',
  bgPanel: '#161b30',
  bgCard: '#1e2540',
  bgCardHover: '#262f52',
  bgInput: '#111629',
  border: '#323c62',
  borderBright: '#58679d',
  gold: '#f4c86a',
  goldSoft: '#b89448',
  violet: '#9c86ec',
  violetDark: '#6b53c4',
  cyan: '#5ce1d0',
  rose: '#f16c8d',
  emerald: '#48d68d',
  amber: '#f59e0b',
  textMain: '#f1f4ff',
  textSub: '#aab4d6',
  textMuted: '#737ea6',
};

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface HitRegion extends Rect {
  id?: string;
  onTap: (vx: number, vy: number) => void;
}

export interface ScrollZone extends Rect {
  key: string;
  contentHeight: number;
  onScroll: (nextOffset: number) => void;
  getOffset: () => number;
}

export function pointInRect(px: number, py: number, r: Rect): boolean {
  return px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h;
}

export function costColor(cost: number): string {
  switch (cost) {
    case 1:
      return '#8e9bb8';
    case 2:
      return '#48c78e';
    case 3:
      return '#529eff';
    case 4:
      return '#b374ff';
    case 5:
      return '#f6b846';
    default:
      return '#9c86ec';
  }
}

export function tierColor(tierId: string): string {
  switch (tierId) {
    case 'bronze':
      return '#c68356';
    case 'silver':
      return '#b2bfd4';
    case 'gold':
      return '#f2c15a';
    case 'platinum':
      return '#55d8c8';
    case 'diamond':
      return '#7ab4ff';
    case 'king':
      return '#e879f9';
    default:
      return '#9c86ec';
  }
}

export function roundRectPath(
  ctx: WxCanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

export function fillRoundRect(
  ctx: WxCanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
  fill: string | WxCanvasGradient,
): void {
  roundRectPath(ctx, x, y, w, h, r);
  ctx.fillStyle = fill;
  ctx.fill();
}

export function strokeRoundRect(
  ctx: WxCanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
  stroke: string,
  lineWidth = 1.5,
): void {
  roundRectPath(ctx, x, y, w, h, r);
  ctx.strokeStyle = stroke;
  ctx.lineWidth = lineWidth;
  ctx.stroke();
}

export function drawPill(
  ctx: WxCanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  bg: string,
  border: string,
  text: string,
  textColor: string,
  fontSize = 14,
): void {
  fillRoundRect(ctx, x, y, w, h, h / 2, bg);
  if (border) {
    strokeRoundRect(ctx, x, y, w, h, h / 2, border, 1.2);
  }
  ctx.fillStyle = textColor;
  ctx.font = `600 ${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x + w / 2, y + h / 2 + 0.5, Math.max(10, w - 12));
}

export function drawProgressBar(
  ctx: WxCanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  ratio: number,
  bg: string,
  fg: string,
  radius = 3,
): void {
  const clamped = Math.max(0, Math.min(1, ratio));
  fillRoundRect(ctx, x, y, w, h, radius, bg);
  if (clamped > 0.001) {
    fillRoundRect(ctx, x, y, Math.max(radius * 2, w * clamped), h, radius, fg);
  }
}

export function drawClippedText(
  ctx: WxCanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  color: string,
  font = '16px "PingFang SC", "Microsoft YaHei", sans-serif',
  align: 'left' | 'center' | 'right' = 'left',
  baseline: 'top' | 'middle' | 'bottom' = 'middle',
): void {
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  if (ctx.measureText(text).width <= maxWidth) {
    ctx.fillText(text, x, y);
    return;
  }
  let out = text;
  while (out.length > 1 && ctx.measureText(out + '…').width > maxWidth) {
    out = out.slice(0, -1);
  }
  ctx.fillText(out + '…', x, y);
}

export function drawWrappedText(
  ctx: WxCanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  color: string,
  font = '15px "PingFang SC", "Microsoft YaHei", sans-serif',
  maxLines = 4,
): number {
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  const paragraphs = String(text || '').split('\n');
  let linesDrawn = 0;

  for (const para of paragraphs) {
    let line = '';
    for (let i = 0; i < para.length; i += 1) {
      const ch = para[i];
      const test = line + ch;
      if (ctx.measureText(test).width > maxWidth && line.length > 0) {
        if (linesDrawn >= maxLines - 1) {
          let trimmed = line;
          while (trimmed.length > 1 && ctx.measureText(trimmed + '…').width > maxWidth) {
            trimmed = trimmed.slice(0, -1);
          }
          ctx.fillText(trimmed + '…', x, y + linesDrawn * lineHeight);
          return linesDrawn + 1;
        }
        ctx.fillText(line, x, y + linesDrawn * lineHeight);
        linesDrawn += 1;
        line = ch;
      } else {
        line = test;
      }
    }
    if (line.length > 0 || para.length === 0) {
      if (linesDrawn >= maxLines) break;
      ctx.fillText(line, x, y + linesDrawn * lineHeight);
      linesDrawn += 1;
      if (linesDrawn >= maxLines) break;
    }
  }
  return linesDrawn;
}

export function drawButton(
  stage: Stage,
  ctx: WxCanvasRenderingContext2D,
  rect: Rect,
  label: string,
  onTap: () => void,
  opts: {
    bg?: string;
    border?: string;
    color?: string;
    fontSize?: number;
    radius?: number;
    disabled?: boolean;
    sublabel?: string;
  } = {},
): void {
  const disabled = Boolean(opts.disabled);
  const bg = disabled ? '#1d2236' : opts.bg || PALETTE.bgCard;
  const border = disabled ? '#2c334f' : opts.border || PALETTE.borderBright;
  const color = disabled ? PALETTE.textMuted : opts.color || PALETTE.textMain;
  const radius = opts.radius ?? 10;
  const fontSize = opts.fontSize ?? 16;

  fillRoundRect(ctx, rect.x, rect.y, rect.w, rect.h, radius, bg);
  strokeRoundRect(ctx, rect.x, rect.y, rect.w, rect.h, radius, border, 1.5);

  if (opts.sublabel) {
    drawClippedText(
      ctx,
      label,
      rect.x + rect.w / 2,
      rect.y + rect.h * 0.37,
      rect.w - 16,
      color,
      `700 ${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`,
      'center',
      'middle',
    );
    drawClippedText(
      ctx,
      opts.sublabel,
      rect.x + rect.w / 2,
      rect.y + rect.h * 0.72,
      rect.w - 16,
      disabled ? PALETTE.textMuted : PALETTE.textSub,
      `500 ${Math.max(11, fontSize - 4)}px "PingFang SC", "Microsoft YaHei", sans-serif`,
      'center',
      'middle',
    );
  } else {
    drawClippedText(
      ctx,
      label,
      rect.x + rect.w / 2,
      rect.y + rect.h / 2 + 0.5,
      rect.w - 14,
      color,
      `700 ${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`,
      'center',
      'middle',
    );
  }

  if (!disabled) {
    stage.addHitRegion({
      x: rect.x,
      y: rect.y,
      w: rect.w,
      h: rect.h,
      onTap,
    });
  }
}

export function drawEmblemBadge(
  ctx: WxCanvasRenderingContext2D,
  cx: number,
  cy: number,
  radius: number,
  serial: string,
  accent: string,
  teamBorder?: string,
): void {
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = '#181e36';
  ctx.fill();
  ctx.lineWidth = teamBorder ? 2.5 : 1.8;
  ctx.strokeStyle = teamBorder || accent;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.78, 0, Math.PI * 2);
  ctx.fillStyle = `${accent}33`;
  ctx.fill();

  const shortTag = serial.replace(/^Y/i, '').slice(0, 3);
  ctx.fillStyle = '#f6f8ff';
  ctx.font = `700 ${Math.max(11, Math.round(radius * 0.75))}px "PingFang SC", "Microsoft YaHei", sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(shortTag, cx, cy + 0.5);
  ctx.restore();
}

export function promptInput(
  title: string,
  placeholder: string,
  initialValue = '',
): Promise<string | null> {
  return new Promise(resolve => {
    wx.showModal({
      title,
      content: initialValue || '',
      editable: true,
      placeholderText: placeholder,
      confirmText: '确认',
      cancelText: '取消',
      success: res => {
        if (res.confirm) {
          resolve((res.content ?? '').trim());
        } else {
          resolve(null);
        }
      },
      fail: () => resolve(null),
    });
  });
}

export function confirmAction(title: string, content: string): Promise<boolean> {
  return new Promise(resolve => {
    wx.showModal({
      title,
      content,
      confirmText: '确认',
      cancelText: '取消',
      success: res => resolve(Boolean(res.confirm)),
      fail: () => resolve(false),
    });
  });
}

export class Stage {
  readonly canvas: WxCanvas;
  readonly ctx: WxCanvasRenderingContext2D;
  private dpr = 1;
  private winW = VIRTUAL_W;
  private winH = VIRTUAL_H;
  private scale = 1;
  private offsetX = 0;
  private offsetY = 0;
  safeLeft = 16;
  safeRight = 16;
  private hitRegions: HitRegion[] = [];
  private scrollZones: ScrollZone[] = [];
  private toastMsg = '';
  private toastUntil = 0;
  private logoImg: WxImage | null = null;
  private logoReady = false;

  private activeTouchId: number | null = null;
  private downX = 0;
  private downY = 0;
  private lastY = 0;
  private dragging = false;
  private activeScroll: ScrollZone | null = null;

  constructor() {
    this.canvas = wx.createCanvas();
    const ctx = this.canvas.getContext('2d');
    if (!ctx) {
      throw new Error('无法初始化微信小游戏 Canvas 2D 上下文');
    }
    this.ctx = ctx;
    this.resize();
    this.loadLogo();
    this.bindTouch();
  }

  private loadLogo(): void {
    try {
      const img = wx.createImage();
      img.onload = () => {
        this.logoReady = true;
      };
      img.src = 'assets/logo.png';
      this.logoImg = img;
    } catch {
      this.logoImg = null;
    }
  }

  drawLogo(ctx: WxCanvasRenderingContext2D, x: number, y: number, size: number): void {
    if (this.logoImg && this.logoReady) {
      ctx.save();
      roundRectPath(ctx, x, y, size, size, size * 0.24);
      ctx.clip();
      ctx.drawImage(this.logoImg, x, y, size, size);
      ctx.restore();
    } else {
      fillRoundRect(ctx, x, y, size, size, size * 0.24, PALETTE.violetDark);
      drawClippedText(ctx, '星', x + size / 2, y + size / 2, size, '#fff', `700 ${Math.round(size * 0.55)}px sans-serif`, 'center', 'middle');
    }
  }

  resize(): void {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.dpr = Math.min(3, Math.max(1, info.pixelRatio || 1));
    this.winW = Math.max(320, info.windowWidth || VIRTUAL_W);
    this.winH = Math.max(240, info.windowHeight || VIRTUAL_H);
    this.canvas.width = Math.round(this.winW * this.dpr);
    this.canvas.height = Math.round(this.winH * this.dpr);

    this.scale = Math.min(this.winW / VIRTUAL_W, this.winH / VIRTUAL_H);
    this.offsetX = (this.winW - VIRTUAL_W * this.scale) / 2;
    this.offsetY = (this.winH - VIRTUAL_H * this.scale) / 2;

    if (info.safeArea) {
      this.safeLeft = Math.max(14, Math.round(info.safeArea.left / this.scale));
      this.safeRight = Math.max(14, Math.round((this.winW - info.safeArea.right) / this.scale));
    }
  }

  toVirtual(clientX: number, clientY: number): { x: number; y: number } {
    return {
      x: (clientX - this.offsetX) / this.scale,
      y: (clientY - this.offsetY) / this.scale,
    };
  }

  beginFrame(): void {
    this.hitRegions = [];
    this.scrollZones = [];
    this.ctx.setLineDash([]);
    this.ctx.save();
    this.ctx.scale(this.dpr, this.dpr);
    this.ctx.fillStyle = PALETTE.bgDeep;
    this.ctx.fillRect(0, 0, this.winW, this.winH);
    this.ctx.translate(this.offsetX, this.offsetY);
    this.ctx.scale(this.scale, this.scale);
  }

  endFrame(): void {
    this.renderToast();
    this.ctx.restore();
  }

  addHitRegion(region: HitRegion): void {
    this.hitRegions.push(region);
  }

  addScrollZone(zone: ScrollZone): void {
    this.scrollZones.push(zone);
  }

  showToast(message: string, durationMs = 2600): void {
    this.toastMsg = message;
    this.toastUntil = Date.now() + durationMs;
  }

  private renderToast(): void {
    if (!this.toastMsg || Date.now() > this.toastUntil) return;
    const text = this.toastMsg;
    const ctx = this.ctx;
    ctx.font = '600 16px "PingFang SC", "Microsoft YaHei", sans-serif';
    const w = Math.min(720, Math.max(200, ctx.measureText(text).width + 44));
    const h = 42;
    const x = (VIRTUAL_W - w) / 2;
    const y = 74;
    fillRoundRect(ctx, x, y, w, h, 21, 'rgba(18, 22, 42, 0.94)');
    strokeRoundRect(ctx, x, y, w, h, 21, PALETTE.gold, 1.5);
    drawClippedText(ctx, text, VIRTUAL_W / 2, y + h / 2, w - 24, PALETTE.gold, '600 16px "PingFang SC", "Microsoft YaHei", sans-serif', 'center', 'middle');
  }

  private bindTouch(): void {
    wx.onTouchStart(e => {
      const t = e.changedTouches[0] || e.touches[0];
      if (!t) return;
      const pt = this.toVirtual(t.clientX, t.clientY);
      this.activeTouchId = t.identifier;
      this.downX = pt.x;
      this.downY = pt.y;
      this.lastY = pt.y;
      this.dragging = false;
      this.activeScroll = null;
      for (let i = this.scrollZones.length - 1; i >= 0; i -= 1) {
        if (pointInRect(pt.x, pt.y, this.scrollZones[i])) {
          this.activeScroll = this.scrollZones[i];
          break;
        }
      }
    });

    wx.onTouchMove(e => {
      const t = e.changedTouches.find(c => c.identifier === this.activeTouchId) || e.changedTouches[0];
      if (!t) return;
      const pt = this.toVirtual(t.clientX, t.clientY);
      const dist = Math.hypot(pt.x - this.downX, pt.y - this.downY);
      if (dist > 10) {
        this.dragging = true;
      }
      if (this.dragging && this.activeScroll) {
        const dy = pt.y - this.lastY;
        const maxScroll = Math.max(0, this.activeScroll.contentHeight - this.activeScroll.h);
        const next = Math.max(0, Math.min(maxScroll, this.activeScroll.getOffset() - dy));
        this.activeScroll.onScroll(next);
      }
      this.lastY = pt.y;
    });

    const finish = (e: WxTouchEvent, cancelled: boolean) => {
      const t = e.changedTouches.find(c => c.identifier === this.activeTouchId) || e.changedTouches[0];
      if (!cancelled && !this.dragging && t) {
        const pt = this.toVirtual(t.clientX, t.clientY);
        for (let i = this.hitRegions.length - 1; i >= 0; i -= 1) {
          const r = this.hitRegions[i];
          if (pointInRect(pt.x, pt.y, r)) {
            r.onTap(pt.x, pt.y);
            break;
          }
        }
      }
      this.activeTouchId = null;
      this.dragging = false;
      this.activeScroll = null;
    };

    wx.onTouchEnd(e => finish(e, false));
    wx.onTouchCancel(e => finish(e, true));
  }
}
