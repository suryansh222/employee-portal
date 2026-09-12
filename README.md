# Colleague Workspace - Night Edition

> Source-only GitHub copy: the original database, screenshots, and local test outputs are not included. Existing accounts and attendance stay in your original ZIP. See GITHUB_PACKAGE_NOTES.md.
## Version 3: employee accounts and document delivery

A full-stack employee portal with the supplied American Express-inspired blue/navy design. It uses Python, FastAPI and SQLite. It has no automatic demonstration login, built-in user passwords or seeded employee/business records.

**Start here: [QUICK_START.md](QUICK_START.md).** The application is independent software and is not connected to American Express identity, payroll or HR systems. Branding authorization is the deployer's responsibility. See BRANDING_NOTICE.txt.

## Included features

| Area | Implemented behaviour |
|---|---|
| Account setup | One-time, local first-administrator setup protected by a random setup key printed in the server terminal. |
| Login | Employee and Administrator tabs; employee ID or email; backend role verification; sign-out. |
| Account administration | Create accounts, edit profile/role/status, disable/reactivate accounts, generate replacement temporary passwords and allocate leave balances. |
| Passwords | No defaults. Generated temporary employee passwords must be changed before application access. Own-password change and local server-console recovery are included. |
| Payslips | Administrator uploads a PDF assigned to one account and salary month; employee sees their own history and can download. |
| Offer letters | Administrator publishes the supplied PDF to one account; employee downloads from My Documents. |
| Document history | One published payslip per employee/month and one current offer letter per employee. Archive before replacing; administrators retain archived files. |
| Attendance | Check In / Check Out, overnight date handling, history, metrics, CSV export and correction requests. |
| Existing workspaces | Leave requests, profiles, preferences, support tickets, goals, service requests, team posts and administrative reviews remain available. |

No salaries or employment documents are manufactured by the application. All delivered payslips and offer letters are the actual PDFs an administrator uploads. No digital signing, company verification, payroll calculation, bank payments or authenticity checks are included.

## Installation

Requirements: Python **3.10 or newer**, a modern browser and an internet connection for the first dependency installation. Tested here using Python 3.13.5 on Linux; Windows batch files were written and inspected, not executed on Windows in this environment.

**No Docker, Node.js, Node build step, XAMPP or separate database server is required.** All application images and styles are local; the portal does not request external web fonts.

### Windows

Extract the ZIP to its own folder, then double-click **START_WINDOWS.bat** inside `American_Express_Employee_Portal`. The launcher locates `py -3` or `python`, creates `.venv`, installs `requirements.txt`, and runs the backend. It uses `http://127.0.0.1:8000` unless you choose another port.

A different port from PowerShell:

```powershell
.\START_WINDOWS.bat 8001
```

