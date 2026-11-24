import { useEffect, useMemo, useState } from 'react';
import { Check, Shield, ShieldCheck, Trash2, UserCheck, UserPlus, Users, X } from 'lucide-react';
import { ApiError, api } from './types';
import { loginAccount, logoutAccount, registerAccount, updateProfile } from './autochess/api';
import type { AccountRole, AdminPermission, AutoChessAccount } from './autochess/types';

export interface PermissionDef {
  id: AdminPermission;
  label: string;
  description: string;
}

export const PERMISSION_ITEMS: PermissionDef[] = [
  {
    id: 'player_manage',
    label: '玩家管理',
    description: '查看已注册用户列表，可选择将普通账户踢出并删除',
  },
  {
    id: 'story_manage',
    label: '剧情创作管理',
    description: '访问并编辑剧情创作室（story/editor）工作区、源码、流程图与发布',
  },
  {
    id: 'server_manage',
    label: '服务器管理',
    description: '修改服务器设置（/api/ui/settings）并查看本地敏感路径',
  },
  {
    id: 'character_manage',
    label: '角色管理',
    description: '编辑角色数据、备份恢复、AI 重训及全局规则',
  },
];

export const PERMISSION_LABELS: Record<AdminPermission, string> = {
  player_manage: '玩家管理',
  story_manage: '剧情创作管理',
  server_manage: '服务器管理',
  character_manage: '角色管理',
};

export interface AccountSummary {
  id: string;
  username: string;
  display_name: string;
  role: AccountRole;
  role_label: string;
  permissions: AdminPermission[];
  is_primary: boolean;
  created_at: number;
  wx_bound?: boolean;
  can_kick?: boolean;
  stats: {
    games: number;
    wins: number;
    top2: number;
    pve_clears: number;
  };
}

export interface AdminListResponse {
  admins: AccountSummary[];
  users: AccountSummary[];
  primary_admin: string;
}

export interface AdminMutationResponse extends AdminListResponse {
  ok: boolean;
  created?: boolean;
  account: AutoChessAccount;
}

export interface PlayerListResponse {
  players: AccountSummary[];
  primary_admin: string;
}

export interface PlayerKickResponse {
  ok: boolean;
  deleted: { id: string; username: string; display_name: string };
  revoked_tokens: number;
  players: AccountSummary[];
}

export function roleLabel(account: Pick<AutoChessAccount, 'role' | 'role_label'> | null): string {
  if (!account) return '游客';
  if (account.role_label) return account.role_label;
  if (account.role === 'super_admin') return '主管理员';
  if (account.role === 'admin') return '管理员';
  return '普通用户';
}

export function isSuperAdmin(account: AutoChessAccount | null): boolean {
  return Boolean(account && (account.is_super_admin || account.role === 'super_admin'));
}

export function hasPermission(account: AutoChessAccount | null, perm: AdminPermission): boolean {
  if (!account) return false;
  if (isSuperAdmin(account)) return true;
  return account.role === 'admin' && Array.isArray(account.permissions) && account.permissions.includes(perm);
}

export function fetchAdmins(): Promise<AdminListResponse> {
  return api<AdminListResponse>('/admins');
}

export function addAdmin(payload: {
  username: string;
  permissions: AdminPermission[];
  password?: string;
  display_name?: string;
}): Promise<AdminMutationResponse> {
  return api<AdminMutationResponse>('/admins', payload);
}

export function updateAdminPermissions(
  accountId: string,
  permissions: AdminPermission[],
): Promise<AdminMutationResponse> {
  return api<AdminMutationResponse>('/admins/permissions', { account_id: accountId, permissions });
}

export function removeAdmin(accountId: string): Promise<AdminMutationResponse> {
  return api<AdminMutationResponse>('/admins/remove', { account_id: accountId });
}

export function fetchPlayers(): Promise<PlayerListResponse> {
  return api<PlayerListResponse>('/players');
}

export function kickDeletePlayer(accountId: string): Promise<PlayerKickResponse> {
  return api<PlayerKickResponse>('/players/kick', { account_id: accountId });
}

