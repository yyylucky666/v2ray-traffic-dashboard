#!/usr/bin/env python3
"""Create synthetic traffic and optionally serve an unauthenticated localhost demo."""
import argparse
import datetime as dt
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys

SOURCE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(SOURCE/'src'))
from v2ray_traffic_dashboard import accounting,exporter,domain_list


def build(output,now=None):
    output=Path(output)
    if output.exists():raise ValueError('Demo output already exists; choose an empty new directory')
    output.mkdir(parents=True)
    shutil.copytree(SOURCE/'web',output/'web')
    cfg=SOURCE/'examples/config.json';cats=json.loads(cfg.read_text())['categories']
    now=now or dt.datetime.now(accounting.TZ)
    today=now.astimezone(accounting.TZ).date()
    first=today-dt.timedelta(days=34)
    db=accounting.connect_db(output/'synthetic.sqlite3')
    try:
        db.execute('INSERT INTO meta VALUES (?,?)',('started_at',dt.datetime.combine(first,dt.time(8),accounting.TZ).isoformat()))
        db.execute('INSERT INTO meta VALUES (?,?)',('sample',json.dumps({'at':now.isoformat(),'epoch':'synthetic-demo','counters':{}})))
        for offset in range(35):
            day=first+dt.timedelta(days=offset)
            for n,c in enumerate(cats):
                up=(offset+3)*(n+1)*17123
                down=(offset%7+2)*(7-n)*982345
                db.execute('INSERT INTO daily VALUES (?,?,?,?)',(day.isoformat(),c['id'],up,down))
        db.commit()
    finally:db.close()
    index=exporter.export(output/'synthetic.sqlite3',cfg,output/'web/data',now)
    index['demo']=True
    exporter.atomic_json(output/'web/data/index.json',index)
    db=domain_list.connect(output/'synthetic-domains.sqlite3')
    try:
        for key,value in {'recording_started_at':now.isoformat(),'first_record_at':dt.datetime.combine(first,dt.time(8),accounting.TZ).isoformat(),'last_collected_at':now.isoformat(),'caught_up':True,'max_domains_per_day':1000}.items():
            domain_list.put(db,key,value)
        for offset in range(35):
            day=first+dt.timedelta(days=offset)
            for n in range(25):
                host=('a-very-long-synthetic-destination-hostname.' if n==0 else 'service-'+str(n)+'.')+'example.com'
                stamp=dt.datetime.combine(day,dt.time(16,n),accounting.TZ).isoformat()
                db.execute('INSERT INTO domains VALUES (?,?,?,?)',(day.isoformat(),host,offset+n+1,stamp))
        db.commit()
    finally:db.close()
    domain_list.export(output/'synthetic-domains.sqlite3',output/'web/data')
    return output/'web'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--serve',action='store_true')
    p.add_argument('--port',type=int,default=8765)
    args=p.parse_args()
    web=build(args.output)
    print('Synthetic demo generated. All displayed numbers are invented.')
    if args.serve:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(SimpleHTTPRequestHandler,directory=str(web)))
        print('Open http://127.0.0.1:'+str(server.server_address[1])+' (localhost-only synthetic demo).',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()

if __name__=='__main__':main()
