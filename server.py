"""American Express-inspired colleague workspace. Independent software, not an official company service.
Run python server.py. Attendance uses server-side IST and one record per shift start date.
"""
from __future__ import annotations
import argparse,csv,hashlib,hmac,html,io,json,os,re,secrets,sqlite3,threading,time,webbrowser
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import contextmanager,asynccontextmanager
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request,Response,Depends,Body,Query
from fastapi.responses import FileResponse,JSONResponse,HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('PORTAL_DATA_DIR',str(ROOT/'data')))
DB=DATA/'workspace.db'
MAX_DOCUMENT_BYTES=10*1024*1024
SETUP_KEY=DATA/'setup.key'
IST=timezone(timedelta(hours=5,minutes=30))
LEAVES=['Comp off','Bereavement Leave','Birthday Leave','Earned Leave','Wedding Leave','Unpaid','Sabbatical Leave']
KINDS=['flow','letter','expense','travel','referral','service','regularization','tax']
ATTEMPTS={};LOCK=threading.Lock()
def now():return datetime.now(IST)
def stamp():return now().isoformat(timespec='seconds')
def fail(message,code=422):raise HTTPException(code,message)
def text(body,key,minimum=0,maximum=4000):
 v=body.get(key,'')
 if not isinstance(v,str) or not minimum<=len(v.strip())<=maximum:fail(f'{key.replace("_"," ")}: enter {minimum}-{maximum} characters.')
 return v.strip()
def number(value,lo,hi):
 try:v=float(value)
 except (ValueError,TypeError):fail('Enter a valid number.')
 if not lo<=v<=hi:fail(f'Value must be between {lo:g} and {hi:g}.')
 return v
def parsedate(value):
 try:d=date.fromisoformat(value)
 except (ValueError,TypeError):fail('Enter a valid date.')
 if not 2020<=d.year<=2100:fail('Date is outside the supported range.')
 return d
def hashpass(password,salt=None):
 salt=salt or secrets.token_hex(16)
 return salt+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
def passok(password,stored):return hmac.compare_digest(hashpass(password,stored.split('$')[0]),stored)
@contextmanager
def db():
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
 try:yield c;c.commit()
 except Exception:c.rollback();raise
 finally:c.close()
def rows(c,sql,args=()):return [dict(r) for r in c.execute(sql,args).fetchall()]
def notify(c,uid,title,body='',target='dashboard'):c.execute('INSERT INTO notifications(user_id,title,body,target,created_at) VALUES(?,?,?,?,?)',(uid,title,body,target,stamp()))
def audit(c,uid,action,entity,ident=None,detail=''):c.execute('INSERT INTO audit(user_id,action,entity,entity_id,detail,created_at) VALUES(?,?,?,?,?,?)',(uid,action,entity,ident,detail,stamp()))
def init_db():
 DATA.mkdir(parents=True,exist_ok=True)
 with db() as c:
  c.execute('PRAGMA journal_mode=WAL')
  c.executescript('''
  CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,employee_id TEXT UNIQUE,first_name TEXT,last_name TEXT,email TEXT UNIQUE,password_hash TEXT,role TEXT,designation TEXT,department TEXT,location TEXT,phone TEXT,joined TEXT,manager TEXT,preferences TEXT DEFAULT '{}');
  CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),csrf TEXT,expires REAL);
  CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT,stage TEXT,flow TEXT,reference TEXT,trigger_date TEXT,due_date TEXT,status TEXT DEFAULT 'Pending',description TEXT,resolution TEXT DEFAULT '',created_at TEXT);
  CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),date TEXT,clock_in TEXT,clock_out TEXT,worked_seconds INTEGER DEFAULT 0,late_seconds INTEGER DEFAULT 0,off_seconds INTEGER DEFAULT 0,note TEXT DEFAULT '',UNIQUE(user_id,date));
  CREATE TABLE IF NOT EXISTS leave_balances(user_id INTEGER REFERENCES users(id),type TEXT,balance REAL,PRIMARY KEY(user_id,type));
  CREATE TABLE IF NOT EXISTS leave_requests(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),type TEXT,start_date TEXT,end_date TEXT,days REAL,reason TEXT,status TEXT DEFAULT 'Pending',review_note TEXT DEFAULT '',reviewed_by INTEGER REFERENCES users(id),created_at TEXT);
  CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),category TEXT,title TEXT,description TEXT,priority TEXT,status TEXT DEFAULT 'Open',admin_note TEXT DEFAULT '',created_at TEXT);
  CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT,description TEXT,target_date TEXT,progress INTEGER DEFAULT 0,created_at TEXT);
  CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),kind TEXT,title TEXT,details TEXT,status TEXT DEFAULT 'Pending',admin_note TEXT DEFAULT '',created_at TEXT);
  CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT,body TEXT DEFAULT '',target TEXT DEFAULT 'dashboard',is_read INTEGER DEFAULT 0,created_at TEXT);
  CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),body TEXT,created_at TEXT);
  CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,title TEXT,department TEXT,location TEXT,type TEXT DEFAULT 'Full time');
  CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),action TEXT,entity TEXT,entity_id INTEGER,detail TEXT DEFAULT '',created_at TEXT);
  CREATE INDEX IF NOT EXISTS idx_leaves ON leave_requests(user_id,status,start_date,end_date);
  CREATE INDEX IF NOT EXISTS idx_tasks ON tasks(user_id,status);
  ''')
  c.execute("CREATE TABLE IF NOT EXISTS shift_settings(user_id INTEGER PRIMARY KEY REFERENCES users(id),start_time TEXT NOT NULL DEFAULT '20:30',end_time TEXT NOT NULL DEFAULT '04:30')")
  # Additive migration; existing employee data is never deleted on startup.
  columns={r['name'] for r in c.execute('PRAGMA table_info(attendance)')}
  for column in ('shift_start','shift_end'):
   if column not in columns:c.execute(f'ALTER TABLE attendance ADD COLUMN {column} TEXT')
  c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_shift ON attendance(user_id) WHERE clock_in IS NOT NULL AND clock_out IS NULL")
  c.execute("INSERT OR IGNORE INTO shift_settings(user_id,start_time,end_time) SELECT id,'20:30','04:30' FROM users")
  # The portal's standard overnight shift is 8:30 PM–4:30 AM IST.
  c.execute("UPDATE shift_settings SET start_time='20:30', end_time='04:30' WHERE start_time='21:00' AND end_time='06:00'")
  # Version 3 starts with no pre-created people, accounts or business records.
  columns={r['name'] for r in c.execute('PRAGMA table_info(users)')}
  for name,sql in [('is_active','INTEGER NOT NULL DEFAULT 1'),('must_change_password','INTEGER NOT NULL DEFAULT 0'),('profile_photo','TEXT'),('manager_id','INTEGER REFERENCES users(id)')]:
   if name not in columns:c.execute(f'ALTER TABLE users ADD COLUMN {name} {sql}')
  # Backfill the new manager relationship from the legacy free-text manager field when possible.
  c.execute("UPDATE users SET manager_id=(SELECT m.id FROM users m WHERE m.is_active=1 AND (lower(m.employee_id)=lower(users.manager) OR lower(trim(m.first_name||' '||m.last_name))=lower(trim(users.manager))) LIMIT 1) WHERE manager_id IS NULL AND manager IS NOT NULL AND trim(manager)<>''")
  c.executescript("""
  CREATE TABLE IF NOT EXISTS employee_documents(
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK(kind IN ('payslip','offer_letter')),
    title TEXT NOT NULL, pay_period TEXT, issue_date TEXT NOT NULL,
    original_name TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL, sha256 TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
    archived_at TEXT, archived_by INTEGER REFERENCES users(id));
  CREATE UNIQUE INDEX IF NOT EXISTS idx_current_payslip
    ON employee_documents(user_id,pay_period) WHERE kind='payslip' AND archived_at IS NULL;
  CREATE UNIQUE INDEX IF NOT EXISTS idx_current_offer
    ON employee_documents(user_id) WHERE kind='offer_letter' AND archived_at IS NULL;
  CREATE TABLE IF NOT EXISTS login_attempts(
    id INTEGER PRIMARY KEY, address TEXT NOT NULL, identifier TEXT NOT NULL, attempted REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(attempted);
  """)
  if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
   # Printed only in the local server terminal; never returned over HTTP.
   if not SETUP_KEY.exists():
    try:
     with SETUP_KEY.open('x',encoding='utf-8') as f:f.write(secrets.token_urlsafe(32))
     SETUP_KEY.chmod(0o600)
    except FileExistsError:pass
   print('\nFIRST-TIME SETUP - create your administrator account in the browser.',flush=True)
   print('Your one-time setup key: '+SETUP_KEY.read_text().strip(),flush=True)
   print('Keep this key private. It stops working after setup.\n',flush=True)
 (DATA/'documents').mkdir(exist_ok=True)
 try:DATA.chmod(0o700);(DATA/'documents').chmod(0o700)
 except OSError:pass
