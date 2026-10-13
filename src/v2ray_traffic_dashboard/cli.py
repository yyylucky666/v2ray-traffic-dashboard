import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from . import __version__
from . import accounting, config, exporter
from .classification import candidate


def main():
    parser = argparse.ArgumentParser(description='V2Ray category traffic accounting and static dashboard')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--config', default=os.environ.get('VTD_CONFIG', '/etc/v2ray-traffic-dashboard/config.json'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('collect')
    sub.add_parser('doctor')
    sub.add_parser('export')
    report = sub.add_parser('report')
    report.add_argument('--period', default='today')
    report.add_argument('--json', action='store_true')
    prepare = sub.add_parser('prepare-config')
    prepare.add_argument('--input', required=True)
    prepare.add_argument('--output', required=True)
    prepare.add_argument('--direct-tag', default='direct')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        cfg = config.load(args.config)
        root = Path(cfg['state_dir'])
        if args.command == 'prepare-config':
            result = candidate(json.loads(Path(args.input).read_text()), cfg, args.direct_tag)
            # Exclusive creation prevents overwriting any existing or live configuration.
            with Path(args.output).open('x') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                f.write('\n')
            print('Candidate written privately; live configuration unchanged. Validate and review before activation.')
        elif args.command == 'doctor':
            accounting.process_epoch(cfg['v2ray_service'])
            r = subprocess.run([cfg['v2ray_binary'], 'api', 'stats', '-s', cfg['stats_server'], '-json'],
                               capture_output=True, text=True, timeout=10)
            if r.returncode:
                raise RuntimeError('Statistics API is unavailable')
            accounting.parse_counters(json.loads(r.stdout), cfg['categories'])
            print('V2Ray process, loopback API and category counters are available; counters were not reset.')
        elif args.command == 'collect':
            accounting.collect(root, cfg['stats_server'], cfg['v2ray_binary'], cfg['v2ray_service'],
                               cfg['categories'], cfg.get('retention_days', 400))
            exporter.export(root / 'traffic.sqlite3', args.config, Path(cfg['web_dir']) / 'data')
        elif args.command == 'export':
            exporter.export(root / 'traffic.sqlite3', args.config, Path(cfg['web_dir']) / 'data')
        else:
            accounting.report(root, args.period, args.json, cfg['categories'])
    except Exception as exc:
        print('v2ray-traffic-dashboard: ' + str(exc), file=sys.stderr)
        return 1
    return 0
