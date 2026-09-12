"""Local recovery tests. Each case uses a disposable database, never project data."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import manage

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workspace-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        for name,value in [('DATA', self.path),('DB', self.path/'workspace.db'),('SETUP_KEY', self.path/'setup.key')]:
            item = patch.object(server, name, value)
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with server.db() as connection:
            server.provision(connection, {'first_name':'Recovery Test','employee_id':'OWNER','email':'owner@example.test','role':'admin'}, 'Original test password 782!', False)
            connection.execute("INSERT INTO sessions VALUES('test-token',1,'test-csrf',9999999999)")
    def test_r01_password_updated_sessions_revoked_and_audited(self):
        self.assertTrue(manage.reset_password('OWNER', 'New recovery test password 729!'))
        with server.db() as connection:
            user=connection.execute('SELECT * FROM users WHERE id=1').fetchone()
            self.assertTrue(server.passok('New recovery test password 729!',user['password_hash']))
            self.assertFalse(server.passok('Original test password 782!',user['password_hash']))
            self.assertEqual(user['role'],'admin')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT action FROM audit').fetchone()[0],'Local account recovery')
    def test_r02_short_password_rejected_without_change(self):
        with self.assertRaises(server.HTTPException):manage.reset_password('OWNER','short')
        with server.db() as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],1)
    def test_r03_unknown_account_is_not_created(self):
        self.assertFalse(manage.reset_password('unknown', 'New recovery test password 729!'))
        with server.db() as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
    def test_r04_email_lookup_and_disabled_account_stays_disabled(self):
        with server.db() as connection:connection.execute('UPDATE users SET is_active=0 WHERE id=1')
        self.assertTrue(manage.reset_password('OWNER@EXAMPLE.TEST','New recovery test password 729!'))
        with server.db() as connection:self.assertEqual(connection.execute('SELECT is_active FROM users WHERE id=1').fetchone()[0],0)
    def test_r05_no_database_requires_initial_setup(self):
        with patch.object(server,'DB',self.path/'missing.db'):
            with self.assertRaises(FileNotFoundError):manage.reset_password('OWNER','New recovery test password 729!')
        self.assertFalse((self.path/'missing.db').exists())

if __name__ == '__main__':unittest.main()
