import type {
  AutoChessAccount,
  AutoChessAuthState,
  AutoChessCatalog,
  AutoChessLeaderboardResponse,
  AutoChessMatchState,
  AutoChessMatchSummary,
  AutoChessRankedSettlement,
  AutoChessRuleset,
  AutoChessRoomState,
  AutoChessRoomSummary,
  AutoChessStoryDetail,
  AutoChessStoryIndexItem,
} from '@shared/autochess/types';
import { MG_CONFIG } from '../config';
import { apiRequest, getSavedPlayerName, setAuthToken, withSession } from './transport';

export type {
  AutoChessAccount,
  AutoChessActiveSynergy,
  AutoChessArenaPreset,
  AutoChessAugment,
  AutoChessAuthState,
  AutoChessCatalog,
  AutoChessCombatFrame,
  AutoChessCombatSnapshot,
  AutoChessCombatUnit,
  AutoChessCommanderSummary,
  AutoChessExtraStoryRef,
  AutoChessLeaderboardResponse,
  AutoChessLoreField,
  AutoChessMatchState,
  AutoChessMatchSummary,
  AutoChessOwnedUnit,
  AutoChessRankedSettlement,
  AutoChessRuleset,
  AutoChessRoomState,
  AutoChessRoomSummary,
  AutoChessRoundReport,
  AutoChessShopSlot,
  AutoChessStoryChapter,
  AutoChessStoryChapterMeta,
  AutoChessStoryDetail,
  AutoChessStoryIndexItem,
  AutoChessStoryParagraph,
  AutoChessSynergyDef,
  AutoChessUnitLore,
  AutoChessUnitMeta,
  AutoChessUnitWiki,
  AutoChessVfxEvent,
} from '@shared/autochess/types';

export { AUTOCHESS_ROLE_LABELS, resolveUnitWiki } from '@shared/autochess/types';

const storyDetailCache = new Map<string, AutoChessStoryDetail>();

export async function fetchAutoChessStories(): Promise<AutoChessStoryIndexItem[]> {
  const res = await apiRequest<{ stories: AutoChessStoryIndexItem[] }>('/autochess/stories', {
    method: 'GET',
  });
  return res.stories || [];
}

export async function fetchAutoChessStoryDetail(
  storyId: string,
  chapterId?: string,
): Promise<AutoChessStoryDetail> {
  const key = `${storyId}::${chapterId || ''}`;
  const cached = storyDetailCache.get(key);
  if (cached) return cached;
  const qs = chapterId ? `?chapter=${encodeURIComponent(chapterId)}` : '';
  const res = await apiRequest<{ story: AutoChessStoryDetail }>(
    `/autochess/stories/${encodeURIComponent(storyId)}${qs}`,
    { method: 'GET' },
  );
  if (res.story) {
    storyDetailCache.set(key, res.story);
  }
  return res.story;
}

export function ensureSession(name?: string): Promise<{ id: string; name: string; session_token?: string }> {
  return apiRequest('/session', {
    method: 'POST',
    data: { name: (name || getSavedPlayerName()).slice(0, 20) },
  });
}

export function fetchAutoChessCatalog(ruleset: AutoChessRuleset = 'standard'): Promise<AutoChessCatalog> {
  const path = ruleset === 'half_hs' ? '/autochess/catalog?ruleset=half_hs' : '/autochess/catalog';
  return apiRequest<AutoChessCatalog>(path, { method: 'GET' });
}

export function getAuthMe(): Promise<AutoChessAuthState> {
  return apiRequest<AutoChessAuthState>('/autochess/auth/me', { method: 'GET' });
}

export function registerAccount(params: {
  username: string;
  password: string;
  display_name?: string;
}): Promise<AutoChessAuthState & { auth_token?: string }> {
  return apiRequest('/autochess/auth/register', { method: 'POST', data: params });
}

export function loginAccount(params: {
  username: string;
  password: string;
}): Promise<AutoChessAuthState & { auth_token?: string }> {
  return apiRequest('/autochess/auth/login', { method: 'POST', data: params });
}

export async function logoutAccount(): Promise<{ ok: boolean }> {
  try {
    return await apiRequest<{ ok: boolean }>('/autochess/auth/logout', { method: 'POST', data: {} });
  } finally {
    setAuthToken('');
  }
}

function getWeChatLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    wx.login({
      timeout: 8000,
      success: res => {
        if (res.code) {
          resolve(res.code);
        } else {
          reject(new Error(res.errMsg || '获取微信登录凭证失败'));
        }
      },
      fail: err => reject(new Error(err?.errMsg || '调用 wx.login 失败')),
    });
  });
}

export async function loginWithWeChat(
  displayName?: string,
): Promise<AutoChessAuthState & { auth_token?: string; created?: boolean }> {
  let code = '';
  if (MG_CONFIG.transport !== 'cloud') {
    code = await getWeChatLoginCode();
  } else {
    try {
      code = await getWeChatLoginCode();
    } catch {
      // CloudRun injects X-WX-OPENID automatically even if wx.login is skipped.
      code = '';
    }
  }
  return apiRequest('/autochess/auth/wechat', {
    method: 'POST',
    data: { code, ...(displayName ? { display_name: displayName } : {}) },
  });
}

export async function bindWeChatAccount(params: {
  username: string;
  password: string;
}): Promise<AutoChessAuthState & { auth_token?: string }> {
  let code = '';
  if (MG_CONFIG.transport !== 'cloud') {
    code = await getWeChatLoginCode();
  } else {
    try {
      code = await getWeChatLoginCode();
    } catch {
      code = '';
    }
  }
  return apiRequest('/autochess/auth/wechat/bind', {
    method: 'POST',
    data: { ...params, code },
  });
}

