# Deploy the employee portal on Railway

## Status of this package

Prepared for deployment; NOT uploaded and NOT live. No public URL has been created.
The full existing frontend and Python backend are included. No employee records,
database, uploaded documents, saved sessions or live passwords are included.
The original local startup scripts remain available and unchanged.

## Before publishing

This is independent software, not an official American Express service. Review
BRANDING_NOTICE.txt and obtain the required authorization for the branding. Do not
collect passwords used for a separate corporate account. Use test-only data until
the software and hosting have received an appropriate security/privacy review.
This package is deployment preparation, not a security certification.

Railway hosting has usage/plan costs. Review its current price and limits before
activating a service. This package does not purchase a plan or create resources.

## Deploy the complete application

1. Extract this ZIP. Upload the CONTENTS of its employee-portal folder to your
   private GitHub repository. Dockerfile, requirements.txt, railway.json and
   server.py should appear at the repository root, not inside a ZIP. Alternatively,
   Railway's authenticated CLI can deploy that local folder directly.
2. Connect Railway, create a project and a service from that repository/source.
   The service uses the included Dockerfile. Docker Desktop is NOT needed on
   your Windows computer; Railway performs the image build.
3. Attach a persistent volume to this service at /app/data BEFORE launching it.
   Both the SQLite database and employee document files go on this volume.
   The startup guard deliberately fails if Railway reports no attached volume.
   Do not manually set RAILWAY_VOLUME_MOUNT_PATH to bypass this check.
4. In the service's Variables tab set:

   | Variable | Value |
   | --- | --- |
   | PORTAL_DATA_DIR | /app/data |
   | PORTAL_SECURE_COOKIE | 1 |
   | FORWARDED_ALLOW_IPS | * |
   | PORTAL_ADMIN_EMAIL | Your administrator email, entered privately |
   | PORTAL_ADMIN_PASSWORD | A unique password of at least 16 characters, entered privately |
   | PORTAL_ADMIN_ID | ADMIN, or your chosen administrator ID |

   Password validation accepts 12-128 characters; 16+ is recommended here.
   Use a sealed variable for the initial password when available. Do not send
   that password in chat, write it in the source, or commit a real .env file.
   Trusting all forwarded-proxy sources is intended ONLY for Railway's managed
   HTTPS edge. Never expose this service with a public raw TCP proxy. In other
   hosting environments, restrict this setting to their actual trusted proxies.
5. In Settings > Networking > Public Networking, choose Generate Domain. Railway
   supplies RAILWAY_PUBLIC_DOMAIN. After creating/changing the domain, deploy or
   redeploy to pass it into the running service. PORTAL_ALLOWED_HOSTS may contain
   additional exact custom hostnames; wildcard hosts are rejected.
6. Keep one service replica and one Uvicorn worker. Apply the changes and deploy.
   The start command is python cloud_start.py; the health path is /api/health.
   A first deployment without the required volume, domain or administrator
   variables will fail safely. Configure those items and redeploy.
7. Open the generated HTTPS URL. Select Administrator and sign in with the email
   or ID and password you set in Variables. The cloud startup creates only this
   first administrator. No sample employees are created. Create employee accounts
   through the administration interface.
8. After confirming login, REMOVE PORTAL_ADMIN_PASSWORD from Railway Variables
   and redeploy. Existing accounts and documents persist; startup never resets an
   existing administrator password. Keep the password in your password manager.

## What was added

- cloud_start.py: Railway startup, explicit persistent-volume requirement, secure
  cookies, exact-host filtering, HTTPS requirement, proxy configuration, initial
  administrator creation from private variables, database-backed health response.
- Dockerfile and .dockerignore: cloud image containing application code, not data.
- railway.json: build, single-replica startup, healthcheck and restart settings.
- .env.example: variable names only; no real credentials.
- tests/test_cloud.py: tests for the deployment settings and initial administrator.

The original server.py has NOT been changed. Public first-time setup and API
schema/documentation routes are disabled only by the cloud wrapper. The existing
local setup-key check is not weakened. Setup keys are not printed to cloud logs.

## Data, operations and limitations

GitHub is source storage, not your employee database. Do not upload workspace.db,
setup.key, data/documents, passwords or employee PDFs to the repository.

A persistent volume is not a backup. Configure protected backups and test restore
procedures before real use. Preserve the database AND its document files together.
A volume-backed service can have brief downtime during redeployments. Railway's
deploy healthcheck is not continuous uptime monitoring.

Do not attach the old local data directory during this initial deployment.
Migrating real records needs a separate protected transfer and validation.

The application does not provide organizational SSO, MFA, application-managed
at-rest encryption or malware scanning of uploads. Those needs, dependency patching,
access control reviews and applicable employee-data policies require further work
before production use with sensitive records. Read README.md for existing limits.

## Official documentation consulted, 12 September 2026

- Railway FastAPI deployment: https://docs.railway.com/guides/fastapi
- Railway persistent volumes: https://docs.railway.com/volumes
- Railway configuration: https://docs.railway.com/config-as-code/reference
- Railway healthchecks: https://docs.railway.com/deployments/healthchecks
- Railway public networking: https://docs.railway.com/networking/public-networking
- Railway variables: https://docs.railway.com/variables/reference
- Railway plans: https://docs.railway.com/pricing/plans
- FastAPI trusted proxies: https://fastapi.tiangolo.com/advanced/behind-a-proxy/
