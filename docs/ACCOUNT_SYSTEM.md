# PowerBid Account System

This module is opt-in. Existing demos remain public unless authentication is explicitly enabled.

## Production setup

1. Mount a dedicated persistent host directory (for example /srv/powerbid-accounts) into the PowerBid container at /data. Never store the live database in the container image or writable image layer.
2. Build the updated Dockerfile.studio (FastAPI + Argon2id + email validator).
3. Provision the very first administrator interactively, before opening registration:

    docker exec -it CONTAINER_NAME python -m app.account_auth bootstrap-admin --username poweradmin --email OWNER_EMAIL

   The CLI securely prompts for the administrator password and refuses duplicate bootstrapping. Never put the password in Git, chat, shell arguments, or logs.
4. Configure these container environment variables:

    POWERBID_AUTH_ENABLED=1
    POWERBID_AUTH_DB_PATH=/data/powerbid-accounts.sqlite3
    POWERBID_REGISTRATION_OPEN=0
    POWERBID_COOKIE_SECURE=1

5. Verify health, login, authenticated user status, and access denial for anonymous API calls in a private candidate deployment before changing the production Caddy route.
6. Set POWERBID_REGISTRATION_OPEN=1 only when public signup is intended; ordinary signups always receive the member role.

## Security

- Argon2id password hashes; passwords must be 12 to 128 characters.
- Only SHA-256 digests of random session tokens are stored in SQLite.
- Seven-day expiring Secure / HttpOnly / SameSite=Lax cookie.
- Logout and account disable revoke sessions immediately.
- Admin APIs enumerate and enable/disable non-admin accounts.
- Wrong passwords are limited to five attempts per account over a 15-minute window.
- State-changing API requests reject invalid Origin and require X-PowerBid-Request header.
- Database is private (0600 file permissions).
- No automatic first-public-user promotion to administrator.

## API routes

- GET /api/auth/config: feature flag and registration status.
- POST /api/auth/register: gated signup.
- POST /api/auth/login: password login.
- GET /api/auth/me: current user.
- POST /api/auth/logout: revoke current session.
- GET /api/auth/users: admin account listing.
- POST /api/auth/users/{id}/enabled: admin disable / enable.
- GET /api/health: remains public.
- All other /api/* endpoints: require a valid session while POWERBID_AUTH_ENABLED=1.

The public homepage remains accessible. The /app path displays a login screen when auth is enabled. In disabled mode, the current public demo behavior remains unchanged.

## Data and rollback

SQLite WAL may produce -wal and -shm sidecar files. For a consistent live backup, use SQLite's .backup API instead of copying only the main .sqlite3 file while writers are active. Backups must be stored off-host and access controlled. Keep the /data mount intact across Docker upgrades, rollbacks, and prune operations. Do not run docker volume prune on this server.

To rollback, restore the previous image and Caddy route without deleting /data. Avoid turning off authentication if future user-owned server data becomes accessible.

## Scope limits

This first milestone provides login, registration, sessions, roles, administrator disabling and server-side API access control. It does NOT yet implement password recovery, email confirmation, 2FA, role delegation, or persistent per-user bid-project storage. Those require separate design and tests.

## Local tests

Install Python web dependencies and run the account tests and existing API regressions. Browser previews should use a throwaway SQLite file and insecure cookies only on local loopback HTTP, never on the HTTPS production domain.

## One-time browser-based administrator setup (optional, recommended)

The administrator's own password can be chosen on a dedicated, single-use
activation page rather than shared over chat or embedded into deployment scripts.

Set the production container environment to:

    POWERBID_AUTH_ENABLED=auto
    POWERBID_ADMIN_SETUP_ENABLED=1
    POWERBID_REGISTRATION_OPEN=1
    POWERBID_COOKIE_SECURE=1

In auto mode, the public demo remains accessible while there is no administrator,
provided the mounted account database is intact. After the administrator
is created, all API routes immediately begin enforcing authenticated sessions
and public registration becomes available. Missing or inaccessible account
storage fails closed rather than reopening API access.

On the server, with the persistent /data directory already mounted, issue an
invitation using the Python module inside the deployment container:

    docker exec CONTAINER python -c 'from app.admin_setup import issue_invite; print(issue_invite())'

The output is a single-use HTTPS link whose secret lives in the URL fragment,
not in HTTP request logs. The secret is stored as a SHA-256 digest on the server,
expires after 24 hours, and is consumed atomically when the first administrator
registers. The admin provides their username, email and password inside the
HTTPS page. Never put the invitation URL into a public repository or screenshots.

After the first admin has activated, it is recommended to redeploy with
POWERBID_ADMIN_SETUP_ENABLED=0 to disable the setup endpoint entirely.
For production resilience, retain persistent off-host database backups.
