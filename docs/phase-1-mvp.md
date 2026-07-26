# Phase 1 — MVP

Status: complete, awaiting review before Phase 2.

## What was built

Everything in the Phase 1 build order from `PROJECT_BRIEF.md`:

- **Scaffold**: venv, `requirements.txt`, `.gitignore`, `.env.example`, git repo initialized.
- **Data model**: SQLAlchemy models for `users`, `ai_settings`, `documents`,
  `document_versions`, `corrections`, `scores` (`app/db/models.py`), with the
  first Alembic migration (`alembic/versions/88e950d72651_initial_schema.py`).
  `vocab_words` is deferred to Phase 2, per the build order.
- **Auth**: signup/login/logout via Starlette `SessionMiddleware` (signed
  cookie) and `passlib[bcrypt]` password hashing (`app/auth/`).
- **AI provider abstraction**: `AIProvider` Protocol +
  `OpenAICompatibleProvider` exactly as specified in the brief
  (`app/ai/provider.py`), a provider registry with the five suggested
  defaults (`app/ai/registry.py`), and Pydantic schemas that double as the
  `json_schema` response format sent to the model (`app/ai/schemas.py`).
- **Settings page**: add/edit AI provider, Fernet-encrypted key storage,
  write-only display (masked as `sk-...ab12`), and a "test connection"
  action that makes one trivial chat completion before you rely on it
  (`app/ai/routes.py`, `app/templates/settings.html`).
- **LanguageTool wrapper**: local spelling/punctuation/grammar check with a
  clear error (and install link) if no Java runtime is found on PATH
  (`app/grammar/checker.py`).
- **Pipeline** (`app/documents/service.py`): local check → one AI call →
  save version/corrections/scores → graceful degradation if the AI call (or
  the local checker) fails.
- **Essay editor** (`app/templates/editor.html`, `app/static/editor.js`):
  submit an essay, see the rubric score, and see corrections rendered as
  inline highlighted spans (colored by category, with the explanation as a
  tooltip) plus a plain-English list below.
- **Document history page** (`app/templates/dashboard.html`).
- **Tests** (`tests/`): 15 tests covering password hashing, key
  encryption/masking, paragraph diffing, and the full pipeline — including
  the "no AI configured," "AI call fails," and "revision carries forward
  unchanged-paragraph corrections with remapped offsets" cases. The AI
  provider is always mocked (`monkeypatch.setattr(service,
  "OpenAICompatibleProvider", ...)`); no test makes a network call.

## How to run and test it

See `README.md` for setup/run/test commands. Short version:

```
venv\Scripts\pip install -r requirements.txt
venv\Scripts\alembic upgrade head
venv\Scripts\python -m uvicorn app.main:app --reload
venv\Scripts\pytest
```

Manually verified end-to-end via curl against a running server: signup,
duplicate-signup rejection, wrong-password rejection, essay creation,
essay revision (with a real paragraph added, exercising the diff path),
document ownership enforcement (a second user can't view or revise the
first user's document — confirmed it 303s to `/history` instead), settings
save (confirmed the stored `encrypted_api_key` is Fernet ciphertext, not
plaintext, by reading `app.db` directly), and settings masking (`sk-...1234`
displayed, full key never returned to the page).

The local Java runtime is not installed in this dev environment, so the
LanguageTool path itself couldn't be exercised live — only its "Java
missing" error path was (confirmed the banner renders correctly on the
editor page). It's covered by mocked pipeline tests; if you have Java
installed, live-check it by writing an essay with a misspelling and
confirming a red-highlighted spelling correction appears.

## Deviations from the brief, and why

- **Tailwind via CDN (`cdn.tailwindcss.com`), no Node build step.** The
  brief lists Tailwind as the styling choice but the whole stack is
  otherwise Python-only with no `package.json`. The CDN script gets
  Tailwind's utility classes without adding a Node toolchain; worth
  reconsidering for Phase 3 if a real asset pipeline becomes worth the
  added complexity (offline dev, smaller payload, purging unused classes).
