import { ApiError, api } from '../types';
import type {
  AutoChessAccount,
  AutoChessAuthState,
  AutoChessCatalog,
  AutoChessMatchState,
  AutoChessMatchSummary,
  AutoChessRoomState,
  AutoChessRoomSummary,
} from './types';

async function withSession<T>(fn: () => Promise<T>, playerName = '指挥官'): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      await api('/session', { name: playerName.trim() || '指挥官' });
      return fn();
    }
    throw err;
  }
}

export function fetchAutoChessCatalog(): Promise<AutoChessCatalog> {
  return api<AutoChessCatalog>('/autochess/catalog');
}

export async function listAutoChessMatches(playerName?: string): Promise<AutoChessMatchSummary[]> {
  const res = await withSession(() => api<{ matches: AutoChessMatchSummary[] }>('/autochess/matches'), playerName);
  return res.matches;
}

export async function createAutoChessMatch(params: {
  mode: 'lobby4' | 'pve12';
  arena_preset: string;
  player_name: string;
}): Promise<AutoChessMatchState> {
  const res = await withSession(
    () => api<{ match: AutoChessMatchState }>('/autochess/matches', params),
    params.player_name,
  );
  return res.match;
}

export async function getAutoChessMatch(id: string, playerName?: string): Promise<AutoChessMatchState> {
  const res = await withSession(() => api<{ match: AutoChessMatchState }>(`/autochess/matches/${id}`), playerName);
  return res.match;
}

export async function deleteAutoChessMatch(id: string, playerName?: string): Promise<void> {
  await withSession(async () => {
    const resp = await fetch(`/api/ui/autochess/matches/${id}`, { method: 'DELETE' });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new ApiError(data.message || '删除失败', resp.status);
  }, playerName);
}

export async function sendAutoChessAction(
  id: string,
  action: string,
  payload: Record<string, unknown> = {},
  playerName?: string,
): Promise<{ ok: boolean; message: string; match: AutoChessMatchState }> {
  return withSession(
    () => api<{ ok: boolean; message: string; match: AutoChessMatchState }>(`/autochess/matches/${id}/action`, {
      action,
      ...payload,
    }),
    playerName,
  );
}

// ── Guest Local Token Overrides ───────────────────────────────────────────

const GUEST_TOKENS_KEY = 'autochess_guest_tokens_v1';

export function readGuestTokens(): Record<string, string> {
  try {
    const raw = localStorage.getItem(GUEST_TOKENS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function saveGuestToken(serial: string, tokenUrl: string): Record<string, string> {
  const next = { ...readGuestTokens(), [serial]: tokenUrl };
  try {
    localStorage.setItem(GUEST_TOKENS_KEY, JSON.stringify(next));
  } catch {
    // ignore storage quota failure
  }
  return next;
}

export function clearGuestToken(serial: string): Record<string, string> {
  const next = { ...readGuestTokens() };
  delete next[serial];
  try {
    localStorage.setItem(GUEST_TOKENS_KEY, JSON.stringify(next));
  } catch {
    // ignore storage failure
  }
  return next;
}

// ── Independent Account & Token API ───────────────────────────────────────

export function getAuthMe(): Promise<AutoChessAuthState> {
  return api<AutoChessAuthState>('/autochess/auth/me');
}

export function registerAccount(params: {
  username: string;
  password: string;
  display_name?: string;
}): Promise<AutoChessAuthState> {
  return api<AutoChessAuthState>('/autochess/auth/register', params);
}

export function loginAccount(params: {
  username: string;
  password: string;
}): Promise<AutoChessAuthState> {
  return api<AutoChessAuthState>('/autochess/auth/login', params);
}

export function logoutAccount(): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>('/autochess/auth/logout', {});
}

export function updateProfile(params: {
  display_name?: string;
  old_password?: string;
  new_password?: string;
}): Promise<{ account: AutoChessAccount }> {
  return api<{ account: AutoChessAccount }>('/autochess/auth/profile', params);
}

export function setUnitToken(serial: string, tokenUrl: string): Promise<{ account: AutoChessAccount }> {
  return api<{ account: AutoChessAccount }>(`/autochess/tokens/${encodeURIComponent(serial)}`, {
    token_url: tokenUrl,
  });
}

export async function resetUnitToken(serial: string): Promise<{ account: AutoChessAccount }> {
  const resp = await fetch(`/api/ui/autochess/tokens/${encodeURIComponent(serial)}`, { method: 'DELETE' });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(data.message || '恢复默认头图失败', resp.status);
  return data as { account: AutoChessAccount };
}

// ── Multiplayer Rooms API (Requires Logged-in Account) ────────────────────

export async function listRooms(): Promise<AutoChessRoomSummary[]> {
  const res = await api<{ rooms: AutoChessRoomSummary[] }>('/autochess/rooms');
  return res.rooms;
}

export async function createRoom(params: {
  name?: string;
  arena_preset: string;
  max_players: number;
  fill_bots: boolean;
  prep_duration: number;
}): Promise<AutoChessRoomState> {
  const res = await api<{ room: AutoChessRoomState }>('/autochess/rooms', params);
  return res.room;
}

export async function joinRoom(code: string): Promise<AutoChessRoomState> {
  const res = await api<{ room: AutoChessRoomState }>(`/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/join`, {});
  return res.room;
}

export async function getRoom(code: string, spectateCid?: string | null): Promise<AutoChessRoomState> {
  const qs = spectateCid ? `?spectate=${encodeURIComponent(spectateCid)}` : '';
  const res = await api<{ room: AutoChessRoomState }>(`/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}${qs}`);
  return res.room;
}

export function controlRoom(
  code: string,
  op: 'ready' | 'config' | 'leave' | 'start',
  payload: Record<string, unknown> = {},
): Promise<{ ok: boolean; message?: string; disbanded?: boolean; room: AutoChessRoomState | null }> {
  return api(`/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/control`, {
    op,
    ...payload,
  });
}

export function sendRoomAction(
  code: string,
  action: string,
  payload: Record<string, unknown> = {},
  spectateCid?: string | null,
): Promise<{ ok: boolean; message: string; room: AutoChessRoomState }> {
  return api(`/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/action`, {
    action,
    ...payload,
    ...(spectateCid ? { spectate_cid: spectateCid } : {}),
  });
}

export function roomEventsUrl(code: string, spectateCid?: string | null): string {
  const qs = spectateCid ? `?spectate=${encodeURIComponent(spectateCid)}` : '';
  return `/api/ui/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/events${qs}`;
}