def normalize_historical_attendance():
    """Make preloaded historical attendance varied while preserving manual/admin edits."""
    marker=DATA/'.attendance_realistic_v3'
    if marker.exists(): return
    with db() as c:
        people=rows(c,"SELECT id FROM users WHERE role='employee' AND is_active=1")
        if not people:
            marker.write_text(stamp(),encoding='utf-8'); return
        latest=now().date()-timedelta(days=1)
        start=latest-timedelta(days=29)
        import random
        for person in people:
            uid=person['id']
            shift=shift_for(uid,c)
            for i in range(30):
                day=start+timedelta(days=i)
                existing=c.execute("SELECT * FROM attendance WHERE user_id=? AND date=?",(uid,str(day))).fetchone()
                editable=(existing is None or str(existing['note'] or '').lower().startswith('historical attendance'))
                if not editable: continue
                scheduled_start=datetime.fromisoformat(f'{day}T{shift["start_time"]}').replace(tzinfo=IST)
                scheduled_end=shift_window(day,shift)[1]
                if day.weekday()>=5:
                    values=(uid,str(day),None,None,0,0,int(shift['duration_seconds']),'Weekly off — Saturday/Sunday',scheduled_start.isoformat(),scheduled_end.isoformat())
                else:
                    rng=random.Random(f'attendance-v3:{uid}:{day.isoformat()}')
                    # Keep the demo believable without making every day identical.
                    # Most days are normal; a few have modest lateness or shorter/longer hours.
                    late=rng.choice([0,0,0,2,4,6,8,11,15,20,27])
                    worked_minutes=rng.randint(7*60+45,8*60+25)
                    cin=scheduled_start+timedelta(minutes=late)
                    cout=cin+timedelta(minutes=worked_minutes)
                    note=rng.choice(['Regular shift','Worked from office','Shift attendance','Attendance recorded'])
                    values=(uid,str(day),cin.isoformat(),cout.isoformat(),worked_minutes*60,late*60,0,note,scheduled_start.isoformat(),scheduled_end.isoformat())
                c.execute("""INSERT INTO attendance(user_id,date,clock_in,clock_out,worked_seconds,late_seconds,off_seconds,note,shift_start,shift_end)
                             VALUES(?,?,?,?,?,?,?,?,?,?)
                             ON CONFLICT(user_id,date) DO UPDATE SET
                             clock_in=excluded.clock_in,clock_out=excluded.clock_out,worked_seconds=excluded.worked_seconds,
                             late_seconds=excluded.late_seconds,off_seconds=excluded.off_seconds,note=excluded.note,
                             shift_start=excluded.shift_start,shift_end=excluded.shift_end""",values)
        marker.write_text(stamp(),encoding='utf-8')

async def lifespan(app):init_db();normalize_historical_attendance();yield
app=FastAPI(title='Colleague Workspace API',version='3.0.0',lifespan=lifespan,docs_url='/api/docs',redoc_url=None,openapi_url='/api/openapi.json')
class BodyLimitMiddleware:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        limit=MAX_DOCUMENT_BYTES+65536 if scope.get('path')=='/api/admin/documents' else 1000000
        total=0
        async def limited_receive():
            nonlocal total
            message=await receive()
            if message['type']=='http.request':
                total+=len(message.get('body',b''))
                if total>limit:raise StarletteHTTPException(413,'Request is too large.')
            return message
        await self.app(scope,limited_receive,send)
app.add_middleware(BodyLimitMiddleware)

@app.middleware('http')
async def secure(request,call_next):
 if request.method in {'POST','PATCH','DELETE','PUT'}:
  origin=request.headers.get('origin')
  if origin and origin!=str(request.base_url).rstrip('/'):return JSONResponse({'detail':'Cross-origin writes are not allowed.'},status_code=403)
  try:large=int(request.headers.get('content-length','0'))>(MAX_DOCUMENT_BYTES+65536 if request.url.path=='/api/admin/documents' else 1000000)
  except ValueError:large=True
  if large:return JSONResponse({'detail':'Request is too large.'},status_code=413)
 response=await call_next(request)
 response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin'})
 if not request.url.path.startswith('/api/docs'):response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
 if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
 return response
@app.exception_handler(sqlite3.OperationalError)
async def db_error(request,exc):return JSONResponse({'detail':'Database is busy or unavailable. Please retry.'},status_code=503)
def auth(request:Request):
 digest=hashlib.sha256(request.cookies.get('portal_session','').encode()).hexdigest()
 with db() as c:r=c.execute('SELECT s.csrf,s.expires,s.token_hash,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?',(digest,)).fetchone()
 if not r or not r['is_active'] or r['expires']<time.time():fail('Please sign in to continue.',401)
 u=dict(r)
 if u['must_change_password'] and request.url.path not in {'/api/session','/api/auth/password','/api/auth/logout'}:fail('Change your temporary password before continuing.',403)
 if request.method not in {'GET','HEAD','OPTIONS'} and not hmac.compare_digest(request.headers.get('x-csrf-token',''),u['csrf']):fail('Security token missing or expired. Refresh and try again.',403)
 return u
def admin(u=Depends(auth)):
 if u['role']!='admin':fail('Administrator access is required.',403)
 return u
def public(u):
 result={k:u[k] for k in ['id','employee_id','first_name','last_name','email','role','designation','department','location','phone','joined','manager']};result['manager_id']=u.get('manager_id');result['preferences']=json.loads(u.get('preferences','{}'));result['is_active']=bool(u.get('is_active',1));result['must_change_password']=bool(u.get('must_change_password',0));result['photo_url']='/api/profile/photo?v='+str(u.get('id')) if u.get('profile_photo') else '';return result
def issue(uid,response):
 token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
 with db() as c:
  c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),));c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,time.time()+57600));u=dict(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())
 response.set_cookie('portal_session',token,max_age=57600,httponly=True,secure=os.environ.get('PORTAL_SECURE_COOKIE')=='1',samesite='strict',path='/')
 return {'authenticated':True,'user':public(u),'csrf':csrf}
@app.get('/api/health')
def health():return {'status':'ok','database':'sqlite'}
@app.get('/api/session')
def session(request:Request):
 with db() as c:setup_required=not bool(c.execute('SELECT 1 FROM users LIMIT 1').fetchone())
 try:
  u=auth(request)
  return {'authenticated':True,'user':public(u),'csrf':u['csrf'],'setup_required':False}
 except HTTPException:return {'authenticated':False,'setup_required':setup_required}

def password_value(b,key='password',minimum=12):
    value=b.get(key)
    if not isinstance(value,str) or not minimum<=len(value)<=128:
        fail(f'{key.replace("_"," ")}: use {minimum}-128 characters.')
    if minimum>=12 and not value.strip():fail('The password cannot contain only spaces.')
    return value

def valid_email(b):
    email=text(b,'email',3,254).lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('Enter a valid email address.')
    return email

def provision(c,b,password,must_change=True):
    employee_id=text(b,'employee_id',2,30).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{1,29}',employee_id):
        fail('Employee ID: use letters, numbers, hyphens or underscores (2-30 characters).')
    first=text(b,'first_name',1,60);last=text(b,'last_name',0,60);email=valid_email(b)
    role=b.get('role','employee')
    if role not in {'employee','admin'}:fail('Choose Employee or Administrator.')
    vals=[employee_id,first,last,email,hashpass(password),role,
          text(b,'designation',0,100),text(b,'department',0,100),
          text(b,'location',0,100),text(b,'phone',0,24),
          str(parsedate(b['joined'])) if b.get('joined') else str(now().date()),
          text(b,'manager',0,100),int(must_change)]
    try:
        r=c.execute('INSERT INTO users(employee_id,first_name,last_name,email,password_hash,role,designation,department,location,phone,joined,manager,must_change_password) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',vals)
    except sqlite3.IntegrityError:fail('That email address or employee ID is already in use.',409)
    uid=r.lastrowid
    c.execute("INSERT INTO shift_settings(user_id,start_time,end_time) VALUES(?,?,?)",(uid,'20:30','04:30'))
    c.executemany('INSERT INTO leave_balances VALUES(?,?,?)',[(uid,k,None if k in {'Unpaid','Sabbatical Leave'} else 0) for k in LEAVES])
    return dict(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())

