"""Run only on an isolated Linux CI runner with nginx/htpasswd preinstalled."""
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
from v2ray_traffic_dashboard.cli import main as cli

def run(*args,**kw):return subprocess.run(list(args),check=True,**kw)


def main():
    if sys.platform!='linux' or os.geteuid()!=0:
        raise RuntimeError('Isolated Linux root runner required')
    paths=[Path('/opt/v2ray-traffic-dashboard'),Path('/etc/v2ray-traffic-dashboard'),Path('/var/www/v2ray-traffic-dashboard')]
    if any(p.exists() for p in paths):raise RuntimeError('Refusing a runner with an existing installation')
    run(sys.executable,str(ROOT/'scripts/install.py'),'--apply')
    with tempfile.TemporaryDirectory() as temp:
        demo=Path(temp)/'demo';run(sys.executable,str(ROOT/'scripts/demo.py'),'--output',str(demo))
        cfg=json.loads(Path('/etc/v2ray-traffic-dashboard/config.json').read_text())
        state=Path(cfg['state_dir']);shutil.copyfile(demo/'synthetic.sqlite3',state/'traffic.sqlite3')
        password=secrets.token_urlsafe(24)
        run('htpasswd','-Bci','/etc/v2ray-traffic-dashboard/htpasswd','fixture',input=password+'\n',text=True,capture_output=True)
        auth=Path('/etc/v2ray-traffic-dashboard/htpasswd');auth.chmod(0o640);os.chown(auth,0,Path('/etc/v2ray-traffic-dashboard').stat().st_gid)
        sys.argv=['v2ray-traffic-dashboard','export'];assert cli()==0
        # Units are only the dashboard's own units; no V2Ray service exists on this runner.
        try:
            run('/usr/sbin/nginx','-e','/var/log/v2ray-traffic-dashboard/error.log','-t','-c','/etc/v2ray-traffic-dashboard/nginx.conf')
            run('systemctl','enable','--now','v2ray-traffic-dashboard-web.service')
            run('systemctl','is-active','--quiet','v2ray-traffic-dashboard-web.service')
        except Exception:
            subprocess.run(['systemctl','status','v2ray-traffic-dashboard-web.service','--no-pager'])
            subprocess.run(['journalctl','-u','v2ray-traffic-dashboard-web.service','-n','30','--no-pager'])
            log=Path('/var/log/v2ray-traffic-dashboard/error.log')
            if log.exists():print(log.read_text(),flush=True)
            raise
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def status(path,credential=None):
            headers={}
            if credential:headers['Authorization']='Basic '+base64.b64encode(('fixture:'+credential).encode()).decode()
            try:
                with opener.open(urllib.request.Request('http://127.0.0.1:8080'+path,headers=headers),timeout=5) as response:
                    return response.status,response.read(),response.headers
            except urllib.error.HTTPError as e:return e.code,e.read(),e.headers
        try:
            for resource in ('/','/app.js','/data/index.json'):
                assert status(resource)[0]==401
                code,body,headers=status(resource,password);assert code==200
                assert headers['X-Content-Type-Options']=='nosniff'
            assert status('/','wrong-password')[0]==401
            index=json.loads(status('/data/index.json',password)[1]);assert len(index['categories'])==6
            run('logrotate','-d','/etc/logrotate.d/v2ray-traffic-dashboard',capture_output=True)
            saved=(state/'traffic.sqlite3').read_bytes()
        finally:
            run('systemctl','disable','--now','v2ray-traffic-dashboard-web.service')
        run(sys.executable,str(ROOT/'scripts/uninstall.py'),'--apply')
        assert (state/'traffic.sqlite3').read_bytes()==saved
        assert not any(p.exists() for p in paths)
    print('Linux install, own web service, auth401/200, CLI export, logrotate and uninstall with retained database passed.')

if __name__=='__main__':main()