Manual setup, one command at a time, from the project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py --port 8000
```

Use `python -m venv .venv` when `py` is unavailable but `python` works. Do not skip environment creation. Directly calling the environment's Python avoids requiring a PowerShell activation script.

### Linux / macOS

```bash
bash start.sh
```

Or:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Keep the terminal open; Ctrl+C stops the server. Opening `static/index.html` as a file is not a working installation. There is no read-only HTML preview in this release; screenshots are in `screenshots`.

## First-time setup and login

The first run creates an empty `data/workspace.db` and prints a randomly generated one-time key in the terminal. It also stores that key in `data/setup.key` until initial setup completes. The browser shows **Create your administrator**.

Choose your own name, email, administrator ID and password (12-128 characters). Submit the setup key with these fields. The setup endpoint accepts local requests only and closes after the first account is created; the key file is then removed. It cannot be used to create a second owner.

Once configured, unauthenticated visitors see the Employee/Administrator login screen. There is no public registration or default account. A valid cookie can preserve an existing session for up to 16 hours to cover a night shift. This is normal session persistence, not automatic login to a shared account. Sign out on shared devices.

Administrators create each employee under **Employee Accounts**. A random temporary password is shown once, then removed when its dialog closes. Share it privately. Employees must change it before accessing records. Administrators can reset it but cannot view the old password. The administrator cannot disable or demote their own account, and the last active administrator is protected.

Email addresses are account identifiers, not an email integration. Invitations, verification emails and reset emails are not sent. A valid email format is required, but ownership is not verified by this application.

### Forgotten administrator password

Stop the server and run `RESET_PASSWORD_WINDOWS.bat`, or:

```powershell
.\.venv\Scripts\python.exe manage.py reset-password
```

The server operator enters the account email/ID and a new password using hidden console input. The script replaces the hash, revokes all sessions and records an audit event. It does not alter the account's role or enabled status. Direct server-file access is therefore highly privileged and must be restricted. This recovery tool is not exposed over HTTP.

## Upload and document access

**Administrator workflow:** Document Centre -> Upload document -> choose employee -> choose Payslip or Offer letter -> enter month when required, title and issue date -> select PDF -> Upload & publish.

**Employee workflow:** sign in -> My Payslips or My Documents -> Download. My Documents includes both types; My Payslips offers a salary-month filter.

Each upload is limited to **10 MiB (10,485,760 bytes)**, shown as 10 MB in the interface. The application allows a `.pdf` extension, checks the PDF header and end marker, rejects unsafe filenames, limits streamed request size and generates a random internal filename. These checks are not a full PDF parser, antivirus scanner or authenticity check. Only administrators can upload.

Uploaded bytes are stored outside the static web directory in `data/documents`. Download requests must pass session and role/ownership checks. An unrelated employee receives a not-found response; anonymous requests are denied. Downloads are sent as attachments with no-store and nosniff response headers. Employee IDs supplied in query parameters do not override ownership checks.

One current payslip per employee/month and one current offer letter per employee are enforced by database indexes. To correct a document, archive it and upload a replacement. There is no silent overwrite. Archived PDFs remain on disk and in the administrator's historical register; they are no longer available to the employee. Automatic purge, retention rules, archive restoration, bulk upload, Word attachments and electronic signatures are not implemented.

An in-app notification is created when a file is published. No email or SMS is sent. Administrators are privileged and can access all uploaded files.

## Night shift and other workspaces

The initial account schedule is **20:30 to 04:30 the following morning, IST (UTC+05:30)**. This is the application's initial setting, not a claim about an employer's working hours. Accounts can edit their schedule when no shift is active.

Check In records server time. Check Out closes the active record even after midnight. Attendance is keyed to the scheduled shift's start date. A new check-in after midnight, up to the scheduled end minute, is assigned to the preceding night. An already open record always takes priority. Duplicate check-ins, checkout without an open shift, and restarting a completed shift are rejected. Early check-in is allowed; keep the server's clock accurate.

The application saves planned start/end timestamps with each record, so schedule edits do not rewrite old duration calculations. Extra-time metrics are informational elapsed time, not approved or payable overtime. Break deductions, grace periods, employer-specific holidays and North American daylight-saving time are not modeled. Timezone is fixed to IST.

Paid-leave balances start at zero and are allocated by administrators. Unpaid and Sabbatical Leave have no tracked quota. Leave uses inclusive calendar days and reserves pending applications against available balance. Automatic accruals and employer policy rules are not included.

Requests and ticket approvals are persisted, but approval does not send money, make travel bookings or issue official documents. Team posts and directory entries come from actual accounts and user input. The task and recruitment views start empty; task assignment and vacancy-management interfaces are not part of this update.

## Storage, upgrading and backup

```text
American_Express_Employee_Portal/
  START_WINDOWS.bat
  RESET_PASSWORD_WINDOWS.bat
  RUN_TESTS_WINDOWS.bat
  start.sh
  server.py
  manage.py
  requirements.txt
  requirements-test.txt
  static/
    index.html
    app.js
    accounts-documents.js
    styles.css
    amex-theme.css
    accounts-documents.css
    assets/amex-logo.svg
  tests/
  qa/
  data/                    # created locally; not included in ZIP
    workspace.db
    documents/
