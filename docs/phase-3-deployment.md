# Phase 3 — Deployment prep

Status: complete, awaiting review. **This phase is prep and documentation
only.** Nothing was provisioned, no domain was registered, and no script
below was run against real infrastructure — everything under `deploy/` is a
template for you to read and run yourself when you're ready to actually go
live, per your explicit instruction for this phase.

## What was built

- **Env-driven prod/dev settings** (`app/config.py`, `app/main.py`): a new
  `APP_ENV` variable (`development` by default, `production` when set)
  drives two behavior differences:
  - `SessionMiddleware` is created with `https_only=IS_PRODUCTION` — in
    production the session cookie is only ever sent over HTTPS; in
    development (plain `http://127.0.0.1`) it still works without a cert.
  - FastAPI's interactive docs (`/docs`, `/redoc`, `/openapi.json`) are
    disabled when `APP_ENV=production`, left on otherwise. There's no
    private data in the schema itself, but there's no reason to expose an
    interactive "call any endpoint" console on a public instance either.
  - `is_production(app_env: str) -> bool` is a small pure function so this
    logic is unit-testable without spinning up a server
    (`tests/test_config.py`). A second test file
    (`tests/test_prod_settings.py`) reloads `app.config`/`app.main` under
    both `APP_ENV` values and asserts on the actual `FastAPI` app object
    and its `SessionMiddleware` kwargs, so the wiring itself is covered,
    not just the pure function.
  - `.env.example` gained `APP_ENV=development` (see Deviations).
