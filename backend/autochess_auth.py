"""Independent Auto-Chess SQLite account authentication, cross-client state sharing, and custom tokens."""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from autochess_catalog import UNIT_CATALOG, normalize_ruleset
from autochess_ranked import (
    build_leaderboard,
    default_ranked_profile,
    public_ranked_profile,
    settle_ranked_match,
)

KIND_ACCOUNT = 'autochess_account'
KIND_TOKEN = 'autochess_auth_token'
KIND_WX_BIND = 'autochess_wx_bind'

ROLE_USER = 'user'
ROLE_ADMIN = 'admin'
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_LABELS = {
    ROLE_USER: '普通用户',
    ROLE_ADMIN: '管理员',
    ROLE_SUPER_ADMIN: '主管理员',
}

PERM_PLAYER_MANAGE = 'player_manage'
PERM_STORY_MANAGE = 'story_manage'
PERM_SERVER_MANAGE = 'server_manage'
PERM_CHARACTER_MANAGE = 'character_manage'
ALL_PERMISSIONS = (
    PERM_PLAYER_MANAGE,
    PERM_STORY_MANAGE,
    PERM_SERVER_MANAGE,
    PERM_CHARACTER_MANAGE,
)
PERMISSION_LABELS = {
    PERM_PLAYER_MANAGE: '玩家管理',
    PERM_STORY_MANAGE: '剧情创作管理',
    PERM_SERVER_MANAGE: '服务器管理',
    PERM_CHARACTER_MANAGE: '角色管理',
}
PERMISSION_DEFS = [
    {
        'id': PERM_PLAYER_MANAGE,
        'label': PERMISSION_LABELS[PERM_PLAYER_MANAGE],
        'description': '查看已注册用户列表，可选择将普通账户踢出并删除',
    },
    {
        'id': PERM_STORY_MANAGE,
        'label': PERMISSION_LABELS[PERM_STORY_MANAGE],
        'description': '访问并编辑剧情创作室（story/editor）工作区、源码、流程图与发布',
    },
    {
        'id': PERM_SERVER_MANAGE,
        'label': PERMISSION_LABELS[PERM_SERVER_MANAGE],
        'description': '修改服务器设置（/api/ui/settings）并查看本地敏感路径',
    },
    {
        'id': PERM_CHARACTER_MANAGE,
        'label': PERMISSION_LABELS[PERM_CHARACTER_MANAGE],
        'description': '编辑角色数据（/api/ui/data*）、备份恢复（/api/ui/backups*）、AI 重训（/api/ui/training*）及全局规则',
    },
]

PRIMARY_ADMIN_USERNAME = 'fanmm01'
PRIMARY_ADMIN_ID = 'fanmm01'
PRIMARY_ADMIN_DEFAULT_PASSWORD = 'fanmm0829'

_USERNAME_RE = re.compile(r'^[\w\u4e00-\u9fff-]{3,20}$')
_DATA_IMAGE_RE = re.compile(r'^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$', re.IGNORECASE)
_HTTP_URL_RE = re.compile(r'^https?://[^\s<>"\']{4,512}$', re.IGNORECASE)
_ICON_URL_RE = re.compile(r'^/ui/(icons|portraits)/[A-Za-z0-9_.-]{3,64}$')
_TOKEN_MAX_DATA_LEN = 240_000
_PBKDF2_ITERATIONS = 120_000
_SESSION_TTL_SEC = 86400 * 30


