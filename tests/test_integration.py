import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from v2ray_traffic_dashboard import accounting,config
from v2ray_traffic_dashboard.classification import candidate

ROOT=Path(__file__).resolve().parent.parent


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.cfg=config.load(ROOT/'examples/config.json')
        self.original={'inbounds':[{'tag':'proxy','listen':'127.0.0.1','port':12345,'protocol':'socks','settings':{'auth':'noauth'}}],
            'outbounds':[{'tag':'direct','protocol':'freedom','settings':{'domainStrategy':'UseIPv4'}},{'tag':'deny','protocol':'blackhole'}],
            'routing':{'domainStrategy':'IPIfNonMatch','rules':[{'type':'field','ip':['geoip:private'],'outboundTag':'deny'},
                {'type':'field','protocol':['bittorrent'],'outboundTag':'deny'}]},'dns':{'servers':['localhost']}}

    def tearDown(self):self.tmp.cleanup()

    def test_candidate_preserves_original_rules_dns_and_proxy_inbounds(self):
        before=copy.deepcopy(self.original);result=candidate(self.original,self.cfg)
        self.assertEqual(before,self.original)
        n=len(self.cfg['categories'])+1
        self.assertEqual(result['routing']['rules'][n:],self.original['routing']['rules'])
        self.assertEqual(result['dns'],self.original['dns'])
        self.assertEqual(result['inbounds'][:-1],self.original['inbounds'])
        self.assertEqual(result['inbounds'][-1]['listen'],'127.0.0.1')
        self.assertEqual(result['outbounds'][0]['protocol'],'loopback')
        self.assertEqual(result['outbounds'][2]['settings'],{'domainStrategy':'UseIPv4'})
        self.assertTrue(result['policy']['system']['statsOutboundDownlink'])

    def test_duplicate_integration_and_balancers_fail(self):
        with self.assertRaises(ValueError):candidate(candidate(self.original,self.cfg),self.cfg)
        self.original['routing']['balancers']=[{'tag':'pool'}]
        with self.assertRaises(ValueError):candidate(self.original,self.cfg)

    def test_public_api_and_invalid_categories_rejected(self):
        for edit in (lambda d:d.update(stats_server='203.0.113.1:10085'),
                     lambda d:d['categories'][1].update(id=d['categories'][0]['id']),
                     lambda d:d['categories'][0].update(domains=[])):
            data=copy.deepcopy(self.cfg);edit(data);p=self.path/'bad.json';p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):config.load(p)

    def test_existing_api_requires_matching_loopback_and_route(self):
        self.original['api']={'tag':'api','services':['StatsService']}
        self.original['inbounds'].append({'tag':'api-in','listen':'0.0.0.0','port':10085,'protocol':'dokodemo-door'})
        with self.assertRaises(ValueError):candidate(self.original,self.cfg)
        self.original['inbounds'][-1]['listen']='127.0.0.1'
        self.original['routing']['rules'].insert(0,{'type':'field','inboundTag':['api-in'],'outboundTag':'api'})
        result=candidate(self.original,self.cfg)
        self.assertEqual(result['inbounds'],self.original['inbounds'])

    def test_collector_reads_cumulative_api_without_reset(self):
        cats=self.cfg['categories'];payload={'stat':[{'name':'outbound>>>'+c['tag']+'>>>traffic>>>'+direction,'value':'100'}
            for c in cats for direction in ('uplink','downlink')]}
        with mock.patch.object(accounting,'process_epoch',return_value='process-one'),mock.patch.object(accounting.subprocess,'run') as run:
            run.return_value=subprocess.CompletedProcess([],0,json.dumps(payload),'')
            accounting.collect(self.path,'127.0.0.1:10085','/usr/local/bin/v2ray','v2ray.service',cats)
            self.assertEqual(run.call_args.args[0],['/usr/local/bin/v2ray','api','stats','-s','127.0.0.1:10085','-json'])
        db=accounting.connect_db(self.path/'traffic.sqlite3')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM daily').fetchone()[0],0);db.close()

    def test_prepare_cli_exclusive_output_and_private_permissions(self):
        original=self.path/'original.json';original.write_text(json.dumps(self.original));out=self.path/'candidate.json'
        cmd=[sys.executable,str(ROOT/'bin/v2ray-traffic-dashboard'),'--config',str(ROOT/'examples/config.json'),
             'prepare-config','--input',str(original),'--output',str(out)]
        self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,0)
        self.assertEqual(out.stat().st_mode&0o777,0o600)
        first=out.read_bytes();self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
        self.assertEqual(out.read_bytes(),first)

    def test_install_uninstall_sandbox_preserves_proxy_and_database(self):
        dest=self.path/'stage';dest.mkdir()
        proxy=dest/'etc/v2ray/config.json';proxy.parent.mkdir(parents=True);proxy.write_text('sentinel-proxy')
        state=dest/'var/lib/v2ray-traffic-dashboard';state.mkdir(parents=True)
        database=state/'traffic.sqlite3';database.write_bytes(b'sentinel-database')
        cmd=[sys.executable,str(ROOT/'scripts/install.py'),'--destdir',str(dest),'--web-group','nogroup']
        first=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(first.returncode,0,first.stderr)
        unit=(dest/'etc/systemd/system/v2ray-traffic-dashboard.service').read_text()
        self.assertIn('ProtectSystem=strict',unit)
        nginx=(dest/'etc/v2ray-traffic-dashboard/nginx.conf').read_text()
        self.assertIn('user nobody nogroup;',nginx)
        self.assertIn('listen 127.0.0.1:8080',nginx);self.assertIn('auth_basic_user_file',nginx)
        self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
        uninstall=subprocess.run([sys.executable,str(ROOT/'scripts/uninstall.py'),'--destdir',str(dest)],capture_output=True,text=True)
        self.assertEqual(uninstall.returncode,0,uninstall.stderr)
        self.assertEqual(proxy.read_text(),'sentinel-proxy');self.assertEqual(database.read_bytes(),b'sentinel-database')
        self.assertFalse((dest/'opt/v2ray-traffic-dashboard').exists())

    def test_install_symlink_escape_and_path_overlap_fail_before_mutation(self):
        dest=self.path/'escape';dest.mkdir();(dest/'opt').symlink_to(self.path/'outside')
        result=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--destdir',str(dest)],capture_output=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.path/'outside').exists())
        dest2=self.path/'overlap'
        result=subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--destdir',str(dest2),'--prefix','/var/www/v2ray-traffic-dashboard'],capture_output=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse(dest2.exists())

    def test_retention_exact_days(self):
        db=accounting.connect_db(self.path/'retention.sqlite3');now=dt.datetime(2026,1,2,tzinfo=accounting.TZ)
        db.execute('INSERT INTO daily VALUES (?,?,?,?)',('2026-01-01','openai',1,2));db.commit()
        accounting.record_sample(db,now,'one',{'openai':{'uplink':1,'downlink':2}},retention_days=1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM daily').fetchone()[0],0);db.close()

    def test_demo_uses_synthetic_data_and_refuses_existing_directory(self):
        spec=importlib.util.spec_from_file_location('demo',ROOT/'scripts/demo.py');demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
        output=self.path/'demo';now=dt.datetime(2026,2,1,12,tzinfo=accounting.TZ)
        web=demo.build(output,now);index=json.loads((web/'data/index.json').read_text())
        self.assertTrue(index['demo']);self.assertEqual(index['months'],['2026-02','2026-01','2025-12'])
        with self.assertRaises(ValueError):demo.build(output,now)

if __name__=='__main__':unittest.main()
