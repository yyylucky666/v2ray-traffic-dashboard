#!/usr/bin/env python3
"""Install only dashboard-owned files. No package manager or proxy mutation."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent.parent
NAME = 'v2ray-traffic-dashboard'


def safe_path(value):
    if not re.fullmatch(r'/[A-Za-z0-9/_.-]+', value) or '..' in Path(value).parts or value == '/':
        raise ValueError('Use a simple absolute path, without spaces or parent traversal')
    return value


def build(args):
    for key in ('prefix', 'state_dir', 'web_dir', 'config_dir', 'unit_dir', 'log_dir', 'nginx_binary'):
        safe_path(getattr(args, key))
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', args.web_user):
        raise ValueError('Invalid web user')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Loopback web port must be 1024..65535')
    paths=[Path(getattr(args,k)) for k in ('prefix','state_dir','web_dir','config_dir','log_dir')]
    if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(paths) for b in paths[i+1:]):
        raise ValueError('Application, state, web, config and log paths must not overlap')
    if not (args.destdir or args.apply):
        print('Preview only. Pass --destdir DIR for a sandbox install, or --apply to install on Linux.')
        print(json.dumps({k:getattr(args,k) for k in ('prefix','state_dir','web_dir','config_dir','unit_dir')},indent=2))
        return
    if args.destdir and args.enable:
        raise ValueError('--enable cannot be used with --destdir')
    gid = os.getgid()
    uid = os.getuid()
    if not args.destdir:
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise ValueError('--apply requires root on Linux')
        import pwd
        account = pwd.getpwnam(args.web_user)
        gid,uid = account.pw_gid,account.pw_uid
    dest = Path(args.destdir).resolve() if args.destdir else Path('/')
    def target(path):
        p = dest / path.lstrip('/')
        if args.destdir and not p.resolve().is_relative_to(dest):
            raise ValueError('Destination escapes sandbox')
        if any(parent.is_symlink() for parent in [p] + list(p.parents)[:-1]):
            raise ValueError('Symlink install destinations are not supported')
        return p
    owned_dirs = [args.prefix,args.config_dir,args.web_dir,args.log_dir]
    # Refuse replacement of existing directories/configurations, even unrelated ones.
    for directory in owned_dirs:
        if target(directory).exists():
            raise ValueError('Destination already exists: ' + directory)
    service_path = args.unit_dir + '/' + NAME + '.service'
    timer_path = args.unit_dir + '/' + NAME + '.timer'
    web_service = args.unit_dir + '/' + NAME + '-web.service'
    if any(target(p).exists() for p in (service_path,timer_path,web_service)):
        raise ValueError('Dashboard unit already exists')
    rotation='/etc/logrotate.d/'+NAME
    if target(rotation).exists():
        raise ValueError('Existing logrotate configuration')
    if target(args.state_dir).is_symlink():
        raise ValueError('State directory may not be a symlink')
    target(args.state_dir)  # Validate parents before any filesystem changes.
    files=[]
    def write(path,content,mode=0o644):
        p=target(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);p.chmod(mode);files.append(path)
    for directory in owned_dirs:
        p=target(directory);p.mkdir(parents=True,exist_ok=False);p.chmod(0o750)
        if not args.destdir:os.chown(p,0,gid)
    state=target(args.state_dir)
    if not state.exists():
        state.mkdir(parents=True,mode=0o700)
    target(args.web_dir).chmod(0o2750)
    shutil.copytree(SOURCE/'src',target(args.prefix+'/src'),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    target(args.prefix+'/bin').mkdir()
    shutil.copy2(SOURCE/'bin'/NAME,target(args.prefix+'/bin/'+NAME));target(args.prefix+'/bin/'+NAME).chmod(0o755)
    for notice in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copy2(SOURCE/notice,target(args.prefix+'/'+notice))
    for name in ('client_body','proxy','fastcgi','uwsgi','scgi'):
        p=target(args.log_dir+'/tmp/'+name);p.mkdir(parents=True,exist_ok=True);p.chmod(0o750)
        if not args.destdir:os.chown(p,uid,gid)
    for source in (SOURCE/'web').iterdir():
        if source.is_file():
            p=target(args.web_dir+'/'+source.name);shutil.copyfile(source,p);p.chmod(0o640)
            if not args.destdir:os.chown(p,0,gid)
    data=target(args.web_dir+'/data');data.mkdir();data.chmod(0o2750)
    if not args.destdir:os.chown(data,0,gid)
    cfg=json.loads((SOURCE/'examples/config.json').read_text());cfg.update(state_dir=args.state_dir,web_dir=args.web_dir)
    write(args.config_dir+'/config.json',json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',0o600)
    command=args.prefix+'/bin/'+NAME+' --config '+args.config_dir+'/config.json'
    write(service_path,f'''[Unit]
Description=Collect V2Ray category traffic and export static snapshots
After=network-online.target {cfg['v2ray_service']}

[Service]
Type=oneshot
ExecStart={command} collect
Nice=19
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={args.state_dir} {args.web_dir}/data
''')
    write(timer_path,'''[Unit]
Description=Collect category traffic every two minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=2min
AccuracySec=5s

[Install]
WantedBy=timers.target
''')
    write(args.config_dir+'/nginx.conf',f'''user {args.web_user};
worker_processes 1;
pid /run/{NAME}-web.pid;
error_log {args.log_dir}/error.log warn;
events {{ worker_connections 64; }}
http {{
    types {{ text/html html; text/css css; application/javascript js; application/json json; image/svg+xml svg; }}
    default_type application/octet-stream;
    log_format dashboard '$remote_addr [$time_local] "$request_method $uri $server_protocol" $status $body_bytes_sent';
    access_log {args.log_dir}/access.log dashboard;
    server_tokens off;
    client_max_body_size 1k;
    client_body_timeout 10s;
    client_header_timeout 10s;
    keepalive_timeout 15s;
    send_timeout 15s;
    client_body_temp_path {args.log_dir}/tmp/client_body;
    proxy_temp_path {args.log_dir}/tmp/proxy;
    fastcgi_temp_path {args.log_dir}/tmp/fastcgi;
    uwsgi_temp_path {args.log_dir}/tmp/uwsgi;
    scgi_temp_path {args.log_dir}/tmp/scgi;
    limit_req_zone $binary_remote_addr zone=vtd:1m rate=5r/s;
    server {{
        listen 127.0.0.1:{args.port};
        server_name localhost;
        root {args.web_dir};
        auth_basic "Traffic dashboard";
        auth_basic_user_file {args.config_dir}/htpasswd;
        limit_req zone=vtd burst=16 nodelay;
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Referrer-Policy no-referrer always;
        add_header Cache-Control "private, no-cache" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'" always;
        location = / {{ try_files /index.html =404; }}
        location ~ ^/(index\\.html|app\\.js|style\\.css|favicon\\.svg)$ {{ try_files $uri =404; }}
        location ~ "^/data/(index|[0-9]{{4}}-[0-9]{{2}})\\.json$" {{ try_files $uri =404; }}
        location / {{ return 404; }}
    }}
}}
''',0o640)
    if not args.destdir:os.chown(target(args.config_dir+'/nginx.conf'),0,gid)
    write(web_service,f'''[Unit]
Description=Protected static V2Ray traffic dashboard
After=network-online.target

[Service]
Type=forking
PIDFile=/run/{NAME}-web.pid
ExecStartPre={args.nginx_binary} -e {args.log_dir}/error.log -t -c {args.config_dir}/nginx.conf
ExecStart={args.nginx_binary} -e {args.log_dir}/error.log -c {args.config_dir}/nginx.conf
ExecReload=/bin/kill -HUP $MAINPID
ExecStop=/bin/kill -QUIT $MAINPID
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
''')
    write(rotation,f'''{args.log_dir}/access.log {args.log_dir}/error.log {{
    daily
    maxsize 5M
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}}
''')
    manifest={'schema':1,'directories':owned_dirs,'files':files,'state_dir':args.state_dir}
    write(args.config_dir+'/managed.json',json.dumps(manifest,indent=2)+'\n',0o600)
    if not args.destdir:
        subprocess.run(['systemctl','daemon-reload'],check=True)
        if args.enable:
            subprocess.run([args.prefix+'/bin/'+NAME,'--config',args.config_dir+'/config.json','doctor'],check=True)
            subprocess.run(['systemctl','enable','--now',NAME+'.timer'],check=True)
    print('Dashboard files installed. V2Ray configuration and process were not modified.')
    print('Edit config.json, validate classification, create htpasswd and configure HTTPS before public access.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--destdir',help='Offline staging root; never runs systemctl')
    parser.add_argument('--enable',action='store_true',help='Preflight API then enable only the collector timer')
    for name,value in [('prefix','/opt/'+NAME),('state-dir','/var/lib/'+NAME),('web-dir','/var/www/'+NAME),
                       ('config-dir','/etc/'+NAME),('unit-dir','/etc/systemd/system'),('log-dir','/var/log/'+NAME),
                       ('nginx-binary','/usr/sbin/nginx'),('web-user','nobody')]:parser.add_argument('--'+name,default=value)
    parser.add_argument('--port',type=int,default=8080)
    args=parser.parse_args()
    try:build(args)
    except Exception as exc:parser.exit(1,'Installation failed: '+str(exc)+'\n')

if __name__=='__main__':main()