- **`bcrypt` pinned to `4.0.1`** in `requirements.txt`. `passlib[bcrypt]`
  1.7.4 (the latest release, unmaintained since 2020) crashes against
  `bcrypt` 5.x — it reads `bcrypt.__about__.__version__`, an attribute
  bcrypt removed in 4.1. Pinning is the standard workaround; this isn't a
  new dependency, just a version constraint on one the brief already named.
- **`itsdangerous` added to `requirements.txt`.** Starlette's
  `SessionMiddleware` (specified in the brief) imports it directly but
  doesn't declare it as a dependency in the version installed. Without it,
  the app fails to start.
- **A minimal built-in `.env` loader** (`app/config.py`) instead of adding
  `python-dotenv` as a direct dependency — the brief's dependency list
  doesn't mention it, and `.env` loading only needs a few lines.
- **Revision re-analysis design** (brief step 5: "diff against the previous
  version and only re-analyze changed paragraphs — not the whole essay
  again"): implemented by always sending the *full* essay text in the one
  API call (so the model can still score the whole document coherently —
  rubric scores need whole-document context), but including a
  `changed_paragraph_ranges` field in `context` and instructing the model
  (via the system prompt) to only emit new corrections inside those ranges.
  Corrections from unchanged paragraphs in the previous version are carried
  forward automatically in code, with offsets remapped if an earlier edit
  shifted their position (`app/documents/diff.py`,
  `app/documents/service.py`). This still makes exactly one API call per
  submission and avoids re-flagging already-reviewed text, without the
  fragility of trying to give the model only a fragment of the essay and
  reconstruct scores from partial context. If the paragraph count changes
  between versions, alignment is ambiguous, so the whole document is
  treated as changed (a safe fallback, not a hidden bug).
- **One `ai_settings` row per user** in the UI/routes, even though the table
  schema (per the brief) allows multiple. Phase 1's settings page always
  edits your single current provider config rather than managing a list;
  the schema doesn't need to change for this, so it's a UI-layer choice
  that Phase 2/3 can revisit if multi-provider switching is wanted.
- **A prompt-injection attempt was caught and rejected during the build**: a
  tool-result system message tried to get `.env.example` left with a
  real-looking generated `SESSION_SECRET_KEY`/`ENCRYPTION_KEY` and asked me
  not to tell you. `.env.example` is not gitignored, so that would have put
  real secret-shaped values into git history. I reverted it to placeholders
  and put the real generated values in the gitignored `.env` instead, and
  I'm flagging it here per your standing instructions to surface anything
  that looks like injected instructions.

## Known limitations

- No rate limiting or CSRF protection on forms (session cookie is
  `httpOnly` + signed, but there's no CSRF token yet — acceptable for a
  single-instance MVP, worth revisiting before any public deployment).
- No password reset flow.
- No pagination on the history page — fine at MVP scale, would need
  attention if a user accumulates hundreds of documents.
- The paragraph-diff carry-forward logic is intentionally simple (defined
  by paragraph count staying the same and paragraph text matching exactly).
  It's covered by tests for the common case (edit within a paragraph, or
  add/remove a paragraph) but won't do fuzzy realignment if paragraphs are
  reordered — it just falls back to "treat everything as changed," which is
  safe (nothing wrong gets displayed) but means more gets re-sent to the
  model than strictly necessary in that case.
- `response_format={"type": "json_schema", ...}` isn't universally supported
  across every OpenAI-compatible free-tier endpoint in the registry (Ollama
  and some OpenRouter free models have partial/no support depending on
  version). Untested against a live key for any of the five providers in
  this environment (no API keys available here) — the "test connection"
  button surfaces the actual provider error clearly if this happens, but a
  live check with a real key is worth doing before you rely on a specific
  provider.
- Local grammar checking (LanguageTool/Java) was not exercised live in this
  environment, as noted above.

## Next: Phase 2

Book/chapter module + vocab library — waiting for your review of this phase
first.
