/* Ambient TypeScript declarations for WeChat Mini Game runtime. */

interface WxTouch {
  identifier: number;
  clientX: number;
  clientY: number;
  pageX: number;
  pageY: number;
}

interface WxTouchEvent {
  touches: WxTouch[];
  changedTouches: WxTouch[];
  timeStamp: number;
}

interface WxCanvas {
  width: number;
  height: number;
  getContext(contextType: '2d'): WxCanvasRenderingContext2D | null;
}

interface WxImage {
  src: string;
  width: number;
  height: number;
  onload: (() => void) | null;
  onerror: ((err: unknown) => void) | null;
}

interface WxCanvasRenderingContext2D {
  canvas: WxCanvas;
  fillStyle: string | WxCanvasGradient;
  strokeStyle: string | WxCanvasGradient;
  lineWidth: number;
  lineCap: 'butt' | 'round' | 'square';
  lineJoin: 'round' | 'bevel' | 'miter';
  font: string;
  textAlign: 'left' | 'right' | 'center' | 'start' | 'end';
  textBaseline: 'top' | 'hanging' | 'middle' | 'alphabetic' | 'ideographic' | 'bottom';
  globalAlpha: number;
  shadowColor: string;
  shadowBlur: number;
  shadowOffsetX: number;
  shadowOffsetY: number;
  save(): void;
  restore(): void;
  scale(x: number, y: number): void;
  translate(x: number, y: number): void;
  rotate(angle: number): void;
  beginPath(): void;
  closePath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  quadraticCurveTo(cpx: number, cpy: number, x: number, y: number): void;
  arc(x: number, y: number, radius: number, startAngle: number, endAngle: number, anticlockwise?: boolean): void;
  rect(x: number, y: number, w: number, h: number): void;
  clip(): void;
  fill(): void;
  stroke(): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  strokeRect(x: number, y: number, w: number, h: number): void;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number, maxWidth?: number): void;
  strokeText(text: string, x: number, y: number, maxWidth?: number): void;
  measureText(text: string): { width: number };
  setLineDash(segments: number[]): void;
  createLinearGradient(x0: number, y0: number, x1: number, y1: number): WxCanvasGradient;
  createRadialGradient(x0: number, y0: number, r0: number, x1: number, y1: number, r1: number): WxCanvasGradient;
  drawImage(image: WxImage | WxCanvas, dx: number, dy: number, dw?: number, dh?: number): void;
}

interface WxCanvasGradient {
  addColorStop(offset: number, color: string): void;
}

interface WxRequestTask {
  abort(): void;
}

interface WxResponse<T = unknown> {
  statusCode: number;
  data: T;
  header?: Record<string, string>;
}

interface WxWindowInfo {
  pixelRatio: number;
  windowWidth: number;
  windowHeight: number;
  screenWidth?: number;
  screenHeight?: number;
  safeArea?: {
    left: number;
    right: number;
    top: number;
    bottom: number;
    width: number;
    height: number;
  };
}

interface WxLaunchOptions {
  scene: number;
  query: Record<string, string>;
}

interface WxApi {
  createCanvas(): WxCanvas;
  createImage(): WxImage;
  getWindowInfo?(): WxWindowInfo;
  getSystemInfoSync(): WxWindowInfo;
  onTouchStart(cb: (e: WxTouchEvent) => void): void;
  onTouchMove(cb: (e: WxTouchEvent) => void): void;
  onTouchEnd(cb: (e: WxTouchEvent) => void): void;
  onTouchCancel(cb: (e: WxTouchEvent) => void): void;
  onWindowResize?(cb: (res: { windowWidth: number; windowHeight: number }) => void): void;
  onShow(cb: (res: { query?: Record<string, string> }) => void): void;
  onHide(cb: () => void): void;
  getLaunchOptionsSync(): WxLaunchOptions;
  request<T = unknown>(options: {
    url: string;
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
    data?: unknown;
    header?: Record<string, string>;
    timeout?: number;
    dataType?: 'json' | 'text';
    success?: (res: WxResponse<T>) => void;
    fail?: (err: { errMsg?: string }) => void;
  }): WxRequestTask;
  cloud?: {
    init(options?: { env?: string; traceUser?: boolean }): void;
    callContainer<T = unknown>(options: {
      config?: { env?: string };
      path: string;
      method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
      header?: Record<string, string>;
      data?: unknown;
      success?: (res: WxResponse<T>) => void;
      fail?: (err: { errMsg?: string }) => void;
    }): void;
  };
  login(options: {
    timeout?: number;
    success?: (res: { code?: string; errMsg?: string }) => void;
    fail?: (err: { errMsg?: string }) => void;
  }): void;
  getStorageSync<T = unknown>(key: string): T | '';
  setStorageSync(key: string, data: unknown): void;
  removeStorageSync(key: string): void;
  showToast(options: { title: string; icon?: 'success' | 'error' | 'loading' | 'none'; duration?: number }): void;
  showModal(options: {
    title?: string;
    content?: string;
    editable?: boolean;
    placeholderText?: string;
    showCancel?: boolean;
    confirmText?: string;
    cancelText?: string;
    success?: (res: { confirm: boolean; cancel: boolean; content?: string }) => void;
    fail?: (err: { errMsg?: string }) => void;
  }): void;
  showShareMenu?(options: { withShareTicket?: boolean; menus?: string[] }): void;
  onShareAppMessage?(cb: () => { title: string; query?: string; imageUrl?: string }): void;
  shareAppMessage?(options: { title: string; query?: string; imageUrl?: string }): void;
}

declare const wx: WxApi;
declare function requestAnimationFrame(cb: (time: number) => void): number;
declare function setTimeout(cb: (...args: unknown[]) => void, ms?: number): number;
declare function clearTimeout(id: number): void;
