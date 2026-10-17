#!/usr/bin/python3
"""Local V2Ray byte accounting. No credentials, packet capture or public listener."""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess

TZ = dt.timezone(dt.timedelta(hours=8))
DEFAULT_ROOT = Path('/var/lib/v2ray-traffic-dashboard')


def connect_db(path):
    db = sqlite3.connect(str(path), timeout=5)
    db.execute('PRAGMA journal_mode=DELETE')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS daily (
            day TEXT NOT NULL, category TEXT NOT NULL,
            uplink INTEGER NOT NULL, downlink INTEGER NOT NULL,
            PRIMARY KEY(day, category));
        CREATE TABLE IF NOT EXISTS hourly (
            hour TEXT NOT NULL, category TEXT NOT NULL,
            uplink INTEGER NOT NULL, downlink INTEGER NOT NULL,
            PRIMARY KEY(hour, category));
        CREATE TABLE IF NOT EXISTS events (
            at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
    ''')
    return db


def parse_counters(payload, categories):
    by_name = {s['name']: int(s.get('value', 0)) for s in payload.get('stat', [])}
    result = {}
    for category in categories:
        directions = {}
        for direction in ('uplink', 'downlink'):
            name = 'outbound>>>' + category['tag'] + '>>>traffic>>>' + direction
            if name not in by_name:
                raise ValueError('Missing counter for ' + category['id'] + '/' + direction)
            value = by_name[name]
            if value < 0:
                raise ValueError('Negative traffic counter')
            directions[direction] = value
        result[category['id']] = directions
    return result


def record_sample(db, now, epoch, counters, retention_days=400):
    """Seed existing totals; persist deltas transactionally; mark every reset/gap."""
    row = db.execute("SELECT value FROM meta WHERE key='sample'").fetchone()
    previous = json.loads(row[0]) if row else None
    current = {'at': now.isoformat(), 'epoch': epoch, 'counters': counters}
    day = now.astimezone(TZ).date().isoformat()
    with db:
        if previous:
            prior_time = dt.datetime.fromisoformat(previous['at'])
            if now <= prior_time:
                raise ValueError('Clock did not advance; sample not committed')
            db.execute("INSERT OR IGNORE INTO meta VALUES ('hourly_started_at',?)", (prior_time.astimezone(TZ).isoformat(),))
            gap = (now - prior_time).total_seconds()
            if gap > 300:
                db.execute('INSERT INTO events VALUES (?,?,?)',
                           (now.isoformat(), 'sampling_gap', str(int(gap)) + ' seconds'))
            process_changed = epoch != previous['epoch']
            for category, values in counters.items():
                before = previous['counters'].get(category)
                if before is None:
                    db.execute('INSERT INTO events VALUES (?,?,?)',
                               (now.isoformat(), 'new_category', category))
                    continue
                delta = {}
                reset = process_changed
                for direction, value in values.items():
                    if process_changed or value < before[direction]:
                        delta[direction] = value
                        reset = True
                    else:
                        delta[direction] = value - before[direction]
                if reset:
                    db.execute('INSERT INTO events VALUES (?,?,?)',
                               (now.isoformat(), 'counter_reset', category))
                db.execute('''INSERT INTO daily VALUES (?,?,?,?)
                    ON CONFLICT(day, category) DO UPDATE SET
                    uplink=uplink+excluded.uplink, downlink=downlink+excluded.downlink''',
                           (day, category, delta['uplink'], delta['downlink']))
                hour = now.astimezone(TZ).replace(minute=0, second=0, microsecond=0).isoformat()
                db.execute('''INSERT INTO hourly VALUES (?,?,?,?)
                    ON CONFLICT(hour, category) DO UPDATE SET
                    uplink=uplink+excluded.uplink, downlink=downlink+excluded.downlink''',
                           (hour, category, delta['uplink'], delta['downlink']))
        else:
            db.execute('INSERT INTO meta VALUES (?,?)', ('started_at', now.isoformat()))
            db.execute("INSERT OR IGNORE INTO meta VALUES ('hourly_started_at',?)", (now.astimezone(TZ).isoformat(),))
            db.execute('INSERT INTO events VALUES (?,?,?)',
                       (now.isoformat(), 'baseline', 'Counters seeded; historical traffic excluded'))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('sample',?)",
                   (json.dumps(current, separators=(',', ':')),))
        cutoff = (now.astimezone(TZ).date() - dt.timedelta(days=retention_days - 1)).isoformat()
        db.execute('DELETE FROM daily WHERE day < ?', (cutoff,))
        db.execute('DELETE FROM hourly WHERE hour < ?', (cutoff,))
        db.execute('DELETE FROM events WHERE at < ?', (cutoff,))


def process_epoch(service='v2ray.service'):
    pid = subprocess.check_output(
        ['systemctl', 'show', service, '-p', 'MainPID', '--value'], text=True).strip()
    if not pid.isdigit() or int(pid) == 0:
        raise RuntimeError('V2Ray is not running')
    text = Path('/proc/' + pid + '/stat').read_text()
    start_ticks = text.rsplit(')', 1)[1].split()[19]
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + pid + ':' + start_ticks


def collect(root, server, binary, service, categories, retention_days=400):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        epoch = process_epoch(service)
        result = subprocess.run(
            [binary, 'api', 'stats', '-s', server, '-json'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if result.returncode:
            raise RuntimeError('V2Ray statistics API failed; counters not changed')
        counters = parse_counters(json.loads(result.stdout), categories)
        if process_epoch(service) != epoch:
            raise RuntimeError('V2Ray restarted during sampling; retry next interval')
        db = connect_db(root / 'traffic.sqlite3')
        try:
            record_sample(db, dt.datetime.now(TZ), epoch, counters, retention_days)
        finally:
            db.close()
        print('分类流量采样成功；北京时间 ' + dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S'))


def report(root, period, as_json, categories):
    path = root / 'traffic.sqlite3'
    if not path.exists():
        raise RuntimeError('尚无统计数据；分类统计未启用或尚未完成首次采样')
    now = dt.datetime.now(TZ)
    period = {'today': now.strftime('%Y-%m-%d'), 'month': now.strftime('%Y-%m')}.get(period, period)
    try:
        dt.datetime.strptime(period, '%Y-%m-%d' if len(period) == 10 else '%Y-%m')
    except ValueError:
        raise ValueError('周期应为 today、month、YYYY-MM-DD 或 YYYY-MM')
    if len(period) not in (7, 10):
        raise ValueError('Invalid period')
    db = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
    try:
        rows = {r[0]: {'uplink': r[1], 'downlink': r[2]} for r in db.execute(
            'SELECT category,SUM(uplink),SUM(downlink) FROM daily WHERE day LIKE ? GROUP BY category',
            (period + '%',))}
        meta = dict(db.execute('SELECT key,value FROM meta'))
        events = list(db.execute('SELECT at,kind,detail FROM events WHERE substr(at,1,10) LIKE ? AND kind IN (?,?)',
                                (period + '%', 'counter_reset', 'sampling_gap')))
    finally:
        db.close()
    data = []
    for c in categories:
        counts = rows.get(c['id'], {'uplink': 0, 'downlink': 0})
        data.append({'category': c['id'], 'label': c['label'], **counts,
                     'total': counts['uplink'] + counts['downlink']})
    data.sort(key=lambda x: x['total'], reverse=True)
    last = json.loads(meta['sample'])['at']
    result = {'period': period, 'timezone': 'Asia/Shanghai', 'started_at': meta['started_at'],
              'last_sample': last, 'categories': data, 'reset_or_gap_events': len(events),
              'accounting': 'Outbound application bytes; not cloud-provider billed bytes. '
                            'Deltas crossing midnight belong to the sampling day. '
                            'Resets can lose the unsampled tail of the old process.'}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print('分类流量统计：' + period + '（北京时间）')
    print('开始统计：' + meta['started_at'] + '；最近采样：' + last)
    print('\n| 分类 | 上传 MiB | 下载 MiB | 合计 MiB |')
    print('|---|---:|---:|---:|')
    for item in data:
        print('| {} | {:.3f} | {:.3f} | {:.3f} |'.format(
            item['label'], item['uplink'] / 1048576, item['downlink'] / 1048576, item['total'] / 1048576))
    print('\n单位为代理出站应用字节；统计范围仅覆盖分类规则匹配到的连接。')
    print('跨午夜的采样增量计入采样当天；重置/采样中断事件：' + str(len(events)))
    print('进程重启或计数器重置时，未采到的旧进程尾部流量无法恢复。')
    age = (now - dt.datetime.fromisoformat(last)).total_seconds()
    if age > 300:
        print('注意：最近采样超过5分钟，需检查 v2ray-traffic-dashboard.timer/service。')

