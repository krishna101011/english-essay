# English Essay Coach

A multi-user website for improving English writing. Users write essays or
book-chapter reflections, get them checked for spelling/punctuation/grammar
locally (free), then get sentence-structure feedback, vocabulary upgrade
suggestions, and a rubric score from an AI model of their choice.

See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for the full design and build order,
and the phase docs for what's built so far:
[Phase 1](docs/phase-1-mvp.md), [Phase 2](docs/phase-2-book-vocab.md).

## Setup

Requirements: Python 3.11+, a local Java runtime (17+) for the grammar
checker (see [Adoptium](https://adoptium.net/) if you don't have one).

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

## Run

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
