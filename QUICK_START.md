# Start your employee portal
## Version 3 - accounts, payslips and offer letters

**Use this new ZIP in a separate folder. Stop the old server first.** This version starts with no pre-created accounts, no automatic login and no sample employee records. You choose your own administrator account.

## 1. Start the application

You need Python 3.10 or newer, Chrome or Edge, and internet access for the first package installation. No Docker, Node.js or separate database installation is needed.

Extract the complete ZIP. Open the **American_Express_Employee_Portal** folder and double-click **START_WINDOWS.bat**. The launcher creates `.venv`, installs the required packages, and opens:

```text
http://127.0.0.1:8000
```

Keep the terminal window open. It is running the backend. Press **Ctrl+C** in that window when you want to stop the application.

When port 8000 is occupied, open PowerShell in the application folder and run:

```powershell
.\START_WINDOWS.bat 8001
```

Then use `http://127.0.0.1:8001`. The launcher handles the missing `.venv` step automatically; you do not have to activate the environment.

## 2. Create your administrator - first run only

The first browser page is **Create your administrator**. In the server terminal, find:

```text
Your one-time setup key: ...
```

Copy the actual key into the first field in the browser. Fill in your name, your chosen administrator ID and email address, and a password of at least 12 characters. Confirm the password and create the account.

The setup key stops working after successful setup. There is **no default administrator password**. Use a password chosen specifically for this independent workspace, not a company single-sign-on password. Keep your account credentials private.

After setup, opening the application without an active session displays **Employee / Administrator sign-in**. An existing authenticated session can remain signed in for up to 16 hours; use Sign out on a shared computer.

## 3. Add employees

Sign in as **Administrator**, then open **Employee Accounts -> Add employee**. Enter the employee's name, employee ID, email and other details, leave the access role as **Employee**, and choose **Create account**.

A unique temporary password appears once. Copy it and share it privately with that employee. It is not emailed automatically, and the administrator cannot retrieve it later. A replacement can be generated using **Manage -> Reset password**.

Paid-leave balances start at zero. To allocate a balance, use **Employee Accounts -> Manage -> Allocate leave**. Enter the balances approved for your organization; this application does not provide employer leave policies.

## 4. Upload a payslip or offer letter

Open **Document Centre -> Upload document**.

Choose the employee and document type. For a payslip, choose the salary month. For an offer letter, no salary month is required. Enter the title and issue date, choose a **PDF up to 10 MB**, then select **Upload & publish**.

The document is immediately listed in that employee's account. Only that employee and administrators can download it through the application.

One current payslip per employee per month and one current offer letter per employee are supported. To replace a published document, **archive the old file first**, then upload the replacement. Archived files remain available to administrators but are removed from employee access.

This is an upload-and-delivery system. It does not calculate salaries, generate payslips, sign offer letters or verify a document's authenticity.

## 5. Employee sign-in

Sign out from the account menu. Select the **Employee** tab and enter the assigned employee ID or email address and temporary password. The employee must choose a new password before opening their workspace.

**My Payslips** contains the monthly payslips. **My Documents** contains offer letters and payslips. Use the Download button beside a document.

**Check In / Check Out** still records the night shift. The initial schedule is 8:30 PM to 4:30 AM the following morning, in IST. Hours are editable under Time & Attendance. A check-in before midnight and checkout after midnight remain one record.

## Your data and the old version

The new application creates:

```text
American_Express_Employee_Portal/
  data/
    workspace.db
    documents/
```

Back up the entire `data` folder with the server stopped. Do not delete it when updating code. Documents are stored in `documents`, while accounts and document ownership are stored in `workspace.db`; you need both.

The earlier version's `data/portal.db` is **not imported**. Keep the old project as a backup. Copying that old database into this folder will not migrate its records. The old default accounts do not work in the new workspace.

## Problems and recovery

**Python not found:** install Python 3.10 or newer, enable the installer's PATH option, reopen the terminal and run the launcher again.

**Missing `.venv\Scripts\python.exe`:** run `START_WINDOWS.bat` from the extracted folder; it creates the environment before launching. An old or broken `.venv` can be renamed to `.venv_old` while the server is stopped. Never rename or delete `data` for this fix.

**Forgot administrator password:** stop the server, then double-click **RESET_PASSWORD_WINDOWS.bat**. Enter the account ID/email and choose a new password. Password entry is hidden. This local recovery tool requires access to the server files and invalidates the account's previous sessions. It does not enable a disabled account.

**PDF upload rejected:** confirm the file is a PDF no larger than 10 MB. For a duplicate month or existing offer letter, archive the old document first. The file must have a PDF signature and end marker; renaming another format to `.pdf` will not convert it.

**Page does not open:** keep the terminal running, inspect the first error, and enter the exact local address shown there. Do not open `static/index.html` directly.

## Before real employee use

This is independent software, not an official American Express portal or a company integration. The branding does not imply authorization. The default address works only on the server computer.

Do not publish the local server directly on the internet. A managed deployment needs authorization, HTTPS, security/privacy review, appropriate backups and document-storage controls. The application does not encrypt stored files or scan them for malware. See README.md for the implementation limits.

### Attendance administration

Administrators now have two dedicated options in the sidebar:
- **Attendance Edit** — select any active employee and edit the previous 14 completed shift dates directly.
- **Regularize Requests** — review employee attendance-correction requests and approve/reject them. Approved regularizations automatically update the attendance record.

Employees have **Regularize Attendance** as a dedicated option for submitting corrections.


## Realistic attendance data
On first server start, the portal safely normalizes rows marked as historical seed attendance: Saturday and Sunday become weekly offs and weekday times become varied. It does not overwrite manual/admin edits. You can also run `MAKE_ATTENDANCE_REALISTIC_WINDOWS.bat` manually.

## Themes and profile photos
Open **My Profile** to upload a JPG, PNG, or WEBP photo up to 5 MB. Open the account menu and choose **Workspace theme** to select American Express, Midnight, Forest, or Sand. The theme is saved only in the current browser.


## Source-only GitHub package
The supplied workspace database is intentionally excluded from this copy. Existing employee/admin accounts, saved sessions, attendance, and requests remain only in the original ZIP. On a new installation, complete first-time administrator setup as described above. Keep any original `data` folder backed up privately; do not upload it to GitHub. See `GITHUB_PACKAGE_NOTES.md`.