def limit_attempt(request,identifier):
    ip=request.client.host if request.client else 'unknown';when=time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM login_attempts WHERE attempted<?',(when-300,))
        per_ip=c.execute('SELECT COUNT(*) FROM login_attempts WHERE address=?',(ip,)).fetchone()[0]
        per_name=c.execute('SELECT COUNT(*) FROM login_attempts WHERE identifier=?',(identifier,)).fetchone()[0]
        if per_ip>=30 or per_name>=10:fail('Too many sign-in attempts. Wait five minutes.',429)
        c.execute('INSERT INTO login_attempts(address,identifier,attempted) VALUES(?,?,?)',(ip,identifier,when))
    return ip

@app.post('/api/auth/setup',status_code=201)
def setup(request:Request,response:Response,b:dict=Body(...)):
    if not request.client or request.client.host not in {'127.0.0.1','::1','localhost','testclient'}:
        fail('Run first-time setup on the server computer.',403)
    limit_attempt(request,'first-time-setup')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM users LIMIT 1').fetchone():fail('Administrator setup has already been completed.',409)
        provided=text(b,'setup_key',1,200)
        if not SETUP_KEY.exists() or not hmac.compare_digest(provided,SETUP_KEY.read_text().strip()):
            fail('The setup key is incorrect. Copy it from the server terminal.',403)
        pw=password_value(b)
        if pw!=b.get('confirm_password'):fail('The passwords do not match.')
        user=provision(c,{**b,'role':'admin'},pw,False)
        audit(c,user['id'],'Created first administrator','user',user['id'])
    SETUP_KEY.unlink(missing_ok=True)
    return issue(user['id'],response)

@app.post('/api/auth/login')
def login(request:Request,response:Response,b:dict=Body(...)):
    identifier=text({'identifier':b.get('identifier',b.get('email',''))},'identifier',2,254).lower()
    password=password_value(b,minimum=1)
    role=b.get('role','employee')
    if role not in {'employee','admin'}:fail('Choose Employee or Administrator.')
    ip=limit_attempt(request,identifier)
    with db() as c:
        found=c.execute('SELECT * FROM users WHERE lower(email)=? OR lower(employee_id)=?',(identifier,identifier)).fetchone()
    # Comparable password work for unknown accounts avoids an obvious timing distinction.
    stored=found['password_hash'] if found else '00'*16+'$'+'00'*32
    valid=passok(password,stored)
    if not found or not valid or not found['is_active'] or found['role']!=role:
        fail('Sign-in details are incorrect, or this account is inactive. Check the selected account type.',401)
    with db() as c:
        c.execute('DELETE FROM login_attempts WHERE address=? AND identifier=?',(ip,identifier))
        audit(c,found['id'],'Signed in','user',found['id'])
    return issue(found['id'],response)

@app.post('/api/auth/password')
def change_password(response:Response,b:dict=Body(...),u=Depends(auth)):
    current=password_value(b,'current_password',1);new=password_value(b,'new_password')
    if not passok(current,u['password_hash']):fail('The current password is incorrect.',400)
    if new!=b.get('confirm_password'):fail('The new passwords do not match.')
    if new==current:fail('Choose a different password.')
    encoded=hashpass(new)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        # Do not resurrect a session invalidated by a simultaneous administrator reset.
        fresh=c.execute('SELECT password_hash,is_active FROM users WHERE id=?',(u['id'],)).fetchone()
        if not fresh['is_active'] or fresh['password_hash']!=u['password_hash']:fail('Your account changed. Sign in again.',401)
        c.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?',(encoded,u['id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
        audit(c,u['id'],'Changed password','user',u['id'])
    return issue(u['id'],response)

@app.post('/api/auth/logout')
def logout(response:Response,u=Depends(auth)):
 with db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(u['token_hash'],))
 response.delete_cookie('portal_session',path='/');return {'ok':True}
@app.patch('/api/profile')
def profile(b:dict=Body(...),u=Depends(auth)):
 vals=[text(b,'first_name',1,60),text(b,'last_name',0,60),text(b,'phone',0,24),text(b,'location',1,100),u['id']]
 with db() as c:c.execute('UPDATE users SET first_name=?,last_name=?,phone=?,location=? WHERE id=?',vals);audit(c,u['id'],'Updated profile','user',u['id']);r=dict(c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())
 return public(r)

@app.post('/api/profile/photo')
async def upload_profile_photo(request:Request,u=Depends(auth)):
    allowed={
        'image/jpeg':('.jpg',b'\xff\xd8\xff'),
        'image/png':('.png',b'\x89PNG\r\n\x1a\n'),
        'image/webp':('.webp',b'RIFF')
    }
    async with request.form(max_files=1,max_fields=2,max_part_size=5*1024*1024) as form:
        uploaded=form.get('file')
        if not isinstance(uploaded,UploadFile):
            fail('Select a JPG, PNG, or WEBP photo.')
        mime=(uploaded.content_type or '').lower()
        if mime not in allowed:
            fail('Only JPG, PNG, or WEBP photos are accepted.')
        data=await uploaded.read(5*1024*1024+1)
        if len(data)>5*1024*1024:
            fail('The profile photo exceeds the 5 MB limit.',413)
        ext,magic=allowed[mime]
        if not data.startswith(magic):
            fail('The selected file does not match its image type.')
        if mime=='image/webp' and (len(data)<12 or data[8:12]!=b'WEBP'):
            fail('The selected WEBP file is invalid.')
        photo_dir=DATA/'profile_photos'
        photo_dir.mkdir(parents=True,exist_ok=True)
        with db() as c:
            old=c.execute('SELECT profile_photo FROM users WHERE id=?',(u['id'],)).fetchone()
            filename=secrets.token_hex(24)+ext
            destination=photo_dir/filename
            destination.write_bytes(data)
            try: destination.chmod(0o600)
            except OSError: pass
            c.execute('UPDATE users SET profile_photo=? WHERE id=?',(filename,u['id']))
            audit(c,u['id'],'Updated profile photo','user',u['id'])
        if old and old['profile_photo']:
            try:(photo_dir/old['profile_photo']).unlink(missing_ok=True)
            except OSError:pass
        with db() as c:return public(dict(c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()))

@app.get('/api/profile/photo')
def get_profile_photo(request:Request):
    u=auth(request)
    with db() as c:r=c.execute('SELECT profile_photo FROM users WHERE id=?',(u['id'],)).fetchone()
    if not r or not r['profile_photo']:
        raise HTTPException(404,'No profile photo has been uploaded.')
    p=DATA/'profile_photos'/r['profile_photo']
    if not p.is_file(): raise HTTPException(404,'Profile photo not found.')
    media={'.jpg':'image/jpeg','.png':'image/png','.webp':'image/webp'}.get(p.suffix.lower(),'application/octet-stream')
    return FileResponse(p,media_type=media,headers={'Cache-Control':'private, max-age=3600'})
@app.patch('/api/preferences')
def preferences(b:dict=Body(...),u=Depends(auth)):
 keys=['attendance_reminders','request_updates','weekly_summary','compact_view'];prefs={k:b.get(k,False) for k in keys}
 if any(type(v)!=bool for v in prefs.values()):fail('Preferences must be true or false.')
 with db() as c:c.execute('UPDATE users SET preferences=? WHERE id=?',(json.dumps(prefs),u['id']));audit(c,u['id'],'Updated preferences','user',u['id'])
 return prefs
@app.get('/api/members')
def members(q:str=Query('',max_length=100),u=Depends(auth)):
 with db() as c:
        data=rows(c,"SELECT id,employee_id,first_name,last_name,email,designation,department,location,manager,manager_id,profile_photo FROM users WHERE is_active=1 AND first_name||' '||last_name||' '||department||' '||employee_id LIKE ? ORDER BY first_name",('%'+q+'%',))
        for person in data: person['photo_url']='/api/profile/photo?v='+str(person['id']) if person.get('profile_photo') else ''
        return data
@app.get('/api/tasks')
def tasks(u=Depends(auth)):
 with db() as c:return rows(c,'SELECT * FROM tasks WHERE user_id=? ORDER BY id',(u['id'],))
@app.patch('/api/tasks/{ident}')
def task_update(ident:int,b:dict=Body(...),u=Depends(auth)):
 status=b.get('status');res=text(b,'resolution',3 if status=='Completed' else 0)
 if status not in ['Pending','Completed']:fail('Invalid task status.')
 with db() as c:
  r=c.execute('UPDATE tasks SET status=?,resolution=? WHERE id=? AND user_id=?',(status,res,ident,u['id']))
  if not r.rowcount:fail('Task not found.',404)
  audit(c,u['id'],'Updated task','task',ident,status);notify(c,u['id'],'Task '+status.lower(),res[:120],'tasks')
 return {'ok':True}
