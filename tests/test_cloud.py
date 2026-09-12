"""Deployment tests use temporary data and local HTTP only; no hosting is contacted."""
import contextlib, io, os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cloud_start, server
PASSWORD = 'Disposable cloud test password 752!'

class CloudSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cloud-settings-')
        self.addCleanup(self.temp.cleanup)
        self.env = {'RAILWAY_VOLUME_MOUNT_PATH': self.temp.name,
                    'RAILWAY_PUBLIC_DOMAIN':'portal.example.test', 'FORWARDED_ALLOW_IPS':'127.0.0.1'}
    def settings(self, **changes):
        with patch.dict(os.environ, dict(self.env, **changes), clear=True):
            return cloud_start.read_settings()
    def test_c01_valid_settings_and_secure_cookies(self):
        with patch.dict(os.environ, self.env, clear=True):
            s = cloud_start.read_settings()
            self.assertEqual(os.environ['PORTAL_SECURE_COOKIE'], '1')
            self.assertIn('healthcheck.railway.app', s.allowed_hosts)
            self.assertEqual(s.data_dir, Path(self.temp.name))
            self.assertEqual(s.port, 8080)
    def test_c02_missing_volume_rejected(self):
        with self.assertRaises(RuntimeError): self.settings(RAILWAY_VOLUME_MOUNT_PATH='')
    def test_c03_missing_mount_rejected(self):
        with self.assertRaises(RuntimeError): self.settings(RAILWAY_VOLUME_MOUNT_PATH=self.temp.name+'/missing')
    def test_c04_data_outside_volume_rejected(self):
        with self.assertRaises(RuntimeError): self.settings(PORTAL_DATA_DIR=str(Path(self.temp.name).parent/'unmounted'))
    def test_c05_bad_domains_rejected(self):
        for public, extra in [('', ''), ('', '*'), ('portal.example.test','*.example.test'), ('https://example.test','')]:
            with self.subTest(public=public,extra=extra), self.assertRaises(RuntimeError):
                self.settings(RAILWAY_PUBLIC_DOMAIN=public, PORTAL_ALLOWED_HOSTS=extra)
    def test_c06_bad_port_rejected(self):
        for port in ('0','65536','wrong'):
            with self.subTest(port=port), self.assertRaises(RuntimeError): self.settings(PORT=port)
    def test_c07_proxy_trust_must_be_explicit(self):
        with self.assertRaises(RuntimeError): self.settings(FORWARDED_ALLOW_IPS='')

class CloudBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cloud-bootstrap-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name,value in [('DATA',root),('DB',root/'workspace.db'),('SETUP_KEY',root/'setup.key')]:
            item=patch.object(server,name,value); item.start(); self.addCleanup(item.stop)
        with contextlib.redirect_stdout(io.StringIO()): server.init_db()
    def test_c08_missing_credentials_create_no_account(self):
        with patch.dict(os.environ,{},clear=True), self.assertRaises(RuntimeError): cloud_start.bootstrap_admin(server)
        with server.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],0)
    def test_c09_create_once_and_hash_password(self):
        env={'PORTAL_ADMIN_EMAIL':'admin@example.test','PORTAL_ADMIN_PASSWORD':PASSWORD}
        with patch.dict(os.environ,env,clear=True): self.assertTrue(cloud_start.bootstrap_admin(server))
        self.assertFalse(server.SETUP_KEY.exists())
        with server.db() as db:
            user=db.execute('SELECT * FROM users').fetchone()
            self.assertEqual(user['role'],'admin')
            self.assertTrue(server.passok(PASSWORD,user['password_hash']))
            self.assertNotIn(PASSWORD,user['password_hash'])
        with patch.dict(os.environ,{},clear=True): self.assertFalse(cloud_start.bootstrap_admin(server))
        with server.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
    def test_c10_weak_password_rejected(self):
        env={'PORTAL_ADMIN_EMAIL':'admin@example.test','PORTAL_ADMIN_PASSWORD':'short'}
        with patch.dict(os.environ,env,clear=True),self.assertRaises(server.HTTPException): cloud_start.bootstrap_admin(server)

class CloudHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cloud-http-');cls.root=Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.base=f'http://127.0.0.1:{cls.port}'
        cls.env=dict(os.environ,RAILWAY_VOLUME_MOUNT_PATH=str(cls.root),PORTAL_DATA_DIR=str(cls.root),PORT=str(cls.port),
                     RAILWAY_PUBLIC_DOMAIN='portal.example.test',PORTAL_ALLOWED_HOSTS='',FORWARDED_ALLOW_IPS='127.0.0.1',
                     PORTAL_ADMIN_EMAIL='admin@example.test',PORTAL_ADMIN_PASSWORD=PASSWORD)
        cls.log=(cls.root/'cloud.log').open('w');cls.start_server()
    @classmethod
    def start_server(cls):
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'cloud_start.py')],env=cls.env,stdout=cls.log,stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                if httpx.get(cls.base+'/api/health',headers={'Host':'healthcheck.railway.app'},timeout=1).status_code==200:return
            except httpx.HTTPError:pass
            if cls.process.poll() is not None:raise RuntimeError('Cloud test startup failed: '+(cls.root/'cloud.log').read_text())
            time.sleep(.1)
        raise RuntimeError('Cloud test server did not start.')
    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.log.close();cls.temp.cleanup()
    def get(self,path,https=True,host='portal.example.test'):
        headers={'Host':host}
        if https:headers['X-Forwarded-Proto']='https'
        return httpx.get(self.base+path,headers=headers)
    def test_c11_health_host_and_https(self):
        self.assertEqual(self.get('/api/health',False,'healthcheck.railway.app').status_code,200)
        home=self.get('/');self.assertEqual(home.status_code,200);self.assertIn('Strict-Transport-Security',home.headers)
        self.assertEqual(self.get('/',False).status_code,400)
        self.assertEqual(self.get('/',host='untrusted.example').status_code,400)
        self.assertEqual(self.get('/api/docs').status_code,404)
    def test_c12_secure_login_and_dashboard(self):
        headers={'Host':'portal.example.test','X-Forwarded-Proto':'https','Origin':'https://portal.example.test'}
        r=httpx.post(self.base+'/api/auth/login',headers=headers,json={'identifier':'admin@example.test','password':PASSWORD,'role':'admin'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('secure',r.headers['set-cookie'].lower());self.assertIn('httponly',r.headers['set-cookie'].lower())
        headers['Cookie']='portal_session='+r.cookies.get('portal_session')
        self.assertEqual(httpx.get(self.base+'/api/dashboard',headers=headers).status_code,200)
        self.assertEqual(self.get('/api/dashboard').status_code,401)
    def test_c13_setup_blocked_secrets_not_logged(self):
        r=httpx.post(self.base+'/api/auth/setup',headers={'Host':'portal.example.test','X-Forwarded-Proto':'https'},json={})
        self.assertEqual(r.status_code,404)
        text=(self.root/'cloud.log').read_text();self.assertNotIn(PASSWORD,text);self.assertNotIn('Your one-time setup key:',text)
    def test_c14_restart_without_bootstrap_preserves_admin(self):
        self.process.terminate();self.process.wait(timeout=10)
        type(self).env.pop('PORTAL_ADMIN_PASSWORD',None);type(self).start_server()
        r=httpx.post(self.base+'/api/auth/login',headers={'Host':'portal.example.test','X-Forwarded-Proto':'https'},
                     json={'identifier':'admin@example.test','password':PASSWORD,'role':'admin'})
        self.assertEqual(r.status_code,200,r.text);self.assertFalse((self.root/'setup.key').exists())

if __name__=='__main__':unittest.main()
