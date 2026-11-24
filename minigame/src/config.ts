export type TransportMode = 'cloud' | 'http';

export interface MiniGameConfig {
  transport: TransportMode;
  cloudEnv: string;
  cloudService: string;
  apiBase: string;
  defaultPlayerName: string;
}

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env || {};

const rawTransport = (env.VITE_MG_TRANSPORT || '').trim().toLowerCase();
const cloudEnv = (env.VITE_MG_CLOUD_ENV || 'prod-d9g5x7znk95dd5373').trim();
const cloudService = (env.VITE_MG_CLOUD_SERVICE || 'backend').trim();
const apiBase = (env.VITE_MG_API_BASE || 'https://xingxu-fz.fun/api/ui').replace(/\/+$/, '');

export const MG_CONFIG: MiniGameConfig = {
  transport: rawTransport === 'cloud' ? 'cloud' : 'http',
  cloudEnv,
  cloudService,
  apiBase,
  defaultPlayerName: '星序棋手',
};
