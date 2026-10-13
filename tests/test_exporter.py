import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from v2ray_traffic_dashboard import exporter


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.db=self.root/'stats.db';db=sqlite3.connect(self.db)
        db.executescript('CREATE TABLE meta(key TEXT,value TEXT);CREATE TABLE daily(day TEXT,category TEXT,uplink INT,downlink INT);CREATE TABLE events(at TEXT,kind TEXT,detail TEXT);')
        db.executemany('INSERT INTO meta VALUES (?,?)',[('started_at','2026-09-30T23:00:00+08:00'),('sample',json.dumps({'at':'2026-10-13T10:00:00+08:00','private_sentinel':'must-not-export'}))])
        db.executemany('INSERT INTO daily VALUES (?,?,?,?)',[('2026-09-30','openai',10,20),('2026-10-01','openai',30,40),('2026-10-13','openai',50,60),('2026-10-13','google',70,80)])
        db.execute('INSERT INTO events VALUES (?,?,?)',('2026-10-13T09:00:00+08:00','counter_reset','hidden-client-identifier'));db.commit();db.close()
        self.categories=self.root/'categories.json';self.categories.write_text(json.dumps({'categories':[{'id':'openai','label':'OpenAI','tag':'secret-tag','domains':['private-domain']},{'id':'google','label':'Google','tag':'other'}]}))
        self.out=self.root/'data';self.now=dt.datetime(2026,10,13,10,tzinfo=exporter.TZ)

    def tearDown(self): self.tmp.cleanup()

    def test_month_and_day_totals_and_quality(self):
        index=exporter.export(self.db,self.categories,self.out,self.now)
        self.assertEqual(index['month_totals']['2026-10'],{'upload':150,'download':180})
        data=json.loads((self.out/'2026-10.json').read_text());self.assertEqual(data['days']['2026-10-13']['google'],{'upload':70,'download':80})
        self.assertEqual(data['quality']['2026-10-13'],{'counter_reset':1})

    def test_read_only_database_and_no_sensitive_fields(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        exporter.export(self.db,self.categories,self.out,self.now)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        all_json=''.join(p.read_text() for p in self.out.glob('*.json'))
        for private in ['must-not-export','hidden-client-identifier','secret-tag','private-domain']: self.assertNotIn(private,all_json)

    def test_empty_current_month_exists_and_stale_files_removed(self):
        self.out.mkdir();(self.out/'2020-01.json').write_text('{}')
        exporter.export(self.db,self.categories,self.out,self.now.replace(month=11))
        self.assertEqual(json.loads((self.out/'2026-11.json').read_text())['days'],{})
        self.assertFalse((self.out/'2020-01.json').exists())


if __name__=='__main__': unittest.main()
