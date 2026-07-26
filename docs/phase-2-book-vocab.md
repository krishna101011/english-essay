# Phase 2 — Book/chapter module + vocab

Status: complete, awaiting review before Phase 3.

## What was built

- **Book/chapter documents**: the new-document form (`app/templates/editor.html`)
  now has an Essay / Book-chapter-reflection radio toggle. Choosing "Book
  chapter reflection" reveals `book_title`/`author` fields (plain JS
  show/hide, no new dependency). `app/documents/routes.py::editor_create`
  validates `doc_type` against the `DocumentType` enum (falls back to
  `essay` on anything unrecognized) and only stores `book_title`/`author`
  when the type is `book_chapter`. The pipeline already read
  `document.type`/`book_title`/`author` into the AI call's `context` back in
  Phase 1, so no `service.py` changes were needed there — verified with a new
  test (`tests/test_book_chapter.py`) asserting the mocked provider receives
  `book_title`/`author` in `context`.
- **`vocab_words` table**: added the `VocabWord` model
  (`app/db/models.py`) exactly per the brief's data model, plus a new
  Alembic migration (`alembic/versions/354365d4ca9a_add_vocab_words.py`).
  Added a `UniqueConstraint(user_id, word)` (see Deviations) so repeat
  suggestions can be detected and counted instead of duplicated.
- **Vocab suggestions from the AI call**: `LLMCorrection` (`app/ai/schemas.py`)
  gained optional `definition`/`example_sentence` fields, and the system
  prompt (`app/ai/provider.py`) now asks the model to fill them in whenever
  it emits a `category=vocab` correction. In the pipeline
  (`app/documents/service.py::submit_version`), any `vocab` correction that
  comes back with both fields populated is upserted into the user's vocab
  library via the new `app/vocab/service.py::upsert_suggested_word`
  (case-insensitive match on `word`; a repeat suggestion increments
  `times_suggested` rather than creating a duplicate row; `mastered` is left
  untouched on repeats). If the model omits `definition` or
  `example_sentence` for a vocab correction, the correction is still saved as
  usual but no library entry is created — covered by
  `tests/test_vocab.py::test_pipeline_skips_vocab_word_when_definition_missing`.
- **Vocab library page** (`app/vocab/routes.py`, `app/templates/vocab.html`):
  `GET /vocab` lists the current user's words (unmastered first, newest
  first), each showing word/definition/example sentence and a suggestion
  count when > 1. `POST /vocab/{id}/toggle-mastered` flips the mastered flag
  (ownership-checked against `user_id`) and redirects back. A "Vocabulary"
  link was added to the nav in `base.html`.
- **Score-over-time chart** on the dashboard (`app/documents/routes.py::history`,
  `app/templates/dashboard.html`, `app/static/dashboard.js`): a single-series
  SVG line chart of `overall_score` across all of the user's document
  versions (across every document, not per-document), ordered by
  `submitted_at`, with a hover tooltip (title + date + score) and a direct
  label on the last point. Rendered with plain SVG/vanilla JS — no charting
  library added. Only shown once there are 2+ scored versions to plot.
- **Tests** (`tests/test_vocab.py`, `tests/test_book_chapter.py`): 5 new
  tests — vocab word creation, case-insensitive de-dup with suggestion
  counting, pipeline integration (vocab correction → library entry),
  skip-on-missing-fields, and book-chapter context passed to the AI call.
  The AI provider is mocked in every new test the same way Phase 1 did it
  (`monkeypatch.setattr(service, "OpenAICompatibleProvider", ...)`); no test
  makes a network call. Full suite: 20 passed (15 from Phase 1 + these 5).

## How to run and test it

Same as Phase 1 — see `README.md`. Since a new table was added, run the
migration before starting the server:

```
venv\Scripts\alembic upgrade head
venv\Scripts\pytest
```

