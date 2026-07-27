# Security notes: CSRF protection

Status: complete. This wasn't in `PROJECT_BRIEF.md` and should have been -
every route that changes state was reachable by a plain `<form>` POST with
no protection against a cross-site forgery.

## Approach: double-submit cookie, no new dependency

Chose the double-submit-cookie pattern over a library (e.g.
`starlette-csrf`, `fastapi-csrf-protect`) for two reasons: it's about 40
lines of code total (`app/auth/csrf.py`), and it needs no server-side
session storage of tokens beyond the cookie itself - a good fit for an app
that's otherwise entirely stateless aside from the signed session cookie.

How it works:

1. **`CSRFCookieMiddleware`** (Starlette `BaseHTTPMiddleware`, registered in
   `app/main.py`) runs on every request. If the request has no `csrf_token`
   cookie yet, it generates one (`secrets.token_urlsafe(32)`) and sets it on
   the response (`httponly=True`, `samesite="lax"`, `secure=IS_PRODUCTION`).
   It also stashes the token on `request.state.csrf_token` so templates can
   read it without every route handler having to pass it through the
   context dict explicitly.
2. Every `<form method="post">` in the templates renders that token into a
   hidden field: `<input type="hidden" name="csrf_token" value="{{
   request.state.csrf_token }}">`.
3. **`verify_csrf`** (a FastAPI dependency, also in `app/auth/csrf.py`)
   reads the submitted `csrf_token` form field and compares it against the
   `csrf_token` cookie using `secrets.compare_digest` (constant-time, to
   avoid a timing side-channel on the comparison itself). A missing or
   mismatched token raises `HTTPException(403)`.

Why this defeats CSRF: a same-origin page can read its own `csrf_token`
cookie's value indirectly, because the *server* reads it and renders it
into the form - the browser never needs to expose it to JavaScript. A
cross-site attacker's forged form can make the victim's browser *send* the
cookie (cookies aren't origin-scoped to the page that sends the request),
but the attacker's page cannot *read* that cookie's value to also put it in
the hidden field, because of same-origin policy. Without knowing the value,
the attacker can't produce a request where the submitted field matches the
cookie, so `verify_csrf` rejects it.

## What's protected

`Depends(verify_csrf)` was added to every state-changing route:

| Route | File |
|---|---|
| `POST /signup` | `app/auth/routes.py` |
| `POST /login` | `app/auth/routes.py` |
| `POST /logout` | `app/auth/routes.py` |
| `POST /settings` (save AI provider) | `app/ai/routes.py` |
| `POST /settings/test` (test connection) | `app/ai/routes.py` |
| `POST /` (new essay/chapter) | `app/documents/routes.py` |
| `POST /documents/{id}` (revise essay/chapter) | `app/documents/routes.py` |
| `POST /vocab/{id}/toggle-mastered` | `app/vocab/routes.py` |

`/logout` and `/settings/test` weren't named explicitly in the request but
are state-changing POSTs (session teardown; `last_verified_at`/`is_active`
writes respectively), so they're covered too for consistency - "every
state-changing route" was the actual instruction, the named list was
illustrative.

GET routes are untouched: reads don't need CSRF protection, and every page
that renders a POST form already has a fresh `request.state.csrf_token`
available regardless of which route rendered it, since the middleware runs
globally.

## Testing

`tests/test_csrf.py` (9 tests) covers, per protected router:

- A request with no CSRF cookie at all is rejected (403).
- A request with a cookie present but a submitted token that doesn't match
  it is rejected (403) - this is the actual forged-cross-site-request
  scenario, not just "field missing."
- A request where the submitted token matches the cookie succeeds
  (login redirects, essay submit renders 200, vocab toggle flips
  `mastered` and redirects).

Covered end-to-end via `fastapi.testclient.TestClient` against the real
app (`tests/conftest.py`'s new `client` fixture), with `get_db` overridden
to the same in-memory SQLite session the other DB-touching fixtures use.
One fixture change was needed to make this work: the in-memory engine now
uses `poolclass=StaticPool` (`tests/conftest.py`) - without it, the ASGI
dispatch path TestClient uses can hand out a second physical connection to
the `sqlite:///:memory:` URL, which SQLite treats as an entirely separate,
table-less database, causing spurious "no such table" errors unrelated to
CSRF itself.

No real AI provider calls are made by these tests; the essay-submit test
exercises the "no AI provider configured" degrade-gracefully path already
covered by `tests/test_pipeline.py`, since CSRF enforcement happens before
route logic runs regardless of what that logic does downstream.

## Known limitations

- The CSRF cookie is not itself encrypted or tied to the session - it's a
  random opaque value, which is all the double-submit pattern requires.
  If the session cookie is ever compromised via XSS, the CSRF cookie
  provides no additional protection (XSS bypasses CSRF defenses generally,
  by design - they defend against different threats).
- `same_site="lax"` (matching the session cookie's setting from Phase 3)
  blocks the vast majority of cross-site POST forgeries on its own in
  modern browsers; this implementation is defense in depth for older
  browsers or `same_site` misconfigurations, not the only layer.
- No rate limiting or password-reset flow yet - unrelated to CSRF,
  carried over as a known gap from Phase 1.