export function ClassicAuthModal({
  open,
  account,
  initialMode = 'login',
  promptMessage,
  onClose,
  onAuthenticated,
}: {
  open: boolean;
  account: AutoChessAccount | null;
  initialMode?: 'login' | 'register';
  promptMessage?: string;
  onClose: () => void;
  onAuthenticated: (account: AutoChessAccount | null) => void;
}) {
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

  const grantedPerms = account?.permissions || [];

  return (
    <div className="modal-scrim" onClick={onClose}>
      <section
        className="modal classic-auth-modal"
        role="dialog"
        aria-modal="true"
        aria-label="星序账号登录"
        onClick={e => e.stopPropagation()}
      >
        <header>
          <h2>{account ? `账号中心 · ${account.display_name}` : '星序账号登录'}</h2>
          <button type="button" className="icon-button" title="关闭" aria-label="关闭" onClick={onClose}>
            <X size={19} />
          </button>
        </header>

        <p>
          {account
            ? `账号 @${account.username} · 与自走棋共用同一账号体系`
            : '与自走棋共用同一账号体系：游客仅可浏览与游玩，不可编辑数据或服务器设置'}
        </p>

        {promptMessage && !account && <p className="error-text">{promptMessage}</p>}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="save-message" role="status">
            <Check size={15} />
            {notice}
          </p>
        )}

        {!account ? (
          <>
            <div className="tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'login'}
                className={tab === 'login' ? 'active' : ''}
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
                className={tab === 'register' ? 'active' : ''}
                onClick={() => {
                  setTab('register');
                  setError('');
                }}
              >
                注册新账号
              </button>
            </div>

            <form onSubmit={submitAuth}>
              <label className="field">
                用户名（3–20位）
                <input
                  type="text"
                  autoComplete="username"
                  placeholder="输入用户名"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  required
                />
              </label>

              {tab === 'register' && (
                <label className="field">
                  显示昵称（可选，默认同用户名）
                  <input
                    type="text"
                    maxLength={24}
                    placeholder="用于房间与战绩显示"
                    value={displayName}
                    onChange={e => setDisplayName(e.target.value)}
                  />
                </label>
              )}

              <label className="field">
                密码（至少 6 位）
                <input
                  type="password"
                  autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
                  placeholder="请输入密码"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                />
              </label>

              <div className="modal-note">
                <Shield size={17} />
                <span>游客不能编辑角色、剧情工作区、玩家账号或服务器设置；需管理员授权后方可编辑。</span>
              </div>

              <div className="modal-actions">
                <button type="button" className="button" onClick={onClose}>
                  取消
                </button>
                <button type="submit" className="button primary" disabled={busy}>
                  {busy ? '提交中…' : tab === 'login' ? '立即登录' : '注册并登录'}
                </button>
              </div>
            </form>
          </>
        ) : (
          <>
            <div className="auth-summary-card">
              <div className="auth-summary-head">
                <span>账号权限</span>
                <span className={`role-pill role-${account.role || 'user'}`}>
                  {isSuperAdmin(account) ? <ShieldCheck size={13} /> : <UserCheck size={13} />}
                  {roleLabel(account)}
                </span>
              </div>
              <div className="perm-pill-row">
                {grantedPerms.length ? (
                  grantedPerms.map(perm => (
                    <span key={perm} className="perm-pill">
                      {PERMISSION_LABELS[perm] || perm}
                    </span>
                  ))
                ) : (
                  <span className="muted">无后台编辑权限（普通账号）</span>
                )}
              </div>
            </div>

            <form onSubmit={submitProfile}>
              <label className="field">
                显示昵称
                <input
                  type="text"
                  maxLength={24}
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  required
                />
              </label>
              <label className="field">
                原密码（修改密码时填写）
                <input
                  type="password"
                  autoComplete="current-password"
                  value={oldPassword}
                  onChange={e => setOldPassword(e.target.value)}
                  placeholder="不改密码请留空"
                />
              </label>
              <label className="field">
                新密码（至少 6 位）
                <input
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  placeholder="输入新密码"
                />
              </label>

              <div className="modal-actions auth-modal-actions-between">
                <button type="button" className="button stop-button" onClick={handleLogout} disabled={busy}>
                  退出登录
                </button>
                <button type="submit" className="button primary" disabled={busy}>
                  {busy ? '保存中…' : '保存账号资料'}
                </button>
              </div>
            </form>
          </>
        )}
      </section>
    </div>
  );
}

