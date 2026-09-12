"""Deterministic service tests for midnight boundaries using an isolated database.
These tests freeze the server clock only inside the test process. The shipped
server has no time spoofing route or environment variable.
"""
from datetime import datetime,date,timedelta
from contextlib import closing
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from fastapi import HTTPException

class OvernightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='amex-night-tests-')
        cls.data=Path(cls.tmp.name)
        cls.data_patch=patch.object(server,'DATA',cls.data);cls.data_patch.start()
        cls.db_patch=patch.object(server,'DB',cls.data/'portal.db');cls.db_patch.start()
        cls.key_patch=patch.object(server,'SETUP_KEY',cls.data/'setup.key');cls.key_patch.start()
        with patch.object(server,'now',return_value=cls.at('2026-09-10T19:00:00')):server.init_db()
        with server.db() as c:
            for ident in (1,2):
                server.provision(c,{'employee_id':f'NIGHT{ident}','first_name':'Test','email':f'night{ident}@example.test'},'Night tests only 823!',False)
        with closing(sqlite3.connect(server.DB)) as source,closing(sqlite3.connect(cls.data/'base.db')) as target:source.backup(target)
    @classmethod
    def tearDownClass(cls):
        cls.key_patch.stop();cls.db_patch.stop();cls.data_patch.stop();cls.tmp.cleanup()
    @staticmethod
    def at(value):return datetime.fromisoformat(value).replace(tzinfo=server.IST)
    def setUp(self):
        with closing(sqlite3.connect(self.data/'base.db')) as source,closing(sqlite3.connect(server.DB)) as target:source.backup(target)
    def action(self,t,action,uid=2):
        with patch.object(server,'now',return_value=self.at(t)):return server.attendance_action(uid,action)
    def status(self,t,uid=2):
        with patch.object(server,'now',return_value=self.at(t)):return server.attendance_status(uid)
    def test_n01_midnight_preserves_open_record(self):
        first=self.action('2026-09-10T20:30:00','check-in')
        midnight=self.status('2026-09-11T00:01:00')
        self.assertEqual(midnight['today']['id'],first['today']['id'])
        self.assertEqual(midnight['shift_date'],'2026-09-10')
        self.assertEqual(midnight['state'],'checked_in')
        self.assertEqual(midnight['today']['worked_seconds'],12660)
    def test_n02_next_morning_check_out_same_id_and_nine_hours(self):
        first=self.action('2026-09-10T20:30:00','check-in')
        last=self.action('2026-09-11T04:30:00','check-out')
        self.assertEqual(first['today']['id'],last['today']['id'])
        self.assertEqual(last['shift_date'],'2026-09-10')
        self.assertEqual(last['today']['worked_seconds'],28800)
        self.assertEqual(last['today']['late_seconds'],0)
    def test_n03_overtime_checkout_still_closes_previous_night(self):
        self.action('2026-09-10T20:30:00','check-in')
        last=self.action('2026-09-11T06:30:00','check-out')
        self.assertEqual(last['date'],'2026-09-10')
        with patch.object(server,'now',return_value=self.at('2026-09-11T04:00:00')):
            history=server.attendance_data(2,end=date(2026,9,10))['history']
        self.assertEqual(history[0]['worked_seconds'],36000)
        self.assertEqual(history[0]['overtime_seconds'],7200)
    def test_n04_post_midnight_late_check_in_uses_previous_date(self):
        first=self.action('2026-09-11T00:30:00','check-in')
        self.assertEqual(first['shift_date'],'2026-09-10')
        self.assertEqual(first['today']['late_seconds'],14400)
        last=self.action('2026-09-11T04:30:00','check-out')
        self.assertEqual(last['today']['worked_seconds'],14400)
    def test_n05_new_night_allows_new_record(self):
        self.action('2026-09-10T20:30:00','check-in');self.action('2026-09-11T04:30:00','check-out')
        next_night=self.action('2026-09-11T20:30:00','check-in')
        self.assertEqual(next_night['shift_date'],'2026-09-11')
        with server.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM attendance WHERE user_id=2').fetchone()[0],2)
    def test_n06_early_check_in_has_no_late_penalty(self):
        first=self.action('2026-09-10T20:15:00','check-in')
        self.assertEqual(first['today']['late_seconds'],0)
        self.assertEqual(first['shift_date'],'2026-09-10')
    def test_n07_exact_end_time_is_previous_night(self):
        shift=server.shift_for(2)
        self.assertEqual(server.shift_date(self.at('2026-09-11T04:30:00'),shift),date(2026,9,10))
        self.assertEqual(server.shift_date(self.at('2026-09-11T04:31:00'),shift),date(2026,9,11))
    def test_n08_month_and_year_rollover(self):
        self.action('2026-12-31T20:30:00','check-in')
        last=self.action('2027-01-01T04:30:00','check-out')
        self.assertEqual(last['today']['date'],'2026-12-31')
        self.assertEqual(last['today']['worked_seconds'],28800)
    def test_n09_history_uses_saved_duration_after_schedule_edit(self):
        self.action('2026-09-10T20:30:00','check-in');self.action('2026-09-11T05:00:00','check-out')
        with server.db() as c:c.execute("UPDATE shift_settings SET start_time='23:00',end_time='06:00' WHERE user_id=2")
        with patch.object(server,'now',return_value=self.at('2026-09-11T12:00:00')):metrics=server.attendance_data(2,end=date(2026,9,10))
        self.assertEqual(metrics['history'][0]['overtime_seconds'],1800)
        self.assertEqual(metrics['history'][0]['shift_start'],'2026-09-10T20:30:00+05:30')
    def test_n10_late_snapshot_and_corrected_next_morning(self):
        with patch.object(server,'now',return_value=self.at('2026-09-11T12:00:00')):
            day,tin,tout,start,end=server.correction_times({'date':'2026-09-10','clock_in':'20:45','clock_out':'05:45'},2)
        self.assertEqual(tout.date(),date(2026,9,11))
        self.assertEqual((tout-tin).total_seconds(),32400)
        self.assertEqual((tin-start).total_seconds(),900)
    def test_n11_completed_shift_cannot_be_started_twice_before_dawn(self):
        self.action('2026-09-10T20:30:00','check-in');self.action('2026-09-11T04:00:00','check-out')
        with self.assertRaises(HTTPException) as caught:self.action('2026-09-11T04:01:00','check-in')
        self.assertEqual(caught.exception.status_code,409)
    def test_n12_no_open_shift_rejects_check_out(self):
        with self.assertRaises(HTTPException) as caught:self.action('2026-09-10T20:30:00','check-out')
        self.assertEqual(caught.exception.status_code,409)

if __name__=='__main__':unittest.main()
