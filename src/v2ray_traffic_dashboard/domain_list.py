"""Bounded, incremental access-log domain inventory. Never records source addresses."""
import argparse
import datetime as dt
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

TZ = dt.timezone(dt.timedelta(hours=8))
PATTERN = re.compile(r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)?\s+.*?\baccepted\s+(?:tcp|udp):([^\s]+)\s+\[([^\]]+)\]\s*$')


def parse(line, tag='usage-other', log_timezone='UTC'):
    match = PATTERN.match(line)
    if not match or match[3].split('->')[-1].strip() != tag:
        return None
    host, separator, port = match[2].rpartition(':')
    if not separator or not port.isdigit() or not 0 < int(port) <= 65535:
        return None
    host = host.strip('[]').rstrip('.').lower()
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    try:
        host = host.encode('idna').decode('ascii')
        if len(host) > 253 or '.' not in host or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in host.split('.')):
            return None
        stamp = dt.datetime.strptime(match[1], '%Y/%m/%d %H:%M:%S').replace(tzinfo=ZoneInfo(log_timezone)).astimezone(TZ)
    except (ValueError, UnicodeError):
        return None
    return stamp.date().isoformat(), host, stamp.isoformat()


def connect(database):
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(database, timeout=5)
    os.chmod(database, 0o600)
    db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS domains(day TEXT,domain TEXT,connections INTEGER,last_seen TEXT,PRIMARY KEY(day,domain));
