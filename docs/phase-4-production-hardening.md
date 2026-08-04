# Phase 4 — production hardening for open signups

Status: complete, awaiting review. Nothing in this phase touched
`deploy/vps` or `deploy/fly`, nothing was provisioned, and no real email was
sent from anywhere in this environment — every test mocks `EmailSender`.

CSRF protection (double-submit cookie) was already in place going into this
phase; see `docs/security-notes.md` for that write-up. This phase builds on
top of it — every new state-changing route below also carries
`Depends(verify_csrf)`.

## What was built

### Phase 1 production safety follow-up

- **Shared rate-limit storage:** development defaults to `memory://`; every
  `APP_ENV=production` startup now requires `RATE_LIMIT_STORAGE_URI` to be a
  `redis://` or `rediss://` URL. Install the Python `redis` package from
  `requirements.txt`, provision Redis separately, and keep its URL in the
  deployment secret store. This prevents each Uvicorn worker from maintaining
  a separate in-memory limit counter.
- **Required production variables:** `SESSION_SECRET_KEY` must be an
  unpredictable value at least 32 characters long, `ENCRYPTION_KEY` must be
  a valid Fernet key, and `RATE_LIMIT_STORAGE_URI` must reference Redis. The
  application fails startup rather than using defaults.
- **Provider endpoints:** Gemini, Groq, and OpenRouter use server-defined
  approved HTTPS URLs. Custom endpoints are disabled by default. A trusted
  self-hosted operator may set `ALLOW_CUSTOM_AI_ENDPOINTS=true`; those URLs
  must be HTTPS, contain no embedded credentials/query/fragment, resolve only
  to public addresses, and are called with redirects disabled. Do not enable
  this on hosted multi-tenant deployments; network egress controls remain the
  final protection against DNS rebinding.
- **Cost/reliability guardrails:** submissions, rewrites, and settings tests
  are limited; titles, document content, model names, URLs, and request bodies
  are capped. AI requests have a 30-second default timeout and LanguageTool
  has a 15-second default timeout. Errors do not echo provider request details
  or URLs, and an essay is saved even if either check times out.
- **Browser defenses:** CSP, frame, MIME-sniffing, referrer, permissions, and
  production HSTS headers are set centrally. Inline editor event handlers were
  removed so executable script remains self-hosted (Tailwind's existing CDN
  compiler is allow-listed temporarily; replace it with built local CSS before
  imposing a CSP with no third-party style execution).

### Email

- **`EmailSender` protocol** (`app/email/sender.py`): `send(to, subject,
  body) -> None`.
- **`ConsoleEmailSender`**: logs the email instead of sending it. Used
  automatically whenever `SMTP_HOST` is unset — local dev and every test in
  this suite (tests go further and swap in a `FakeEmailSender` fixture that
  records sent messages instead of even hitting the logger, so assertions
  can check exactly what was sent).