def shift_for(uid,c=None):
 if c is None:
  with db() as conn:return shift_for(uid,conn)
 r=c.execute('SELECT start_time,end_time FROM shift_settings WHERE user_id=?',(uid,)).fetchone()
 start,end=(r['start_time'],r['end_time']) if r else ('20:30','04:30')
 seconds=((int(end[:2])*60+int(end[3:]))-(int(start[:2])*60+int(start[3:])))%1440*60
 return {'start_time':start,'end_time':end,'timezone':'Asia/Kolkata','timezone_label':'IST (UTC+05:30)','name':'Overnight shift','overnight':end<start,'duration_seconds':seconds}

def shift_date(t,shift):
 """Early-morning check-ins belong to the preceding night's shift."""
 return t.date()-timedelta(days=1) if shift['overnight'] and t.strftime('%H:%M')<=shift['end_time'] else t.date()

def shift_window(day,shift):
 start=datetime.fromisoformat(f"{day}T{shift['start_time']}").replace(tzinfo=IST)
 end=datetime.fromisoformat(f"{day}T{shift['end_time']}").replace(tzinfo=IST)
 if end<=start:end+=timedelta(days=1)
 return start,end

def attendance_status(uid,c=None,t=None):
 t=t or now()
 if c is None:
  with db() as conn:return attendance_status(uid,conn,t)
 shift=shift_for(uid,c);day=shift_date(t,shift)
 # A midnight rollover must never hide an open attendance record.
 r=c.execute('SELECT * FROM attendance WHERE user_id=? AND clock_in IS NOT NULL AND clock_out IS NULL ORDER BY clock_in DESC LIMIT 1',(uid,)).fetchone()
 if r:day=date.fromisoformat(r['date'])
 else:r=c.execute('SELECT * FROM attendance WHERE user_id=? AND date=?',(uid,str(day))).fetchone()
 start,end=shift_window(day,shift)
 if r and r['shift_start'] and r['shift_end']:start,end=datetime.fromisoformat(r['shift_start']),datetime.fromisoformat(r['shift_end'])
 record=dict(r) if r else None
 if record and record['clock_in'] and not record['clock_out']:record['worked_seconds']=max(0,int((t-datetime.fromisoformat(record['clock_in'])).total_seconds()))
 state='checked_out' if record and record['clock_out'] else 'checked_in' if record and record['clock_in'] else 'not_checked_in'
 return {'today':record,'state':state,'shift':shift,'shift_date':str(day),'scheduled_start':start.isoformat(),'scheduled_end':end.isoformat(),'server_time':t.isoformat(timespec='milliseconds')}

@app.get('/api/shift')
def get_shift(u=Depends(auth)):return shift_for(u['id'])

@app.patch('/api/shift')
def update_shift(b:dict=Body(...),u=Depends(auth)):
 start=text(b,'start_time',5,5);end=text(b,'end_time',5,5)
 if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',start) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',end):fail('Use valid times in HH:MM format.')
 length=((int(end[:2])*60+int(end[3:]))-(int(start[:2])*60+int(start[3:])))%1440
 if end>=start or not 60<=length<=960:fail('Choose an overnight shift lasting 1 to 16 hours, with the end time on the next morning.')
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT 1 FROM attendance WHERE user_id=? AND clock_in IS NOT NULL AND clock_out IS NULL',(u['id'],)).fetchone():fail('Check out of the active shift before changing your schedule.',409)
  c.execute('INSERT INTO shift_settings(user_id,start_time,end_time) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET start_time=excluded.start_time,end_time=excluded.end_time',(u['id'],start,end))
  audit(c,u['id'],'Changed night-shift schedule','shift',u['id'],f'{start} - {end} IST')
  return shift_for(u['id'],c)

@app.get('/api/attendance/status')
def get_attendance_status(u=Depends(auth)):return attendance_status(u['id'])

def attendance_data(uid,period='week',end=None):
 shift=shift_for(uid);end=end or shift_date(now(),shift)-timedelta(days=1);start=end-timedelta(days=6 if period=='week' else 29)
 with db() as c:history=rows(c,'SELECT * FROM attendance WHERE user_id=? ORDER BY date DESC',(uid,))
 for r in history:
  if r['clock_in'] and not r['clock_out']:r['worked_seconds']=max(0,int((now()-datetime.fromisoformat(r['clock_in'])).total_seconds()))
  planned=int((datetime.fromisoformat(r['shift_end'])-datetime.fromisoformat(r['shift_start'])).total_seconds()) if r['shift_start'] and r['shift_end'] else shift['duration_seconds']
  r['overtime_seconds']=max(0,r['worked_seconds']-planned)
 mapped={r['date']:r for r in history};chart=[]
 for i in range((end-start).days+1):
  day=str(start+timedelta(days=i));chart.append(dict(mapped.get(day,{'date':day,'clock_in':None,'clock_out':None,'worked_seconds':0,'late_seconds':0,'off_seconds':0,'overtime_seconds':0,'note':''})))
 work=[r for r in chart if r['clock_in']]
 return {'chart':chart,'history':history,'period':period,'start':str(start),'end':str(end),'avg_work':round(sum(r['worked_seconds'] for r in work)/len(work)) if work else 0,'avg_late':round(sum(r['late_seconds'] for r in work)/len(work)) if work else 0,'avg_overtime':round(sum(r['overtime_seconds'] for r in work)/len(work)) if work else 0,'total_worked':sum(r['worked_seconds'] for r in work),'shift':shift}

@app.get('/api/attendance')
def attendance(period:str='week',end:date|None=None,u=Depends(auth)):
 if period not in ['week','month']:fail('Choose week or month.')
 return attendance_data(u['id'],period,end)

@app.get('/api/admin/attendance/{user_id}')
def admin_attendance(user_id:int,u=Depends(admin)):
 with db() as c:
  person=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
  if not person:fail('Employee account not found.',404)
  shift=shift_for(user_id,c)
  end=shift_date(now(),shift)-timedelta(days=1)
  start=end-timedelta(days=13)
  history=rows(c,'SELECT * FROM attendance WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date',(user_id,str(start),str(end)))
 return {'employee':public(dict(person)),'start':str(start),'end':str(end),'shift':shift,'records':history}