CREATE TABLE IF NOT EXISTS issues(day TEXT,kind TEXT,count INTEGER,PRIMARY KEY(day,kind));''')
    return db


def put(db, key, value):
    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))


def issue(db, day, kind):
    db.execute('INSERT INTO issues VALUES (?,?,1) ON CONFLICT(day,kind) DO UPDATE SET count=count+1', (day, kind))


def opener(path):
    return gzip.open(path, 'rb') if str(path).endswith('.gz') else open(path, 'rb')


def fingerprint(path, length=4096):
    with opener(path) as f:
        prefix = f.read(length)
    return {'length': len(prefix), 'sha256': hashlib.sha256(prefix).hexdigest()}


def matches(path, cursor):
    return fingerprint(path, cursor['anchor']['length']) == cursor['anchor']


def collect(database, access_log, tag='usage-other', log_timezone='UTC', retention_days=400,
            max_bytes=4 * 1024 * 1024, max_domains=1000, now=None):
    """Commit aggregate and byte cursor together; recover identifiable rotated tails."""
    ZoneInfo(log_timezone)
    if not 1 <= retention_days <= 3660 or not 1024 <= max_bytes <= 16 * 1024 * 1024 or not 1 <= max_domains <= 5000:
        raise ValueError('Invalid retention or collection bounds')
    now = now or dt.datetime.now(TZ)
    day = now.astimezone(TZ).date().isoformat()
    path = Path(access_log)
    stat = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ValueError('Access log must be a regular file')
    db = connect(database)
    try:
        db.execute('BEGIN IMMEDIATE')
        meta = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM meta')}
        settings = {'access_log': str(path.resolve()), 'tag': tag, 'log_timezone': log_timezone}
        if meta.get('settings', settings) != settings:
            raise ValueError('Log path, tag or timezone changed; use a fresh domain database')
        put(db, 'settings', settings)
        if 'recording_started_at' not in meta:
            put(db, 'recording_started_at', now.isoformat())
        cursor = meta.get('cursor')
        pending = meta.get('pending', [])
        if cursor and (cursor['inode'] != stat.st_ino or cursor['device'] != stat.st_dev or stat.st_size < cursor['offset'] or not matches(path, cursor)):
            if cursor['offset'] == 0:
                pass
            elif len(pending) < 8:
                pending.append(cursor)
            else:
                issue(db, day, 'rotation_gap')
            cursor = None
        if cursor is None:
            cursor = {'inode': stat.st_ino, 'device': stat.st_dev, 'offset': 0, 'anchor': fingerprint(path), 'discarding': False}
        consumed = 0
        first = meta.get('first_record_at')
        cutoff = (now.astimezone(TZ).date() - dt.timedelta(days=retention_days - 1)).isoformat()
        counts = {d: n for d, n in db.execute('SELECT day,COUNT(*) FROM domains GROUP BY day')}

        def read(source, position, live):
            nonlocal consumed, first
            with opener(source) as f:
                f.seek(position['offset'])
                while consumed < max_bytes:
                    start = f.tell()
                    raw = f.readline(8192)
                    if not raw:
                        return True
                    consumed += len(raw)
                    if not raw.endswith(b'\n') and live and f.tell() == os.fstat(f.fileno()).st_size and len(raw) < 8192:
                        f.seek(start)
                        return False  # Incomplete final record: wait for the writer.
                    if not raw.endswith(b'\n'):
                        position['discarding'] = True
                        position['offset'] = f.tell()
                        continue
                    if position.get('discarding'):
                        position['discarding'] = False
                        issue(db, day, 'oversized_record')
                    else:
                        record = parse(raw.decode('utf-8', errors='replace').rstrip(), tag, log_timezone)
                        if record and record[0] >= cutoff and record[0] <= day:
                            record_day, host, stamp = record
                            existing = db.execute('SELECT 1 FROM domains WHERE day=? AND domain=?', (record_day, host)).fetchone()
                            if existing or counts.get(record_day, 0) < max_domains:
                                db.execute('INSERT INTO domains VALUES (?,?,1,?) ON CONFLICT(day,domain) DO UPDATE SET connections=connections+1,last_seen=MAX(last_seen,excluded.last_seen)', (record_day, host, stamp))
                                if not existing:
                                    counts[record_day] = counts.get(record_day, 0) + 1
                                first = min(first, stamp) if first else stamp
                            else:
                                issue(db, record_day, 'domain_limit')
                    position['offset'] = f.tell()
                return False

        remaining = []
        for old in pending:
            if consumed >= max_bytes:
                remaining.append(old)
                continue
            found = None
            for candidate in sorted(path.parent.glob(path.name + '.*'))[:16]:
                if candidate.is_file() and not candidate.is_symlink():
                    try:
                        if matches(candidate, old):
                            found = candidate
                            break
                    except (OSError, EOFError):
                        continue
            if found is None:
                issue(db, day, 'rotation_gap')
            elif not read(found, old, False):
                remaining.append(old)
        if consumed < max_bytes:
            read(path, cursor, True)
        # Detect truncation/replacement during a read and roll back its increments.
        latest = path.stat()
        if latest.st_ino != cursor['inode'] or latest.st_dev != cursor['device'] or latest.st_size < cursor['offset'] or not matches(path, cursor):
            raise RuntimeError('Access log rotated during collection; retry on the next timer tick')
        if cursor['anchor']['length'] < min(4096, latest.st_size):
            cursor['anchor'] = fingerprint(path)
        put(db, 'cursor', cursor)
        put(db, 'pending', remaining)
        put(db, 'first_record_at', first)
        put(db, 'last_collected_at', now.isoformat())
        put(db, 'caught_up', not remaining and cursor['offset'] >= latest.st_size)
        put(db, 'max_domains_per_day', max_domains)
        db.execute('DELETE FROM domains WHERE day<?', (cutoff,))
        db.execute('DELETE FROM issues WHERE day<?', (cutoff,))
        db.commit()
        return consumed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.domains-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
            f.write('\n')
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def export(database, output, row_limit=500):
    """Publish destination names and counts only; keep paths/cursors private."""
    output = Path(output)
    db = sqlite3.connect('file:' + str(Path(database).resolve()) + '?mode=ro', uri=True)
    try:
        db.execute('BEGIN')
        meta = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM meta')}
        months = [r[0] for r in db.execute('SELECT DISTINCT substr(day,1,7) FROM domains ORDER BY 1')]
        def summary(start, end):
            rows = db.execute('SELECT domain,SUM(connections),MAX(last_seen) FROM domains WHERE day>=? AND day<? GROUP BY domain ORDER BY SUM(connections) DESC,domain LIMIT ?', (start, end, row_limit)).fetchall()
            total, connections = db.execute('SELECT COUNT(DISTINCT domain),COALESCE(SUM(connections),0) FROM domains WHERE day>=? AND day<?', (start, end)).fetchone()
            issues = dict(db.execute('SELECT kind,SUM(count) FROM issues WHERE day>=? AND day<? GROUP BY kind', (start, end)))
            return {'domains': [{'domain': h, 'connections': n, 'last_seen': at} for h, n, at in rows], 'total_domains': total, 'total_connections': connections, 'truncated': total > row_limit, 'issues': issues}
        for month in months:
            start = dt.date.fromisoformat(month + '-01')
            end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1).isoformat()
            days = [r[0] for r in db.execute('SELECT DISTINCT day FROM domains WHERE day>=? AND day<? ORDER BY day', (start.isoformat(), end))]
            data = {'schema': 1, 'month': month, 'days': {d: summary(d, (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()) for d in days}, 'monthly': summary(start.isoformat(), end)}
            atomic_json(output / ('domains-' + month + '.json'), data)
        index = {'schema': 1, 'category': 'other', 'timezone': 'Asia/Shanghai', 'months': months, 'row_limit': row_limit,
                 **{k: meta.get(k) for k in ('recording_started_at', 'first_record_at', 'last_collected_at', 'caught_up', 'max_domains_per_day')}}
        index['issues'] = dict(db.execute('SELECT kind,SUM(count) FROM issues GROUP BY kind'))
        atomic_json(output / 'domains-index.json', index)
        for file in output.glob('domains-????-??.json'):
            if file.name[8:15] not in months:
                file.unlink()
        return index
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--access-log', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--tag', default='usage-other')
    p.add_argument('--log-timezone', default='UTC')
    p.add_argument('--retention-days', type=int, default=400)
    args = p.parse_args()
    os.umask(0o077)
    collect(args.database, args.access_log, args.tag, args.log_timezone, args.retention_days)
    export(args.database, args.output)


if __name__ == '__main__':
    main()