- **`SMTPEmailSender`**: stdlib `smtplib` only, no new dependency. Reads
  `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `FROM_EMAIL`
  from `app/config.py`. `get_email_sender()` picks between the two based on
  whether `SMTP_HOST` is set.

### Email verification

- `EmailVerificationToken` model (`app/db/models.py`) — random
  `secrets.token_urlsafe(32)` token, 24-hour expiry, single-use (`used_at`
  set on consumption). Only a SHA-256 hash of the token is persisted
  (`token_hash` column) — same reasoning as not storing passwords in
  plaintext: a DB read or leak shouldn't hand out directly-usable
  verification/reset links. `app/auth/tokens.py`'s `create_*` helpers
  generate the raw token, store its hash, and stash the raw value as a
  transient (non-persisted) `.token` attribute on the returned object so the
  caller can still build the email link; `consume_*` hashes the incoming
  token value and looks up by `token_hash`. No per-token salt: these are
  high-entropy, single-use, expiring tokens, not low-entropy secrets an
  attacker would try to brute-force offline, so a fast hash is enough — it
  only needs to stop a raw DB dump from being directly usable.
  `alembic/versions/d74d3075709b_*.py` adds the table plus a
  `users.email_verified` boolean column (`server_default='0'` so the
  migration backfills existing rows as unverified).
- Signup (`POST /signup`) creates the user, then immediately creates a
  verification token and emails a `/verify-email?token=...` link.
  `GET /verify-email` consumes the token and sets `email_verified = True`,
  rendering `verify_email.html` (success or invalid/expired state).
- **Essay/chapter creation is blocked until verified — login is not.**
  `POST /` (new document) checks `user.email_verified` and redirects to `/`
  if false; revising an *existing* document isn't gated, since a user can't
  have an existing document without having first passed the creation gate.
  `GET /` passes `email_verified` into `editor.html`, which swaps the
  "write something new" form for an amber banner explaining why when the
  user hasn't verified yet — so the block is visible before they try to
  submit, not just after.

### Password reset

- `PasswordResetToken` model — same shape as the email-verification token,
  1-hour expiry, single-use.
- `GET`/`POST /forgot-password`: takes an email, and — **only if an account
  with that email exists** — creates a token and emails a
  `/reset-password?token=...` link. The response text is identical either
  way ("If an account with that email exists, we've sent a password reset
  link.") so this can't be used to enumerate registered emails.
- `GET`/`POST /reset-password`: takes the token and a new password (8-char
  minimum, same rule as signup), consumes the token, and updates
  `password_hash`. An invalid, expired, or already-used token renders a
  clear error instead of a generic failure.
- `login.html` gained a "Forgot your password?" link.

### Rate limiting (`slowapi`, pre-approved)

Wired into `app/main.py`: `app.state.limiter`, the `RateLimitExceeded`
exception handler, and `SlowAPIMiddleware` (adds `X-RateLimit-*` /
`Retry-After` response headers). Limits, all keyed per source IP
(`app/rate_limit.py`):

| Route | Limit | Why this number |
|---|---|---|
| `POST /login` | 10/minute | Generous for a user fumbling their password a few times; tight enough to make credential-stuffing impractical. |
| `POST /signup` | 5/hour | Normal signup is a one-time action per person; caps mass account creation from a single IP. |
| `POST /forgot-password` | 5/hour | The request step sends an email, so this also caps using the app to spam a target's inbox. |

### Honeypot

Signup form (`signup.html`) has a `website` field, off-screen (absolutely
positioned outside the viewport, not `display:none` — some scraper bots
skip fields hidden that way but still fill in off-screen ones, so
off-screen alone isn't foolproof either, but combined with `tabindex="-1"`
and `aria-hidden="true"` it's invisible and unreachable for a real user
while still catching the common case of a bot that fills every field it
finds). If `website` arrives non-empty, `POST /signup` silently redirects
to `/login` as if signup succeeded — no user is created, no email is sent,
and the bot gets no signal that it was caught.

### SQLite WAL mode

`app/db/session.py`: `enable_sqlite_wal(engine)` registers a `connect`
event that runs `PRAGMA journal_mode=WAL`. Applied to the module-level
`engine` whenever `DATABASE_URL` is a file-based SQLite URL (skipped for
`:memory:`, which doesn't support WAL and would just no-op — skipping it
explicitly avoids relying on that silent fallback). WAL lets readers (e.g.
the backup script's `.backup` command, below) run concurrently with the
app's writes instead of blocking on SQLite's default rollback-journal lock.

### Self-service account deletion

`POST /settings/delete-account` (`settings.html`, "Delete account" section):
requires re-entering the current password, then `db.delete(user)`. Every
child relationship (`ai_settings`, `documents` → `document_versions` →
`corrections`/`scores`, `vocab_words`, `email_verification_tokens`,
`password_reset_tokens`) is `cascade="all, delete-orphan"` in the ORM
mapping, so a single delete-and-commit removes everything belonging to the
user. Wrong password re-renders the settings page with an error and deletes
nothing.

### Backup script

`scripts/backup_db.sh`: `sqlite3 app.db ".backup 'backups/app-<UTC
timestamp>.db'"` (a consistent snapshot — safe to run while the app is
live, unlike a plain file copy), gzips it, and keeps only the 7 most recent
rotations in `backups/` (gitignored). Meant to be run on a schedule (cron)
on whatever machine actually hosts `app.db` — not run against anything in
this environment. The script's header comments show where to add a step to
copy the newest backup to off-server storage (S3/rclone/rsync) once real
infra exists; nothing like that is wired up now, per your instruction not
to provision anything.

## Deviations from the request, and why

- **No "resend verification email" feature.** The request specifies signup
  sends the link and creation is blocked until verified — it doesn't ask
  for a resend path. Adding one wasn't requested, so a user who loses the
  original email has no in-app way to get a new one yet; noted below as a
  known limitation rather than built speculatively.
- **`SlowAPIMiddleware` added in addition to the exception handler.** Not
  explicitly requested, but it's the standard companion piece to
  `app.state.limiter` in slowapi's own setup docs — without it the rate
  limit still enforces (its 429 comes from `HTTPException` and FastAPI's
  default handler catches it either way), but response headers
  (`X-RateLimit-Remaining`, `Retry-After`) are absent, which is worse UX for
  any client trying to back off politely. No new dependency — same package
  you pre-approved.