```

This release intentionally uses **workspace.db**, not the earlier **portal.db**. It does not import the earlier shared accounts or sample data. Extract it into a new folder and keep the old installation as a backup. Copying the old `portal.db` into the new folder does not migrate it. No existing files on your computer are modified by downloading or extracting this separate project.

For this version's own backups, stop the server and copy the **entire data folder** to protected storage. A SQLite database alone does not contain the uploaded PDFs. Conversely, PDF files alone do not contain their ownership and account metadata. Preserve both. Do not delete or recreate `data` as a password-recovery method. Changes to `.venv` do not require changing `data`.

Application updates should preserve the whole data folder. Schema migrations in this version are additive; there is no automatic legacy-data import, database downgrade path or concurrent multi-server storage support.

## Security and deployment boundaries

Implemented controls include salted password hashes (PBKDF2-HMAC-SHA256, 600,000 iterations), hashed random session tokens, HTTP-only SameSite=Strict cookies, CSRF checks, same-origin write checks, role and ownership validation, parameterized SQL, escaping of displayed text, persistent login throttling, request-size limits, private randomized file storage, session revocation on reset/disable and audit events.

These controls **do not constitute a security audit or production certification**. PDF files and the SQLite database are not encrypted at rest by the application. Anyone with access to the server filesystem can bypass application-level document permissions. File scanning, content disarm/reconstruction, multifactor authentication, organizational single sign-on, email verification, managed encryption keys, retention enforcement, centralized monitoring and off-site backup automation are not included.

The server binds only to loopback by default. Use it locally until an authorized deployment has received a security/privacy review. A shared employee deployment requires properly configured HTTPS, host/proxy restrictions, secure cookies, trusted identity/access provisioning, malware defenses for uploaded documents, protected storage, backup/restore procedures and monitoring. Do not disable firewall or corporate security policies to expose it.

Configuration options:

| Variable | Behaviour |
|---|---|
| `PORTAL_DATA_DIR` | Alternate directory containing this version's workspace.db and documents. |
| `PORTAL_PORT` | Default server port; command-line --port takes priority. |
| `PORTAL_SECURE_COOKIE` | Set to 1 only with correctly configured HTTPS. Plain local HTTP otherwise cannot use the cookie. |
| `PORTAL_ALLOW_NETWORK` | Explicit opt-in required before a non-loopback --host; not a deployment security solution. |

The old automatic-access and seeded-password environment variables are not used. Use the first-run setup or account management instead.

## Tests and API

**63 automated backend/service/recovery tests passed** in the build environment: 46 real-HTTP integration cases, 12 deterministic overnight cases and 5 local recovery cases. **82 UI checks passed**, including desktop/mobile layouts and account/document actions, using the qualified test method in TEST_REPORT.md. This is not a penetration test.

Run normal tests after installation:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Or double-click RUN_TESTS_WINDOWS.bat. Tests use disposable databases and do not touch the application's data. The optional Playwright harness in `qa/check_interface.py` uses a test-only HTTP bridge to an isolated server because native browser navigation was restricted in the build environment. See TEST_REPORT.md for its setup and limitations.

Interactive API documentation is at `/api/docs` while running; its standard Swagger UI assets may need internet. The portal itself uses local assets. Endpoint descriptions and schemas are at `/api/openapi.json`.

Key new endpoints:

```text
GET    /api/session
POST   /api/auth/setup
POST   /api/auth/login
POST   /api/auth/logout
POST   /api/auth/password
GET    /api/admin/employees
POST   /api/admin/employees
PATCH  /api/admin/employees/{id}
POST   /api/admin/employees/{id}/reset-password
GET    /api/admin/employees/{id}/leave-balances
PATCH  /api/admin/employees/{id}/leave-balances
GET    /api/admin/documents
POST   /api/admin/documents
POST   /api/admin/documents/{id}/archive
GET    /api/documents
GET    /api/documents/{id}/download
POST   /api/attendance/check-in
POST   /api/attendance/check-out
```

Authenticated writes require the session's X-CSRF-Token. Accounts flagged for a temporary-password change cannot access normal endpoints before completing that change. Uploads use multipart form data; the other new writes use JSON.

## Implementation references

- Python virtual environments: https://docs.python.org/3/library/venv.html
- FastAPI request files and multipart forms: https://fastapi.tiangolo.com/tutorial/request-files/
- OWASP file-upload considerations: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP password storage: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

These are implementation references, not claims that every recommendation or certification is met.
