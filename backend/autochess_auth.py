"""Independent Auto-Chess SQLite account authentication, cross-client state sharing, and custom tokens."""

import hashlib
import hmac
import re
import secrets
import threading
import time

from autochess_catalog import UNIT_CATALOG
from autochess_ranked import (
    build_leaderboard,
    default_ranked_profile,
    public_ranked_profile,
    settle_ranked_match,
)

KIND_ACCOUNT = 'autochess_account'
KIND_TOKEN = 'autochess_auth_token'

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


class AutoChessAuthService:
    """Manages salted PBKDF2 accounts, cookies, stats, and custom token overrides in ui_store."""

    def __init__(self, store, cookie_name='autochess_auth'):
        self.store = store
        self.cookie_name = cookie_name
        self.lock = threading.RLock()

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
        return {
            'id': rec['id'],
            'username': rec.get('username', rec['id']),
            'display_name': rec.get('display_name') or rec.get('username', rec['id']),
            'created_at': rec.get('created_at', 0),
            'token_overrides': dict(rec.get('token_overrides') or {}),
            'stats': {
                'games': int(stats.get('games', 0) or 0),
                'wins': int(stats.get('wins', 0) or 0),
                'top2': int(stats.get('top2', 0) or 0),
                'pve_clears': int(stats.get('pve_clears', 0) or 0),
            },
            'ranked': public_ranked_profile(rec.get('ranked')),
        }

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
                'password_salt': salt,
                'password_hash': _hash_password(pw, salt),
                'created_at': time.time(),
                'token_overrides': {},
                'stats': {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0},
                'ranked': default_ranked_profile(),
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

    def record_ranked_result(self, account_id, placement, match_id=None, rng=None):
        """Idempotently settle an 8-player ranked match into account LP, shield cards, coins, and stats."""
        if not account_id:
            return None, None
        with self.lock:
            rec = self.store.get(KIND_ACCOUNT, account_id)
            if not rec:
                return None, None
            raw_ranked = rec.get('ranked') or {}
            settled_ids = raw_ranked.get('settled_match_ids') or []
            if match_id and str(match_id) in settled_ids:
                return self.public_account(rec), None

            updated_ranked, settlement = settle_ranked_match(
                raw_ranked, placement, match_id=match_id, rng=rng
            )
            rec['ranked'] = updated_ranked

            st = dict(rec.get('stats') or {'games': 0, 'wins': 0, 'top2': 0, 'pve_clears': 0})
            st['games'] = int(st.get('games', 0) or 0) + 1
            if int(placement) == 1:
                st['wins'] = int(st.get('wins', 0) or 0) + 1
            if int(placement) <= 2:
                st['top2'] = int(st.get('top2', 0) or 0) + 1
            rec['stats'] = st

            self.store.put(KIND_ACCOUNT, rec)
            return self.public_account(rec), settlement

    def get_ranked_leaderboard(self, viewer_account_id=None, tier_filter=None, limit=100):
        """Return server-wide ranked leaderboard across all registered Auto-Chess accounts."""
        accounts = self.store.list(KIND_ACCOUNT)
        return build_leaderboard(
            accounts,
            viewer_account_id=viewer_account_id,
            tier_filter=tier_filter,
            limit=limit,
        )
