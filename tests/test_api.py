"""Real HTTP integration tests with isolated, disposable accounts and files.
Run: python -m unittest discover -s tests -v
Test credentials below are fixtures only; the application never creates these accounts.
"""
from contextlib import closing
import io,json,os,shutil,socket,sqlite3,subprocess,sys,tempfile,time,unittest
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
ADMIN_PASSWORD='Tests Only Administrator 491!'
EMP_PASSWORD='Tests Only Employee 782!'
PDF=b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n'

class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='workspace-v3-tests-')
        cls.data=Path(cls.tmp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.base=f'http://127.0.0.1:{cls.port}'
        cls.env=dict(os.environ,PORTAL_DATA_DIR=str(cls.data))
        cls.log=(cls.data/'server.log').open('w')
        cls.start_server()
        cls.save_snapshot('empty.db')
        owner=httpx.Client(base_url=cls.base,timeout=30)
        setup=owner.post('/api/auth/setup',json={'setup_key':(cls.data/'setup.key').read_text().strip(),
            'first_name':'Test','last_name':'Owner','employee_id':'QAADMIN','email':'owner@example.test',
            'password':ADMIN_PASSWORD,'confirm_password':ADMIN_PASSWORD})
        assert setup.status_code==201,setup.text
        owner.headers['X-CSRF-Token']=setup.json()['csrf']
        for n in (1,2):
            r=owner.post('/api/admin/employees',json={'first_name':f'Employee{n}','last_name':'Testing',
                'employee_id':f'QAEMP{n}','email':f'employee{n}@example.test','department':'Testing','location':'Test location'})
            assert r.status_code==201,r.text
            with httpx.Client(base_url=cls.base,timeout=30) as employee:
                r2=employee.post('/api/auth/login',json={'identifier':f'QAEMP{n}','password':r.json()['temporary_password'],'role':'employee'})
                assert r2.status_code==200,r2.text
                employee.headers['X-CSRF-Token']=r2.json()['csrf']
                r3=employee.post('/api/auth/password',json={'current_password':r.json()['temporary_password'],'new_password':EMP_PASSWORD,'confirm_password':EMP_PASSWORD})
                assert r3.status_code==200,r3.text
        owner.close();cls.save_snapshot('baseline.db')

    @classmethod
    def start_server(cls):
        cls.proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--no-browser','--port',str(cls.port)],env=cls.env,stdout=cls.log,stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                if httpx.get(cls.base+'/api/health',timeout=1).status_code==200:return
            except httpx.HTTPError:pass
            if cls.proc.poll() is not None:raise RuntimeError((cls.data/'server.log').read_text())
            time.sleep(.1)
        raise RuntimeError('HTTP test server did not start')
    @classmethod
    def save_snapshot(cls,name):
        with closing(sqlite3.connect(cls.data/'workspace.db')) as source,closing(sqlite3.connect(cls.data/name)) as target:source.backup(target)
    def restore(self,name='baseline.db'):
        with closing(sqlite3.connect(self.data/name)) as source,closing(sqlite3.connect(self.data/'workspace.db')) as target:source.backup(target)
    def setUp(self):
        self.restore();self.clients=[]
        for file in (self.data/'documents').iterdir():file.unlink()
    def tearDown(self):
        for c in self.clients:c.close()
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate();cls.proc.wait(timeout=10);cls.log.close();cls.tmp.cleanup()
    def client(self,who=None):
        c=httpx.Client(base_url=self.base,timeout=30);self.clients.append(c)
        if who:
            r=c.post('/api/auth/login',json={'identifier':'QAADMIN' if who=='admin' else f'QAEMP{who}',
                'password':ADMIN_PASSWORD if who=='admin' else EMP_PASSWORD,'role':'admin' if who=='admin' else 'employee'})
            self.assertEqual(r.status_code,200,r.text);c.headers['X-CSRF-Token']=r.json()['csrf']
        return c
    def upload(self,c=None,uid=2,kind='payslip',period='2026-09',filename='document.pdf',content=PDF,**extra):
        c=c or self.client('admin')
        data={'user_id':str(uid),'kind':kind,'pay_period':period,'issue_date':'2026-09-10','title':'Uploaded test document',**extra}
        return c.post('/api/admin/documents',data=data,files={'file':(filename,content,'application/pdf')})

    def test_01_anonymous_session_does_not_auto_login(self):
        c=self.client();r=c.get('/api/session');self.assertFalse(r.json()['authenticated']);self.assertNotIn('demo_mode',r.json())
        self.assertEqual(c.get('/api/dashboard').status_code,401)
        self.assertEqual(c.post('/api/auth/demo').status_code,404)
    def test_02_no_default_credentials_or_sample_business_records(self):
        c=self.client();self.assertEqual(c.post('/api/auth/login',json={'identifier':'employee@portal.local','password':'Demo@12345'}).status_code,401)
        with closing(sqlite3.connect(self.data/'workspace.db')) as d:
            for table in ['attendance','tasks','jobs','posts','employee_documents']:
                self.assertEqual(d.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
    def test_03_employee_id_email_login_and_role_validation(self):
        c=self.client();self.assertEqual(c.post('/api/auth/login',json={'identifier':'employee1@example.test','password':EMP_PASSWORD,'role':'employee'}).status_code,200)
        self.assertEqual(c.post('/api/auth/login',json={'identifier':'QAEMP1','password':EMP_PASSWORD,'role':'admin'}).status_code,401)
    def test_04_session_cookie_and_logout(self):
        c=self.client();r=c.post('/api/auth/login',json={'identifier':'QAEMP1','password':EMP_PASSWORD})
        cookie=r.headers['set-cookie'].lower();self.assertIn('httponly',cookie);self.assertIn('samesite=strict',cookie)
        c.headers['X-CSRF-Token']=r.json()['csrf'];self.assertEqual(c.post('/api/auth/logout').status_code,200)
        self.assertEqual(c.get('/api/dashboard').status_code,401)
    def test_05_csrf_required_for_writes(self):
        c=self.client(1);del c.headers['X-CSRF-Token'];self.assertEqual(c.post('/api/attendance/check-in',json={}).status_code,403)
    def test_06_cross_origin_writes_rejected(self):
        c=self.client(1);r=c.post('/api/attendance/check-in',json={},headers={'Origin':'https://untrusted.example'});self.assertEqual(r.status_code,403)
    def test_07_login_is_rate_limited(self):
        c=self.client()
        for _ in range(10):self.assertEqual(c.post('/api/auth/login',json={'identifier':'unknown@example.test','password':'incorrect'}).status_code,401)
        self.assertEqual(c.post('/api/auth/login',json={'identifier':'unknown@example.test','password':'incorrect'}).status_code,429)
    def test_08_setup_is_key_protected_and_single_use(self):
        c=self.client();self.assertEqual(c.post('/api/auth/setup',json={}).status_code,409)
        self.restore('empty.db');(self.data/'setup.key').write_text('test-secret-setup-key')
        self.assertTrue(c.get('/api/session').json()['setup_required'])
        payload={'setup_key':'wrong','first_name':'New','employee_id':'OWNER2','email':'new@example.test','password':ADMIN_PASSWORD,'confirm_password':ADMIN_PASSWORD}
        self.assertEqual(c.post('/api/auth/setup',json=payload).status_code,403)
        payload['setup_key']='test-secret-setup-key';r=c.post('/api/auth/setup',json=payload);self.assertEqual(r.status_code,201,r.text)
        self.assertFalse((self.data/'setup.key').exists());self.assertEqual(c.post('/api/auth/setup',json=payload).status_code,409)
    def test_09_manager_assignment_and_team_visibility(self):
        a=self.client('admin')
        r=a.patch('/api/admin/employees/2',json={'manager_id':3})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['manager_id'],3)
        non_manager=self.client(1)
        self.assertEqual(non_manager.get('/api/manager/team').status_code,403)
        parent=self.client(2)
        team=parent.get('/api/manager/team')
        self.assertEqual(team.status_code,200,team.text)
        self.assertEqual([x['id'] for x in team.json()['reportees']],[2])

    def test_10_manager_can_review_reportee_leave(self):
        a=self.client('admin')
        self.assertEqual(a.patch('/api/admin/employees/2',json={'manager_id':3}).status_code,200)
        # Give employee 2 a paid leave balance.
        self.assertEqual(a.patch('/api/admin/employees/2/leave-balances',json={'balances':{'Comp off':5,'Bereavement Leave':5,'Birthday Leave':5,'Earned Leave':5,'Wedding Leave':5}}).status_code,200)
        reportee=self.client(1)
        r=reportee.post('/api/leaves',json={'type':'Earned Leave','start_date':'2026-10-05','end_date':'2026-10-06','reason':'Family work'})
        self.assertEqual(r.status_code,201,r.text)
        m=self.client(2)
        team=m.get('/api/manager/team').json()
        self.assertEqual(len(team['leaves']),1)
        leave_id=team['leaves'][0]['id']
        r=m.patch(f'/api/manager/leaves/{leave_id}',json={'status':'Approved','note':'Approved by reporting manager'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(m.get('/api/manager/team').json()['leaves'][0]['status'],'Approved')
        self.assertEqual(reportee.get('/api/leaves').json()[0]['status'],'Approved')

    def test_11_manager_cannot_review_non_reportee_leave(self):
        a=self.client('admin')
        self.assertEqual(a.patch('/api/admin/employees/2',json={'manager_id':3}).status_code,200)
        self.assertEqual(a.patch('/api/admin/employees/3',json={'manager_id':2}).status_code,409)

    def test_09_admin_creates_unique_account_forced_password_change(self):
        a=self.client('admin');r=a.post('/api/admin/employees',json={'first_name':'New','employee_id':'NEW001','email':'new@example.test'})
        self.assertEqual(r.status_code,201,r.text);data=r.json();self.assertTrue(data['user']['must_change_password'])
        c=self.client();r=c.post('/api/auth/login',json={'identifier':'NEW001','password':data['temporary_password']});self.assertEqual(r.status_code,200)
        c.headers['X-CSRF-Token']=r.json()['csrf'];self.assertEqual(c.get('/api/dashboard').status_code,403);self.assertEqual(c.get('/api/documents').status_code,403)
        r=c.post('/api/auth/password',json={'current_password':data['temporary_password'],'new_password':EMP_PASSWORD,'confirm_password':EMP_PASSWORD})
        self.assertEqual(r.status_code,200,r.text);c.headers['X-CSRF-Token']=r.json()['csrf'];self.assertEqual(c.get('/api/dashboard').status_code,200)
    def test_10_employee_cannot_manage_accounts_or_upload(self):
        c=self.client(1)
        for method,path in [('GET','/api/admin/employees'),('GET','/api/admin/documents'),('POST','/api/admin/employees'),('POST','/api/admin/documents'),('POST','/api/admin/employees/3/reset-password')]:
            self.assertEqual(c.request(method,path,json={}).status_code,403,path)
    def test_11_duplicate_employee_id_and_email_rejected(self):
        a=self.client('admin')
        for b in [{'first_name':'Repeat','employee_id':'QAEMP1','email':'different@example.test'},{'first_name':'Repeat','employee_id':'DIFFERENT','email':'EMPLOYEE1@example.test'}]:
            self.assertEqual(a.post('/api/admin/employees',json=b).status_code,409)
    def test_12_employee_reset_invalidates_sessions(self):
        a=self.client('admin');e=self.client(1);r=a.post('/api/admin/employees/2/reset-password');self.assertEqual(r.status_code,200)
        self.assertEqual(e.get('/api/dashboard').status_code,401)
        r=e.post('/api/auth/login',json={'identifier':'QAEMP1','password':r.json()['temporary_password']});self.assertTrue(r.json()['user']['must_change_password'])
    def test_13_disable_account_revokes_access(self):
        a=self.client('admin');e=self.client(1);r=a.patch('/api/admin/employees/2',json={'is_active':False});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(e.get('/api/documents').status_code,401)
        self.assertEqual(e.post('/api/auth/login',json={'identifier':'QAEMP1','password':EMP_PASSWORD}).status_code,401)
    def test_14_administrator_cannot_disable_self(self):
        a=self.client('admin');self.assertEqual(a.patch('/api/admin/employees/1',json={'is_active':False}).status_code,409)
        self.assertEqual(a.patch('/api/admin/employees/1',json={'role':'employee'}).status_code,409)
    def test_15_password_validation_and_session_rotation(self):
        e=self.client(1);second=self.client(1)
        for current,new,confirm in [('wrong',EMP_PASSWORD,EMP_PASSWORD),(EMP_PASSWORD,'short','short'),(EMP_PASSWORD,'New Password Example 491','mismatch')]:
            self.assertIn(e.post('/api/auth/password',json={'current_password':current,'new_password':new,'confirm_password':confirm}).status_code,[400,422])
        r=e.post('/api/auth/password',json={'current_password':EMP_PASSWORD,'new_password':'New Password Example 491','confirm_password':'New Password Example 491'})
        self.assertEqual(r.status_code,200);self.assertEqual(second.get('/api/dashboard').status_code,401)
    def test_16_passwords_not_returned_in_accounts(self):
        data=self.client('admin').get('/api/admin/employees').json()
        self.assertTrue(all('password_hash' not in x and 'password' not in x for x in data))
        with closing(sqlite3.connect(self.data/'workspace.db')) as d:self.assertNotIn(EMP_PASSWORD,d.execute('SELECT password_hash FROM users WHERE id=2').fetchone()[0])
    def test_17_pdf_upload_and_employee_download_roundtrip(self):
        a=self.client('admin');r=self.upload(a);self.assertEqual(r.status_code,201,r.text)
        e=self.client(1);docs=e.get('/api/documents').json();self.assertEqual(len(docs),1)
        downloaded=e.get(f"/api/documents/{r.json()['id']}/download")
        self.assertEqual(downloaded.content,PDF);self.assertEqual(downloaded.headers['content-type'],'application/pdf')
        self.assertIn('attachment;',downloaded.headers['content-disposition']);self.assertEqual(downloaded.headers['cache-control'],'no-store')
    def test_18_document_ownership_and_anonymous_access(self):
        r=self.upload();ident=r.json()['id'];other=self.client(2)
        self.assertEqual(other.get('/api/documents').json(),[]);self.assertEqual(other.get(f'/api/documents/{ident}/download').status_code,404)
        self.assertEqual(self.client().get(f'/api/documents/{ident}/download').status_code,401)
        self.assertEqual(self.client('admin').get(f'/api/documents/{ident}/download').status_code,200)
    def test_19_document_filters_do_not_leak_other_accounts(self):
        a=self.client('admin');self.upload(a,uid=2);self.upload(a,uid=3)
        e=self.client(1);d=e.get('/api/documents?user_id=3').json();self.assertEqual(len(d),1);self.assertEqual(d[0]['user_id'],2)
        self.assertEqual(len(a.get('/api/admin/documents?user_id=3').json()),1)
    def test_20_offer_letter_upload_without_pay_period(self):
        r=self.upload(kind='offer_letter',period='');self.assertEqual(r.status_code,201,r.text)
        d=self.client(1).get('/api/documents?kind=offer_letter').json();self.assertEqual(len(d),1);self.assertIsNone(d[0]['pay_period'])
    def test_21_document_type_and_pdf_signature_validation(self):
        a=self.client('admin')
        for filename,content in [('document.html',PDF),('document.pdf',b'<script>danger</script>'),('document.pdf',b'%PDF-1.4\nINCOMPLETE CONTENT')]:
            self.assertEqual(self.upload(a,filename=filename,content=content).status_code,422)
        self.assertEqual(list((self.data/'documents').iterdir()),[])
    def test_22_uploaded_filename_path_traversal_rejected(self):
        a=self.client('admin')
        for name in ['../document.pdf','nested/document.pdf']:
            self.assertEqual(self.upload(a,filename=name).status_code,422)
    def test_23_document_size_limit(self):
        r=self.upload(content=b'%PDF-1.4\n'+b' '*(10*1024*1024)+b'%%EOF');self.assertEqual(r.status_code,413)
        self.assertEqual(list((self.data/'documents').iterdir()),[])
    def test_24_invalid_employee_or_period_rejected(self):
        a=self.client('admin')
        self.assertEqual(self.upload(a,uid=999).status_code,422)
        for period in ['', '2026-13','not-a-month']:self.assertEqual(self.upload(a,period=period).status_code,422)
    def test_25_duplicate_payslip_rejected_not_overwritten(self):
        a=self.client('admin');self.assertEqual(self.upload(a).status_code,201);self.assertEqual(self.upload(a).status_code,409)
        self.assertEqual(len(list((self.data/'documents').iterdir())),1)
        self.assertEqual(self.upload(a,period='2026-08').status_code,201)
    def test_26_single_current_offer_letter(self):
        a=self.client('admin');self.assertEqual(self.upload(a,kind='offer_letter').status_code,201)
        self.assertEqual(self.upload(a,kind='offer_letter').status_code,409)
    def test_27_archive_revokes_employee_access_retains_admin_history(self):
        a=self.client('admin');ident=self.upload(a).json()['id'];e=self.client(1)
        self.assertEqual(a.post(f'/api/admin/documents/{ident}/archive').status_code,200)
        self.assertEqual(e.get('/api/documents').json(),[]);self.assertEqual(e.get(f'/api/documents/{ident}/download').status_code,404)
        self.assertEqual(a.get('/api/admin/documents').json(),[]);self.assertEqual(len(a.get('/api/admin/documents?include_archived=true').json()),1)
        self.assertEqual(a.get(f'/api/documents/{ident}/download').status_code,200)
    def test_28_replacement_after_archive(self):
        a=self.client('admin');ident=self.upload(a).json()['id'];a.post(f'/api/admin/documents/{ident}/archive')
        r=self.upload(a,filename='replacement.pdf');self.assertEqual(r.status_code,201,r.text)
        d=self.client(1).get('/api/documents').json();self.assertEqual(len(d),1);self.assertEqual(d[0]['original_name'],'replacement.pdf')
    def test_29_storage_not_exposed_by_static_routes(self):
        self.upload()
        stored=next((self.data/'documents').iterdir()).name
        c=self.client()
        for path in ['/data/documents/'+stored,'/static/documents/'+stored,'/static/../data/documents/'+stored,'/static/../data/setup.key']:
            self.assertEqual(c.get(path).status_code,404,path)
    def test_30_documents_and_accounts_survive_restart(self):
        a=self.client('admin');ident=self.upload(a).json()['id'];e=self.client(1)
        self.proc.terminate();self.proc.wait(timeout=10);type(self).start_server()
        self.assertEqual(e.get(f'/api/documents/{ident}/download').content,PDF)
        self.assertEqual(len(a.get('/api/admin/employees').json()),3)
    def test_31_new_paid_leave_balances_are_zero_and_allocatable(self):
        e=self.client(1);balances=e.get('/api/leave-balances').json()
        paid={x['type']:2 for x in balances if x['balance'] is not None}
        self.assertTrue(all(x['balance'] in (0,None) for x in balances))
        a=self.client('admin');self.assertEqual(a.patch('/api/admin/employees/2/leave-balances',json={'balances':paid}).status_code,200)
        self.assertEqual([x for x in e.get('/api/leave-balances').json() if x['type']=='Earned Leave'][0]['balance'],2)
    def test_32_check_in_out_and_duplicate_protection(self):
        e=self.client(1);r=e.post('/api/attendance/check-in',json={});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(e.post('/api/attendance/check-in',json={}).status_code,409)
        ident=r.json()['today']['id'];r=e.post('/api/attendance/check-out',json={'attendance_id':ident});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['today']['id'],ident);self.assertEqual(r.json()['state'],'checked_out')
    def test_33_overnight_settings_saved_and_locked_during_shift(self):
        e=self.client(1);self.assertEqual(e.patch('/api/shift',json={'start_time':'22:00','end_time':'07:00'}).status_code,200)
        e.post('/api/attendance/check-in',json={});self.assertEqual(e.patch('/api/shift',json={'start_time':'23:00','end_time':'07:00'}).status_code,409)
        self.assertEqual(e.get('/api/shift').json()['start_time'],'22:00')
    def test_34_audit_records_upload_and_download(self):
        a=self.client('admin');ident=self.upload(a).json()['id'];self.client(1).get(f'/api/documents/{ident}/download')
        actions=[x['action'] for x in a.get('/api/admin/overview').json()['audit']]
        self.assertIn('Uploaded payslip',actions);self.assertIn('Downloaded document',actions)
    def test_35_employee_receives_document_notification(self):
        self.upload();d=self.client(1).get('/api/notifications').json();self.assertTrue(any(x['title']=='Payslip available' for x in d))
    def test_36_request_does_not_generate_employment_proof(self):
        e=self.client(1);r=e.post('/api/requests',json={'kind':'letter','title':'Employment confirmation','details':{'purpose':'Test document request'}})
        self.assertEqual(r.status_code,201,r.text);self.assertEqual(e.get(f"/api/requests/{r.json()['id']}/document").status_code,404)
    def test_37_support_ticket_and_goal_workflows(self):
        e=self.client(1)
        r=e.post('/api/tickets',json={'category':'IT Support','title':'Workstation issue','description':'A test issue to be reviewed','priority':'Medium'});self.assertEqual(r.status_code,201,r.text)
        r=e.post('/api/goals',json={'title':'Complete training','description':'Finish the course','target_date':'2026-12-31','progress':0});self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(e.patch(f"/api/goals/{r.json()['id']}",json={'progress':50}).status_code,200)
        self.assertEqual(self.client(2).get('/api/goals').json(),[])
    def test_38_multiple_file_upload_is_rejected(self):
        a=self.client('admin');r=a.post('/api/admin/documents',data={'user_id':'2','kind':'payslip','title':'Test files','pay_period':'2026-09','issue_date':'2026-09-10'},files=[('file',('one.pdf',PDF,'application/pdf')),('file',('two.pdf',PDF,'application/pdf'))]);self.assertEqual(r.status_code,400)
    def test_39_streamed_request_limit_without_content_length(self):
        a=self.client('admin')
        def chunks():
            for _ in range(18):yield b' '*65536
        r=a.post('/api/goals',content=chunks(),headers={'Content-Type':'application/json'});self.assertEqual(r.status_code,413,r.text)
    def test_40_document_metadata_does_not_expose_storage_name(self):
        self.upload();d=self.client(1).get('/api/documents').json()[0]
        self.assertNotIn('storage_name',d);self.assertNotIn('sha256',d)
    def test_41_old_database_is_not_loaded_or_modified(self):
        legacy=self.data/'portal.db';legacy.write_bytes(b'legacy-test-data')
        self.proc.terminate();self.proc.wait(timeout=10);type(self).start_server()
        self.assertEqual(legacy.read_bytes(),b'legacy-test-data');self.assertEqual(len(self.client('admin').get('/api/admin/employees').json()),3)
    def test_42_static_app_contains_no_demo_controls(self):
        c=self.client()
        for route in ['/static/app.js','/static/accounts-documents.js','/']:
            data=c.get(route).text
            for obsolete in ['Switch Demo Account','Demo@12345','Admin@12345','auth/demo','INDEPENDENT LOCAL DEMO','SAMPLE ACCOUNTS']:
                self.assertNotIn(obsolete,data)
        self.assertEqual(c.get('/OPEN_PREVIEW.html').status_code,404)
    def test_43_missing_file_returns_controlled_404(self):
        ident=self.upload().json()['id'];next((self.data/'documents').iterdir()).unlink()
        self.assertEqual(self.client(1).get(f'/api/documents/{ident}/download').status_code,404)
    def test_44_disabled_account_cannot_receive_new_document(self):
        a=self.client('admin');a.patch('/api/admin/employees/2',json={'is_active':False})
        self.assertEqual(self.upload(a).status_code,422)
    def test_45_security_response_headers(self):
        r=self.client().get('/api/session')
        self.assertEqual(r.headers['x-content-type-options'],'nosniff');self.assertEqual(r.headers['x-frame-options'],'DENY')
        self.assertEqual(r.headers['cache-control'],'no-store');self.assertIn("frame-ancestors 'none'",r.headers['content-security-policy'])
    def test_46_archive_requires_admin_and_csrf(self):
        a=self.client('admin');ident=self.upload(a).json()['id'];e=self.client(1)
        self.assertEqual(e.post(f'/api/admin/documents/{ident}/archive').status_code,403)
        del a.headers['X-CSRF-Token'];self.assertEqual(a.post(f'/api/admin/documents/{ident}/archive').status_code,403)

if __name__=='__main__':unittest.main()
