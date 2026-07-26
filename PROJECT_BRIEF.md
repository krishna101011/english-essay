# Project brief: english-essay

A multi-user website for improving English writing. Users write essays or
book-chapter reflections, get them checked for spelling/punctuation/grammar
(free, local), then get sentence-structure feedback, vocabulary upgrade
suggestions, and a rubric score from an AI model — using whichever free-tier
API key the user configures in their own account settings.

Read this whole file before writing any code. Follow the build order at the
bottom exactly — implement one phase, stop, document it, and wait for review
before starting the next. Do not skip ahead.

## Tech stack (do not substitute without asking)

| Layer | Choice |
|---|---|
| Backend | FastAPI + Uvicorn, Python 3.11+ |
| ORM / migrations | SQLAlchemy + Alembic |
| Database | SQLite (file-based) for now, behind the ORM so a later move to Postgres is a connection-string change only |
| Auth | Starlette `SessionMiddleware` (signed httpOnly cookie) + `passlib[bcrypt]`. No JWT. |
| Local grammar check | `language_tool_python` (wraps LanguageTool; requires a local Java runtime — check for `java` on first run and print a clear error with install instructions if missing) |
| AI provider client | `openai` Python SDK, repointed via `base_url` per provider |
| Secret encryption | `cryptography` (Fernet symmetric encryption) |
| Frontend | Jinja2 templates + HTMX for partial updates + Tailwind CSS. Vanilla JS only where necessary (the essay editor's inline-highlight rendering). No SPA framework. |

## The AI provider abstraction (core design constraint)

Do not hardcode any single AI vendor into business logic. Build one interface:

```python
class AIProvider(Protocol):
    def analyze(self, essay_text: str, local_findings: dict, context: dict) -> EssayFeedback: ...
```

Default implementation, `OpenAICompatibleProvider`, must work unmodified for
Google Gemini (OpenAI-compatible endpoint), Groq, OpenRouter, and local
Ollama — only `api_key`, `base_url`, and `model` change per provider:

```python
class OpenAICompatibleProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def analyze(self, essay_text, local_findings, context):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[SYSTEM_PROMPT, {"role": "user", "content": build_user_message(essay_text, local_findings, context)}],
            response_format={"type": "json_schema", "json_schema": ESSAY_FEEDBACK_SCHEMA},
        )
        return EssayFeedback.parse(response)
```

Provider registry / suggested defaults for the settings dropdown:

| Provider | base_url | Example free model |
|---|---|---|
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| OpenRouter | `https://openrouter.ai/api/v1` | any `*:free` model |
| Ollama (local) | `http://localhost:11434/v1` | whatever the user has pulled |
| Custom | user-supplied | user-supplied |

## Per-user API key storage (non-negotiable security requirements)

- One master secret in the environment (`ENCRYPTION_KEY`, a Fernet key) —
  never committed, never logged.
- Each user's provider API key is encrypted with that master key before it
  is written to the `ai_settings` table. It is decrypted only in memory, only
  for the duration of the outgoing call to that user's provider.
- The settings form is write-only: after saving, return and display only a
  masked value (e.g. `sk-...ab12`). Never pre-fill the decrypted key into a
  form field. Never include it in a JSON response to the frontend.
- Include a "test connection" action that makes one trivial call to confirm
  the key/model/base_url work before the user relies on it.

## Data model

```
users              id, email (unique), password_hash, created_at
ai_settings        id, user_id FK, provider, encrypted_api_key, model_name,
                    base_url (nullable), is_active, last_verified_at
documents          id, user_id FK, type (essay | book_chapter), title,
                    book_title (nullable), author (nullable), created_at
document_versions  id, document_id FK, content, version_number, submitted_at
corrections        id, version_id FK, category (spelling | punctuation |
                    grammar | sentence_structure | vocab), start_offset,
                    end_offset, original_text, suggested_text, explanation,
                    source (local | llm)
scores             id, version_id FK, overall_score, grammar_score,
                    vocab_score, structure_score, clarity_score,
                    feedback_summary
vocab_words        id, user_id FK, word, definition, example_sentence,
                    source_document_id (nullable), times_suggested, mastered,
                    added_at
```

## Core pipeline (`app/documents/service.py`)

1. On submission, run LanguageTool locally first — spelling, punctuation,
   basic grammar. No API call for this step.
2. Make exactly ONE call to the user's configured AI provider per
   submission, containing the essay text plus the local findings. Ask for:
   sentence-structure feedback, vocabulary upgrade suggestions, and a rubric
   score (grammar, vocabulary richness, structure, clarity) with a short
   qualitative summary. Force structured JSON output via
   `response_format`/`json_schema` — do not accept free-form prose.
3. Save the version, all corrections (tagged `source`), and the score.
4. Return corrections with character offsets so the frontend can render
   inline underlines at the right position in the text.
5. On a resubmission/revision, diff against the previous version and only
   re-analyze changed paragraphs — not the whole essay again.
6. If the provider call fails (rate limit, bad key, network), fail
   gracefully: still show the local LanguageTool results, and surface a
   clear, specific error for the AI portion rather than a blank failure.

## Folder structure

```
english-essay/
  README.md                 project overview + setup/run instructions
  PROJECT_BRIEF.md           this file
  docs/
    phase-1-mvp.md           written AFTER phase 1 is done
    phase-2-book-vocab.md    written AFTER phase 2 is done
    phase-3-deployment.md    written AFTER phase 3 is done
  app/
    main.py
    auth/                    signup, login, logout, session helpers
    ai/                      AIProvider interface, OpenAICompatibleProvider,
                              provider registry, Pydantic schemas
    grammar/                 LanguageTool wrapper
    documents/                essay + book-chapter routes, the pipeline service
    vocab/                   vocab library + suggestion routes
    db/                      SQLAlchemy models, session/engine setup
    templates/
      base.html
      editor.html
      settings.html
      dashboard.html
    static/
      editor.js               inline-highlight rendering for the essay editor
      style.css
  alembic/
  tests/
  requirements.txt
  .env.example
  .gitignore
```

Each `docs/phase-N-*.md` is a record written after that phase is complete —
what was actually built, any deviations from this brief and why, how to run
and test it, and known limitations. Not written in advance.

## Environment variables (`.env.example`)

```
DATABASE_URL=sqlite:///./app.db
SESSION_SECRET_KEY=change-me
ENCRYPTION_KEY=generate-with-fernet-generate-key
```

## Build order — implement one phase at a time, stop between phases

### Phase 1 — MVP
1. Scaffold the project: venv, `requirements.txt`, `.gitignore`, `.env.example`, git init.
2. SQLAlchemy models + first Alembic migration for `users`, `ai_settings`,
   `documents`, `document_versions`, `corrections`, `scores`.
3. Auth: signup, login, logout, session middleware, password hashing.
4. Settings page: add/edit AI provider, encrypted key storage, test-connection action.
5. `AIProvider` interface + `OpenAICompatibleProvider`.
6. LanguageTool wrapper (local check).
7. Essay editor page: textarea, submit, runs the full pipeline, renders score
   + inline corrections with plain-English explanations.
8. Document history list page.
9. Basic tests for the pipeline logic, with the AI provider call mocked —
   tests must never make real API calls.
10. Write `docs/phase-1-mvp.md`. Stop and wait for review.

### Phase 2 — Book/chapter module + vocab (only after Phase 1 is approved)
1. Extend the editor to support `type=book_chapter` with `book_title`/`author` fields.
2. Vocab library page: words pulled from AI suggestions, with definition and
   example sentence, simple mastered/not-mastered toggle.
3. Score-over-time chart on the dashboard.
4. Write `docs/phase-2-book-vocab.md`. Stop and wait for review.

### Phase 3 — Deployment prep (only after Phase 2 is approved)
1. Production settings split from dev settings (env-driven).
2. Notes/scripts for deploying to a small VPS or platform (Fly.io/Railway/Render).
3. HTTPS/domain checklist, since sessions and passwords require it once this
   leaves your local machine.
4. Write `docs/phase-3-deployment.md`.

## Non-negotiables

- Never commit `.env` or any real API key.
- Never return a decrypted provider key to the frontend.
- Keep the `AIProvider` interface generic — no vendor SDK reaches into
  `documents/`, `vocab/`, or any route handler directly.
- Ask before adding any dependency not listed in this brief.
- After each phase, stop, summarize what changed, and wait for explicit
  approval before continuing to the next phase.
