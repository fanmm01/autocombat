import { useEffect, useState } from 'react';
import { ApiError } from '../types';
import { loginAccount, logoutAccount, registerAccount, updateProfile } from './api';
import type { AutoChessAccount } from './types';

const AC_PERM_LABELS: Record<string, string> = {
  player_manage: '玩家管理',
  story_manage: '剧情创作管理',
  server_manage: '服务器管理',
  character_manage: '角色管理',
};

interface Props {
  open: boolean;
  account: AutoChessAccount | null;
  initialMode?: 'login' | 'register';
  promptMessage?: string;
  onClose: () => void;
  onAuthenticated: (account: AutoChessAccount | null) => void;
}

export function AutoChessAuthModal({
  open,
  account,
  initialMode = 'login',
  promptMessage,
  onClose,
  onAuthenticated,
}: Props) {
  const [tab, setTab] = useState<'login' | 'register'>(initialMode);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!open) return;
    setError('');
    setNotice('');
    setTab(initialMode);
    if (account) {
      setDisplayName(account.display_name || account.username);
      setOldPassword('');
      setNewPassword('');
    } else {
      setPassword('');
    }
  }, [open, initialMode, account]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function submitAuth(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setNotice('');
    const u = username.trim();
    if (u.length < 3 || u.length > 20) {
      setError('用户名需为 3–20 位字符（支持字母、数字、汉字、_、-）');
      return;
    }
    if (password.length < 6) {
      setError('密码长度至少为 6 位');
      return;
    }
    setBusy(true);
    try {
      const res =
        tab === 'login'
          ? await loginAccount({ username: u, password })
          : await registerAccount({
              username: u,
              password,
              display_name: displayName.trim() || undefined,
            });
      onAuthenticated(res.account);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitProfile(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setNotice('');
    if (newPassword && newPassword.length < 6) {
      setError('新密码长度至少为 6 位');
      return;
    }
    setBusy(true);
    try {
      const payload: { display_name?: string; old_password?: string; new_password?: string } = {
        display_name: displayName.trim(),
      };
      if (newPassword) {
        payload.old_password = oldPassword;
        payload.new_password = newPassword;
      }
      const res = await updateProfile(payload);
      onAuthenticated(res.account);
      setOldPassword('');
      setNewPassword('');
      setNotice('账号资料已保存并同步');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    setError('');
    try {
      await logoutAccount();
      onAuthenticated(null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ac-modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="自走棋账号中心">
      <div className="ac-modal ac-auth-modal" onClick={e => e.stopPropagation()}>
        <div className="ac-modal-head">
          <div>
            <h3>{account ? `指挥官账号：${account.display_name}` : '星序统一账号中心'}</h3>
            <p>
              {account
                ? `账号 @${account.username} · 权限：${account.role_label || '普通用户'}${
                    account.permissions?.length
                      ? `（${account.permissions.map(p => AC_PERM_LABELS[p] || p).join('、')}）`
                      : ''
                  } · 与经典模式共用同一账号体系`
                : '与经典模式共用账号体系：登录后解锁多人联机开房间、排位赛与跨端数据互通'}
            </p>
          </div>
          <button type="button" className="ac-btn ac-btn-ghost ac-btn-sm" onClick={onClose}>
            ✕ 关闭
          </button>
        </div>

        {promptMessage && !account && <div className="ac-banner ac-banner-warn">{promptMessage}</div>}
        {error && <div className="ac-banner ac-banner-err">{error}</div>}
        {notice && <div className="ac-banner ac-banner-ok">{notice}</div>}

        {!account ? (
          <div className="ac-auth-body">
            <div className="ac-auth-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'login'}
                className={`ac-wiki-tab ${tab === 'login' ? 'active' : ''}`}
                onClick={() => {
                  setTab('login');
                  setError('');
                }}
              >
                登录账号
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'register'}
                className={`ac-wiki-tab ${tab === 'register' ? 'active' : ''}`}
                onClick={() => {
                  setTab('register');
                  setError('');
                }}
              >
                注册新账号
              </button>
            </div>

            <form className="ac-auth-form" onSubmit={submitAuth}>
              <label className="ac-field">
                <span>用户名（3–20位）</span>
                <input
                  type="text"
                  autoComplete="username"
                  placeholder="例如：star_commander"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  required
                />
              </label>

              {tab === 'register' && (
                <label className="ac-field">
                  <span>游戏昵称（可选，默认同用户名）</span>
                  <input
                    type="text"
                    maxLength={24}
                    placeholder="对局内显示的指挥官名称"
                    value={displayName}
                    onChange={e => setDisplayName(e.target.value)}
                  />
                </label>
              )}

              <label className="ac-field">
                <span>密码（至少 6 位）</span>
                <input
                  type="password"
                  autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
                  placeholder="请输入密码"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                />
              </label>

              <div className="ac-auth-foot-note">
                未登录也可直接体验「12波次PvE闯关」与「4人AI练习大厅」；登录后开放多人联机开房间与跨端数据互通。
              </div>

              <div className="ac-modal-actions">
                <button type="submit" className="ac-btn ac-btn-primary" disabled={busy}>
                  {busy ? '提交中...' : tab === 'login' ? '立即登录' : '注册并登录'}
                </button>
              </div>
            </form>
          </div>
        ) : (
          <div className="ac-auth-body">
            {account.ranked && (
              <div className="ac-auth-ranked-card">
                <div className="ac-auth-ranked-head">
                  <span className={`ac-tier-badge ac-tier-${account.ranked.rank_info.tier_id}`}>
                    {account.ranked.rank_info.full_label}
                  </span>
                  <strong>{account.ranked.total_lp} 排位分</strong>
                  <span className="muted" style={{ fontSize: '0.76rem' }}>
                    {account.ranked.silver_floor_unlocked ? '已解锁白银永不掉青铜保护' : '距白银保护还需晋级白银'}
                  </span>
                </div>
                <div className="ac-auth-ranked-meta">
                  <span>排位 {account.ranked.wins}/{account.ranked.games} 胜 ({account.ranked.firsts}吃鸡)</span>
                  <span>连胜 {account.ranked.win_streak}</span>
                  <span>保段卡 {account.ranked.shield_cards}/{account.ranked.shield_card_cap}</span>
                  <span>局外金币 {account.ranked.coins}</span>
                </div>
              </div>
            )}

            <div className="ac-stats-grid">
              <div className="ac-stat-card">
                <div className="ac-stat-label">累计战绩</div>
                <div className="ac-stat-val">
                  {account.stats.wins} 胜 / {account.stats.games} 局
                </div>
              </div>
              <div className="ac-stat-card">
                <div className="ac-stat-label">前二 / 试炼通关</div>
                <div className="ac-stat-val">
                  {account.stats.top2} 前二 · {account.stats.pve_clears} 通关
                </div>
              </div>
              <div className="ac-stat-card">
                <div className="ac-stat-label">已定制头图</div>
                <div className="ac-stat-val">{Object.keys(account.token_overrides || {}).length} 枚</div>
              </div>
            </div>

            <form className="ac-auth-form" onSubmit={submitProfile}>
              <label className="ac-field">
                <span>显示昵称</span>
                <input
                  type="text"
                  maxLength={24}
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  required
                />
              </label>

              <div className="ac-auth-divider">可选：修改密码（留空则仅保存昵称）</div>

              <label className="ac-field">
                <span>原密码</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  value={oldPassword}
                  onChange={e => setOldPassword(e.target.value)}
                  placeholder="修改密码时填写"
                />
              </label>

              <label className="ac-field">
                <span>新密码（至少 6 位）</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  placeholder="输入新密码"
                />
              </label>

              <div className="ac-modal-actions ac-modal-actions-between">
                <button type="button" className="ac-btn ac-btn-danger" onClick={handleLogout} disabled={busy}>
                  退出登录
                </button>
                <button type="submit" className="ac-btn ac-btn-primary" disabled={busy}>
                  {busy ? '保存中...' : '保存账号资料'}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