- **Deployment templates** (`deploy/`), two paths since the brief named
  either "a small VPS or platform (Fly.io/Railway/Render)":
  - `deploy/vps/` — a small-VPS path: `english-essay.service` (a systemd
    unit running plain `uvicorn --workers 2`, no new ASGI-server dependency
    added), `nginx.conf` (HTTP-only reverse-proxy template — deliberately
    left for `certbot` to rewrite into HTTPS, see checklist below), and
    `setup.sh` (a reference script: installs Python/nginx/certbot/a JRE,
    creates the venv, generates a real `.env` with fresh
    `SESSION_SECRET_KEY`/`ENCRYPTION_KEY`, runs migrations, installs the
    systemd unit and nginx site). Every file says plainly it's a template
    meant to be run by you, not by this repo.
  - `deploy/fly/` — a platform path: `Dockerfile` (includes the JRE
    LanguageTool needs) and `fly.toml` (a Fly app config with a persistent
    volume for the SQLite file and `force_https = true`). Railway and
    Render both also deploy from a Dockerfile, so the same file covers all
    three named platforms; `fly.toml` is Fly-specific but the pattern
    (persistent volume for `/data`, env-driven config, HTTPS forced at the
    platform's edge) carries over directly to Railway/Render's own config
    format if you go that route instead.
- **HTTPS/domain checklist** — see below.

## HTTPS/domain checklist

Sessions carry a signed cookie and the settings page carries API keys
end-to-end over the connection, so none of this is optional once the app
leaves your local machine:

- [ ] DNS: point an A/AAAA record (VPS path) or your platform's assigned
      CNAME (Fly/Railway/Render path) at the server before requesting a
      certificate — certbot and most platforms' managed-TLS both validate
      via DNS or an HTTP challenge that needs the domain resolving first.
- [ ] TLS certificate: `certbot --nginx -d your-domain.example` on the VPS
      path (auto-renews via a systemd timer certbot installs); Fly/Railway/
      Render all provision and renew a managed cert automatically once the
      custom domain is attached — no certbot needed on that path.
- [ ] Force HTTPS: `force_https = true` in `fly.toml` (already set in the
      template); on the VPS path, certbot's `--nginx` flag adds the
      port-80-to-443 redirect for you when it issues the cert.
- [ ] Set `APP_ENV=production` in the real environment (`.env` on the VPS,
      `fly secrets`/platform env vars elsewhere) — this is what flips
      `https_only` on the session cookie. Forgetting this step silently
      keeps the cookie sendable over plain HTTP.
- [ ] Generate fresh `SESSION_SECRET_KEY` and `ENCRYPTION_KEY` for
      production — never reuse the ones from local `.env`. `setup.sh`
      generates both automatically; on Fly/Railway/Render, generate them
      the same way (see README) and set them as platform secrets, never in
      a committed file.
- [ ] Confirm `.env` (or the platform's secret store) is never committed —
      already gitignored repo-wide, but worth a second look before your
      first push from a fresh clone on the server.
- [ ] HSTS: once you've confirmed HTTPS works end-to-end, consider adding
      `add_header Strict-Transport-Security "max-age=31536000" always;` to
      the nginx template (left out by default so a misconfigured cert
      renewal doesn't lock out plain HTTP during setup).

## How to test it

```
venv\Scripts\pytest
```

`pytest` should report 24 passed (20 from Phases 1–2 + 4 new: 2 for
`is_production`, 2 reloading the app under each `APP_ENV`). No new
dependency was added — production serving still uses plain `uvicorn`
(`--workers N`), consistent with the brief's tech stack.

The `deploy/` templates weren't run in this environment (per your
instruction not to touch live infrastructure). If you want to dry-run the
VPS path locally before touching a real server, `bash deploy/vps/setup.sh`
would fail fast on `sudo apt-get` inside most sandboxes — it's meant for a
real Ubuntu/Debian VPS. The Fly.io path can be sanity-checked without
registering anything by running `docker build -f deploy/fly/Dockerfile .`
locally if you have Docker installed; I did not do this here since it
wasn't asked for and building an image is its own (mildly) side-effectful
action.

## Deviations from the brief, and why

- **`APP_ENV` added to `.env.example`**, not in the brief's original
  3-variable list. That list was written for the Phase 1 scaffold, before
  Phase 3's "production settings split from dev settings (env-driven)"
  requirement existed — there's no way to satisfy that requirement without
  an environment variable to switch on.
- **No `gunicorn` added.** Some uvicorn deployment guides pair it with
  gunicorn as a process manager; skipped since uvicorn's own `--workers`
  flag covers a single small VPS, and the brief's tech stack names Uvicorn
  specifically with no mention of gunicorn — adding it would be an
  unrequested dependency.
- **Docker added only under `deploy/fly/`, not as the VPS path.** The VPS
  path runs the app directly via systemd + a venv, matching "small VPS" in
  the brief literally; Docker only shows up where the platform (Fly,
  and Railway/Render by extension) requires a container to deploy from.

## Known limitations

- SQLite is a single file on a single instance. The Fly template mounts a
  persistent volume so redeploys don't wipe it, and the VPS path just lives
  on local disk — neither survives a multi-instance/autoscaled setup. The
  brief already anticipated this ("SQLite for now, behind the ORM so a
  later move to Postgres is a connection-string change only"); Phase 3
  doesn't change the ORM layer, just documents the current single-instance
  constraint.
- No backup strategy for the SQLite file is documented yet — worth adding
  before real user data accumulates (e.g. a cron'd `sqlite3 .backup` on the
  VPS path, or a Fly volume snapshot schedule).
- The systemd unit's `ProtectSystem=strict` sandboxing was chosen as a safe
  default but not tested against a real systemd on a real VPS in this
  environment — worth a first-deploy sanity check that the app can still
  read/write `app.db` and `.env` under that restriction (it should, given
  `ReadWritePaths` covers the working directory, but "should" isn't
  "verified live").
- No rate limiting, no CSRF protection, no password reset flow — same
  known limitations carried over from Phase 1, unrelated to deployment
  itself and not in scope for this phase.

## Next

All three phases from `PROJECT_BRIEF.md` are now built and documented.
Waiting for your review before any of this touches real infrastructure.