`pytest` should report 20 passed. Manually verified via a running server:
signup/login, creating a book-chapter document (form toggle reveals
book_title/author, values persist and render back on the document's page),
`/vocab` renders correctly with no words yet ("No words yet..." empty
state), and the dashboard chart correctly stays hidden with fewer than 2
scored versions.

I was not able to do a full live click-through with a real AI provider key
in this environment (no API keys available here, same limitation noted in
Phase 1), so the vocab-library-gets-populated-by-a-real-model path and the
populated score chart are verified by the mocked pipeline tests above, not
by live browser use. If you have a free-tier key configured, the fastest
live check is: submit an essay with an obviously weak word choice ("The
essay was good."), then check `/vocab` for a new entry, and submit a second
essay to see the dashboard chart appear.

## Deviations from the brief, and why

- **`UniqueConstraint(user_id, word)` on `vocab_words`**, not in the brief's
  data model. Without it, resubmitting/revising an essay that still contains
  the same weak word would create a new row every time instead of using
  `times_suggested` (a column the brief's own schema included, implying
  de-dup was intended). Matching is case-insensitive (`func.lower`) so
  "Meticulous" and "meticulous" count as the same word.
- **`LLMCorrection.definition`/`example_sentence` added as optional fields**,
  not in the brief's schema. The brief says vocab words carry a definition
  and example sentence, but the existing `EssayFeedback`/`LLMCorrection`
  schema (from Phase 1, unchanged in this area) had no field to carry them
  back from the model. Rather than a second API call (the brief requires
  exactly one call per submission), these ride along on the existing
  `vocab`-category correction and are simply ignored/absent for
  `sentence_structure` corrections.
- **Score chart is account-wide, not per-document.** The brief says "chart
  on the dashboard," and the dashboard already lists all of a user's
  documents — an account-wide trend line answers "am I improving?" more
  directly than one chart per document would. Worth revisiting if you'd
  rather see per-document trends instead.
- **No new charting dependency.** Built as inline SVG + vanilla JS
  (`app/static/dashboard.js`), consistent with the brief's "vanilla JS only
  where necessary" frontend rule and the existing `editor.js` pattern.

## Known limitations

- Vocab word matching is exact-word (case-insensitive), not
  lemma/stem-aware — "commendable" and "commendably" would be tracked as
  separate words.
- No pagination on the vocab library page, same rationale as the Phase 1
  history page (fine at this scale).
- The score chart's x-axis is date-only (`YYYY-MM-DD`); multiple
  submissions on the same day render at the same x position with no
  same-day jitter.

## Follow-up: manual verification pass

Done in a later session, after the rest of Phase 2 above. The prior pass
didn't have a live browser or a real AI provider key available, so the
book-chapter flow, the vocab mastered toggle, and the score chart with real
pipeline-generated data were only covered by unit tests, not clicked
through. This time:

- Started the real app (`uvicorn`, `venv\Scripts\python.exe -m uvicorn
  app.main:app`) plus a small local stand-in for an OpenAI-compatible
  endpoint (a throwaway FastAPI app, not part of this repo) that returns
  fixed canned feedback from `POST /v1/chat/completions`. Pointed a
  `custom`-provider `AISettings` row at it (`base_url=http://127.0.0.1:.../v1`),
  so the full pipeline — real HTTP client, real `response_format` parsing,
  real DB writes — ran without any real API key or network call leaving the
  machine.
- The Chrome extension wasn't connected for the first part of this pass, so
  signup/login/settings/document-creation were driven via `curl` with a
  cookie jar instead — same routes, forms, and redirects a browser would
  hit. Confirmed: settings save + "test connection" succeeds against the
  mock provider; creating a `book_chapter` document renders "Revise this
  book chapter" and the `book_title`/`author` line correctly; the vocab
  correction from the mock response appears in `/vocab`; a second
  submission produces a second scored version.
- The extension reconnected partway through, so the score chart, the
  book-chapter radio toggle, and the vocab mastered button were then
  clicked through in an actual rendered Chrome tab (screenshots taken).

**Bug found and fixed**: the score-chart tooltip (`app/static/dashboard.js`)
had no `white-space: nowrap`, so hovering the rightmost point — near the
card's edge — wrapped the tooltip text into a vertical one-word-per-line
column that overflowed below the chart card instead of showing
`"A short essay — 2026-07-26: 92"` on one line. Fixed by adding
`whitespace-nowrap` and flipping the tooltip to the left of the cursor when
there isn't enough room to the right, so it never overflows the container.
While in there, also widened each point's hover hit-target from a bare
4px-radius `<circle>` to that circle plus an invisible 10px-radius circle
layered under it — the visible dot was genuinely small to hover precisely,
independent of the tooltip-wrapping bug. Verified the fix in the browser
(tooltip renders as one line, on both the leftmost and rightmost points, no
overflow) and confirmed no test regressions (`pytest`: 20 passed,
unchanged — `dashboard.js` has no dedicated unit tests, same as `editor.js`
in Phase 1).

Everything else — book/chapter creation, the mastered toggle (checked both
directions), the chart rendering with real scores (84 → 92 across two
mock-provider-scored submissions) — worked on the first try with no other
changes needed.

One thing worth knowing: the local dev `app.db` now has a
`verify2@example.com` test account with two sample documents (an essay and
a book-chapter reflection) and one vocab word from this verification pass.
Harmless test data, not committed (`app.db` is gitignored), but flagging it
in case you were about to click around your own dev DB and wondered where
it came from.

## Next: Phase 3

Deployment prep — waiting for your review of this phase first.
