#!/usr/bin/python3
"""Export only aggregated counters, never proxy configuration or raw access logs."""
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import tempfile

TZ = dt.timezone(dt.timedelta(hours=8))


def atomic_json(path, data):
    payload = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    fd, temp = tempfile.mkstemp(prefix='.snapshot-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def export(db_path, categories_path, output, now=None):
    now = now or dt.datetime.now(TZ)
    categories = json.loads(Path(categories_path).read_text())['categories']
    public_categories = [{'id': c['id'], 'label': c['label']} for c in categories]
    ids = {c['id'] for c in categories}
    db = sqlite3.connect('file:' + str(Path(db_path)) + '?mode=ro', uri=True, timeout=5)
    try:
        db.execute('BEGIN')
        meta = dict(db.execute('SELECT key,value FROM meta'))
        last_sample = json.loads(meta['sample'])['at']
        rows = db.execute('SELECT day,category,uplink,downlink FROM daily ORDER BY day,category').fetchall()
        quality = db.execute("SELECT substr(at,1,10),kind,COUNT(*) FROM events WHERE kind IN ('counter_reset','sampling_gap') GROUP BY substr(at,1,10),kind").fetchall()
    finally:
        db.close()
    by_month = {}
    day_totals = {}
    for day, category, up, down in rows:
        if category not in ids:
            continue
        month = day[:7]
        by_month.setdefault(month, {}).setdefault(day, {})[category] = {'upload': up, 'download': down}
        total = day_totals.setdefault(day, {'upload': 0, 'download': 0})
        total['upload'] += up
        total['download'] += down
    current_month = now.strftime('%Y-%m')
    by_month.setdefault(current_month, {})
    quality_days = {}
    for day, kind, count in quality:
        quality_days.setdefault(day, {})[kind] = count
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    month_totals = {}
    for month, days in by_month.items():
        upload = sum(day_totals[d]['upload'] for d in days)
        download = sum(day_totals[d]['download'] for d in days)
        month_totals[month] = {'upload': upload, 'download': download}
        atomic_json(output / (month + '.json'), {
            'schema': 1, 'month': month, 'last_sample': last_sample,
            'days': days, 'quality': {d: v for d, v in quality_days.items() if d.startswith(month)}})
    recent = sorted(day_totals)[-14:]
    index = {'schema': 1, 'timezone': 'Asia/Shanghai', 'started_at': meta['started_at'],
             'last_sample': last_sample, 'generated_at': now.isoformat(), 'categories': public_categories,
             'months': sorted(by_month, reverse=True), 'month_totals': month_totals,
             'recent_days': {d: day_totals[d] for d in recent}}
    # Publish index last, after every referenced monthly file exists.
    atomic_json(output / 'index.json', index)
    for path in output.glob('????-??.json'):
        if path.stem not in by_month:
            path.unlink()
    return index

