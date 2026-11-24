import { MG_CONFIG } from '../config';
import { deleteStorage, readStorage, writeStorage } from './storage';

const KEY_SESSION_TOKEN = 'mg_combat_session_token_v1';
const KEY_AUTH_TOKEN = 'mg_autochess_auth_token_v1';
const KEY_PLAYER_NAME = 'mg_player_name_v1';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

let cachedSessionToken = readStorage<string>(KEY_SESSION_TOKEN) || '';
let cachedAuthToken = readStorage<string>(KEY_AUTH_TOKEN) || '';
let cloudInitialized = false;

export function getSavedPlayerName(): string {
  return (readStorage<string>(KEY_PLAYER_NAME) || '').trim() || MG_CONFIG.defaultPlayerName;
}

export function setSavedPlayerName(name: string): void {
  const cleaned = name.trim().slice(0, 20);
  if (cleaned) {
    writeStorage(KEY_PLAYER_NAME, cleaned);
  }
}

export function getAuthToken(): string {
  return cachedAuthToken;
}

export function setAuthToken(token: string): void {
  cachedAuthToken = token.trim();
  if (cachedAuthToken) {
    writeStorage(KEY_AUTH_TOKEN, cachedAuthToken);
  } else {
    deleteStorage(KEY_AUTH_TOKEN);
  }
}

export function setSessionToken(token: string): void {
  cachedSessionToken = token.trim();
  if (cachedSessionToken) {
    writeStorage(KEY_SESSION_TOKEN, cachedSessionToken);
  } else {
    deleteStorage(KEY_SESSION_TOKEN);
  }
}

export function ensureCloudInitialized(): boolean {
  if (MG_CONFIG.transport !== 'cloud') return false;
  if (!wx.cloud) return false;
  if (!cloudInitialized) {
    wx.cloud.init({
      env: MG_CONFIG.cloudEnv || undefined,
      traceUser: true,
    });
    cloudInitialized = true;
  }
  return true;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  data?: unknown;
  timeout?: number;
}

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (cachedSessionToken) {
    headers['X-Combat-Session'] = cachedSessionToken;
  }
  if (cachedAuthToken) {
    headers['Authorization'] = `Bearer ${cachedAuthToken}`;
    headers['X-AutoChess-Auth'] = cachedAuthToken;
  }
  return headers;
}

function captureTokensFromPayload(payload: unknown): void {
  if (!payload || typeof payload !== 'object') return;
  const record = payload as Record<string, unknown>;
  if (typeof record.session_token === 'string' && record.session_token) {
    setSessionToken(record.session_token);
  }
  if (typeof record.auth_token === 'string' && record.auth_token) {
    setAuthToken(record.auth_token);
  }
}

function parseBody(raw: unknown): unknown {
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch {
      return { message: raw };
    }
  }
  return raw;
}

export function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method || (opts.data !== undefined ? 'POST' : 'GET');
  const headers = buildHeaders();
  const useCloud = ensureCloudInitialized();

  return new Promise<T>((resolve, reject) => {
    const handleSuccess = (res: WxResponse<unknown>) => {
      const body = parseBody(res.data);
      captureTokensFromPayload(body);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        resolve(body as T);
        return;
      }
      const msg =
        body && typeof body === 'object' && typeof (body as Record<string, unknown>).message === 'string'
          ? String((body as Record<string, unknown>).message)
          : `请求失败 (${res.statusCode})`;
      reject(new ApiError(msg, res.statusCode));
    };

    const handleFail = (err: { errMsg?: string }) => {
      reject(new ApiError(err?.errMsg || '网络连接失败，请检查后端服务状态', 0));
    };

    if (useCloud && wx.cloud) {
      if (MG_CONFIG.cloudService) {
        headers['X-WX-SERVICE'] = MG_CONFIG.cloudService;
      }
      wx.cloud.callContainer({
        config: MG_CONFIG.cloudEnv ? { env: MG_CONFIG.cloudEnv } : undefined,
        path: '/api/ui' + path,
        method,
        header: headers,
        data: opts.data,
        success: handleSuccess,
        fail: handleFail,
      });
      return;
    }

    wx.request({
      url: MG_CONFIG.apiBase + path,
      method,
      data: opts.data,
      header: headers,
      timeout: opts.timeout ?? 14000,
      dataType: 'json',
      success: handleSuccess,
      fail: handleFail,
    });
  });
}

export async function withSession<T>(fn: () => Promise<T>, playerName?: string): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      await apiRequest('/session', {
        method: 'POST',
        data: { name: (playerName || getSavedPlayerName()).slice(0, 20) },
      });
      return fn();
    }
    throw err;
  }
}
