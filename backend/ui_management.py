"""Account-gated data editor, atomic source updates, recoverable backups, task snapshots, and admin/player management."""
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import pprint
import secrets
import shutil
import threading
import time
import zipfile

from flask import jsonify, request, Response
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound
from autochess_auth import (
    AuthError,
    PERMISSION_DEFS,
    PERMISSION_LABELS,
    PERM_CHARACTER_MANAGE,
    PERM_PLAYER_MANAGE,
    PRIMARY_ADMIN_USERNAME,
)
from ui_effects import EffectComments, format_character, runtime_character
from skill_identity import identify_skills, validate_global_skill_ids
from project_paths import runtime_dir

ROOT = Path(__file__).resolve().parent
FILES = ('characters_data.py', 'characters_data_pvp.py', 'team_tables.py', 'ai_weights.json', 'ai_weights_pvp.json')


def atomic_write(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.' + secrets.token_hex(5) + '.tmp')
    temp.write_bytes(data)
    os.replace(temp, path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Management:
    def __init__(self, bp, context, root=ROOT, auth=None):
        self.c, self.root = context, Path(root)
        self.auth = auth
        self.runtime = runtime_dir(self.root)
        self.runtime.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.loaded_version = digest((self.root / 'characters_data.py').read_bytes())
        self.training = None
        for path, name, method in [('/data', 'data', 'GET'), ('/data/save', 'save', 'POST'),
                                   ('/backups', 'backups', 'GET'), ('/backups', 'backup', 'POST'),
                                   ('/backups/<bid>/download', 'download', 'GET'),
                                   ('/backups/<bid>/restore', 'restore', 'POST'),
                                   ('/admins', 'list_admins', 'GET'),
                                   ('/admins', 'add_admin', 'POST'),
                                   ('/admins/permissions', 'update_admin_permissions', 'POST'),
                                   ('/admins/<account_id>/permissions', 'put_admin_permissions', 'PUT'),
                                   ('/admins/remove', 'remove_admin', 'POST'),
                                   ('/admins/<account_id>', 'delete_admin', 'DELETE'),
                                   ('/players', 'list_players', 'GET'),
                                   ('/players/kick', 'kick_player', 'POST'),
                                   ('/players/<account_id>', 'delete_player', 'DELETE')]:
            bp.add_url_rule('/api/ui' + path, 'manage_' + name, getattr(self, name), methods=[method])

    def set_auth(self, auth):
        self.auth = auth

    @staticmethod
    def _auth_err(exc):
        return jsonify(error=True, message=str(exc)), exc.status

    @staticmethod
    def _check_origin():
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/') and not origin.startswith('https://servicewechat.com'):
            raise Forbidden('请从战术室页面发起操作')

    def _auth_token(self):
        auth_header = (request.headers.get('Authorization') or '').strip()
        if auth_header.lower().startswith('bearer '):
            bearer = auth_header[7:].strip()
            if bearer:
                return bearer
        header_tok = (request.headers.get('X-AutoChess-Auth') or '').strip()
        if header_tok:
            return header_tok
        if self.auth:
            return request.cookies.get(self.auth.cookie_name, '')
        return ''

    def current_account(self):
        if not self.auth:
            return None
        return self.auth.authenticate(self._auth_token())

    def has_permission(self, perm):
        acc = self.current_account()
        return bool(self.auth and acc and self.auth.has_permission(acc, perm))

    def is_super_admin(self):
        acc = self.current_account()
        return bool(self.auth and acc and self.auth.is_super_admin(acc))

    def require_permission(self, perm):
        if not self.auth:
            raise Forbidden('账号认证服务未初始化')
        acc = self.current_account()
        if not acc:
            raise Forbidden('游客不能编辑，请先登录管理员账号')
        if not self.auth.has_permission(acc, perm):
            label = PERMISSION_LABELS.get(perm, perm)
            raise Forbidden(f'当前账号缺少「{label}」权限')
        return acc

    def require_local(self):
        """Compatibility gate enforcing character-management admin permission."""
        return self.require_permission(PERM_CHARACTER_MANAGE)

    def require_super_admin(self):
        if not self.auth:
            raise Forbidden('账号认证服务未初始化')
        acc = self.current_account()
        if not acc:
            raise Forbidden('请先登录主管理员账号')
        if not self.auth.is_super_admin(acc):
            raise Forbidden('仅主管理员（fanmm01）可增删管理员及分配权限')
        return acc

    def list_admins(self):
        actor = self.require_super_admin()
        try:
            admins, users = self.auth.list_accounts_for_admin(actor['id'])
        except AuthError as exc:
            return self._auth_err(exc)
        return jsonify(
            admins=admins,
            users=users,
            permission_defs=PERMISSION_DEFS,
            primary_admin=PRIMARY_ADMIN_USERNAME,
        )

    def add_admin(self):
        actor = self.require_super_admin()
        data = self.c['body']() or {}
        try:
            account, created = self.auth.grant_admin(
                actor['id'],
                username=data.get('username', ''),
                permissions=data.get('permissions'),
                password=data.get('password'),
                display_name=data.get('display_name'),
            )
            admins, users = self.auth.list_accounts_for_admin(actor['id'])
        except AuthError as exc:
            return self._auth_err(exc)
        return jsonify(
            ok=True,
            created=created,
            account=account,
            admins=admins,
            users=users,
            permission_defs=PERMISSION_DEFS,
            primary_admin=PRIMARY_ADMIN_USERNAME,
        )

    def update_admin_permissions(self):
        actor = self.require_super_admin()
        data = self.c['body']() or {}
        target = data.get('account_id') or data.get('username') or ''
        return self._apply_admin_permissions(actor, target, data.get('permissions'))

    def put_admin_permissions(self, account_id):
        self._check_origin()
        actor = self.require_super_admin()
        data = self.c['body']() or {}
        return self._apply_admin_permissions(actor, account_id, data.get('permissions'))

    def _apply_admin_permissions(self, actor, target, permissions):
        try:
            account = self.auth.update_admin_permissions(actor['id'], target, permissions)
            admins, users = self.auth.list_accounts_for_admin(actor['id'])
        except AuthError as exc:
            return self._auth_err(exc)
        return jsonify(
            ok=True,
            account=account,
            admins=admins,
            users=users,
            permission_defs=PERMISSION_DEFS,
            primary_admin=PRIMARY_ADMIN_USERNAME,
        )

    def remove_admin(self):
        actor = self.require_super_admin()
        data = self.c['body']() or {}
        target = data.get('account_id') or data.get('username') or ''
        return self._revoke_admin_target(actor, target)

    def delete_admin(self, account_id):
        self._check_origin()
        actor = self.require_super_admin()
        return self._revoke_admin_target(actor, account_id)

    def _revoke_admin_target(self, actor, target):
        try:
            account = self.auth.revoke_admin(actor['id'], target)
            admins, users = self.auth.list_accounts_for_admin(actor['id'])
        except AuthError as exc:
            return self._auth_err(exc)
        return jsonify(
            ok=True,
            account=account,
            admins=admins,
            users=users,
            permission_defs=PERMISSION_DEFS,
            primary_admin=PRIMARY_ADMIN_USERNAME,
        )

    def list_players(self):
        actor = self.require_permission(PERM_PLAYER_MANAGE)
        try:
            players = self.auth.list_players(actor['id'])
        except AuthError as exc:
            return self._auth_err(exc)
        return jsonify(players=players, permission_defs=PERMISSION_DEFS, primary_admin=PRIMARY_ADMIN_USERNAME)

    def kick_player(self):
        actor = self.require_permission(PERM_PLAYER_MANAGE)
        data = self.c['body']() or {}
        target = data.get('account_id') or data.get('username') or ''
        return self._delete_player_target(actor, target)

    def delete_player(self, account_id):
        self._check_origin()
        actor = self.require_permission(PERM_PLAYER_MANAGE)
        return self._delete_player_target(actor, account_id)

    def _delete_player_target(self, actor, target):
        try:
            deleted, revoked_tokens = self.auth.delete_account(actor['id'], target)
            players = self.auth.list_players(actor['id'])
        except AuthError as exc:
            return self._auth_err(exc)
        return jsonify(
            ok=True,
            deleted=deleted,
            revoked_tokens=revoked_tokens,
            players=players,
        )

    def module(self):
        return self.c['ns']['characters_data_pvp']

    def character_definitions(self, tree):
        """Use source definitions, excluding examples and stale reloaded globals."""
        definitions = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            keys = {key.value for key in node.value.keys if isinstance(key, ast.Constant)}
            if not {'name', 'serial', 'attrs'} <= keys:
                continue
            name = node.targets[0].id
            character = getattr(self.module(), name, None)
            if isinstance(character, dict):
                definitions[name] = node
        return definitions

    def data(self):
        self.require_local()
        with self.lock:
            return self.describe()

    def editable_characters(self, source):
        comments = EffectComments(source)
        definitions = self.character_definitions(ast.parse(source))
        return [identify_skills(comments.restore(ast.literal_eval(node.value), node))
                for name, node in definitions.items()]

    def describe(self):
        current = digest((self.root / 'characters_data.py').read_bytes())
        if current != self.loaded_version:
            with self.c['guard'], self.c['ns']['_lock']:
                self.reload()
        import battle_engine as be
        module = self.module()
        import team_tables
        source = (self.root / 'characters_data.py').read_text(encoding='utf-8-sig')
        nodes = ast.parse(source)
        definitions = self.character_definitions(nodes)
        try:
            characters = self.editable_characters(source)
            validate_global_skill_ids(characters)
        except (ValueError, SyntaxError) as exc:
            raise BadRequest('无法读取禁用效果：' + str(exc)) from exc
        reserved = [ch['serial'] for ch in characters]
        enums = {'type': {str(i): label for i, label in enumerate(
            ['', '伤害', '护盾', '恢复', '增益', '召唤', '制造', '触发法术', '领域', '生命触发',
             '延迟恢复', '战意', '特殊防护', '复生', '计数器', '特殊15', '特殊16', '切换阶段', '位移', '复活']) if i and i not in (15, 16)},
            '客体': {'1': '自身', '2': '其他友方单体', '3': '其他友方全体', '4': '敌方单体', '5': '敌方全体',
                   '12': '任意友方', '13': '自身与友方', '14': '自身与敌方单体', '15': '自身与敌方全体',
                   '24': '友方或敌方单体', '25': '友方单体与敌方群体', '35': '领域全体', '45': '敌方群体',
                   '124': '任意单体', '125': '任意友方与敌方群体', '135': '全场', 'R': '随机单位', 'RP': '随机角色'},
            'timing': {'1': '被动', '2': '主动作', '3': '附加动作', '12': '被动／主动', '23': '主动／附加', '123': '全部'},
            'category': {str(i): x for i, x in enumerate(['', '伤害', '护盾', '恢复', '增益', '召唤', '制造', '触发', '领域', '特殊']) if i},
            '辅助效果': {k: k for k in getattr(be, 'AUX_NAME_TO_CODE', {})},
            '召唤物模板': {k: k for k in module.SUMMON_TEMPLATES},
            '制造物模板': {k: k for k in module.ITEM_TEMPLATES}}
        enums['_mp_formula'] = {'': '固定费用', 'summon_count_ceil_half': '召唤数除二向上取整', 'ceil_2d6_div_2': '2d6 除二向上取整'}
        enums['可叠加'] = {'0': '不叠加／同名刷新', '1': '允许叠加', '2': '允许叠加'}
        enums['成功率奖惩骰'] = {str(i): ('无奖惩' if i == 0 else ('奖励骰' if i > 0 else '惩罚骰') + f' ×{abs(i)}') for i in range(-3, 4)}
        enums['phase'] = {'0': '所有阶段', '1': '阶段一', '2': '阶段二', '3': '阶段三', '4': '阶段四', '99': '保留／不启用'}
        enums['weapon_state'] = {'staff': '杖', 'bow': '弓', 'sword': '剑'}
        enums['variant'] = {'fire_rat_cloak': '火鼠裘防护'}
        enums['友方行为'] = {'': '默认', 'damage_and_heal': '伤害与延迟恢复'}
        for key in ('可闪避性', '可反击性', '可格挡性', '可贯穿性', '领域中心跟随', 'default_persist',
                    'GLOBAL_RANGE_OVERRIDE', '可反击', '可格挡', '可反应', '忽略全局奖惩骰', 'ally_safe'):
            enums[key] = {'0': '否', '1': '是'}
        fields = {key: {} for key in ('character', 'spell', 'effect', 'attrs', 'str_attrs', 'entry')}
        for char in characters:
            for key, value in char.items():
                fields['character'].setdefault(key, value)
            for group in ('attrs', 'str_attrs'):
                for key, value in char.get(group, {}).items():
                    fields[group].setdefault(key, value)
            for spell in char.get('spells', []):
                for key, value in spell.items():
                    if key != '_disabled':
                        fields['spell'].setdefault(key, value)
                for effect in spell.get('effects', []):
                    for key, value in effect.items():
                        if key != '_disabled':
                            fields['effect'].setdefault(key, value)
            for item in char.get('inventory', []):
                for key, value in item.items():
                    fields['entry'].setdefault(key, value)
        return jsonify(characters=characters, enabled_serials=[ch['serial'] for ch in module.ALL_CHARACTERS], summons=module.SUMMON_TEMPLATES,
                       items=module.ITEM_TEMPLATES, version=digest((self.root / 'characters_data.py').read_bytes()),
                       reserved=reserved, enums=enums, fields=fields,
                       presets={'2v2': team_tables.TEAM_TABLES_2V2, '3v3': team_tables.TEAM_TABLES_3V3},
                       settings={'GLOBAL_RANGE_OVERRIDE': getattr(module, 'GLOBAL_RANGE_OVERRIDE', 0)},
                       needs_training=self.runtime.joinpath('needs-training').exists())

    def make_backup(self, reason='manual'):
        folder = self.runtime / 'backups'
        folder.mkdir(exist_ok=True)
        bid = str(time.time_ns()) + '-' + secrets.token_hex(3)
        hashes = {}
        with zipfile.ZipFile(folder / (bid + '.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
            for name in FILES:
                path = self.root / name
                if path.exists():
                    raw = path.read_bytes()
                    hashes[name] = digest(raw)
                    z.writestr(name, raw)
            if hasattr(self, 'settings'):
                raw = json.dumps(self.settings.store.read(), ensure_ascii=False).encode('utf-8')
                hashes['settings.json'] = digest(raw)
                z.writestr('settings.json', raw)
            z.writestr('manifest.json', json.dumps(dict(id=bid, time=time.time(), reason=reason, files=hashes)))
        return bid

    def backups(self):
        self.require_local()
        rows = []
        for path in sorted((self.runtime / 'backups').glob('*.zip'), reverse=True):
            with zipfile.ZipFile(path) as z:
                rows.append(json.loads(z.read('manifest.json')))
        return jsonify(backups=rows)

    def backup(self):
        self.require_local()
        self.c['body']()
        with self.lock:
            return jsonify(id=self.make_backup())

    def backup_path(self, bid):
        if not all(ch in '0123456789abcdef-' for ch in bid):
            raise NotFound('备份不存在')
        path = self.runtime / 'backups' / (bid + '.zip')
        if not path.exists():
            raise NotFound('备份不存在')
        return path

    def download(self, bid):
        self.require_local()
        return Response(self.backup_path(bid).read_bytes(), mimetype='application/zip',
                        headers={'Content-Disposition': f'attachment; filename=backup-{bid}.zip'})

    def reload(self):
        module = self.module()
        cache = Path(importlib.util.cache_from_source(str(self.root / 'characters_data.py')))
        if self.root.resolve() in cache.resolve().parents:
            cache.unlink(missing_ok=True)
        raw = (self.root / 'characters_data.py').read_bytes()
        exec(compile(raw, str(self.root / 'characters_data.py'), 'exec'), module.__dict__)
        # Old backups may predate skill IDs. Restore comments before numbering.
        by_serial = {getattr(module, name)['serial']: getattr(module, name)
                     for name in self.character_definitions(ast.parse(raw))}
        for definition in self.editable_characters(raw.decode('utf-8-sig')):
            current = by_serial[definition['serial']]
            current.clear()
            current.update(runtime_character(definition))
        self.loaded_version = digest(raw)
        import battle_engine
        battle_engine._SUMMON_TEMPLATES = module.SUMMON_TEMPLATES
        # New rooms obtain new data; existing engines keep their own templates.
        self.c['ns']['_SUMMON_TEMPLATES'] = module.SUMMON_TEMPLATES
        self.c['ns']['_Q_TABLE_PVP_CACHE'] = None

    def restore(self, bid):
        self.require_local()
        self.c['body']()
        with self.lock, self.c['guard'], self.c['ns']['_lock']:
            with zipfile.ZipFile(self.backup_path(bid)) as z:
                manifest = json.loads(z.read('manifest.json'))
                payload = {k: z.read(k) for k in manifest['files'] if k in FILES}
                restored_settings = None
                if 'settings.json' in manifest['files'] and hasattr(self, 'settings'):
                    raw = z.read('settings.json')
                    if digest(raw) != manifest['files']['settings.json']:
                        raise BadRequest('设置备份校验失败')
                    from combat_settings import DEFAULTS, validate
                    restored_settings = validate({**DEFAULTS, **json.loads(raw)})
                elif hasattr(self, 'settings') and 'team_tables.py' in payload:
                    # Older backups stored presets directly in Python assignments.
                    tree = ast.parse(payload['team_tables.py'].decode('utf-8-sig'))
                    teams = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                             if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                             and node.targets[0].id in ('TEAM_TABLES_2V2', 'TEAM_TABLES_3V3')}
                    if teams:
                        from combat_settings import validate
                        restored_settings = validate({**self.settings.store.read(), **teams})
                        payload.pop('team_tables.py')
                if any(digest(v) != manifest['files'][k] for k, v in payload.items()):
                    raise BadRequest('备份校验失败')
                for name, value in payload.items():
                    if name.endswith('.py'):
                        compile(value, name, 'exec')
                before = self.make_backup('before restore')
                for name, value in payload.items():
                    atomic_write(self.root / name, value)
                if restored_settings is not None:
                    self.settings.store.write(restored_settings)
            self.reload()
            return jsonify(ok=True, backup=before)

    def validate(self, characters, summons, enabled=None):
        if not isinstance(characters, list) or not characters:
            raise BadRequest('至少保留一个角色')
        serials = set()
        from battle_engine import CombatEngine, CN_NUMS, CAT_LETTERS
        for ch in characters:
            if not isinstance(ch, dict) or not ch.get('name') or not isinstance(ch.get('serial'), str):
                raise BadRequest('角色必须有名称和唯一编号')
            if not __import__('re').fullmatch(r'[A-Z][A-Z0-9_]{0,31}', ch['serial']) or ch['serial'] in serials:
                raise BadRequest('角色编号重复或格式不正确')
            serials.add(ch['serial'])
            if not isinstance(ch.get('attrs'), dict) or any(type(v) not in (int, float, bool) for v in ch['attrs'].values()):
                raise BadRequest('数值属性必须为数字')
            if len([s for s in ch.get('spells', []) if not s.get('_disabled', False)]) >= len(CN_NUMS):
                raise BadRequest(f'当前引擎最多支持 {len(CN_NUMS)-1} 个技能')
            for s in ch.get('spells', []):
                if '_disabled' in s and type(s['_disabled']) is not bool:
                    raise BadRequest('技能禁用状态必须为布尔值')
                if s.get('_disabled', False):
                    continue
                effects = s.get('effects', [])
                if not isinstance(effects, list) or any(not isinstance(e, dict) or ('_disabled' in e and type(e['_disabled']) is not bool) for e in effects):
                    raise BadRequest('技能效果必须为列表，禁用状态必须为布尔值')
                active_effects = [e for e in effects if not e.get('_disabled', False)]
                if not s.get('name') or len(active_effects) > len(CAT_LETTERS):
                    raise BadRequest('技能需有名称，效果数量不能超过引擎支持数量')
                for e in active_effects:
                    if type(e.get('type')) is not int or e['type'] not in (*range(1, 15), 17, 18, 19):
                        raise BadRequest('请选择有效效果类型')
                    if (enabled is None or ch['serial'] in enabled) and e.get('召唤物模板') and e['召唤物模板'] not in summons:
                        raise BadRequest(f"{ch['serial']} · {ch['name']}：召唤物模板「{e['召唤物模板']}」不存在，请修正后启用")
            try:
                eng = CombatEngine()
                self.module().load_character_to_engine(eng, runtime_character(ch), 'validation')
            except Exception as exc:
                raise BadRequest('角色无法加载：' + str(exc)) from exc

    def save(self):
        self.require_local()
        data = self.c['body']()
        with self.lock, self.c['guard'], self.c['ns']['_lock']:
            path = self.root / 'characters_data.py'
            raw = path.read_bytes()
            if data.get('version') != digest(raw):
                raise Conflict('数据已被修改，请重新加载后编辑')
            characters = data.get('characters')
            try:
                json.dumps(data, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise BadRequest('数值必须是有限数字') from exc
            summons = data.get('summons', self.module().SUMMON_TEMPLATES)
            if 'enabled_serials' in data and not isinstance(data['enabled_serials'], list):
                raise BadRequest('启用角色编号必须为列表')
            if not isinstance(characters, list) or not characters or any(not isinstance(ch, dict) for ch in characters):
                raise BadRequest('至少保留一个有效角色')
            try:
                previous = {ch['serial']: ch for ch in self.editable_characters(raw.decode('utf-8-sig'))}
                characters = [identify_skills(ch, previous.get(ch.get('serial'))) for ch in characters]
                validate_global_skill_ids(characters)
            except ValueError as exc:
                raise BadRequest(str(exc)) from exc
            self.validate(characters, summons, data.get('enabled_serials'))
            enabled = data.get('enabled_serials', [ch['serial'] for ch in characters])
            serials = {ch['serial'] for ch in characters}
            if not isinstance(enabled, list) or not enabled:
                raise BadRequest('至少保留一名启用角色')
            if any(not isinstance(s, str) or s not in serials for s in enabled) or len(enabled) != len(set(enabled)):
                raise BadRequest('启用角色编号必须唯一且属于当前角色列表')
            source = raw.decode('utf-8-sig')
            tree = ast.parse(source)
            nodes = {n.targets[0].id: n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
            active = [n.id for n in nodes['ALL_CHARACTERS'].value.elts]
            definitions = self.character_definitions(tree)
            by_serial = {getattr(self.module(), name)['serial']: name for name in definitions}
            lines = source.splitlines(keepends=True)
            edits, saved_names, additions = [], {}, []
            for ch in characters:
                name = by_serial.get(ch['serial'])
                if name is None:
                    base = 'CUSTOM_' + ch['serial']
                    name, suffix = base, 2
                    while name in nodes or name in saved_names.values():
                        name, suffix = base + '_' + str(suffix), suffix + 1
                saved_names[ch['serial']] = name
                value = format_character(name, ch)
                if name in nodes:
                    n = nodes[name]
                    edits.append((n.lineno-1, n.end_lineno, value))
                else:
                    additions.append(value)
            removable = definitions if 'enabled_serials' in data else active
            for name in set(removable) - set(saved_names.values()):
                n = nodes[name]
                edits.append((n.lineno-1, n.end_lineno, ''))
            for name, val in [('SUMMON_TEMPLATES', summons), ('ITEM_TEMPLATES', data.get('items', self.module().ITEM_TEMPLATES))]:
                n = nodes[name]
                later = []
                for assignment in tree.body:
                    if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1:
                        continue
                    target = assignment.targets[0]
                    if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                            and target.value.id == name and isinstance(target.slice, ast.Constant)):
                        later.append((assignment, target.slice.value))
                late_keys = {key for _, key in later}
                base = {key: value for key, value in val.items() if key not in late_keys}
                edits.append((n.lineno-1, n.end_lineno, name + ' = ' + pprint.pformat(base, width=110, sort_dicts=False) + '\n'))
                for assignment, key in later:
                    replacement = (f'{name}[{key!r}] = ' + pprint.pformat(val[key], width=110, sort_dicts=False) + '\n') if key in val else ''
                    edits.append((assignment.lineno-1, assignment.end_lineno, replacement))
            n = nodes['ALL_CHARACTERS']
            names = [saved_names[serial] for serial in enabled]
            edits.append((n.lineno-1, n.end_lineno, '\n'.join(additions) + '\nALL_CHARACTERS = [' + ', '.join(names) + ']\n'))
            if 'settings' in data:
                setting = data['settings'].get('GLOBAL_RANGE_OVERRIDE')
                if type(setting) is not int or setting not in (0, 1):
                    raise BadRequest('全局射程覆盖应为 0 或 1')
                n = nodes['GLOBAL_RANGE_OVERRIDE']
                edits.append((n.lineno-1, n.end_lineno, f'GLOBAL_RANGE_OVERRIDE = {setting}\n'))
            for start, end, val in sorted(edits, reverse=True):
                lines[start:end] = [val]
            updated = ''.join(lines).encode('utf-8')
            compile(updated, str(path), 'exec')
            bid = self.make_backup('before save')
            atomic_write(path, updated)
            self.reload()
            self.runtime.joinpath('needs-training').touch()
            return jsonify(ok=True, version=digest(updated), backup=bid, needs_training=True)

    def snapshot_task(self, jid):
        dest = self.runtime / 'jobs' / jid
        dest.mkdir(parents=True, exist_ok=True)
        for source in self.root.glob('*.py'):
            if source.name != 'autocombat_backend.py':
                shutil.copy2(source, dest / source.name)
        for name in ('ai_weights.json',):
            if (self.root / name).exists():
                shutil.copy2(self.root / name, dest / name)
        if hasattr(self, 'settings'):
            from combat_settings import snapshot
            atomic_write(dest / 'settings-snapshot.json', json.dumps(snapshot(), ensure_ascii=False).encode('utf-8'))
        return dest
