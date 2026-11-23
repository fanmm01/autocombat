import { ApiError, api } from '../types';
import type { AutoChessCatalog, AutoChessMatchState, AutoChessMatchSummary } from './types';

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
