from contextlib import closing
import datetime as dt
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from v2ray_traffic_dashboard import domain_list as d

NOW=dt.datetime(2026,1,2,10,tzinfo=d.TZ)
def line(host='one.example.com',time='2026/01/02 01:00:00',route='usage-other'):
    return f'{time} 192.0.2.10:12345 accepted tcp:{host}:443 [{route}]\n'

class DomainTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.log=self.root/'access.log';self.db=self.root/'domains.sqlite3'
        self.log.write_text('')
    def collect(self,**kw):return d.collect(self.db,self.log,now=NOW,**kw)
    def rows(self):
        with closing(sqlite3.connect(self.db)) as db:return db.execute('SELECT day,domain,connections,last_seen FROM domains ORDER BY domain').fetchall()
    def test_parser_timezone_and_routes(self):
        result=d.parse(line('ONE.Example.com.',time='2026/01/01 17:30:00',route='loop -> usage-other').strip())
        self.assertEqual(result,('2026-01-02','one.example.com','2026-01-02T01:30:00+08:00'))
        self.assertIsNone(d.parse(line(route='usage-other -> direct').strip()))
        self.assertIsNone(d.parse(line(route='direct').strip()))
    def test_reject_ip_and_unsafe_names(self):
        for host in ['192.0.2.1','[2001:db8::1]','evil@one.example.com','<script>.example.com','one..example.com','a'*64+'.example.com']:
            self.assertIsNone(d.parse(line(host).strip()))
    def test_incremental_idempotence(self):
        self.log.write_text(line());self.collect();self.collect()
        with self.log.open('a') as f:f.write(line('two.example.com')+line())
        self.collect();self.assertEqual([r[2] for r in self.rows()],[2,1])
    def test_incomplete_record(self):
        self.log.write_text(line().rstrip('\n'));self.collect();self.assertEqual(self.rows(),[])
        with self.log.open('a') as f:f.write('\n')
        self.collect();self.collect();self.assertEqual(self.rows()[0][2],1)
    def test_budget_does_not_drop_split_record(self):
        self.log.write_text(line()*40)
        for _ in range(8):self.collect(max_bytes=1024)
        self.assertEqual(self.rows()[0][2],40)
    def test_copytruncate_recovers_compressed_tail(self):
        self.log.write_text(line()*60);self.collect()
        old=self.log.read_bytes()+line('tail.example.com').encode()
        with gzip.open(str(self.log)+'.1.gz','wb') as f:f.write(old)
        self.log.write_text(line('new.example.com'));self.collect();self.collect()
        self.assertEqual([(r[1],r[2]) for r in self.rows()],[('new.example.com',1),('one.example.com',60),('tail.example.com',1)])
    def test_rename_rotation(self):
        self.log.write_text(line());self.collect()
        with self.log.open('a') as f:f.write(line('tail.example.com'))
        self.log.rename(str(self.log)+'.1');self.log.write_text(line('new.example.com'))
        self.collect();self.assertEqual(len(self.rows()),3)
    def test_missing_archive_reports_gap(self):
        self.log.write_text(line());self.collect();self.log.write_text(line('new.example.com'));self.collect()
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute("SELECT count FROM issues WHERE kind='rotation_gap'").fetchone()[0],1)
    def test_limits_and_retention(self):
        self.log.write_text(line('old.example.com',time='2025/12/01 12:00:00')+line()+line('two.example.com')+line())
        self.collect(max_domains=1,retention_days=2)
        self.assertEqual([(r[1],r[2]) for r in self.rows()],[('one.example.com',2)])
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute("SELECT count FROM issues WHERE kind='domain_limit'").fetchone()[0],1)
    def test_export_privacy_and_daily_monthly(self):
        self.log.write_text(line()+line()+line('two.example.com',time='2026/01/01 01:00:00'));self.collect()
        output=self.root/'public';index=d.export(self.db,output,row_limit=1)
        data=json.loads((output/'domains-2026-01.json').read_text())
        self.assertEqual(data['monthly']['total_connections'],3)
        self.assertTrue(data['monthly']['truncated'])
        self.assertEqual(data['days']['2026-01-02']['domains'][0]['connections'],2)
        self.assertNotIn('192.0.2.10',str(data)+str(index));self.assertNotIn('cursor',str(index));self.assertNotIn(str(self.log),str(index))
    def test_changed_settings_roll_back(self):
        self.log.write_text(line());self.collect()
        with self.assertRaises(ValueError):self.collect(tag='different')
        self.assertEqual(self.rows()[0][2],1)
    def test_oversized_record_cannot_stall(self):
        self.log.write_text('x'*17000+'\n'+line())
        for _ in range(24):self.collect(max_bytes=1024)
        self.assertEqual(self.rows()[0][2],1)
    def test_empty_log_rotation_does_not_import_archives(self):
        self.collect();Path(str(self.log)+'.1').write_text(line('old.example.com'))
        self.log.unlink();self.log.write_text(line());self.collect()
        self.assertEqual([r[1] for r in self.rows()],['one.example.com'])