class AuthError(ValueError):
    """Domain error with explicit HTTP status code for account operations."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        bytes.fromhex(salt_hex),
        _PBKDF2_ITERATIONS,
    ).hex()


def normalize_role(rec):
    if not rec:
        return ROLE_USER
    if rec.get('id') == PRIMARY_ADMIN_ID:
        return ROLE_SUPER_ADMIN
    if rec.get('role') == ROLE_ADMIN:
        return ROLE_ADMIN
    return ROLE_USER


def normalize_permissions(rec, role=None):
    effective_role = role or normalize_role(rec)
    if effective_role == ROLE_SUPER_ADMIN:
        return list(ALL_PERMISSIONS)
    if effective_role != ROLE_ADMIN:
        return []
    raw = (rec or {}).get('permissions')
    if raw is None:
        return list(ALL_PERMISSIONS)
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [perm for perm in ALL_PERMISSIONS if perm in raw]


def validate_permissions(permissions, allow_none=False):
    if permissions is None:
        if allow_none:
            return list(ALL_PERMISSIONS)
        raise AuthError('请选择至少一项管理员权限', 400)
    if not isinstance(permissions, (list, tuple)) or any(not isinstance(item, str) for item in permissions):
        raise AuthError('权限列表格式不正确', 400)
    unknown = [item for item in permissions if item not in ALL_PERMISSIONS]
    if unknown:
        raise AuthError(f'包含未知权限：{unknown[0]}', 400)
    normalized = [perm for perm in ALL_PERMISSIONS if perm in permissions]
    if not normalized:
        raise AuthError('请至少为管理员分配一项权限', 400)
    return normalized


def validate_token_url(token_url):
    val = str(token_url or '').strip()
    if not val:
        raise AuthError('头图地址不能为空', 400)
    if _DATA_IMAGE_RE.match(val):
        if len(val) > _TOKEN_MAX_DATA_LEN:
            raise AuthError('自定义头像图片过大，请裁剪压缩后再上传（需 <= 180KB）', 400)
        return val
    if _ICON_URL_RE.match(val) or _HTTP_URL_RE.match(val):
        return val
    raise AuthError('头图仅支持本地图片上传、标准 HTTP(S) 图片链接或内置徽章路径', 400)


def exchange_wechat_code(code, appid=None, secret=None):
    """Exchange a WeChat Mini Game/Program wx.login code for openid via jscode2session."""
    clean_code = str(code or '').strip()
    if not clean_code:
        raise AuthError('缺少微信登录 code', 400)
    wx_appid = (appid or os.environ.get('AUTOCOMBAT_WX_APPID') or '').strip()
    wx_secret = (secret or os.environ.get('AUTOCOMBAT_WX_SECRET') or '').strip()
    if not wx_appid or not wx_secret:
        raise AuthError('服务端未配置微信小程序 AppID/Secret（非云托管环境需配置 AUTOCOMBAT_WX_APPID 与 AUTOCOMBAT_WX_SECRET）', 503)
    query = urllib.parse.urlencode({
        'appid': wx_appid,
        'secret': wx_secret,
        'js_code': clean_code,
        'grant_type': 'authorization_code',
    })
    url = f'https://api.weixin.qq.com/sns/jscode2session?{query}'
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AuthError(f'微信登录凭证校验失败：{exc}', 502) from exc
    if data.get('errcode'):
        raise AuthError(f"微信登录校验失败：{data.get('errmsg') or data.get('errcode')}", 401)
    openid = str(data.get('openid') or '').strip()
    if not openid:
        raise AuthError('微信登录未返回有效的 openid', 502)
    return openid


class AutoChessAuthService:
    """Manages salted PBKDF2 accounts, role permissions, cookies, stats, and custom token overrides in ui_store."""

    def __init__(self, store, cookie_name='autochess_auth'):
        self.store = store
        self.cookie_name = cookie_name
        self.lock = threading.RLock()
        self.ensure_primary_admin()

    def ensure_primary_admin(self):
        """Ensure the primary administrator account exists without overwriting an updated password."""
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, PRIMARY_ADMIN_ID)
            if rec is None:
                salt = secrets.token_hex(16)
                initial_pw = os.environ.get('AUTOCOMBAT_PRIMARY_ADMIN_PASSWORD') or PRIMARY_ADMIN_DEFAULT_PASSWORD
                rec = {
                    'id': PRIMARY_ADMIN_ID,
                    'username': PRIMARY_ADMIN_USERNAME,
                    'display_name': PRIMARY_ADMIN_USERNAME,
                    'role': ROLE_SUPER_ADMIN,
                    'permissions': list(ALL_PERMISSIONS),
                    'password_salt': salt,
                    'password_hash': _hash_password(initial_pw, salt),
                    'created_at': time.time(),
                    'token_overrides': {},
                    'stats': {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0},
                    'ranked': default_ranked_profile(),
                    'ranked_half_hs': default_ranked_profile(),
                }
                self.store.put(KIND_ACCOUNT, rec, updated_at=0.5)
                return rec
            if rec.get('role') != ROLE_SUPER_ADMIN or rec.get('permissions') != list(ALL_PERMISSIONS):
                rec['role'] = ROLE_SUPER_ADMIN
                rec['permissions'] = list(ALL_PERMISSIONS)
                self.store.put(KIND_ACCOUNT, rec)
            return rec

    @staticmethod
    def normalize_username(username):
        raw = str(username or '').strip()
        if not _USERNAME_RE.match(raw):
            raise AuthError('账号名需为 3–20 位中文、字母、数字或下划线/连字符', 400)
        return raw, raw.lower()

    @staticmethod
    def public_account(rec):
        if not rec:
            return None
        stats = rec.get('stats') or {}
        role = normalize_role(rec)
        perms = normalize_permissions(rec, role)
        ranked = public_ranked_profile(rec.get('ranked'))
        ranked_half_hs = public_ranked_profile(rec.get('ranked_half_hs'))
        ranked_half_hs['coins'] = ranked['coins']
        return {
            'id': rec['id'],
            'username': rec.get('username', rec['id']),
            'display_name': rec.get('display_name') or rec.get('username', rec['id']),
            'role': role,
            'role_label': ROLE_LABELS[role],
            'permissions': perms,
            'can_edit': bool(perms),
            'is_super_admin': role == ROLE_SUPER_ADMIN,
            'created_at': rec.get('created_at', 0),
            'token_overrides': dict(rec.get('token_overrides') or {}),
            'stats': {
                'games': int(stats.get('games', 0) or 0),
                'wins': int(stats.get('wins', 0) or 0),
                'top2': int(stats.get('top2', 0) or 0),
                'pve_clears': int(stats.get('pve_clears', 0) or 0),
            },
            'ranked': ranked,
            'ranked_half_hs': ranked_half_hs,
            'wx_bound': bool(rec.get('wx_openid')),
        }

    @staticmethod
    def is_super_admin(account):
        return bool(
            account
            and account.get('id') == PRIMARY_ADMIN_ID
            and account.get('role') == ROLE_SUPER_ADMIN
        )

    @staticmethod
    def is_admin(account):
        return bool(account and account.get('role') in (ROLE_ADMIN, ROLE_SUPER_ADMIN))

    @staticmethod
    def has_permission(account, perm):
        if not account:
            return False
        if AutoChessAuthService.is_super_admin(account):
            return True
        return account.get('role') == ROLE_ADMIN and perm in (account.get('permissions') or [])

    def _issue_token(self, account_id):
        tok = secrets.token_urlsafe(32)
        now = time.time()
        self.store.put(
            KIND_TOKEN,
            {
                'id': tok,
                'account_id': account_id,
                'created_at': now,
                'expires_at': now + _SESSION_TTL_SEC,
            },
        )
        return tok

    def register(self, username, password, display_name=None):
        raw_user, acc_id = self.normalize_username(username)
        pw = str(password or '')
        if len(pw) < 6 or len(pw) > 128:
            raise AuthError('密码长度需为 6–128 位', 400)
        nick = str(display_name or raw_user).strip()[:20] or raw_user

        with self.lock:
            if self.store.get(KIND_ACCOUNT, acc_id):
                raise AuthError(f'账号「{raw_user}」已被注册，请更换或直接登录', 409)
            salt = secrets.token_hex(16)
            rec = {
                'id': acc_id,
                'username': raw_user,
                'display_name': nick,
                'role': ROLE_USER,
                'permissions': [],
                'password_salt': salt,
                'password_hash': _hash_password(pw, salt),
                'created_at': time.time(),
                'token_overrides': {},
                'stats': {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0},
                'ranked': default_ranked_profile(),
                'ranked_half_hs': default_ranked_profile(),
            }
            self.store.put(KIND_ACCOUNT, rec)
            tok = self._issue_token(acc_id)
            return self.public_account(rec), tok

    def login(self, username, password):
        raw_user, acc_id = self.normalize_username(username)
        pw = str(password or '')
        if not pw:
            raise AuthError('请输入密码', 400)

        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, acc_id)
            if not rec:
                raise AuthError('账号或密码错误', 401)
            expected = rec.get('password_hash', '')
            salt = rec.get('password_salt', '')
            actual = _hash_password(pw, salt) if salt else ''
            if not expected or not hmac.compare_digest(actual, expected):
                raise AuthError('账号或密码错误', 401)
            tok = self._issue_token(acc_id)
            return self.public_account(rec), tok

    def logout(self, token):
        if token:
            with self.lock:
                self.store.delete(KIND_TOKEN, token)

    def login_or_register_wechat(self, openid, display_name=None):
        """Authenticate via WeChat OpenID, creating an auto-account on first login."""
        clean_openid = str(openid or '').strip()
        if not 4 <= len(clean_openid) <= 128:
            raise AuthError('无效的微信 OpenID', 400)

        with self.lock:
            bind = self.store.get(KIND_WX_BIND, clean_openid)
            if bind:
                rec = self.store.get(KIND_ACCOUNT, bind.get('account_id', ''))
                if rec:
                    tok = self._issue_token(rec['id'])
                    return self.public_account(rec), tok, False

            acc_id = 'wx_' + secrets.token_hex(6)
            nick = str(display_name or '').strip()[:20] or f'星序棋手{acc_id[-4:].upper()}'
            salt = secrets.token_hex(16)
            random_pw = secrets.token_urlsafe(32)
            now = time.time()
            rec = {
                'id': acc_id,
                'username': acc_id,
                'display_name': nick,
                'role': ROLE_USER,
                'permissions': [],
                'password_salt': salt,
                'password_hash': _hash_password(random_pw, salt),
                'created_at': now,
                'wx_openid': clean_openid,
                'wx_auto_created': True,
                'token_overrides': {},
                'stats': {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0},
                'ranked': default_ranked_profile(),
                'ranked_half_hs': default_ranked_profile(),
            }
            self.store.put(KIND_ACCOUNT, rec)
            self.store.put(
                KIND_WX_BIND,
                {
                    'id': clean_openid,
                    'account_id': acc_id,
                    'created_at': now,
                    'updated_at': now,
                },
            )
            tok = self._issue_token(acc_id)
            return self.public_account(rec), tok, True

    def bind_wechat(self, openid, username, password):
        """Bind a WeChat OpenID to an existing username/password Auto-Chess account."""
        clean_openid = str(openid or '').strip()
        if not 4 <= len(clean_openid) <= 128:
            raise AuthError('无效的微信 OpenID', 400)
        _, acc_id = self.normalize_username(username)
        pw = str(password or '')
        if not pw:
            raise AuthError('请输入密码', 400)

        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, acc_id)
            if not rec:
                raise AuthError('账号或密码错误', 401)
            expected = rec.get('password_hash', '')
            salt = rec.get('password_salt', '')
            actual = _hash_password(pw, salt) if salt else ''
            if not expected or not hmac.compare_digest(actual, expected):
                raise AuthError('账号或密码错误', 401)

            existing_openid = rec.get('wx_openid')
            if existing_openid and existing_openid != clean_openid:
                raise AuthError('该账号已绑定其他微信', 409)

            old_bind = self.store.get(KIND_WX_BIND, clean_openid)
            if old_bind and old_bind.get('account_id') != acc_id:
                old_rec = self.store.get(KIND_ACCOUNT, old_bind.get('account_id', ''))
                if old_rec:
                    old_games = int((old_rec.get('stats') or {}).get('games', 0) or 0)
                    old_ranked_games = int((old_rec.get('ranked') or {}).get('games', 0) or 0)
                    old_ranked_games += int((old_rec.get('ranked_half_hs') or {}).get('games', 0) or 0)
                    if old_rec.get('wx_auto_created') and old_games == 0 and old_ranked_games == 0:
                        old_rec.pop('wx_openid', None)
                        self.store.put(KIND_ACCOUNT, old_rec)
                    else:
                        raise AuthError('当前微信已绑定其他已有战绩的账号', 409)

            now = time.time()
            rec['wx_openid'] = clean_openid
            self.store.put(KIND_ACCOUNT, rec)
            self.store.put(
                KIND_WX_BIND,
                {
                    'id': clean_openid,
                    'account_id': acc_id,
                    'created_at': (old_bind or {}).get('created_at', now),
                    'updated_at': now,
                },
            )
            tok = self._issue_token(acc_id)
            return self.public_account(rec), tok

    def authenticate(self, token):
        if not token:
            return None
        sess = self.store.get(KIND_TOKEN, token)
        if not sess:
            return None
        if float(sess.get('expires_at', 0) or 0) < time.time():
            with self.lock:
                self.store.delete(KIND_TOKEN, token)
            return None
        rec = self.store.get(KIND_ACCOUNT, sess.get('account_id', ''))
        return self.public_account(rec)

    def get_account(self, account_id):
        if not account_id:
            return None
        return self.public_account(self.store.get(KIND_ACCOUNT, account_id))

    def update_profile(self, account_id, display_name=None, old_password=None, new_password=None):
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, account_id)
            if not rec:
                raise AuthError('账号不存在', 404)
            if display_name is not None:
                cleaned = str(display_name).strip()[:20]
                if not cleaned:
                    raise AuthError('昵称不能为空', 400)
                rec['display_name'] = cleaned
            if new_password is not None and str(new_password) != '':
                old_pw = str(old_password or '')
                if not hmac.compare_digest(_hash_password(old_pw, rec.get('password_salt', '')), rec.get('password_hash', '')):
                    raise AuthError('原密码不正确', 401)
                npw = str(new_password)
                if len(npw) < 6 or len(npw) > 128:
                    raise AuthError('新密码长度需为 6–128 位', 400)
                salt = secrets.token_hex(16)
                rec['password_salt'] = salt
                rec['password_hash'] = _hash_password(npw, salt)
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec)

    def set_token_override(self, account_id, serial, token_url):
        if serial not in UNIT_CATALOG:
            raise AuthError(f'未知棋子编号: {serial}', 400)
        clean_url = validate_token_url(token_url)
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, account_id)
            if not rec:
                raise AuthError('账号不存在', 404)
            overrides = dict(rec.get('token_overrides') or {})
            overrides[serial] = clean_url
            rec['token_overrides'] = overrides
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec)

    def clear_token_override(self, account_id, serial):
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, account_id)
            if not rec:
                raise AuthError('账号不存在', 404)
            overrides = dict(rec.get('token_overrides') or {})
            overrides.pop(serial, None)
            rec['token_overrides'] = overrides
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec)

    def record_match_result(self, account_id, placement, mode='lobby4'):
        if not account_id:
            return None
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, account_id)
            if not rec:
                return None
            st = dict(rec.get('stats') or {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0})
            st['games'] = int(st.get('games', 0) or 0) + 1
            if placement == 1:
                st['wins'] = int(st.get('wins', 0) or 0) + 1
                if mode == 'pve12':
                    st['pve_clears'] = int(st.get('pve_clears', 0) or 0) + 1
            if placement is not None and placement <= 2 and mode != 'pve12':
                st['top2'] = int(st.get('top2', 0) or 0) + 1
            rec['stats'] = st
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec)

    def record_ranked_result(self, account_id, placement, match_id=None, rng=None, ruleset='standard'):
        """Idempotently settle an 8-player ranked match into account LP, shield cards, coins, and stats."""
        if not account_id:
            return None, None
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, account_id)
            if not rec:
                return None, None
            ranked_field = 'ranked_half_hs' if normalize_ruleset(ruleset) == 'half_hs' else 'ranked'
            raw_ranked = dict(rec.get(ranked_field) or {})
            settled_ids = raw_ranked.get('settled_match_ids') or []
            if match_id and str(match_id) in settled_ids:
                return self.public_account(rec), None

            if ranked_field == 'ranked_half_hs':
                standard = dict(rec.get('ranked') or default_ranked_profile())
                raw_ranked['coins'] = standard.get('coins', 0)
            updated_ranked, settlement = settle_ranked_match(
                raw_ranked, placement, match_id=match_id, rng=rng
            )
            rec[ranked_field] = updated_ranked
            if ranked_field == 'ranked_half_hs':
                standard['coins'] = updated_ranked['coins']
                rec['ranked'] = standard

            st = dict(rec.get('stats') or {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0})
            st['games'] = int(st.get('games', 0) or 0) + 1
            if int(placement) == 1:
                st['wins'] = int(st.get('wins', 0) or 0) + 1
            if int(placement) <= 2:
                st['top2'] = int(st.get('top2', 0) or 0) + 1
            rec['stats'] = st

            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec), settlement

    def get_ranked_leaderboard(self, viewer_account_id=None, tier_filter=None, limit=100, ruleset='standard'):
        """Return server-wide ranked leaderboard across all registered Auto-Chess accounts."""
        accounts = self.store.list(KIND_ACCOUNT)
        return build_leaderboard(
            accounts,
            viewer_account_id=viewer_account_id,
            tier_filter=tier_filter,
            limit=limit,
            ranked_field='ranked_half_hs' if normalize_ruleset(ruleset) == 'half_hs' else 'ranked',
        )

    @staticmethod
    def _account_summary(rec):
        role = normalize_role(rec)
        perms = normalize_permissions(rec, role)
        stats = rec.get('stats') or {}
        return {
            'id': rec['id'],
            'username': rec.get('username', rec['id']),
            'display_name': rec.get('display_name') or rec.get('username', rec['id']),
            'role': role,
            'role_label': ROLE_LABELS[role],
            'permissions': perms,
            'is_primary': rec['id'] == PRIMARY_ADMIN_ID,
            'created_at': rec.get('created_at', 0),
            'wx_bound': bool(rec.get('wx_openid')),
            'stats': {
                'games': int(stats.get('games', 0) or 0),
                'wins': int(stats.get('wins', 0) or 0),
                'top2': int(stats.get('top2', 0) or 0),
                'pve_clears': int(stats.get('pve_clears', 0) or 0),
            },
        }

    def _require_primary_actor(self, actor_account_id):
        if actor_account_id != PRIMARY_ADMIN_ID:
            raise AuthError('仅主管理员（fanmm01）可增删管理员及分配权限', 403)
        actor = self.store.get(KIND_ACCOUNT, PRIMARY_ADMIN_ID)
        if not actor:
            raise AuthError('主管理员账号不存在', 404)
        return actor

    def list_accounts_for_admin(self, actor_account_id):
        """Return (admins, users) summaries for primary-admin management."""
        self._require_primary_actor(actor_account_id)
        accounts = self.store.list(KIND_ACCOUNT)
        admins, users = [], []
        for rec in accounts:
            summary = self._account_summary(rec)
            if summary['role'] in (ROLE_SUPER_ADMIN, ROLE_ADMIN):
                admins.append(summary)
            else:
                users.append(summary)
        admins.sort(key=lambda item: (0 if item['is_primary'] else 1, item['username'].lower()))
        users.sort(key=lambda item: item['username'].lower())
        return admins, users

    def grant_admin(self, actor_account_id, username, permissions=None, password=None, display_name=None):
        """Promote an existing account or create a new admin account with selected permissions."""
        self._require_primary_actor(actor_account_id)
        raw_user, acc_id = self.normalize_username(username)
        if acc_id == PRIMARY_ADMIN_ID:
            raise AuthError('主管理员账号已拥有最高权限', 400)
        perms = validate_permissions(permissions, allow_none=True)

        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, acc_id)
            if rec:
                if normalize_role(rec) == ROLE_ADMIN:
                    raise AuthError(f'账号「{rec.get("username", raw_user)}」已是管理员，请直接调整其权限', 409)
                rec['role'] = ROLE_ADMIN
                rec['permissions'] = perms
                self.store.put(KIND_ACCOUNT, rec)
                return self.public_account(rec), False

            pw = '' if password is None else str(password)
            if not pw:
                raise AuthError(f'账号「{raw_user}」不存在，请先注册或填写初始密码直接创建', 404)
            if len(pw) < 6 or len(pw) > 128:
                raise AuthError('密码长度需为 6–128 位', 400)
            nick = str(display_name or raw_user).strip()[:20] or raw_user
            salt = secrets.token_hex(16)
            rec = {
                'id': acc_id,
                'username': raw_user,
                'display_name': nick,
                'role': ROLE_ADMIN,
                'permissions': perms,
                'password_salt': salt,
                'password_hash': _hash_password(pw, salt),
                'created_at': time.time(),
                'token_overrides': {},
                'stats': {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0},
                'ranked': default_ranked_profile(),
                'ranked_half_hs': default_ranked_profile(),
            }
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec), True

    def update_admin_permissions(self, actor_account_id, target, permissions):
        """Update the granted permission set for an existing admin account."""
        self._require_primary_actor(actor_account_id)
        target_id = str(target or '').strip().lower()
        if not target_id:
            raise AuthError('请指定要修改权限的管理员账号', 400)
        if target_id == PRIMARY_ADMIN_ID:
            raise AuthError('主管理员权限不可修改', 400)
        perms = validate_permissions(permissions, allow_none=False)

        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, target_id)
            if not rec:
                raise AuthError('目标账号不存在', 404)
            if normalize_role(rec) != ROLE_ADMIN:
                raise AuthError('该账号当前不是管理员', 400)
            rec['permissions'] = perms
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec)

    def revoke_admin(self, actor_account_id, target):
        """Demote an admin account back to regular user while keeping Auto-Chess data."""
        self._require_primary_actor(actor_account_id)
        target_id = str(target or '').strip().lower()
        if not target_id:
            raise AuthError('请指定要移除的管理员账号', 400)
        if target_id == PRIMARY_ADMIN_ID:
            raise AuthError('主管理员账号不可移除管理员权限', 400)

        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, target_id)
            if not rec:
                raise AuthError('目标账号不存在', 404)
            if normalize_role(rec) != ROLE_ADMIN:
                raise AuthError('该账号当前不是管理员', 400)
            rec['role'] = ROLE_USER
            rec['permissions'] = []
            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec)

    def _require_player_manager(self, actor_account_id):
        actor = self.get_account(actor_account_id)
        if not actor or not self.has_permission(actor, PERM_PLAYER_MANAGE):
            raise AuthError('当前账号缺少「玩家管理」权限', 403)
        return actor

    def list_players(self, actor_account_id):
        """List all registered accounts for player management with per-target kick capability."""
        actor = self._require_player_manager(actor_account_id)
        actor_is_super = self.is_super_admin(actor)
        role_order = {ROLE_SUPER_ADMIN: 0, ROLE_ADMIN: 1, ROLE_USER: 2}
        players = []
        for rec in self.store.list(KIND_ACCOUNT):
            summary = self._account_summary(rec)
            if rec['id'] == PRIMARY_ADMIN_ID or rec['id'] == actor['id']:
                can_kick = False
            elif actor_is_super:
                can_kick = True
            else:
                can_kick = summary['role'] == ROLE_USER
            summary['can_kick'] = can_kick
            players.append(summary)
        players.sort(key=lambda item: (role_order.get(item['role'], 9), item['username'].lower()))
        return players

    def delete_account(self, actor_account_id, target):
        """Kick (revoke all tokens) and delete a registered account."""
        actor = self._require_player_manager(actor_account_id)
        target_id = str(target or '').strip().lower()
        if not target_id:
            raise AuthError('请指定要踢出删除的账号', 400)
        if target_id == PRIMARY_ADMIN_ID:
            raise AuthError('不可删除主管理员账号', 400)
        if target_id == actor['id']:
            raise AuthError('不可删除当前登录账号', 400)

        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, target_id)
            if not rec:
                raise AuthError('目标账号不存在', 404)
            target_role = normalize_role(rec)
            if target_role != ROLE_USER and not self.is_super_admin(actor):
                raise AuthError('仅主管理员（fanmm01）可移除或删除管理员账号', 403)

            revoked_tokens = 0
            for tok_doc in self.store.list(KIND_TOKEN):
                if tok_doc.get('account_id') == target_id and tok_doc.get('id'):
                    self.store.delete(KIND_TOKEN, tok_doc['id'])
                    revoked_tokens += 1

            wx_openid = rec.get('wx_openid')
            if wx_openid:
                self.store.delete(KIND_WX_BIND, wx_openid)
            for bind_doc in self.store.list(KIND_WX_BIND):
                if bind_doc.get('account_id') == target_id and bind_doc.get('id'):
                    self.store.delete(KIND_WX_BIND, bind_doc['id'])

            deleted_info = {
                'id': rec['id'],
                'username': rec.get('username', rec['id']),
                'display_name': rec.get('display_name') or rec.get('username', rec['id']),
            }
            self.store.delete(KIND_ACCOUNT, target_id)
            return deleted_info, revoked_tokens
