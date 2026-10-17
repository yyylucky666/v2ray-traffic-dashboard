import datetime as dt
import importlib.util
from pathlib import Path
import sqlite3
import json
import tempfile
import unittest

from v2ray_traffic_dashboard import accounting as traffic


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = traffic.connect_db(Path(self.tmp.name) / 'test.sqlite3')
        self.t = dt.datetime(2026, 10, 12, 12, 0, tzinfo=traffic.TZ)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def sample(self, minutes, up, down, epoch='one'):
        traffic.record_sample(self.db, self.t + dt.timedelta(minutes=minutes), epoch,
                              {'openai': {'uplink': up, 'downlink': down}})

    def totals(self):
        return self.db.execute('SELECT COALESCE(SUM(uplink),0),COALESCE(SUM(downlink),0) FROM daily').fetchone()

    def test_existing_traffic_is_not_charged_retroactively(self):
        self.sample(0, 900000000000, 800000000000)
        self.assertEqual(self.totals(), (0, 0))
        self.sample(2, 900000000123, 800000000456)
        self.assertEqual(self.totals(), (123, 456))

    def test_repeated_counters_do_not_duplicate_bytes(self):
        self.sample(0, 10, 20)
        self.sample(2, 110, 220)
        self.sample(4, 110, 220)
        self.assertEqual(self.totals(), (100, 200))

    def test_process_restart_counts_new_bytes_without_negative_delta(self):
        self.sample(0, 1000, 2000)
        self.sample(2, 1100, 2200)
        self.sample(4, 30, 50, epoch='two')
        self.assertEqual(self.totals(), (130, 250))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM events WHERE kind='counter_reset'").fetchone()[0], 1)

    def test_one_direction_reset_preserves_other_direction(self):
        self.sample(0, 1000, 2000)
        self.sample(2, 20, 2100)
        self.assertEqual(self.totals(), (20, 100))

    def test_clock_reversal_does_not_commit_state(self):
        self.sample(0, 100, 200)
        with self.assertRaises(ValueError):
            self.sample(-1, 150, 300)
        self.sample(2, 200, 400)
        self.assertEqual(self.totals(), (100, 200))

    def test_midnight_uses_beijing_sampling_day(self):
        self.t = dt.datetime(2026, 10, 12, 23, 59, tzinfo=traffic.TZ)
        self.sample(0, 10, 20)
        self.sample(2, 110, 220)
        self.assertEqual(self.db.execute('SELECT day FROM daily').fetchone()[0], '2026-10-13')

    def test_gap_is_recorded_but_cumulative_bytes_retained(self):
        self.sample(0, 10, 20)
        self.sample(20, 110, 220)
        self.assertEqual(self.totals(), (100, 200))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM events WHERE kind='sampling_gap'").fetchone()[0], 1)

    def test_missing_counter_fails_loud(self):
        with self.assertRaises(ValueError):
            traffic.parse_counters({'stat': []}, [{'id': 'openai', 'tag': 'usage-openai'}])

    def test_omitted_zero_value_is_valid(self):
        data = {'stat': [{'name': 'outbound>>>usage-openai>>>traffic>>>uplink'},
                         {'name': 'outbound>>>usage-openai>>>traffic>>>downlink', 'value': '42'}]}
        self.assertEqual(traffic.parse_counters(data, [{'id': 'openai', 'tag': 'usage-openai'}]),
                         {'openai': {'uplink': 0, 'downlink': 42}})


    def test_hourly_and_daily_share_exact_deltas(self):
        self.sample(0,100,200)
        self.sample(2,140,260)
        self.sample(62,240,460)
        self.assertEqual(self.db.execute('SELECT SUM(uplink),SUM(downlink) FROM hourly').fetchone(),self.totals())
        self.assertEqual(self.db.execute('SELECT hour,uplink,downlink FROM hourly ORDER BY hour').fetchall(),[
            ('2026-10-12T12:00:00+08:00',40,60),('2026-10-12T13:00:00+08:00',100,200)])
        self.assertEqual(self.db.execute("SELECT value FROM meta WHERE key='hourly_started_at'").fetchone()[0],self.t.isoformat())

    def test_hour_boundary_uses_sampling_end_and_beijing_timezone(self):
        self.t=dt.datetime(2026,10,12,4,59,tzinfo=dt.timezone.utc)
        self.sample(0,10,20);self.sample(2,110,220)
        self.assertEqual(self.db.execute('SELECT hour FROM hourly').fetchone()[0],'2026-10-12T13:00:00+08:00')
        self.assertEqual(self.totals(),(100,200))

    def test_upgrade_does_not_redistribute_historic_daily_totals(self):
        self.sample(0,10,20)
        self.db.execute('DROP TABLE hourly')
        self.db.execute("DELETE FROM meta WHERE key='hourly_started_at'")
        self.db.execute("INSERT INTO daily VALUES ('2026-10-12','openai',5000,9000)")
        self.db.commit();self.db.close()
        self.db=traffic.connect_db(Path(self.tmp.name)/'test.sqlite3')
        self.sample(2,110,220)
        self.assertEqual(self.totals(),(5100,9200))
        self.assertEqual(self.db.execute('SELECT SUM(uplink),SUM(downlink) FROM hourly').fetchone(),(100,200))

    def test_hourly_write_failure_rolls_back_daily_and_cursor(self):
        self.sample(0,10,20)
        self.db.execute("CREATE TRIGGER fail_hourly BEFORE INSERT ON hourly BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.sample(2,110,220)
        self.assertEqual(self.totals(),(0,0))
        self.assertEqual(json.loads(self.db.execute("SELECT value FROM meta WHERE key='sample'").fetchone()[0])['at'],self.t.isoformat())
        self.db.execute('DROP TRIGGER fail_hourly');self.sample(4,210,420)
        self.assertEqual(self.totals(),(200,400))

    def test_hourly_reset_and_retention(self):
        self.sample(0,100,200);self.sample(2,120,240);self.sample(4,10,250)
        self.assertEqual(self.db.execute('SELECT SUM(uplink),SUM(downlink) FROM hourly').fetchone(),(30,50))
        traffic.record_sample(self.db,self.t+dt.timedelta(days=3),'two',{'openai':{'uplink':5,'downlink':6}},retention_days=2)
        self.assertEqual(self.db.execute('SELECT hour FROM hourly').fetchall(),[('2026-10-15T12:00:00+08:00',)])


if __name__ == '__main__':
    unittest.main()