@app.patch('/api/admin/attendance/{user_id}')
def admin_update_attendance(user_id:int,b:dict=Body(...),u=Depends(admin)):
 day=parsedate(b.get('date'))
 shift=shift_for(user_id)
 end_day=shift_date(now(),shift)-timedelta(days=1)
 start_day=end_day-timedelta(days=13)
 if day<start_day or day>end_day:fail(f'Attendance can only be edited for the previous 14 completed shift dates ({start_day} to {end_day}).')
 status=b.get('status','present')
 if status not in {'present','off'}:fail('Status must be present or off.')
 note=text(b,'note',0,500)
 with db() as c:
  person=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
  if not person:fail('Employee account not found.',404)
  if status=='off':
   c.execute('INSERT INTO attendance(user_id,date,clock_in,clock_out,worked_seconds,late_seconds,off_seconds,note,shift_start,shift_end) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET clock_in=NULL,clock_out=NULL,worked_seconds=0,late_seconds=0,off_seconds=?,note=?,shift_start=?,shift_end=?',(user_id,str(day),None,None,0,0,int(shift['duration_seconds']),note,datetime.fromisoformat(f'{day}T{shift["start_time"]}').replace(tzinfo=IST).isoformat(),shift_window(day,shift)[1].isoformat(),int(shift['duration_seconds']),note,datetime.fromisoformat(f'{day}T{shift["start_time"]}').replace(tzinfo=IST).isoformat(),shift_window(day,shift)[1].isoformat()))
  else:
   cin=b.get('clock_in');cout=b.get('clock_out')
   if not isinstance(cin,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',cin):fail('Provide a valid check-in time.')
   if not isinstance(cout,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',cout):fail('Provide a valid check-out time.')
   tin=datetime.fromisoformat(f'{day}T{cin}').replace(tzinfo=IST)
   if shift['overnight'] and cin<=shift['end_time']:tin+=timedelta(days=1)
   tout=datetime.fromisoformat(f'{tin.date()}T{cout}').replace(tzinfo=IST)
   if tout<=tin:tout+=timedelta(days=1)
   if tout>now():fail('Attendance corrections cannot use future times.')
   worked=int((tout-tin).total_seconds())
   if worked>57600:fail('A shift cannot exceed 16 hours.')
   scheduled_start,scheduled_end=shift_window(day,shift)
   late=max(0,int((tin-scheduled_start).total_seconds()))
   c.execute('INSERT INTO attendance(user_id,date,clock_in,clock_out,worked_seconds,late_seconds,off_seconds,note,shift_start,shift_end) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET clock_in=?,clock_out=?,worked_seconds=?,late_seconds=?,off_seconds=0,note=?,shift_start=?,shift_end=?',(user_id,str(day),tin.isoformat(),tout.isoformat(),worked,late,0,note,scheduled_start.isoformat(),scheduled_end.isoformat(),tin.isoformat(),tout.isoformat(),worked,late,note,scheduled_start.isoformat(),scheduled_end.isoformat()))
  audit(c,u['id'],'Updated employee attendance','attendance',user_id,f'{person["employee_id"]} / {day} / {status}')
  record=dict(c.execute('SELECT * FROM attendance WHERE user_id=? AND date=?',(user_id,str(day))).fetchone())
 return {'ok':True,'record':record}


def attendance_action(uid,action,expected_id=None):
 t=now()
 with db() as c:
  c.execute('BEGIN IMMEDIATE');status=attendance_status(uid,c,t);r=status['today'];day=status['shift_date']
  if action=='toggle':action='check-out' if status['state']=='checked_in' else 'check-in'
  if action=='check-in':
   if status['state']=='checked_in':fail('You are already checked in. Use Check Out to end this shift.',409)
   if status['state']=='checked_out':fail('This shift is already complete. Use an attendance correction for changes.',409)
   late=max(0,int((t-datetime.fromisoformat(status['scheduled_start'])).total_seconds()))
   c.execute("INSERT INTO attendance(user_id,date,clock_in,late_seconds,shift_start,shift_end,note) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET clock_in=excluded.clock_in,clock_out=NULL,worked_seconds=0,late_seconds=excluded.late_seconds,off_seconds=0,shift_start=excluded.shift_start,shift_end=excluded.shift_end,note=excluded.note",(uid,day,t.isoformat(),late,status['scheduled_start'],status['scheduled_end'],'Night-shift check in'))
   message='Checked in'
  else:
   if status['state']!='checked_in':fail('There is no active check-in to check out of.',409)
   if expected_id is not None and expected_id!=r['id']:fail('The active shift changed. Refresh before checking out.',409)
   worked=max(0,int((t-datetime.fromisoformat(r['clock_in'])).total_seconds()))
   c.execute('UPDATE attendance SET clock_out=?,worked_seconds=?,note=? WHERE id=?',(t.isoformat(),worked,'Night shift completed',r['id']));message='Checked out'
  audit(c,uid,message,'attendance',detail=day)
  return {'message':message,'date':day,**attendance_status(uid,c,t)}

@app.post('/api/attendance/check-in')
def check_in(u=Depends(auth)):return attendance_action(u['id'],'check-in')

@app.post('/api/attendance/check-out')
def check_out(b:dict=Body(default={}),u=Depends(auth)):return attendance_action(u['id'],'check-out',b.get('attendance_id'))

@app.post('/api/attendance/punch')
def punch(u=Depends(auth)):
 """Legacy endpoint retained for existing local clients; new UI uses explicit actions."""
 result=attendance_action(u['id'],'toggle');result['message']=result['message'].replace('Checked','Punched');return result

@app.get('/api/attendance/export')
def export(u=Depends(auth)):
 with db() as c:data=rows(c,'SELECT date,clock_in,clock_out,worked_seconds,late_seconds,note FROM attendance WHERE user_id=? ORDER BY date',(u['id'],))
 out=io.StringIO(newline='');w=csv.writer(out);w.writerow(['Shift start date','Check in (IST)','Check out (IST)','Worked seconds','Late seconds','Note'])
 def safe(x):
  x='' if x is None else str(x);return "'"+x if x[:1] in ['=','+','-','@','\t','\r'] else x
 w.writerows([[safe(v) for v in r.values()] for r in data]);return Response('\ufeff'+out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="night-shift-attendance.csv"'})

def correction_times(d,uid):
 day=parsedate(d.get('date'));shift=shift_for(uid)
 if not all(isinstance(d.get(k),str) and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',d[k]) for k in ('clock_in','clock_out')):fail('Provide valid check-in and check-out times.')
 tin=datetime.fromisoformat(f'{day}T{d["clock_in"]}').replace(tzinfo=IST)
 if shift['overnight'] and d['clock_in']<=shift['end_time']:tin+=timedelta(days=1)
 tout=datetime.fromisoformat(f'{tin.date()}T{d["clock_out"]}').replace(tzinfo=IST)
 if tout<=tin:tout+=timedelta(days=1)
 if (tout-tin).total_seconds()>57600:fail('A corrected shift cannot exceed 16 hours.')
 if tout>now():fail('Attendance corrections cannot include future check-in or check-out times.')
 start,end=shift_window(day,shift)
 return day,tin,tout,start,end

@app.get('/api/leave-balances')
def balances(u=Depends(auth)):
 with db() as c:
  data=rows(c,'SELECT type,balance FROM leave_balances WHERE user_id=?',(u['id'],));pending={r['type']:r['days'] for r in rows(c,"SELECT type,SUM(days) days FROM leave_requests WHERE user_id=? AND status='Pending' GROUP BY type",(u['id'],))}
 for b in data:b['pending_days']=pending.get(b['type'],0)
 return sorted(data,key=lambda r:LEAVES.index(r['type']))
@app.get('/api/leaves')
def leaves(u=Depends(auth)):
 with db() as c:return rows(c,'SELECT * FROM leave_requests WHERE user_id=? ORDER BY id DESC',(u['id'],))
@app.post('/api/leaves',status_code=201)
def leave_create(b:dict=Body(...),u=Depends(auth)):
 kind=b.get('type');start=parsedate(b.get('start_date'));end=parsedate(b.get('end_date'));days=(end-start).days+1;reason=text(b,'reason',5,2000)
 if kind not in LEAVES or not 1<=days<=90:fail('Choose a leave type and a date range of 1-90 calendar days.')
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute("SELECT id FROM leave_requests WHERE user_id=? AND status IN ('Pending','Approved') AND start_date<=? AND end_date>=?",(u['id'],str(end),str(start))).fetchone():fail('An active request overlaps these dates.',409)
  bal=c.execute('SELECT balance FROM leave_balances WHERE user_id=? AND type=?',(u['id'],kind)).fetchone()[0];reserved=c.execute("SELECT COALESCE(SUM(days),0) FROM leave_requests WHERE user_id=? AND type=? AND status='Pending'",(u['id'],kind)).fetchone()[0]
  if bal is not None and days>bal-reserved:fail(f'Insufficient balance. {max(0,bal-reserved):g} day(s) available after pending requests.',409)
  r=c.execute('INSERT INTO leave_requests(user_id,type,start_date,end_date,days,reason,created_at) VALUES(?,?,?,?,?,?,?)',(u['id'],kind,str(start),str(end),days,reason,stamp()));ident=r.lastrowid;notify(c,u['id'],'Leave request submitted',kind,'time')
  manager_row=c.execute('SELECT manager_id FROM users WHERE id=?',(u['id'],)).fetchone()
  if manager_row and manager_row['manager_id']:
   notify(c,manager_row['manager_id'],'Leave request needs review',u['first_name']+': '+kind,'team')
  else:
   admin_row=c.execute("SELECT id FROM users WHERE role='admin' AND is_active=1 ORDER BY id LIMIT 1").fetchone()
   if admin_row: notify(c,admin_row['id'],'A leave request needs review',u['first_name']+': '+kind,'admin')
  audit(c,u['id'],'Submitted leave','leave',ident)
 return {'id':ident,'status':'Pending','days':days}
@app.delete('/api/leaves/{ident}')
def leave_cancel(ident:int,u=Depends(auth)):
 with db() as c:
  c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM leave_requests WHERE id=? AND user_id=?',(ident,u['id'])).fetchone()
  if not r:fail('Leave request not found.',404)
  if r['status'] not in ['Pending','Approved']:fail('Request is already closed.',409)
  if r['status']=='Approved':c.execute('UPDATE leave_balances SET balance=balance+? WHERE user_id=? AND type=? AND balance IS NOT NULL',(r['days'],u['id'],r['type']))
  c.execute("UPDATE leave_requests SET status='Cancelled' WHERE id=?",(ident,));audit(c,u['id'],'Cancelled leave','leave',ident)
 return {'ok':True}
@app.get('/api/tickets')
def tickets(u=Depends(auth)):
 with db() as c:return rows(c,'SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC',(u['id'],))
@app.post('/api/tickets',status_code=201)
def ticket_create(b:dict=Body(...),u=Depends(auth)):
 cat=b.get('category');priority=b.get('priority');title=text(b,'title',3,150);desc=text(b,'description',5)
 if cat not in ['IT Support','Colleague Services','Helpdesk'] or priority not in ['Low','Medium','High','Urgent']:fail('Choose a valid category and priority.')
 with db() as c:r=c.execute('INSERT INTO tickets(user_id,category,title,description,priority,created_at) VALUES(?,?,?,?,?,?)',(u['id'],cat,title,desc,priority,stamp()));ident=r.lastrowid;notify(c,u['id'],f'Ticket TKT-{ident:04d} created',title,'helpdesk');audit(c,u['id'],'Created support ticket','ticket',ident)
 return {'id':ident,'status':'Open'}
@app.get('/api/goals')
def goals(u=Depends(auth)):
 with db() as c:return rows(c,'SELECT * FROM goals WHERE user_id=? ORDER BY id DESC',(u['id'],))
@app.post('/api/goals',status_code=201)
def goal_create(b:dict=Body(...),u=Depends(auth)):
 title=text(b,'title',3,150);desc=text(b,'description',0,3000);target=parsedate(b.get('target_date'));progress=number(b.get('progress',0),0,100)
 if int(progress)!=progress:fail('Progress must be a whole number.')
 with db() as c:r=c.execute('INSERT INTO goals(user_id,title,description,target_date,progress,created_at) VALUES(?,?,?,?,?,?)',(u['id'],title,desc,str(target),int(progress),stamp()));ident=r.lastrowid;audit(c,u['id'],'Created goal','goal',ident)
 return {'id':ident}
@app.patch('/api/goals/{ident}')
def goal_update(ident:int,b:dict=Body(...),u=Depends(auth)):
 progress=number(b.get('progress'),0,100)
 if progress!=int(progress):fail('Progress must be a whole number.')
 with db() as c:
  r=c.execute('UPDATE goals SET progress=? WHERE id=? AND user_id=?',(int(progress),ident,u['id']))
  if not r.rowcount:fail('Goal not found.',404)
  audit(c,u['id'],'Updated goal progress','goal',ident,str(int(progress)))
 return {'ok':True}
@app.delete('/api/goals/{ident}')
def goal_delete(ident:int,u=Depends(auth)):
 with db() as c:
  r=c.execute('DELETE FROM goals WHERE id=? AND user_id=?',(ident,u['id']))
  if not r.rowcount:fail('Goal not found.',404)
  audit(c,u['id'],'Deleted goal','goal',ident)
 return {'ok':True}
@app.get('/api/requests')
def requests(kind:str='',u=Depends(auth)):
 with db() as c:data=rows(c,'SELECT * FROM requests WHERE user_id=?'+(' AND kind=?' if kind else '')+' ORDER BY id DESC',(u['id'],kind) if kind else (u['id'],))
 for r in data:r['details']=json.loads(r['details'])
 return data
@app.post('/api/requests',status_code=201)
def request_create(b:dict=Body(...),u=Depends(auth)):
 kind=b.get('kind');title=text(b,'title',3,150);d=b.get('details',{})
 if kind not in KINDS or not isinstance(d,dict) or len(json.dumps(d))>10000:fail('Invalid request type or details.')
 if kind=='expense':number(d.get('amount'),.01,1000000)
 if kind=='travel' and parsedate(d.get('end_date'))<parsedate(d.get('start_date')):fail('Travel end date must follow start date.')
 if kind=='regularization':correction_times(d,u['id'])
 with db() as c:
  r=c.execute('INSERT INTO requests(user_id,kind,title,details,created_at) VALUES(?,?,?,?,?)',(u['id'],kind,title,json.dumps(d),stamp()))
  ident=r.lastrowid
  notify(c,u['id'],'Request submitted',f'REQ-{ident:04d}: {title}','flows')
  if kind=='regularization':
   admins=rows(c,"SELECT id FROM users WHERE role='admin' AND is_active=1 AND id<>?",(u['id'],))
   for a in admins:
    notify(c,a['id'],'Attendance adjustment received',f'{u["first_name"]} {u["last_name"]} submitted REQ-{ident:04d} for attendance correction.','attendance-requests')
  audit(c,u['id'],'Submitted '+kind,'request',ident)
 return {'id':ident,'status':'Pending'}
@app.get('/api/jobs')
def jobs(q:str=Query('',max_length=100),u=Depends(auth)):
 with db() as c:return rows(c,'SELECT * FROM jobs WHERE title||department||location LIKE ? ORDER BY id',('%'+q+'%',))
@app.get('/api/posts')
def posts(u=Depends(auth)):
 with db() as c:return rows(c,'SELECT p.*,u.first_name,u.last_name,u.department FROM posts p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 100')
@app.post('/api/posts',status_code=201)
def post_create(b:dict=Body(...),u=Depends(auth)):
 value=text(b,'body',3,2000)
 with db() as c:r=c.execute('INSERT INTO posts(user_id,body,created_at) VALUES(?,?,?)',(u['id'],value,stamp()));audit(c,u['id'],'Posted to team feed','post',r.lastrowid)
 return {'ok':True}
@app.get('/api/notifications')
def notifications(u=Depends(auth)):
 with db() as c:return rows(c,'SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(u['id'],))
@app.post('/api/notifications/read')
def read_notifications(u=Depends(auth)):
 with db() as c:c.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(u['id'],))
 return {'ok':True}
@app.get('/api/dashboard')
def dashboard(u=Depends(auth)):
 with db() as c:
  status=attendance_status(u['id'],c);tasks=rows(c,"SELECT * FROM tasks WHERE user_id=? AND status='Pending' ORDER BY id",(u['id'],));unread=c.execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0',(u['id'],)).fetchone()[0];events=rows(c,"SELECT l.type,u.first_name,u.last_name FROM leave_requests l JOIN users u ON u.id=l.user_id WHERE status='Approved' AND start_date<=? AND end_date>=?",(str(now().date()),str(now().date())));count=c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
 return {'user':public(u),**status,'tasks':tasks,'unread':unread,'events':events,'jobs_count':count}
# Account provisioning and protected employee documents.
def manager_ids(c, root_id):
    return [r['id'] for r in c.execute("""
        WITH RECURSIVE team(id) AS (
            SELECT id FROM users WHERE manager_id=? AND is_active=1
            UNION ALL
            SELECT u.id FROM users u JOIN team t ON u.manager_id=t.id WHERE u.is_active=1
        ) SELECT id FROM team
    """, (root_id,)).fetchall()]

def manager(u=Depends(auth)):
    if u['role'] == 'admin':
        return u
    with db() as c:
        if not c.execute('SELECT 1 FROM users WHERE manager_id=? AND is_active=1 LIMIT 1',(u['id'],)).fetchone():
            fail('Manager access is required.',403)
    return u

@app.get('/api/manager/team')
def manager_team(u=Depends(manager)):
    with db() as c:
        ids=manager_ids(c,u['id'])
        if not ids:
            return {'manager':public(u),'reportees':[],'leaves':[],'attendance':[]}
        qmarks=','.join('?'*len(ids))
        reportees=rows(c,f"SELECT * FROM users WHERE id IN ({qmarks}) ORDER BY first_name,last_name",ids)
        leaves=rows(c,f"SELECT l.*,u.first_name,u.last_name,u.employee_id FROM leave_requests l JOIN users u ON u.id=l.user_id WHERE l.user_id IN ({qmarks}) ORDER BY CASE WHEN l.status='Pending' THEN 0 ELSE 1 END,l.id DESC",ids)
        attendance=rows(c,f"SELECT a.*,u.first_name,u.last_name,u.employee_id FROM attendance a JOIN users u ON u.id=a.user_id WHERE a.user_id IN ({qmarks}) ORDER BY a.date DESC,a.id DESC LIMIT 300",ids)
        return {'manager':public(u),'reportees':[public(x) for x in reportees],'leaves':leaves,'attendance':attendance}

@app.patch('/api/manager/leaves/{ident}')
def manager_review_leave(ident:int,b:dict=Body(...),u=Depends(manager)):
    status=str(b.get('status','')).strip(); note=text(b,'note',0,2000)
    if status not in {'Approved','Rejected'}: fail('Invalid leave review status.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        r=c.execute('SELECT * FROM leave_requests WHERE id=?',(ident,)).fetchone()
        if not r: fail('Leave request not found.',404)
        ids=manager_ids(c,u['id']) if u['role']!='admin' else []
        if u['role']!='admin' and r['user_id'] not in ids: fail('You can only review leave for your reportees.',403)
        if r['status']!='Pending': fail('This leave request has already been reviewed or cancelled.',409)
        if status=='Approved':
            bal=c.execute('SELECT balance FROM leave_balances WHERE user_id=? AND type=?',(r['user_id'],r['type'])).fetchone()[0]
            if bal is not None and bal<r['days']: fail('Insufficient balance.',409)
            c.execute('UPDATE leave_balances SET balance=balance-? WHERE user_id=? AND type=? AND balance IS NOT NULL',(r['days'],r['user_id'],r['type']))
        c.execute('UPDATE leave_requests SET status=?,review_note=?,reviewed_by=? WHERE id=?',(status,note,u['id'],ident))
        notify(c,r['user_id'],'Leave updated: '+status,note,'time');audit(c,u['id'],'Reviewed reportee leave','leave',ident,status)
    return {'ok':True}

@app.get('/api/admin/employees')
def employee_list(q:str=Query('',max_length=100),u=Depends(admin)):
    with db() as c:
        people=rows(c,"SELECT * FROM users WHERE first_name||' '||last_name||' '||employee_id||' '||email LIKE ? ORDER BY first_name",('%'+q+'%',))
        result=[]
        for person in people:
            item=public(person)
            item['document_count']=c.execute('SELECT COUNT(*) FROM employee_documents WHERE user_id=? AND archived_at IS NULL',(person['id'],)).fetchone()[0]
            result.append(item)
        return result

@app.post('/api/admin/employees',status_code=201)
def create_employee(b:dict=Body(...),u=Depends(admin)):
    temporary=secrets.token_urlsafe(18)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        person=provision(c,b,temporary,True)
        manager_id=b.get('manager_id')
        if manager_id not in ('',None):
            try: manager_id=int(manager_id)
            except (ValueError,TypeError): fail('Choose a valid reporting manager.')
            if manager_id==person['id']: fail('An employee cannot report to themselves.',409)
            manager_row=c.execute('SELECT id,role,is_active,first_name,last_name FROM users WHERE id=?',(manager_id,)).fetchone()
            if not manager_row or not manager_row['is_active'] or manager_row['role']!='employee': fail('Choose an active employee as the reporting manager.',409)
            manager_text=f"{manager_row['first_name']} {manager_row['last_name']}"
            c.execute('UPDATE users SET manager=?,manager_id=? WHERE id=?',(manager_text,manager_id,person['id']))
            person=dict(c.execute('SELECT * FROM users WHERE id=?',(person['id'],)).fetchone())
        audit(c,u['id'],'Created account','user',person['id'],person['employee_id'])
    return {'user':public(person),'temporary_password':temporary}

@app.patch('/api/admin/employees/{ident}')
def edit_employee(ident:int,b:dict=Body(...),u=Depends(admin)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        person=c.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
        if not person:fail('Account not found.',404)
        updated={**dict(person),**b}
        first=text(updated,'first_name',1,60);last=text(updated,'last_name',0,60);email=valid_email(updated)
        role=updated.get('role');active=b.get('is_active',bool(person['is_active']))
        if role not in {'employee','admin'} or type(active)!=bool:fail('Invalid role or account status.')
        if ident==u['id'] and (not active or role!='admin'):fail('You cannot disable or demote your own administrator account.',409)
        if person['role']=='admin' and person['is_active'] and (not active or role!='admin'):
            if c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]<=1:
                fail('At least one active administrator is required.',409)
        manager_id=updated.get('manager_id')
        manager_text=text(updated,'manager',0,100)
        if manager_id in ('',None): manager_id=None
        else:
            try: manager_id=int(manager_id)
            except (ValueError,TypeError): fail('Choose a valid reporting manager.')
            if manager_id==ident: fail('An employee cannot report to themselves.',409)
            manager_row=c.execute('SELECT id,role,is_active,first_name,last_name,employee_id FROM users WHERE id=?',(manager_id,)).fetchone()
            if not manager_row or not manager_row['is_active'] or manager_row['role']!='employee':
                fail('Choose an active employee as the reporting manager.',409)
            # Prevent circular reporting chains.
            seen={ident}; cur=manager_id
            while cur is not None:
                if cur in seen: fail('That reporting relationship would create a reporting loop.',409)
                seen.add(cur)
                nxt=c.execute('SELECT manager_id FROM users WHERE id=?',(cur,)).fetchone()
                cur=nxt['manager_id'] if nxt else None
            manager_text=f"{manager_row['first_name']} {manager_row['last_name']}"
        vals=[first,last,email,role,int(active),text(updated,'designation',0,100),
              text(updated,'department',0,100),text(updated,'location',0,100),
              text(updated,'phone',0,24),manager_text if manager_id else '',manager_id,ident]
        try:c.execute('UPDATE users SET first_name=?,last_name=?,email=?,role=?,is_active=?,designation=?,department=?,location=?,phone=?,manager=?,manager_id=? WHERE id=?',vals)
        except sqlite3.IntegrityError:fail('This email address is already in use.',409)
        if not active or role!=person['role']:c.execute('DELETE FROM sessions WHERE user_id=?',(ident,))
        audit(c,u['id'],'Updated account','user',ident,'Active' if active else 'Disabled')
        return public(dict(c.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()))

@app.post('/api/admin/employees/{ident}/reset-password')
def reset_password(ident:int,u=Depends(admin)):
    if ident==u['id']:fail('Use Change password for your own account.',409)
    temporary=secrets.token_urlsafe(18)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM users WHERE id=?',(ident,)).fetchone():fail('Account not found.',404)
        c.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?',(hashpass(temporary),ident))
        c.execute('DELETE FROM sessions WHERE user_id=?',(ident,))
        audit(c,u['id'],'Reset account password','user',ident)
    return {'temporary_password':temporary,'must_change_password':True}

@app.get('/api/admin/employees/{ident}/leave-balances')
def read_employee_balances(ident:int,u=Depends(admin)):
    with db() as c:
        if not c.execute('SELECT 1 FROM users WHERE id=?',(ident,)).fetchone():fail('Account not found.',404)
        return rows(c,'SELECT type,balance FROM leave_balances WHERE user_id=?',(ident,))

@app.patch('/api/admin/employees/{ident}/leave-balances')
def set_employee_balances(ident:int,b:dict=Body(...),u=Depends(admin)):
    values=b.get('balances')
    if not isinstance(values,dict) or set(values)!={k for k in LEAVES if k not in {'Unpaid','Sabbatical Leave'}}:
        fail('Provide each of the five paid-leave balances.')
    validated={k:number(v,0,366) for k,v in values.items()}
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM users WHERE id=?',(ident,)).fetchone():fail('Account not found.',404)
        for kind,value in validated.items():
            pending=c.execute("SELECT COALESCE(SUM(days),0) FROM leave_requests WHERE user_id=? AND type=? AND status='Pending'",(ident,kind)).fetchone()[0]
            if value<pending:fail(f'{kind}: balance cannot be below {pending:g} pending day(s).',409)
            c.execute('UPDATE leave_balances SET balance=? WHERE user_id=? AND type=?',(value,ident,kind))
        audit(c,u['id'],'Allocated leave balances','user',ident,json.dumps(validated))
    return {'ok':True}

DOCUMENT_SELECT='''SELECT d.id,d.user_id,d.kind,d.title,d.pay_period,d.issue_date,
 d.original_name,d.byte_size,d.created_at,d.archived_at,
 p.employee_id,p.first_name,p.last_name,
 a.first_name||' '||a.last_name AS uploaded_by_name
 FROM employee_documents d JOIN users p ON p.id=d.user_id
 JOIN users a ON a.id=d.uploaded_by'''

@app.get('/api/documents')
def my_documents(kind:str='',u=Depends(auth)):
    if kind and kind not in {'payslip','offer_letter'}:fail('Invalid document type.')
    with db() as c:
        return rows(c,DOCUMENT_SELECT+' WHERE d.user_id=? AND d.archived_at IS NULL'+(' AND d.kind=?' if kind else '')+' ORDER BY COALESCE(d.pay_period,d.issue_date) DESC,d.id DESC',
                    (u['id'],kind) if kind else (u['id'],))

@app.get('/api/admin/documents')
def all_documents(user_id:int=0,kind:str='',include_archived:bool=False,u=Depends(admin)):
    if kind and kind not in {'payslip','offer_letter'}:fail('Invalid document type.')
    where=[];args=[]
    if user_id:where.append('d.user_id=?');args.append(user_id)
    if kind:where.append('d.kind=?');args.append(kind)
    if not include_archived:where.append('d.archived_at IS NULL')
    with db() as c:
        return rows(c,DOCUMENT_SELECT+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY d.id DESC',args)

@app.post('/api/admin/documents',status_code=201)
async def upload_document(request:Request,u=Depends(admin)):
    # Authenticate/authorize before multipart parsing. Never save uploads under /static.
    partial=None;destination=None
    try:
        async with request.form(max_files=1,max_fields=6,max_part_size=8192) as form:
            uploaded=form.get('file')
            if not isinstance(uploaded,UploadFile):fail('Select a PDF document.')
            try:uid=int(form.get('user_id',''))
            except (ValueError,TypeError):fail('Choose an employee.')
            kind=form.get('kind')
            if kind not in {'payslip','offer_letter'}:fail('Choose Payslip or Offer letter.')
            title=text({'title':form.get('title','')},'title',3,150)
            period=str(form.get('pay_period','')) if kind=='payslip' else None
            if kind=='payslip' and not re.fullmatch(r'20[2-9][0-9]-(?:0[1-9]|1[0-2])',period):
                fail('Select a payslip month between 2020 and 2099.')
            issue=str(parsedate(form.get('issue_date')))
            filename=uploaded.filename or ''
            if not 5<=len(filename)<=120 or any(x in filename for x in ('/','\\','\x00')) or any(ord(x)<32 for x in filename):
                fail('Use a filename of at most 120 characters with no path or control characters.')
            if not filename.lower().endswith('.pdf'):fail('Only PDF documents are accepted.')
            with db() as c:
                person=c.execute('SELECT id,is_active FROM users WHERE id=?',(uid,)).fetchone()
                if not person or not person['is_active']:fail('Choose an active employee account.')
            if uploaded.size is not None and uploaded.size>MAX_DOCUMENT_BYTES:
                fail('The document exceeds the 10 MB limit.',413)
            storage=secrets.token_hex(24)+'.pdf'
            directory=DATA/'documents';directory.mkdir(exist_ok=True)
            partial=directory/(storage+'.part');destination=directory/storage
            size=0;head=b'';tail=b'';digest=hashlib.sha256()
            with partial.open('xb') as output:
                while True:
                    chunk=await uploaded.read(65536)
                    if not chunk:break
                    size+=len(chunk)
                    if size>MAX_DOCUMENT_BYTES:fail('The document exceeds the 10 MB limit.',413)
                    if len(head)<8:head=(head+chunk)[:8]
                    tail=(tail+chunk)[-4096:];digest.update(chunk);output.write(chunk)
                output.flush();os.fsync(output.fileno())
            if size<16 or not re.match(rb'%PDF-[12]\.[0-9]',head) or b'%%EOF' not in tail:
                fail('The file does not look like a complete PDF. Export it as PDF and try again.')
            try:partial.chmod(0o600)
            except OSError:pass
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                person=c.execute('SELECT is_active FROM users WHERE id=?',(uid,)).fetchone()
                if not person or not person['is_active']:fail('The selected account is no longer active.',409)
                try:
                    r=c.execute('INSERT INTO employee_documents(user_id,kind,title,pay_period,issue_date,original_name,storage_name,byte_size,sha256,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (uid,kind,title,period,issue,filename,storage,size,digest.hexdigest(),u['id'],stamp()))
                except sqlite3.IntegrityError:
                    fail('An active document already exists for this employee and month/type. Archive it before uploading a replacement.',409)
                partial.replace(destination)
                notify(c,uid,'Payslip available' if kind=='payslip' else 'Offer letter available',title,'payslips' if kind=='payslip' else 'documents')
                audit(c,u['id'],'Uploaded '+kind,'document',r.lastrowid,f'Employee {uid}; {size} bytes')
                ident=r.lastrowid
            return {'id':ident,'message':'Document uploaded and assigned to the employee.'}
    except Exception:
        if partial:partial.unlink(missing_ok=True)
        if destination:destination.unlink(missing_ok=True)
        raise

@app.post('/api/admin/documents/{ident}/archive')
def archive_document(ident:int,u=Depends(admin)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        document=c.execute('SELECT * FROM employee_documents WHERE id=?',(ident,)).fetchone()
        if not document:fail('Document not found.',404)
        if document['archived_at']:fail('This document is already archived.',409)
        c.execute('UPDATE employee_documents SET archived_at=?,archived_by=? WHERE id=?',(stamp(),u['id'],ident))
        audit(c,u['id'],'Archived document','document',ident)
        notify(c,document['user_id'],'Document withdrawn',document['title'],'documents')
    return {'ok':True}

@app.get('/api/documents/{ident}/download')
def download_document(ident:int,u=Depends(auth)):
    with db() as c:
        document=c.execute('SELECT * FROM employee_documents WHERE id=?',(ident,)).fetchone()
        if not document or (u['role']!='admin' and (document['user_id']!=u['id'] or document['archived_at'])):
            fail('Document not found.',404)
        if not re.fullmatch(r'[0-9a-f]{48}\.pdf',document['storage_name']):fail('Document storage is unavailable.',404)
        path=DATA/'documents'/document['storage_name']
        if not path.is_file():fail('Document file is unavailable. Contact your administrator.',404)
        audit(c,u['id'],'Downloaded document','document',ident)
    return FileResponse(path,media_type='application/pdf',filename=document['original_name'],
                        content_disposition_type='attachment',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@app.get('/api/admin/overview')
def overview(u=Depends(admin)):
 result={}
 with db() as c:
  for name,table in [('leaves','leave_requests'),('tickets','tickets'),('requests','requests')]:result[name]=rows(c,f'SELECT t.*,u.first_name,u.last_name,u.employee_id FROM {table} t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC')
  result['audit']=rows(c,'SELECT a.*,u.first_name,u.last_name FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100')
 for r in result['requests']:r['details']=json.loads(r['details'])
 return result
@app.patch('/api/admin/{kind}/{ident}')
def review(kind:str,ident:int,b:dict=Body(...),u=Depends(admin)):
 tables={'leaves':'leave_requests','tickets':'tickets','requests':'requests'}
 if kind not in tables:fail('Unknown review category.',404)
 status=str(b.get('status','')).strip();note=text(b,'note',0,2000)
 if status not in (['Open','In progress','Resolved'] if kind=='tickets' else ['Approved','Rejected']):fail('Invalid review status.')
 with db() as c:
  c.execute('BEGIN IMMEDIATE');r=c.execute(f'SELECT * FROM {tables[kind]} WHERE id=?',(ident,)).fetchone()
  if not r:fail('Request not found.',404)
  if kind!='tickets' and r['user_id']==u['id']:fail('You cannot review your own request.',403)
  if kind!='tickets' and r['status']!='Pending':fail('This request has already been reviewed or cancelled.',409)
  if kind=='leaves':
   if status=='Approved':
    bal=c.execute('SELECT balance FROM leave_balances WHERE user_id=? AND type=?',(r['user_id'],r['type'])).fetchone()[0]
    if bal is not None and bal<r['days']:fail('Insufficient balance.',409)
    c.execute('UPDATE leave_balances SET balance=balance-? WHERE user_id=? AND type=? AND balance IS NOT NULL',(r['days'],r['user_id'],r['type']))
   c.execute('UPDATE leave_requests SET status=?,review_note=?,reviewed_by=? WHERE id=?',(status,note,u['id'],ident))
  else:
   if kind=='requests' and r['kind']=='regularization' and status=='Approved':
    d=json.loads(r['details']);day,tin,tout,start,end=correction_times(d,r['user_id']);late=max(0,int((tin-start).total_seconds()))
    active=c.execute('SELECT 1 FROM attendance WHERE user_id=? AND date=? AND clock_in IS NOT NULL AND clock_out IS NULL',(r['user_id'],str(day))).fetchone()
    if active:fail('Check out of the active shift before approving a correction for it.',409)
    c.execute('INSERT INTO attendance(user_id,date,clock_in,clock_out,worked_seconds,late_seconds,note,shift_start,shift_end) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET clock_in=excluded.clock_in,clock_out=excluded.clock_out,worked_seconds=excluded.worked_seconds,late_seconds=excluded.late_seconds,off_seconds=0,note=excluded.note,shift_start=excluded.shift_start,shift_end=excluded.shift_end',(r['user_id'],str(day),tin.isoformat(),tout.isoformat(),int((tout-tin).total_seconds()),late,'Admin-approved overnight correction',start.isoformat(),end.isoformat()))
   c.execute(f'UPDATE {tables[kind]} SET status=?,admin_note=? WHERE id=?',(status,note,ident))
  notify(c,r['user_id'],kind.capitalize()+' updated: '+status,note,'time' if kind=='leaves' else 'helpdesk' if kind=='tickets' else 'flows');audit(c,u['id'],'Reviewed '+kind,kind,ident,status)
 return {'ok':True}
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.get('/',include_in_schema=False)
def index():return FileResponse(ROOT/'static/index.html',headers={'Cache-Control':'no-cache'})
if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Colleague Workspace - employee and administrator portal')
 parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=int(os.environ.get('PORTAL_PORT','8000')));parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
 if args.host not in ['127.0.0.1','localhost','::1'] and os.environ.get('PORTAL_ALLOW_NETWORK')!='1':parser.error('Local-only by default. Read README.md before setting PORTAL_ALLOW_NETWORK=1.')
 if not args.no_browser:threading.Timer(1.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
 import uvicorn
 print('COLLEAGUE WORKSPACE - employee and administrator portal.');uvicorn.run(app,host=args.host,port=args.port,access_log=False)
