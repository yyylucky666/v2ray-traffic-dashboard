#!/usr/bin/env python3
"""Remove dashboard-owned files; preserve accounting data and proxy configuration."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

NAME='v2ray-traffic-dashboard'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config-dir',default='/etc/'+NAME)
    p.add_argument('--destdir')
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    if not (args.apply or args.destdir):
        print('Preview only. Use --apply on Linux or --destdir DIR for offline removal. Accounting data is preserved.')
        return
    if not args.destdir and (sys.platform!='linux' or os.geteuid()!=0):
        p.error('--apply requires root on Linux')
    dest=Path(args.destdir).resolve() if args.destdir else Path('/')
    def target(value):
        path=Path(value)
        if not path.is_absolute() or '..' in path.parts or str(path)=='/':
            raise ValueError('Unsafe managed path')
        result=dest/str(path).lstrip('/')
        if not result.resolve().is_relative_to(dest) or any(x.is_symlink() for x in [result]+list(result.parents)[:-1]):
            raise ValueError('Unsafe symlink or destination')
        return result
    try:
        manifest=json.loads(target(args.config_dir+'/managed.json').read_text())
        if manifest['schema']!=1 or args.config_dir not in manifest['directories']:
            raise ValueError('Invalid installation manifest')
        files=[target(x) for x in manifest['files']]
        directories=[target(x) for x in manifest['directories']]
        state=target(manifest['state_dir'])
        if any(d==state or d in state.parents for d in directories):
            raise ValueError('State directory overlaps removable directories')
        if not args.destdir:
            if any(str(f).endswith(NAME+'-domains.timer') for f in files):
                subprocess.run(['systemctl','disable','--now',NAME+'-domains.timer'],check=True)
                subprocess.run(['systemctl','stop',NAME+'-domains.service'],check=True)
            subprocess.run(['systemctl','disable','--now',NAME+'.timer',NAME+'-web.service'],check=True)
            subprocess.run(['systemctl','stop',NAME+'.service'],check=True)
        for f in files:
            f.unlink(missing_ok=True)
        for d in directories:
            if d.exists():shutil.rmtree(d)
        if not args.destdir:subprocess.run(['systemctl','daemon-reload'],check=True)
        print('Dashboard removed. Accounting data preserved; V2Ray was not changed or restarted.')
    except Exception as exc:p.exit(1,'Uninstall failed: '+str(exc)+'\n')

if __name__=='__main__':main()
