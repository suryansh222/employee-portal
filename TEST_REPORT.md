# Verification report - Colleague Workspace v3

## Executed checks

| Suite | Result | Method |
|---|---|---|
| Account/document/API integration | 46 passed | Real HTTP requests to a running Uvicorn/FastAPI subprocess; isolated SQLite database and uploaded files. |
| Overnight attendance boundaries | 12 passed | Deterministic service tests with a patched test-process clock; no time-spoofing feature exists in the server. |
| Local password recovery | 5 passed | Disposable database; password replacement, missing account/database, password validation and session invalidation. |
| UI rendering and actions | 82 checks passed; 0 uncaught JavaScript errors | Chromium with actual application CSS/JS and a test-only HTTP bridge to a real isolated backend. |
| JavaScript syntax | Passed | node --check for both application JavaScript files. Node is a build QA tool, not an application prerequisite. |
| Python syntax | Passed | py_compile for server.py and manage.py. |

The latest normal test run completed **63 tests with OK**. The reproducible test files are in `tests/`; the captured output is in `tests/last_run.txt`. Random, now-invalid setup keys in that log were redacted. Individual interface results are in `qa/interface_results.json`.

## What the API checks cover

Fresh empty installation, no default accounts, no automatic sign-in, setup-key protection and one-time setup, login by ID/email, role validation, cookie attributes, logout, CSRF/origin checks, throttling, temporary-password enforcement, unique employee identifiers, reset and disable session revocation, active-admin safeguards, leave allocation, password validation and password hash storage.

Document cases cover authorized upload, valid ownership, employee-to-employee isolation, anonymous denial, non-admin denial, month validation, unsupported types and filenames, PDF signature rejection, empty/oversized/multiple-file rejection, streaming request-size enforcement without Content-Length, metadata privacy, storage outside static files, download attachment headers, audit events, persistence after restart, duplicate-period rejection, archive and replacement, and old generated-letter routes remaining absent.

The fixture PDFs are deliberately minimal byte fixtures for signature and access-control tests, not completed payslips or valid business documents. The server only performs basic PDF signature/end-marker validation, not full PDF parsing or malware detection.

## UI workflows and layout coverage

The harness created the first administrator through the form, created an employee, captured and cleared their temporary password dialog, allocated leave, uploaded payslip and offer-letter files, used filters/search, edited account details, signed out, changed login modes, toggled password visibility, completed first-login password change, read employee-owned documents, checked an authenticated download response, checked in/out, archived/replaced an offer letter, reset a password, disabled/reactivated an account and opened administrative review.

The login, Employee Accounts, Document Centre, My Documents and dashboard views were checked at **320, 390, 768, 1024 and 1440 pixels** for body-level horizontal overflow. Wide tables use their own horizontal scroll container. The harness also rendered the existing attendance, tasks, profile, directory, goals, recruitment, support, requests, expenses, travel, guidelines, organization, posts and service pages without route errors.

Screenshots were visually inspected for the login, mobile login and populated administrative document centre. They use fictional QA records. The distributed runtime does not contain that test database or those uploaded fixtures.

## Environment and limitations

Executed on Linux with Python 3.13.5, FastAPI 0.128.2, Uvicorn 0.48.0, Starlette 0.50.0, python-multipart 0.0.29, httpx 0.28.1 and Playwright 1.57.0.

The managed Chromium environment blocks URL navigation. That policy was not changed. Instead, the harness loaded the actual UI with set_content and used a **test-only Python HTTP bridge** for fetch requests. The backend was real and recorded all operations in a temporary database. The bridge is not in any shipped application HTML or JavaScript.

Consequently, the UI results are **not native browser-network end-to-end certification**: browser cookie enforcement, original HTTP page navigation, server CSP enforcement in a normally loaded tab, the browser download UI, native file-picker dialogs and same-origin browser enforcement were not exercised by this harness. The integration suite checks server responses and authorization over HTTP separately.

The Windows launchers were reviewed but could not be executed on Windows here. Their actual behavior on the user's Python installation, browser opening, antivirus policy and network is not certified by these tests. No internet/shared-network deployment, load test, penetration test, legal compliance review, malware scanner, encryption-at-rest system or real company integration was tested or provided.

## Reproduce normal tests

From the project folder, after installing Python:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests allocate temporary directories; they do not connect to or mutate the running user's `data` folder.

## Optional UI harness

This is a developer QA dependency, not required to run the application:

```powershell
.\.venv\Scripts\python.exe -m pip install -r qa\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe qa\check_interface.py --output qa\output
```

An already installed Chromium can be supplied with `--chromium` and its executable path. The harness creates and removes its own server/database, writes screenshots/results to the selected output folder, and intentionally uses the same qualified HTTP-bridge method described above.