export function PermissionGatePanel({
  title,
  permissionLabel,
  account,
  onOpenAuth,
  onBack,
  backLabel = '返回',
}: {
  title: string;
  permissionLabel: string;
  account: AutoChessAccount | null;
  onOpenAuth: (mode?: 'login' | 'register', prompt?: string) => void;
  onBack?: () => void;
  backLabel?: string;
}) {
  return (
    <div className="page">
      <div className="section-heading">
        <div>
          <h1>{title}</h1>
          <p className="muted">统一账号权限受控区 · 仅授权管理员可编辑</p>
        </div>
        {onBack && (
          <button type="button" className="button subtle" onClick={onBack}>
            {backLabel}
          </button>
        )}
      </div>

      <section className="panel auth-gate-panel">
        {!account ? (
          <>
            <div className="auth-gate-badge">
              <Shield size={20} />
              <strong>当前为游客身份，游客不能编辑</strong>
            </div>
            <p className="muted">
              经典模式已与自走棋共用同一套账号体系。访问或修改「{title}」需要登录拥有「{permissionLabel}
              」权限的管理员账号。
            </p>
            <div className="expansion-toolbar">
              <button
                type="button"
                className="button primary"
                onClick={() => onOpenAuth('login', `请登录拥有「${permissionLabel}」权限的管理员账号`)}
              >
                <UserPlus size={16} />
                登录账号
              </button>
              <button type="button" className="button" onClick={() => onOpenAuth('register')}>
                注册新账号
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="auth-gate-badge">
              <UserCheck size={20} />
              <strong>
                当前账号：@{account.username}
                <span className={`role-pill role-${account.role || 'user'}`}>{roleLabel(account)}</span>
              </strong>
            </div>
            <p className="muted">
              当前账号缺少「{permissionLabel}」权限，无法在此编辑。仅有主管理员（fanmm01）可增删管理员并分配权限。
            </p>
            <div className="expansion-toolbar">
              <button
                type="button"
                className="button primary"
                onClick={() => onOpenAuth('login', `请切换至拥有「${permissionLabel}」权限的管理员账号`)}
              >
                切换账号 / 账号中心
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

export function PlayerManagementPanel({ onError }: { onError: (message: string) => void }) {
  const [players, setPlayers] = useState<AccountSummary[]>([]);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState('');
  const [message, setMessage] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetchPlayers();
      setPlayers(res.players);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return players;
    return players.filter(
      p => p.username.toLowerCase().includes(q) || p.display_name.toLowerCase().includes(q),
    );
  }, [players, filter]);

  const handleKick = async (player: AccountSummary) => {
    if (
      !window.confirm(
        `确定要踢出并永久删除账号「${player.display_name}（@${player.username}）」吗？\n该账号的登录凭证将立即失效，账号数据与战绩将被清除且不可恢复。`,
      )
    ) {
      return;
    }
    setBusyId(player.id);
    setMessage('');
    try {
      const res = await kickDeletePlayer(player.id);
      setPlayers(res.players);
      setMessage(
        `已踢出并删除账号「${res.deleted.display_name}（@${res.deleted.username}）」，已失效 ${res.revoked_tokens} 个登录会话`,
      );
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusyId('');
    }
  };

  return (
    <section className="panel editor-content player-manage-panel">
      <div className="section-heading">
        <div>
          <h2>玩家管理</h2>
          <p className="muted">管理已注册账号列表（共 {players.length} 名）；可踢出并删除违约或冗余账号。</p>
        </div>
        <button type="button" className="button subtle" disabled={loading} onClick={() => void load()}>
          刷新列表
        </button>
      </div>

      {message && (
        <p className="save-message" role="status">
          <Check size={15} />
          {message}
        </p>
      )}

      <div className="account-toolbar">
        <input
          type="search"
          aria-label="搜索已注册用户"
          placeholder="搜索用户名或昵称…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
      </div>

      {loading && !players.length ? (
        <p className="muted">正在读取已注册用户…</p>
      ) : !filtered.length ? (
        <p className="muted">没有匹配的已注册账号。</p>
      ) : (
        <div className="account-list">
          {filtered.map(player => (
            <div key={player.id} className="account-row">
              <div className="account-row-main">
                <div className="account-row-title">
                  <strong>{player.display_name}</strong>
                  <span className="muted">@{player.username}</span>
                  <span className={`role-pill role-${player.role}`}>{player.role_label}</span>
                  {player.wx_bound && <span className="tag">微信已绑</span>}
                </div>
                <div className="account-row-meta">
                  <span>
                    自走棋：{player.stats.wins} 胜 / {player.stats.games} 局
                  </span>
                  {player.permissions.length > 0 && (
                    <span>
                      权限：{player.permissions.map(p => PERMISSION_LABELS[p] || p).join('、')}
                    </span>
                  )}
                </div>
              </div>
              <div className="account-row-actions">
                {player.can_kick ? (
                  <button
                    type="button"
                    className="button stop-button compact-button"
                    disabled={busyId === player.id}
                    onClick={() => void handleKick(player)}
                  >
                    <Trash2 size={14} />
                    {busyId === player.id ? '处理中…' : '踢出删除'}
                  </button>
                ) : (
                  <span className="muted">
                    {player.is_primary ? '主管理员受保护' : '不可删除'}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function AdminManagementPanel({ onError }: { onError: (message: string) => void }) {
  const [admins, setAdmins] = useState<AccountSummary[]>([]);
  const [users, setUsers] = useState<AccountSummary[]>([]);
  const [permDrafts, setPermDrafts] = useState<Record<string, AdminPermission[]>>({});
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [addPerms, setAddPerms] = useState<AdminPermission[]>(
    PERMISSION_ITEMS.map(item => item.id),
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const syncLists = (res: AdminListResponse) => {
    setAdmins(res.admins);
    setUsers(res.users);
    setPermDrafts(
      Object.fromEntries(res.admins.map(item => [item.id, [...(item.permissions || [])]])),
    );
  };

  const load = async () => {
    setLoading(true);
    try {
      syncLists(await fetchAdmins());
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const toggleDraftPerm = (accountId: string, perm: AdminPermission) => {
    setPermDrafts(old => {
      const current = old[accountId] || [];
      const next = current.includes(perm)
        ? current.filter(p => p !== perm)
        : [...current, perm];
      return { ...old, [accountId]: next };
    });
  };

  const toggleAddPerm = (perm: AdminPermission) => {
    setAddPerms(old =>
      old.includes(perm) ? old.filter(p => p !== perm) : [...old, perm],
    );
  };

  const handleSavePermissions = async (admin: AccountSummary) => {
    const draft = permDrafts[admin.id] || [];
    if (!draft.length) {
      onError('请至少为管理员保留一项权限');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const res = await updateAdminPermissions(admin.id, draft);
      syncLists(res);
      setMessage(`已更新管理员 @${admin.username} 的权限`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (admin: AccountSummary) => {
    if (
      !window.confirm(
        `确定要移除「${admin.display_name}（@${admin.username}）」的管理员权限吗？\n移除后该账号将降为普通用户，保留自走棋战绩与数据。`,
      )
    ) {
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const res = await removeAdmin(admin.id);
      syncLists(res);
      setMessage(`已移除 @${admin.username} 的管理员权限`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addPerms.length) {
      onError('请至少勾选一项管理员权限');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const res = await addAdmin({
        username: username.trim(),
        permissions: addPerms,
        ...(password ? { password } : {}),
        ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
      });
      syncLists(res);
      setUsername('');
      setPassword('');
      setDisplayName('');
      setMessage(
        res.created
          ? `已创建管理员账号 @${res.account.username}`
          : `已将 @${res.account.username} 设为管理员`,
      );
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handlePromoteUser = async (user: AccountSummary) => {
    if (!addPerms.length) {
      onError('请在上方「添加管理员」区域至少勾选一项权限后再授权');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const res = await addAdmin({ username: user.username, permissions: addPerms });
      syncLists(res);
      setMessage(`已将 @${user.username} 设为管理员`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel editor-content admin-manage-panel">
      <div className="section-heading">
        <div>
          <h2>管理员管理</h2>
          <p className="muted">
            仅主管理员（fanmm01）可增删管理员并分配权限；支持按模块精细授权。
          </p>
        </div>
        <button type="button" className="button subtle" disabled={loading || busy} onClick={() => void load()}>
          刷新
        </button>
      </div>

      {message && (
        <p className="save-message" role="status">
          <Check size={15} />
          {message}
        </p>
      )}

      <h3>当前管理员（{admins.length}）</h3>
      <div className="account-list">
        {admins.map(admin => {
          const draft = permDrafts[admin.id] || admin.permissions || [];
          const sortedOrig = [...(admin.permissions || [])].sort().join(',');
          const sortedDraft = [...draft].sort().join(',');
          const dirty = sortedOrig !== sortedDraft;
          return (
            <div key={admin.id} className="account-row admin-row">
              <div className="account-row-main">
                <div className="account-row-title">
                  <strong>{admin.display_name}</strong>
                  <span className="muted">@{admin.username}</span>
                  <span className={`role-pill role-${admin.role}`}>{admin.role_label}</span>
                </div>
                {admin.is_primary ? (
                  <div className="perm-pill-row">
                    {PERMISSION_ITEMS.map(item => (
                      <span key={item.id} className="perm-pill">
                        {item.label}
                      </span>
                    ))}
                    <span className="muted">主管理员不可修改或移除</span>
                  </div>
                ) : (
                  <div className="perm-checkboxes">
                    {PERMISSION_ITEMS.map(item => (
                      <label key={item.id} title={item.description}>
                        <input
                          type="checkbox"
                          checked={draft.includes(item.id)}
                          disabled={busy}
                          onChange={() => toggleDraftPerm(admin.id, item.id)}
                        />
                        {item.label}
                      </label>
                    ))}
                  </div>
                )}
              </div>
              {!admin.is_primary && (
                <div className="account-row-actions">
                  <button
                    type="button"
                    className="button primary compact-button"
                    disabled={busy || !dirty || !draft.length}
                    onClick={() => void handleSavePermissions(admin)}
                  >
                    保存权限
                  </button>
                  <button
                    type="button"
                    className="button stop-button compact-button"
                    disabled={busy}
                    onClick={() => void handleRevoke(admin)}
                  >
                    移除管理员
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <form className="admin-add-form" onSubmit={handleAddSubmit}>
        <h3>
          <Users size={16} /> 添加管理员
        </h3>
        <p className="muted">
          输入已注册用户名即可提权；若该账号尚未注册，请同时填写初始密码直接创建。
        </p>

        <div className="admin-add-fields">
          <label className="field">
            用户名（必填）
            <input
              type="text"
              aria-label="新管理员用户名"
              placeholder="3–20 位用户名"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
            />
          </label>
          <label className="field">
            初始密码（新建账号时填写）
            <input
              type="password"
              aria-label="新管理员初始密码"
              placeholder="已有账号请留空"
              value={password}
              onChange={e => setPassword(e.target.value)}
            />
          </label>
          <label className="field">
            显示昵称（新建时可选）
            <input
              type="text"
              aria-label="新管理员昵称"
              maxLength={24}
              placeholder="可选"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
            />
          </label>
        </div>

        <div className="admin-perm-picker">
          <span className="muted">分配权限（至少选一项）：</span>
          <div className="perm-checkboxes">
            {PERMISSION_ITEMS.map(item => (
              <label key={item.id} title={item.description}>
                <input
                  type="checkbox"
                  checked={addPerms.includes(item.id)}
                  disabled={busy}
                  onChange={() => toggleAddPerm(item.id)}
                />
                {item.label}
              </label>
            ))}
          </div>
        </div>

        <button type="submit" className="button primary" disabled={busy || !username.trim() || !addPerms.length}>
          添加管理员
        </button>
      </form>

      {users.length > 0 && (
        <div className="admin-users-quick">
          <h3>已注册普通用户（{users.length}）</h3>
          <p className="muted">将按照上方勾选的权限快速升级为管理员：</p>
          <div className="account-list">
            {users.map(user => (
              <div key={user.id} className="account-row">
                <div className="account-row-main">
                  <div className="account-row-title">
                    <strong>{user.display_name}</strong>
                    <span className="muted">@{user.username}</span>
                    <span className="role-pill role-user">普通用户</span>
                  </div>
                </div>
                <div className="account-row-actions">
                  <button
                    type="button"
                    className="button compact-button"
                    disabled={busy || !addPerms.length}
                    onClick={() => void handlePromoteUser(user)}
                  >
                    设为管理员
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
