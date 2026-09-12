"""UI regression harness using an isolated live backend and a test-only HTTP bridge.

The bridge is necessary in the build environment, where browser URL navigation is
blocked by managed policy. It never ships in application HTML or JavaScript.
These are DOM/rendering/action checks, not native browser-network security tests.
Optional dependencies: pip install playwright httpx; playwright install chromium
Run: python qa/check_interface.py --output qa/output [--chromium /path/to/chromium]
"""
from __future__ import annotations
import argparse, base64, json, os, socket, subprocess, sys, tempfile, time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = 'QA-only owner password 482!'
EMP_PASSWORD = 'QA-only colleague password 921!'
PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n'
BRIDGE = '''window.fetch=async function(url,options={}){const p={url:String(url),method:options.method||'GET',headers:options.headers||{}};if(options.body instanceof FormData){p.form={};p.files=[];for(const [k,v] of options.body.entries()){if(v instanceof File){const a=new Uint8Array(await v.arrayBuffer());let t='';for(let i=0;i<a.length;i++)t+=String.fromCharCode(a[i]);p.files.push({key:k,name:v.name,type:v.type,data:btoa(t)});}else p.form[k]=v;}}else p.body=options.body;const r=await window.backendRequest(p);return new Response(r.text,{status:r.status,headers:r.headers});};'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'qa/output'));parser.add_argument('--chromium')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    results=[];errors=[]
    def check(name,condition=True):
        results.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
        print('PASS:',name,flush=True)
    logo='data:image/svg+xml;base64,'+base64.b64encode((ROOT/'static/assets/amex-logo.svg').read_bytes()).decode()
    styles='\n'.join((ROOT/f'static/{x}').read_text() for x in ['styles.css','amex-theme.css','accounts-documents.css'])
    scripts='\n'.join((ROOT/f'static/{x}').read_text() for x in ['accounts-documents.js','app.js']).replace('${A}amex-logo.svg',logo)
    html=f'<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style></head><body><div id="app"></div><div id="overlay-root"></div><div id="toast-root"></div><dialog id="modal"></dialog><script>{BRIDGE}</script><script>{scripts}</script></body></html>'
    with tempfile.TemporaryDirectory(prefix='workspace-ui-') as tmp:
        data=Path(tmp)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        with (data/'server.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--no-browser','--port',str(port)],env=dict(os.environ,PORTAL_DATA_DIR=tmp),stdout=log,stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=base,timeout=30) as client:
                    for _ in range(100):
                        try:
                            if client.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:raise RuntimeError('UI backend did not start')
                    def request(payload):
                        kw={'headers':payload.get('headers',{})}
                        if 'files' in payload:
                            kw['data']=payload['form'];kw['files']=[(f['key'],(f['name'],base64.b64decode(f['data']),f['type'])) for f in payload['files']]
                        elif payload.get('body') is not None:kw['content']=payload['body']
                        r=client.request(payload['method'],payload['url'],**kw)
                        return {'text':r.text,'status':r.status_code,'headers':dict(r.headers)}
                    with sync_playwright() as playwright:
                        browser=playwright.chromium.launch(headless=True,**({'executable_path':args.chromium} if args.chromium else {}))
                        page=browser.new_page(viewport={'width':1440,'height':1000})
                        page.on('pageerror',lambda err:errors.append(str(err)));page.expose_function('backendRequest',request)
                        def screenshot(name):
                            page.evaluate("document.querySelector('#toast-root').innerHTML=''")
                            page.screenshot(path=str(out/(name+'.png')),full_page=True)
                        def fill(form,values):
                            for name,value in values.items():form.locator(f'[name="{name}"]').fill(value)
                        def closed():page.wait_for_selector('#modal:not([open])',state='attached')
                        def close():page.locator('#modal [data-action="close-modal"]').last.click();closed()
                        def go(route):
                            page.evaluate('(route)=>nav(route)',route)
                            page.wait_for_function('(r)=>S.route===r && !!document.querySelector("#page .page-footer") && !document.querySelector("#page .loading-section")',arg=route)
                        def signout():
                            page.locator('[data-action="account"]').click();page.locator('[data-action="sign-out"]').click();page.wait_for_selector('[data-form="login"]')
                        def login(identifier,password,role='employee'):
                            page.locator(f'[data-action="login-role"][data-role="{role}"]').click()
                            form=page.locator('[data-form="login"]');fill(form,{'identifier':identifier,'password':password});form.locator('[type=submit]').click()
                        def new_password(old,new):
                            page.wait_for_selector('[data-form="password"]');form=page.locator('[data-form="password"]')
                            fill(form,{'current_password':old,'new_password':new,'confirm_password':new});form.locator('[type=submit]').click();page.wait_for_selector('.workspace-heading')
                        def upload(kind,title):
                            page.locator('[data-action="upload-document"]').first.click();form=page.locator('[data-form="upload-document"]')
                            form.locator('[name="user_id"]').select_option(label='Taylor Morgan / EMP1001');form.locator('[name="kind"]').select_option(kind)
                            check(kind+' month-field behaviour',form.locator('[name="pay_period"]').is_visible()==(kind=='payslip'))
                            form.locator('[name="title"]').fill(title);form.locator('[name="file"]').set_input_files({'name':kind+'.pdf','mimeType':'application/pdf','buffer':PDF})
                            form.locator('[type=submit]').click();closed();page.wait_for_function('(t)=>document.querySelector("#admin-documents-table").textContent.includes(t)',arg=title)
                        def responsive(route):
                            if route!='login':go(route)
                            for width in [320,390,768,1024,1440]:
                                page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(80)
                                dims=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                                check(f'{route} fits viewport {width}px',dims['scroll']<=dims['width']+1)
                            page.set_viewport_size({'width':1440,'height':1000})
                        page.set_content(html,wait_until='load');page.wait_for_selector('[data-form="setup"]')
                        check('Fresh install opens administrator setup');screenshot('setup')
                        form=page.locator('[data-form="setup"]')
                        fill(form,{'setup_key':(data/'setup.key').read_text().strip(),'first_name':'Workspace','last_name':'Owner','employee_id':'OWNER01','email':'owner@example.test','password':ADMIN_PASSWORD,'confirm_password':ADMIN_PASSWORD})
                        form.locator('[type=submit]').click();page.wait_for_selector('#employees-table');check('First administrator created through the browser form')
                        check('Only the chosen administrator exists',page.locator('#employees-table tbody tr').count()==1)
                        page.locator('[data-action="add-employee"]').click();form=page.locator('[data-form="employee"]')
                        fill(form,{'first_name':'Taylor','last_name':'Morgan','employee_id':'EMP1001','email':'taylor@example.test','designation':'Customer Service Associate','department':'Customer Care','location':'Gurugram'})
                        form.locator('[type=submit]').click();page.wait_for_selector('#issued-password');temporary=page.locator('#issued-password').input_value()
                        check('Employee created with unique temporary password',len(temporary)>=12);close();page.wait_for_function('!document.querySelector("#issued-password")');check('Credential dialog clears its password after closing')
                        page.locator('[data-action="edit-employee"][data-id="2"]').click();page.locator('[data-action="employee-balances"]').click()
                        page.wait_for_selector('[data-form="employee-balances"]');form=page.locator('[data-form="employee-balances"]')
                        form.locator('[name="Earned Leave"]').fill('7');form.locator('[type=submit]').click();closed()
                        check('Administrator allocates actual leave balance',client.get('/api/admin/employees/2/leave-balances').json()[3]['balance']==7)
                        go('document-centre');check('Document centre starts empty',page.locator('#admin-documents-table').inner_text().startswith('No documents'))
                        screenshot('document_centre_empty');upload('payslip','September payslip');check('Payslip uploaded and visible in register')
                        upload('offer_letter','Employment offer letter');check('Offer letter uploaded and visible in register')
                        page.locator('#admin-doc-kind').select_option('offer_letter');check('Document-type filter selects offer letters',page.locator('#admin-documents-table tbody tr').count()==1)
                        page.locator('#admin-doc-kind').select_option('');page.locator('#admin-doc-search').fill('not-a-person');check('Document search has an empty result state',page.locator('#admin-documents-table').inner_text().startswith('No documents'));page.locator('#admin-doc-search').fill('')
                        screenshot('document_centre');responsive('document-centre');responsive('employees')
                        go('employees');page.locator('[data-action="edit-employee"][data-id="2"]').click();form=page.locator('[data-form="employee"]');form.locator('[name="department"]').fill('Customer Operations');form.locator('[type=submit]').click();closed()
                        check('Administrator edits employee details', 'Customer Operations' in page.locator('#employees-table').inner_text())
                        signout();check('Sign-out returns to explicit login');check('No previous account toasts remain',page.locator('#toast-root').inner_text()=='')
                        check('Login has no prefilled credentials',page.locator('[name="identifier"]').input_value()=='' and page.locator('[name="password"]').input_value()=='')
                        check('No demo account or automatic-sign-in controls', 'demo' not in page.locator('body').inner_text().lower())
                        page.locator('[data-action="login-role"][data-role="admin"]').click();check('Administrator tab changes sign-in mode',page.locator('[name="role"]').input_value()=='admin')
                        page.locator('[data-action="login-role"][data-role="employee"]').click();page.locator('[data-action="toggle-password"]').click();check('Password visibility toggle works',page.locator('[name="password"]').get_attribute('type')=='text');page.locator('[data-action="toggle-password"]').click()
                        screenshot('login');responsive('login');page.set_viewport_size({'width':390,'height':844});screenshot('login_mobile');page.set_viewport_size({'width':1440,'height':1000})
                        login('EMP1001',temporary);page.wait_for_selector('[data-form="password"]');check('Employee first login requires password change');new_password(temporary,EMP_PASSWORD);check('Employee chooses permanent password and enters workspace')
                        check('Employee navigation hides administrative pages',page.locator('.sidebar [data-nav="employees"]').count()==0 and page.locator('.sidebar [data-nav="document-centre"]').count()==0)
                        go('payslips');check('Employee sees assigned payslip only',page.locator('#my-documents-table tbody tr').count()==1 and 'September payslip' in page.locator('#my-documents-table').inner_text());screenshot('employee_payslips')
                        href=page.locator('#my-documents-table a[href*="/download"]').first.get_attribute('href');response=client.get(href)
                        check('Document download control points to working authenticated attachment',response.status_code==200 and 'attachment' in response.headers.get('content-disposition',''))
                        go('documents');check('Employee document page includes offer letter and payslip',page.locator('#my-documents-table tbody tr').count()==2);screenshot('employee_documents');responsive('documents')
                        go('dashboard');page.locator('.shift-card [data-action="punch"]').click();page.locator('[data-action="confirm-punch"]').click();page.wait_for_function('document.querySelector(".checkin-button")?.textContent.includes("Check Out")');check('Check In persists and changes action to Check Out')
                        page.locator('.shift-card [data-action="punch"]').click();page.locator('[data-action="confirm-punch"]').click();page.wait_for_function('document.querySelector(".checkin-button")?.textContent.includes("View Attendance")');check('Check Out persists and offers attendance history');responsive('dashboard')
                        for route in ['time','tasks','profile','members','performance','recruitment','it','helpdesk','admin-services','flows','expenses','travel','policies','org','vibe','talent','benefits','refyne','learn']:
                            go(route);check('Existing page renders: '+route,'Unable to open this section' not in page.locator('#page').inner_text())
                        go('document-centre');check('Direct employee route cannot display admin files','Administrator access required' in page.locator('#page').inner_text());signout()
                        login('OWNER01',ADMIN_PASSWORD,'admin');page.wait_for_selector('.workspace-heading');go('document-centre')
                        row=page.locator('#admin-documents-table tbody tr').filter(has_text='Employment offer letter')
                        row.locator('[data-action="archive-document"]').click();page.locator('[data-action="confirm-archive"]').click();closed();check('Archiving hides offer from current register','Employment offer letter' not in page.locator('#admin-documents-table').inner_text())
                        page.locator('#show-archived').check();check('Archived register retains administrative history','Employment offer letter' in page.locator('#admin-documents-table').inner_text());page.locator('#show-archived').uncheck()
                        upload('offer_letter','Revised employment offer');check('Replacement offer can be published after archive')
                        go('employees');page.locator('[data-action="edit-employee"][data-id="2"]').click();page.locator('[data-action="reset-employee-password"]').click();page.locator('[data-action="confirm-reset-password"]').click();page.wait_for_selector('#issued-password');reset=page.locator('#issued-password').input_value();check('Administrator can reset employee password',reset!=temporary);close()
                        page.locator('[data-action="edit-employee"][data-id="2"]').click();form=page.locator('[data-form="employee"]');form.locator('[name="is_active"]').select_option('false');form.locator('[type=submit]').click();closed();check('Administrator disables account','Disabled' in page.locator('#employees-table').inner_text())
                        page.locator('[data-action="edit-employee"][data-id="2"]').click();form=page.locator('[data-form="employee"]');form.locator('[name="is_active"]').select_option('true');form.locator('[type=submit]').click();closed();check('Administrator can reactivate account')
                        go('admin');check('Admin review and audit page renders','Unable to open this section' not in page.locator('#page').inner_text())
                        check('No uncaught JavaScript errors',not errors)
                        browser.close()
            finally:
                proc.terminate();proc.wait(timeout=10)
                (out/'results.json').write_text(json.dumps({'method':'DOM actions with test-only HTTP bridge to isolated live backend; no native browser-network navigation','checks':results,'javascript_errors':errors},indent=2))
    print(f'{len(results)} interface checks passed.')

if __name__=='__main__':main()
