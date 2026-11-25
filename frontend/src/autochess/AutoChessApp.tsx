import { useEffect, useState } from 'react';
import { ArrowLeft, BookOpen, BookText, Image as ImageIcon, Shield, Trophy, UserCheck, UserPlus, X } from 'lucide-react';
import { readPreferences, savePreferences } from '../settings';
import { api } from '../types';
import { getAuthMe, readGuestTokens } from './api';
import { AutoChessAuthModal } from './AutoChessAuthModal';
import { AutoChessLeaderboardModal } from './AutoChessLeaderboardModal';
import { AutoChessPage } from './AutoChessPage';
import { AutoChessTokenModal } from './AutoChessTokenModal';
import type { AutoChessAccount, AutoChessCatalog, AutoChessRuleset } from './types';
import { useMobileLandscape } from './useMobileLandscape';
import './autochess.css';

export function AutoChessApp({ onSwitchToClassic }: { onSwitchToClassic: () => void }) {
  const initialPrefs = readPreferences();
  const isMobileLandscape = useMobileLandscape();
  const [name, setName] = useState(initialPrefs.name);
  const [reduced] = useState(initialPrefs.reduced);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [wikiOpenNonce, setWikiOpenNonce] = useState(0);
  const [storyOpenNonce, setStoryOpenNonce] = useState(0);

  const [account, setAccount] = useState<AutoChessAccount | null>(null);
  const [guestTokens, setGuestTokens] = useState<Record<string, string>>(() => readGuestTokens());
  const [catalog, setCatalog] = useState<AutoChessCatalog | null>(null);
  const [authModal, setAuthModal] = useState<{ open: boolean; mode: 'login' | 'register'; prompt?: string }>({
    open: false,
    mode: 'login',
  });
  const [tokenModal, setTokenModal] = useState<{ open: boolean; serial?: string }>({ open: false });
  const [leaderboardOpen, setLeaderboardOpen] = useState(false);
  const [ruleset, setRuleset] = useState<AutoChessRuleset>('standard');
  const [leaderboardRuleset, setLeaderboardRuleset] = useState<AutoChessRuleset>('standard');
  const rankedProfile = ruleset === 'half_hs' ? account?.ranked_half_hs : account?.ranked;

  const openLeaderboard = (targetRuleset = ruleset) => {
    setLeaderboardRuleset(targetRuleset);
    setLeaderboardOpen(true);
  };

  useEffect(() => {
    document.documentElement.dataset.reduced = String(reduced);
    localStorage.setItem('combat-reduced', String(reduced));
  }, [reduced]);

  useEffect(() => {
    let active = true;
    api<{ id: string }>('/session', { name })
      .then(() => {
        if (active) setConnected(true);
      })
      .catch(e => {
        if (active) setError((e as Error).message);
      });
    getAuthMe()
      .then(res => {
        if (active) setAccount(res.authenticated ? res.account : null);
      })
      .catch(() => {
        if (active) setAccount(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const updatePlayerName = async (nextName: string) => {
    const cleaned = nextName.trim().slice(0, 20);
    if (!cleaned) {
      throw new Error('请填写指挥官称呼');
    }
    await api('/session', { name: cleaned });
    savePreferences({ name: cleaned, reduced });
    setName(cleaned);
    setConnected(true);
  };

  const displayTitle = account ? account.display_name : name;

  return (
    <div className="ac-shell" data-ac-mobile-landscape={isMobileLandscape ? 'true' : 'false'}>
      <header className="ac-topbar">
        <div className="ac-topbar-brand">
          <span className="ac-topbar-mark" aria-hidden="true">
            <img className="ac-topbar-logo" src="/ui/logo.svg" alt="" />
          </span>
          <div className="ac-topbar-title">
            <strong>星序自走棋</strong>
            <small>STARLIGHT AUTO-CHESS</small>
          </div>
        </div>

        <div className="ac-topbar-actions">
          <span className={'connection ' + (connected ? 'online' : '')}>
            <i />
            <span>{connected ? '引擎已连接' : '连接恢复中'}</span>
          </span>

          {rankedProfile && (
            <button
              type="button"
              className={`button subtle compact-button ac-topbar-rank-pill ac-tier-${rankedProfile.rank_info.tier_id}`}
              onClick={() => openLeaderboard()}
              title={`排位积分 ${rankedProfile.total_lp} · 保段卡 ${rankedProfile.shield_cards} · 局外金币 ${rankedProfile.coins}`}
            >
              <span>{rankedProfile.rank_info.full_label}</span>
              <span>· {rankedProfile.coins}金币</span>
            </button>
          )}

          <button
            type="button"
            className="button subtle compact-button ac-topbar-auth-btn"
            onClick={() => setAuthModal({ open: true, mode: 'login' })}
            title={account ? `已登录 @${account.username}` : '登录或注册自走棋账号'}
          >
            {account ? <UserCheck size={15} /> : <UserPlus size={15} />}
            <span>{account ? displayTitle : '登录 / 注册'}</span>
          </button>

          <button
            type="button"
            className="button subtle compact-button ac-topbar-lb-btn"
            onClick={() => openLeaderboard()}
            title="查看全服排位段位与积分排行榜"
          >
            <Trophy size={15} />
            <span>排行榜</span>
          </button>

          <button
            type="button"
            className="button subtle compact-button ac-topbar-token-btn"
            onClick={() => setTokenModal({ open: true })}
            title="自定义场上棋子的圆形头图或徽章"
          >
            <ImageIcon size={15} />
            <span>棋子头图</span>
          </button>

          <button
            type="button"
            className="button subtle compact-button ac-topbar-story-btn"
            onClick={() => setStoryOpenNonce(n => n + 1)}
            title="纯文字阅读角色背景故事、单列前传与大故事开篇《覆辙》"
          >
            <BookText size={15} />
            <span>故事阅读</span>
          </button>

          <button
            type="button"
            className="button subtle compact-button ac-topbar-wiki-btn"
            onClick={() => setWikiOpenNonce(n => n + 1)}
          >
            <BookOpen size={15} />
            <span>自走棋百科</span>
          </button>

          <button
            type="button"
            className="button subtle compact-button ac-mode-switch"
            onClick={onSwitchToClassic}
          >
            <ArrowLeft size={15} />
            <span>返回经典模式</span>
          </button>
        </div>
      </header>

      <main className="ac-main">
        {error && (
          <div className="error-banner" role="alert">
            <Shield size={17} />
            <span>{error}</span>
            <button onClick={() => setError('')} aria-label="关闭错误">
              <X size={16} />
            </button>
          </div>
        )}
        <AutoChessPage
          isMobileLandscape={isMobileLandscape}
          ruleset={ruleset}
          onRulesetChange={setRuleset}
          playerName={displayTitle}
          account={account}
          guestTokens={guestTokens}
          onAccountUpdate={setAccount}
          onCatalogLoaded={setCatalog}
          onOpenAuth={(mode = 'login', prompt) => setAuthModal({ open: true, mode, prompt })}
          onOpenTokenEditor={serial => setTokenModal({ open: true, serial })}
          onOpenLeaderboard={openLeaderboard}
          onPlayerNameChange={updatePlayerName}
          wikiOpenNonce={wikiOpenNonce}
          storyOpenNonce={storyOpenNonce}
          onError={setError}
        />
      </main>

      <AutoChessLeaderboardModal
        key={leaderboardRuleset}
        open={leaderboardOpen}
        ruleset={leaderboardRuleset}
        account={account}
        onClose={() => setLeaderboardOpen(false)}
        onRequestLogin={() =>
          setAuthModal({
            open: true,
            mode: 'login',
            prompt: '登录后即可参加 8 人排位混战并冲击全服段位排行榜',
          })
        }
      />

      <AutoChessAuthModal
        open={authModal.open}
        ruleset={ruleset}
        account={account}
        initialMode={authModal.mode}
        promptMessage={authModal.prompt}
        onClose={() => setAuthModal(prev => ({ ...prev, open: false }))}
        onAuthenticated={nextAcc => {
          setAccount(nextAcc);
          if (nextAcc) setName(nextAcc.display_name || nextAcc.username);
        }}
      />

      <AutoChessTokenModal
        open={tokenModal.open}
        catalog={catalog}
        account={account}
        guestTokens={guestTokens}
        initialSerial={tokenModal.serial}
        onClose={() => setTokenModal(prev => ({ ...prev, open: false }))}
        onAccountUpdate={setAccount}
        onGuestTokensUpdate={setGuestTokens}
      />
    </div>
  );
}
