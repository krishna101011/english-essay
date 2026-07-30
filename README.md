# English Essay Coach

A multi-user website for improving English writing. Users write essays or
book-chapter reflections, get them checked for spelling/punctuation/grammar
locally (free), then get sentence-structure feedback, vocabulary upgrade
suggestions, and a rubric score from an AI model of their choice.

See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for the full design and build order,
and the phase docs for what's built so far:
[Phase 1](docs/phase-1-mvp.md), [Phase 2](docs/phase-2-book-vocab.md),
[Phase 3](docs/phase-3-deployment.md).

## Quickstart (Windows)

Requirements: Python 3.11+, a local Java runtime (17+) for the grammar
checker (see [Adoptium](https://adoptium.net/) if you don't have one).

**First time:**

```
copy .env.example .env
```

Then edit `.env` and set real values for `SESSION_SECRET_KEY` (any random
string) and `ENCRYPTION_KEY` (generate with the command below), and run
`setup.bat`:

```
venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
setup.bat
```

`setup.bat` creates the venv (if it doesn't exist yet), installs
`requirements.txt`, and applies database migrations. It checks for Java and
for `.env` first and stops with a clear message if either is missing,
instead of guessing.

`.env`'s `APP_ENV` defaults to `development`; leave it as-is for local work
(see [docs/phase-3-deployment.md](docs/phase-3-deployment.md) for what
`APP_ENV=production` changes and how to deploy).

**Every time after:**

```
start.bat
```

`start.bat` starts the server in the foreground - keep that window open, since
there's no real email sending locally and verification/reset links print to
this terminal instead (see `app/email/sender.py`) - and opens your browser to
http://localhost:8000 once the server is actually responding.

Sign up, then add an AI provider under Settings before submitting an essay
(the app works without one, but you'll only get local
spelling/grammar/punctuation checks, no sentence-structure feedback,
vocabulary suggestions, or rubric score).

## Manual setup (troubleshooting fallback)

If `setup.bat`/`start.bat` don't work for your environment, here are the
same steps by hand.

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Then edit `.env` and set real values for `SESSION_SECRET_KEY` (any random
string) and `ENCRYPTION_KEY` (generate with the command below):

```
venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Apply database migrations:

```
venv\Scripts\alembic upgrade head
```

Run the server:

```
venv\Scripts\python -m uvicorn app.main:app --reload
```

Visit http://127.0.0.1:8000, sign up, then add an AI provider under
Settings before submitting an essay (the app works without one, but you'll
only get local spelling/grammar/punctuation checks, no sentence-structure
feedback, vocabulary suggestions, or rubric score).

## Test

```
venv\Scripts\pytest
```

Tests mock the AI provider — they never make real API calls.
