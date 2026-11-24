"""Small transactional document store for resumable browser jobs and tournaments."""
import json
import math
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager


def _extract_legacy_timestamp(raw_body):
    """Best-effort timestamp extraction for legacy rows created before record_meta existed."""
    try:
        doc = json.loads(raw_body)
    except (TypeError, ValueError):
        return 1.0
    if isinstance(doc, dict):
        for key in ('updated_at', 'last_login_at', 'created_at', 'created'):
            val = doc.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val) and val > 0:
                return float(val)
    return 1.0


class Store:
    def __init__(self, path, node_id=None):
        self.path, self.lock = str(path), threading.RLock()
        self.node_id = str(node_id or secrets.token_hex(6))
        self._listeners = []
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
            db.execute(
                'CREATE TABLE IF NOT EXISTS record_meta ('
                'kind TEXT, id TEXT, updated_at REAL, deleted INTEGER DEFAULT 0, '
                'origin TEXT DEFAULT "", rev INTEGER DEFAULT 0, PRIMARY KEY(kind,id))'
            )
            cols = {row[1] for row in db.execute('PRAGMA table_info(record_meta)').fetchall()}
            if 'rev' not in cols:
                db.execute('ALTER TABLE record_meta ADD COLUMN rev INTEGER DEFAULT 0')
            db.execute('CREATE INDEX IF NOT EXISTS idx_record_meta_updated ON record_meta(updated_at)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_record_meta_rev ON record_meta(rev)')
        self._backfill_meta()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _next_rev(self, db):
        row = db.execute('SELECT COALESCE(MAX(rev), 0) FROM record_meta').fetchone()
        return int(row[0] or 0) + 1

    def _backfill_meta(self):
        with self.lock, self.connect() as db:
            next_rev = self._next_rev(db)
            missing = db.execute(
                'SELECT r.kind, r.id, r.body FROM records r '
                'LEFT JOIN record_meta m ON r.kind = m.kind AND r.id = m.id '
                'WHERE m.kind IS NULL'
            ).fetchall()
            if missing:
                rows = []
                for kind, rid, raw_body in missing:
                    rows.append((kind, rid, _extract_legacy_timestamp(raw_body), next_rev))
                    next_rev += 1
                db.executemany('INSERT OR IGNORE INTO record_meta VALUES (?,?,?,0,"",?)', rows)
            zero_revs = db.execute(
                'SELECT kind, id FROM record_meta WHERE rev IS NULL OR rev <= 0 ORDER BY updated_at ASC, kind ASC, id ASC'
            ).fetchall()
            if zero_revs:
                updates = []
                for kind, rid in zero_revs:
                    updates.append((next_rev, kind, rid))
                    next_rev += 1
                db.executemany('UPDATE record_meta SET rev=? WHERE kind=? AND id=?', updates)

    def add_change_listener(self, callback):
        with self.lock:
            self._listeners.append(callback)

    def _notify_listeners(self, kinds):
        unique_kinds = list(dict.fromkeys(k for k in kinds if k))
        if not unique_kinds:
            return
        with self.lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(unique_kinds)
            except Exception as exc:
                print(f'[store] change listener error: {exc}', file=sys.stderr)

    def _next_timestamp(self, db, kind, identifier, explicit_ts):
        if explicit_ts is not None:
            return float(explicit_ts)
        now = time.time()
        row = db.execute(
            'SELECT updated_at FROM record_meta WHERE kind=? AND id=?',
            (kind, identifier),
        ).fetchone()
        if row and row[0] is not None:
            existing = float(row[0] or 0.0)
            if now <= existing:
                return existing + 0.001
        return now

    def put(self, kind, value, updated_at=None):
        payload = json.dumps(value, ensure_ascii=False)
        with self.lock, self.connect() as db:
            ts = self._next_timestamp(db, kind, value['id'], updated_at)
            rev = self._next_rev(db)
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (kind, value['id'], payload))
            db.execute(
                'INSERT OR REPLACE INTO record_meta VALUES (?,?,?,0,?,?)',
                (kind, value['id'], ts, self.node_id, rev),
            )
        self._notify_listeners([kind])

    def get(self, kind, identifier):
        with self.connect() as db:
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        return json.loads(row[0]) if row else None

    def put_many(self, records, updated_at=None):
        """Atomically commit a story, its profile and combat checkpoint."""
        items = [(kind, value['id'], json.dumps(value, ensure_ascii=False)) for kind, value in records]
        if not items:
            return
        with self.lock, self.connect() as db:
            rev = self._next_rev(db)
            meta_rows = []
            for offset, (kind, rid, _) in enumerate(items):
                ts = self._next_timestamp(db, kind, rid, updated_at)
                meta_rows.append((kind, rid, ts, self.node_id, rev + offset))
            db.executemany('INSERT OR REPLACE INTO records VALUES (?,?,?)', items)
            db.executemany(
                'INSERT OR REPLACE INTO record_meta VALUES (?,?,?,0,?,?)',
                meta_rows,
            )
        self._notify_listeners([kind for kind, _, _ in items])

    def delete(self, kind, identifier, updated_at=None):
        with self.lock, self.connect() as db:
            ts = self._next_timestamp(db, kind, identifier, updated_at)
            rev = self._next_rev(db)
            db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, identifier))
            db.execute(
                'INSERT OR REPLACE INTO record_meta VALUES (?,?,?,1,?,?)',
                (kind, identifier, ts, self.node_id, rev),
            )
        self._notify_listeners([kind])

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def export_records(self, kinds=None, since=0.0, since_rev=None, include_head=False):
        kind_list = list(kinds) if kinds is not None else None
        if kind_list is not None and not kind_list:
            if include_head:
                with self.lock, self.connect() as db:
                    return [], self._next_rev(db) - 1
            return []
        if since_rev is not None:
            params = [int(since_rev)]
            where = 'm.rev > ?'
            order_by = 'm.rev ASC, m.kind ASC, m.id ASC'
        else:
            params = [float(since or 0.0)]
            where = 'm.updated_at > ?'
            order_by = 'm.updated_at ASC, m.kind ASC, m.id ASC'
        if kind_list is not None:
            placeholders = ','.join('?' for _ in kind_list)
            where += f' AND m.kind IN ({placeholders})'
            params.extend(kind_list)
        sql = (
            'SELECT m.kind, m.id, m.updated_at, m.deleted, m.origin, m.rev, r.body '
            'FROM record_meta m '
            'LEFT JOIN records r ON m.kind = r.kind AND m.id = r.id '
            f'WHERE {where} '
            f'ORDER BY {order_by}'
        )
        with self.lock, self.connect() as db:
            head_rev = self._next_rev(db) - 1
            rows = db.execute(sql, params).fetchall()
        out = []
        for kind, rid, updated_at, deleted, origin, rev, raw_body in rows:
            is_deleted = bool(deleted)
            if is_deleted:
                body = None
            else:
                if raw_body is None:
                    continue
                try:
                    body = json.loads(raw_body)
                except (TypeError, ValueError):
                    continue
            out.append({
                'kind': kind,
                'id': rid,
                'body': body,
                'updated_at': float(updated_at or 0.0),
                'deleted': is_deleted,
                'origin': str(origin or ''),
                'rev': int(rev or 0),
            })
        if include_head:
            return out, head_rev
        return out

    def merge_records(self, incoming, allowed_kinds=None):
        """Merge remote records using Last-Write-Wins without firing local sync listeners."""
        allowed = set(allowed_kinds) if allowed_kinds is not None else None
        upserted = 0
        deleted_count = 0
        skipped = 0
        changed = []
        with self.lock, self.connect() as db:
            next_rev = self._next_rev(db)
            for item in incoming or ():
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                kind = item.get('kind')
                rid = item.get('id')
                inc_ts = item.get('updated_at')
                if (
                    not isinstance(kind, str) or not kind
                    or not isinstance(rid, str) or not rid
                    or not isinstance(inc_ts, (int, float))
                    or isinstance(inc_ts, bool)
                    or not math.isfinite(inc_ts)
                    or inc_ts < 0
                ):
                    skipped += 1
                    continue
                if allowed is not None and kind not in allowed:
                    skipped += 1
                    continue
                inc_ts = float(inc_ts)
                inc_deleted = bool(item.get('deleted', False))
                inc_origin = str(item.get('origin') or '')[:64]

                row = db.execute(
                    'SELECT updated_at, deleted, origin FROM record_meta WHERE kind=? AND id=?',
                    (kind, rid),
                ).fetchone()
                if row is not None:
                    local_ts = float(row[0] or 0.0)
                    local_deleted = int(bool(row[1]))
                    local_origin = str(row[2] or '')
                    if inc_ts < local_ts:
                        skipped += 1
                        continue
                    if inc_ts == local_ts and (inc_origin, int(inc_deleted)) <= (local_origin, local_deleted):
                        skipped += 1
                        continue

                if inc_deleted:
                    db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, rid))
                    db.execute(
                        'INSERT OR REPLACE INTO record_meta VALUES (?,?,?,1,?,?)',
                        (kind, rid, inc_ts, inc_origin, next_rev),
                    )
                    next_rev += 1
                    deleted_count += 1
                    changed.append((kind, rid))
                else:
                    body = item.get('body')
                    if not isinstance(body, dict):
                        skipped += 1
                        continue
                    doc = dict(body)
                    doc['id'] = rid
                    db.execute(
                        'INSERT OR REPLACE INTO records VALUES (?,?,?)',
                        (kind, rid, json.dumps(doc, ensure_ascii=False)),
                    )
                    db.execute(
                        'INSERT OR REPLACE INTO record_meta VALUES (?,?,?,0,?,?)',
                        (kind, rid, inc_ts, inc_origin, next_rev),
                    )
                    next_rev += 1
                    upserted += 1
                    changed.append((kind, rid))
        return {
            'upserted': upserted,
            'deleted': deleted_count,
            'skipped': skipped,
            'changed': changed,
        }

    def summary(self, kinds=None):
        kind_list = list(kinds) if kinds is not None else None
        with self.lock, self.connect() as db:
            if kind_list is not None:
                if not kind_list:
                    return {'node_id': self.node_id, 'counts': {}, 'max_updated_at': 0.0, 'max_rev': 0}
                placeholders = ','.join('?' for _ in kind_list)
                rows = db.execute(
                    f'SELECT kind, COUNT(*) FROM records WHERE kind IN ({placeholders}) GROUP BY kind',
                    kind_list,
                ).fetchall()
                max_row = db.execute(
                    f'SELECT MAX(updated_at), MAX(rev) FROM record_meta WHERE kind IN ({placeholders})',
                    kind_list,
                ).fetchone()
            else:
                rows = db.execute('SELECT kind, COUNT(*) FROM records GROUP BY kind').fetchall()
                max_row = db.execute('SELECT MAX(updated_at), MAX(rev) FROM record_meta').fetchone()
        return {
            'node_id': self.node_id,
            'counts': {k: int(c) for k, c in rows},
            'max_updated_at': float(max_row[0] or 0.0) if max_row else 0.0,
            'max_rev': int(max_row[1] or 0) if max_row else 0,
        }
