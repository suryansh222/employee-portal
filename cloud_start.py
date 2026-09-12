"""Railway entry point. Keep local development on server.py.

Initial administrator secrets belong in Railway Variables, never in source.
Requires an attached persistent volume and Railway's HTTPS reverse proxy.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port: int
    allowed_hosts: list[str]
    proxy_ips: str


def read_settings() -> Settings:
    volume = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '').strip()
    if not volume:
        raise RuntimeError('Attach a persistent Railway volume at /app/data before deploying. Do not manually set RAILWAY_VOLUME_MOUNT_PATH.')
    mount = Path(volume).resolve()
    if not mount.is_dir():
        raise RuntimeError('The persistent volume is not mounted or is unavailable.')
    data = Path(os.environ.get('PORTAL_DATA_DIR', str(mount))).resolve()
    if data != mount and mount not in data.parents:
        raise RuntimeError('PORTAL_DATA_DIR must be on the attached persistent volume.')
    try:
        port = int(os.environ.get('PORT', '8080'))
    except ValueError as exc:
        raise RuntimeError('PORT must be an integer.') from exc
    if not 1 <= port <= 65535:
        raise RuntimeError('PORT must be between 1 and 65535.')
    public = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
    hosts = [h.strip().lower() for h in (public + ',' + os.environ.get('PORTAL_ALLOWED_HOSTS', '')).split(',') if h.strip()]
    if not hosts:
        raise RuntimeError('Generate a Railway public domain, then redeploy; or set PORTAL_ALLOWED_HOSTS to your exact domain.')
    for host in hosts:
        if len(host) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '..' in host:
            raise RuntimeError('Use exact hostnames in PORTAL_ALLOWED_HOSTS, without wildcards, protocol, path or port.')
    hosts = list(dict.fromkeys(hosts + ['healthcheck.railway.app']))
    proxy_ips = os.environ.get('FORWARDED_ALLOW_IPS', '').strip()
    if not proxy_ips:
        raise RuntimeError('Configure FORWARDED_ALLOW_IPS for the trusted HTTPS proxy. On Railway with no public TCP proxy, use *.')
    os.environ['PORTAL_DATA_DIR'] = str(data)
    os.environ['PORTAL_SECURE_COOKIE'] = '1'
    return Settings(data, port, hosts, proxy_ips)


def bootstrap_admin(server) -> bool:
    """Create only the first administrator; never reset an existing account."""
    with server.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            return False
        email = os.environ.get('PORTAL_ADMIN_EMAIL', '').strip()
        password = os.environ.get('PORTAL_ADMIN_PASSWORD', '')
        if not email or not password:
            raise RuntimeError('First launch requires PORTAL_ADMIN_EMAIL and PORTAL_ADMIN_PASSWORD in Railway Variables. Do not put them in GitHub.')
        server.password_value({'password': password})
        user = server.provision(connection, {
            'employee_id': os.environ.get('PORTAL_ADMIN_ID', 'ADMIN'),
            'first_name': os.environ.get('PORTAL_ADMIN_FIRST_NAME', 'Portal'),
            'last_name': os.environ.get('PORTAL_ADMIN_LAST_NAME', 'Administrator'),
            'email': email,
            'role': 'admin',
        }, password, False)
        server.audit(connection, user['id'], 'Created cloud administrator', 'user', user['id'])
    server.SETUP_KEY.unlink(missing_ok=True)
    return True


def create_app(settings: Settings):
    import server
    from fastapi.responses import JSONResponse
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    with contextlib.redirect_stdout(io.StringIO()):
        server.init_db()
    created = bootstrap_admin(server)
    os.environ.pop('PORTAL_ADMIN_PASSWORD', None)
    if created:
        print('Initial administrator created. Remove the bootstrap password from Railway Variables after verifying login.', flush=True)

    @server.app.middleware('http')
    async def cloud_boundary(request, call_next):
        if request.url.path in {'/api/auth/setup', '/api/docs', '/api/docs/oauth2-redirect', '/api/openapi.json'}:
            return JSONResponse({'detail': 'Not available on the cloud deployment.'}, status_code=404)
        if request.url.path == '/api/health':
            try:
                with server.db() as connection:
                    ready = connection.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None
            except Exception:
                ready = False
            return JSONResponse({'status': 'ok' if ready else 'unavailable'}, status_code=200 if ready else 503,
                                headers={'Cache-Control': 'no-store'})
        if request.url.scheme != 'https':
            return JSONResponse({'detail': 'HTTPS is required. Check the trusted proxy configuration.'}, status_code=400)
        response = await call_next(request)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    server.app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts, www_redirect=False)
    return server.app


def main() -> None:
    import uvicorn
    try:
        settings = read_settings()
        app = create_app(settings)
    except Exception as exc:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            raise SystemExit(f'Cloud configuration error: {exc.detail}') from None
        raise SystemExit(f'Cloud startup error: {exc}') from None
    uvicorn.run(app, host='0.0.0.0', port=settings.port, workers=1,
                proxy_headers=True, forwarded_allow_ips=settings.proxy_ips,
                access_log=False, log_level='info')


if __name__ == '__main__':
    main()