- **Revising an existing document isn't gated on verification, only
  creating a new one.** The instruction says "block essay/chapter
  creation," and a user who's never verified can't have an existing
  document to revise in the first place (revision requires a document
  already owned by their user id), so there's no path where this
  distinction matters in practice — it just avoids adding a redundant check.

## How to test it

```
venv\Scripts\pytest -q
```

58 passed (33 from Phases 1–3 + CSRF, 25 new this phase):

- `tests/test_email_verification.py` (8) — signup sends the email, token
  consumption (valid/invalid/reused), creation blocked while unverified
  (with the banner asserted on the page), login still works unverified,
  verified users can create.
- `tests/test_password_reset.py` (6) — request email (existing vs. unknown,
  same response text), reset with valid/invalid/reused token, login with
  the new password afterward.
- `tests/test_rate_limiting.py` (3) — login/signup/forgot-password each
  return 429 on the request past their limit.
- `tests/test_honeypot.py` (3) — filled honeypot silently rejects with no
  user created and no email sent; empty honeypot doesn't interfere; the
  field renders in the form.
- `tests/test_account_deletion.py` (3) — wrong password rejected and
  account survives; correct password cascades through every table; deletion
  requires being logged in.
- `tests/test_wal_mode.py` (2) — `enable_sqlite_wal` actually sets
  `journal_mode=WAL` on a real file-backed engine; doesn't error against
  `:memory:`.

All email sending goes through a `fake_email_sender` fixture
(`tests/conftest.py`) that monkeypatches `app.auth.routes.get_email_sender`
to return a recorder instead of `ConsoleEmailSender`/`SMTPEmailSender` — no
real network calls, no console log noise, and tests can assert on exactly
what would have been sent.

One fixture change worth flagging: the shared `user` fixture now defaults
to `email_verified=True` (most existing tests create documents and
shouldn't have to think about the verification gate); a new
`unverified_user` fixture covers the gate itself. A new autouse
`_reset_rate_limiter` fixture calls `limiter.reset()` before every test —
without it, the rate limiter's per-IP counters (slowapi's in-memory store,
keyed by remote address) would leak across test functions, since every
`TestClient` request reports the same address ("testclient"); unrelated
tests hitting a limited endpoint a few times each could eventually trip a
429 that has nothing to do with what they're testing.

Migrations were smoke-tested against a real (non-`:memory:`) SQLite file in
this environment — `alembic upgrade head` runs clean through all three
revisions and WAL mode was confirmed active (`PRAGMA journal_mode` reports
`wal`) — but neither `app.db` nor any real deployment was touched.

`scripts/backup_db.sh` was **not** executed here: this environment has no
`sqlite3` CLI on `PATH` (confirmed via `which sqlite3`), and running it
against a real `app.db` wasn't asked for. Its logic was reviewed by hand
and it passes `bash -n` (syntax check only). Test it yourself once you have
a real `app.db` and the `sqlite3` CLI available, before relying on it.

## Known limitations

- **No resend-verification path.** A user who can't find or loses the
  original verification email currently has no way to trigger a new one
  short of asking you to run something by hand. Worth adding if this
  becomes a real support burden.
- **Rate limiting is in-process, in-memory (slowapi's default storage).**
  Restarting the app resets every counter, and if this ever runs as more
  than one process/worker, each process enforces its own independent limit
  — a determined attacker distributing requests across workers effectively
  gets `limit × worker_count`. Fine for a single-process deployment (the
  brief's current scale); would need a shared backend (Redis, which slowapi
  supports) to hold under multiple workers.
- **Backup script is local-only and untested against a real `app.db`** in
  this environment, per above. It also doesn't verify the gzip'd snapshot
  is a valid SQLite file after backing up — worth a `gzip -t` /
  `sqlite3 ... "PRAGMA integrity_check"` sanity step before you trust it
  unattended long-term.
- **No CAPTCHA or IP reputation checks** beyond the honeypot and rate
  limits — sufficient against unsophisticated bots, not against a
  determined human-solved-CAPTCHA-farm attacker. Not asked for; flagging
  since "open signups" was the stated motivation for this phase.
- **Account deletion is immediate and irreversible** — no grace period, no
  "are you sure" double-confirmation beyond re-entering the password, no
  soft-delete/undo window. Matches "self-service account deletion... this
  cannot be undone" as specified; worth revisiting only if you want a
  cooling-off period later.
- **WAL mode helps concurrent readers/writers but doesn't change the
  single-file-on-single-instance constraint** already noted in
  `docs/phase-3-deployment.md` — still not safe for a multi-instance
  deployment without moving off SQLite.

## Next

All four phases are now built and documented. Waiting for your review
before any of this touches real infrastructure or sends a real email.
