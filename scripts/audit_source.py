#!/usr/bin/env python3
"""Fail publication checks on likely credentials or generated private artifacts."""
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
patterns=[re.compile(rb'AKIA[0-9A-Z]{16}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
          re.compile(b'-----BEGIN '+rb'(?:[A-Z]+ )?PRIVATE KEY-----'),
          re.compile(rb'"password"\s*:\s*"[^"\s]{4,}"')]
forbidden={'.pem','.key','.p12','.pfx','.sqlite3','.db','.log','.csv'}


def main():
    result=subprocess.run(['git','-C',str(ROOT),'ls-files','-z'],capture_output=True)
    paths=[ROOT/p for p in result.stdout.decode().split('\0') if p] if result.returncode==0 and result.stdout else [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts]
    problems=[]
    for p in paths:
        relative=p.relative_to(ROOT)
        if p.suffix in forbidden or p.name in ('htpasswd','login-info.json','login.json') or relative.parts[:2]==('web','data'):
            problems.append(str(relative)+': forbidden runtime artifact')
        data=p.read_bytes()
        if any(pattern.search(data) for pattern in patterns):problems.append(str(relative)+': possible credential')
        if b'/' + b'Users/' in data:problems.append(str(relative)+': personal macOS path')
    if problems:
        print('\n'.join(problems),file=sys.stderr);return 1
    print('Source audit passed for '+str(len(paths))+' files; no detected credentials or private runtime artifacts.')
    return 0

if __name__=='__main__':sys.exit(main())