export async function listAutoChessMatches(playerName?: string): Promise<AutoChessMatchSummary[]> {
  const res = await withSession(
    () => apiRequest<{ matches: AutoChessMatchSummary[] }>('/autochess/matches', { method: 'GET' }),
    playerName,
  );
  return res.matches;
}

export async function createAutoChessMatch(params: {
  mode: 'lobby4' | 'pve12';
  ruleset?: AutoChessRuleset;
  arena_preset: string;
  player_name: string;
}): Promise<AutoChessMatchState> {
  const res = await withSession(
    () => apiRequest<{ match: AutoChessMatchState }>('/autochess/matches', { method: 'POST', data: params }),
    params.player_name,
  );
  return res.match;
}

export async function getAutoChessMatch(id: string, playerName?: string): Promise<AutoChessMatchState> {
  const res = await withSession(
    () => apiRequest<{ match: AutoChessMatchState }>(`/autochess/matches/${id}`, { method: 'GET' }),
    playerName,
  );
  return res.match;
}

export async function deleteAutoChessMatch(id: string, playerName?: string): Promise<void> {
  await withSession(
    () => apiRequest(`/autochess/matches/${id}`, { method: 'DELETE' }),
    playerName,
  );
}

export async function sendAutoChessAction(
  id: string,
  action: string,
  payload: Record<string, unknown> = {},
  playerName?: string,
): Promise<{
  ok: boolean;
  message: string;
  match: AutoChessMatchState;
  account?: AutoChessAccount;
  ranked_settlement?: AutoChessRankedSettlement | null;
}> {
  return withSession(
    () =>
      apiRequest(`/autochess/matches/${id}/action`, {
        method: 'POST',
        data: { action, ...payload },
      }),
    playerName,
  );
}

export function pollAutoChessMatch(
  id: string,
  since: number,
  timeout = 8,
): Promise<{ changed: boolean; version: number; match: AutoChessMatchState | null }> {
  return apiRequest(`/autochess/matches/${id}/poll?since=${since}&timeout=${timeout}`, {
    method: 'GET',
    timeout: (timeout + 5) * 1000,
  });
}

export function createRankedMatch(params: {
  ruleset?: AutoChessRuleset;
  arena_preset: string;
}): Promise<{ match: AutoChessMatchState; resumed: boolean }> {
  return apiRequest('/autochess/ranked/matches', { method: 'POST', data: params });
}

export function fetchRankedLeaderboard(tier = 'all', limit = 100, ruleset: AutoChessRuleset = 'standard'): Promise<AutoChessLeaderboardResponse> {
  return apiRequest(`/autochess/ranked/leaderboard?tier=${encodeURIComponent(tier)}&limit=${limit}&ruleset=${ruleset}`, {
    method: 'GET',
  });
}

export async function listRooms(): Promise<AutoChessRoomSummary[]> {
  const res = await apiRequest<{ rooms: AutoChessRoomSummary[] }>('/autochess/rooms', { method: 'GET' });
  return res.rooms;
}

export async function createRoom(params: {
  name?: string;
  arena_preset: string;
  max_players: number;
  fill_bots: boolean;
  prep_duration: number;
}): Promise<AutoChessRoomState> {
  const res = await apiRequest<{ room: AutoChessRoomState }>('/autochess/rooms', { method: 'POST', data: params });
  return res.room;
}

export async function joinRoom(code: string): Promise<AutoChessRoomState> {
  const res = await apiRequest<{ room: AutoChessRoomState }>(
    `/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/join`,
    { method: 'POST', data: {} },
  );
  return res.room;
}

export async function getRoom(code: string, spectateCid?: string | null): Promise<AutoChessRoomState> {
  const qs = spectateCid ? `?spectate=${encodeURIComponent(spectateCid)}` : '';
  const res = await apiRequest<{ room: AutoChessRoomState }>(
    `/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}${qs}`,
    { method: 'GET' },
  );
  return res.room;
}

export function controlRoom(
  code: string,
  op: 'ready' | 'config' | 'leave' | 'start',
  payload: Record<string, unknown> = {},
): Promise<{ ok: boolean; message?: string; disbanded?: boolean; room: AutoChessRoomState | null }> {
  return apiRequest(`/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/control`, {
    method: 'POST',
    data: { op, ...payload },
  });
}

export function sendRoomAction(
  code: string,
  action: string,
  payload: Record<string, unknown> = {},
  spectateCid?: string | null,
): Promise<{ ok: boolean; message: string; room: AutoChessRoomState }> {
  return apiRequest(`/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/action`, {
    method: 'POST',
    data: {
      action,
      ...payload,
      ...(spectateCid ? { spectate_cid: spectateCid } : {}),
    },
  });
}

export function pollRoom(
  code: string,
  since: number,
  timeout = 8,
  spectateCid?: string | null,
): Promise<{ changed: boolean; version: number; room: AutoChessRoomState | null }> {
  const qs = spectateCid ? `&spectate=${encodeURIComponent(spectateCid)}` : '';
  return apiRequest(
    `/autochess/rooms/${encodeURIComponent(code.trim().toUpperCase())}/poll?since=${since}&timeout=${timeout}${qs}`,
    {
      method: 'GET',
      timeout: (timeout + 5) * 1000,
    },
  );
}
