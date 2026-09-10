# Hierarchy, Organization & Summarization — integration guide

What Phase 3 and Phase 5 deliver, and how to call it.

**In scope here:** Subject/Topic/Note hierarchy, automatic topic assignment on
every capture, the `GET /hierarchy` endpoint (nested JSON + narration), voice
organization commands, and summarization by Subject/Topic/time-range.

**Not in scope (owned by others):** audio recording, Whisper, transcript
cleaning, entity extraction, note classification (Team Member 1) · vector/RAG
retrieval, TTS, the final voice-query system, hardware trigger (Team Member 3).

---

## Setup

Nothing extra to install beyond `backend/requirements.txt` (one addition,
`numpy`, already transitively required by the project — see "Assumptions and
open items" below). No new environment variables are required; the hierarchy
settings in `app/config.py` all have working defaults.

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## How this plugs into Team Member 1's pipeline

`app/pipeline/capture_pipeline.py` now calls `app.understanding.organizer.organize()`
right after understanding finishes, in both `run_capture()` (the audio path)
and `run_understanding_on_text()` (the `/understand` path). This call is
wrapped in the same try/except pattern as `_run_understanding()` — **if
organization fails for any reason, the note is still stored**, just with
`topic_id` left `NULL` until it is manually filed or reprocessed. A capture
never fails because organization failed.

You don't need to call anything new. Every note that reaches
`persist_capture()` gets organized automatically. If you have a code path that
persists notes outside `capture_pipeline.py`, call it yourself:

```python
from app.understanding.organizer import organize

assignment = organize(db, note)   # note.topic_id is now set; db.flush()ed, not committed
```

### What changed on `Note`

Four new columns, all nullable (a note that hasn't been organized yet, or
whose organization failed, has them all `NULL` — never a broken FK):

| Column | Type | Notes |
|---|---|---|
| `topic_id` | fk → `topics.id`, `ON DELETE SET NULL` | was already a stub column; now actually populated |
| `topic_assignment_method` | str? | `explicit` \| `embedding` \| `llm-match` \| `heuristic` \| `lnt-theme` \| `lnt-lda` \| `unfiled` |
| `topic_assignment_confidence` | float? | 0–1 |
| `topic_assignment_reason` | text? | one sentence, human-readable, logged and returned |

`NoteOut.source` maps the Phase 1 `CaptureSource` values (`dummy` \|
`microphone` \| `upload` \| `text`) onto the Phase 3 schema's `voice` \| `ocr`
\| `manual` via `app.hierarchy.service.note_source_label()` — a single
function, used by both the hierarchy serializer and `api/v1/serializers.py`,
so there is exactly one place that mapping can drift.

### A Python 3.10 compatibility fix in your files

Your two files used `datetime.UTC` (Python 3.11+). The team's actual dev/test
machine runs Python 3.10.12, where that import fails at startup. I changed
both to the 3.10-and-3.11-compatible form — behavior is identical:

- `app/capture/sources.py`
- (and `app/db/models.py`, which I own)

```python
# before
from datetime import UTC, datetime
datetime.now(UTC)
# after
from datetime import datetime, timezone
datetime.now(timezone.utc)
```

If your machine is on 3.11+, this has no effect either way. Worth pinning
`requires-python` in `pyproject.toml` to what the team actually runs.

---

## The topic-assignment algorithm

`app/understanding/organizer.py`, entry point `organize(db, note) ->
TopicAssignment`. Four branches, tried in order, first match wins. Every
decision is logged (`logger.info("organize note=... -> ...")`) and returned as
a `TopicAssignment` with a `method` and `confidence`, so it is inspectable
without reading source:

1. **Explicit placement.** Regex over the note text for patterns like "file
   this under X", "put this under my X", "this belongs under X", "organize
   this under X". If found, `X` is fuzzy-matched (`difflib`) against existing
   Subject names first, then Topic names; reuses a match above the cutoff,
   otherwise creates a new Subject + Topic named `X`. Confidence `1.0`.
2. **Embedding match.** The note is embedded (`app/hierarchy/embeddings.py` —
   see "Open items" below) and compared against every existing Topic's
   comparison text (topic name + summary + up to 30 member notes' text, so a
   topic with no summary yet still has real signal to match against) via
   cosine similarity. The best match above `topic_similarity_threshold`
   (default `0.72`) wins.
3. **LLM disambiguation.** Only reached if step 2 found nothing above
   threshold. Sends the note text plus a numbered list of existing topic
   names to the shared LLM abstraction and asks for the single best fit, or
   "none." A genuine second opinion, not decorative — this is what actually
   catches paraphrases the offline embedding misses (see "Open items").
   Confidence `0.85` when the LLM picks one.
4. **New topic.** Nothing matched. A topic name is proposed from (in order of
   preference) a supplied LNT theme, a supplied LDA topic, or a small
   heuristic (first few salient words of the note). Filed under the
   `default_subject_name` ("General") unless explicit placement already named
   a subject.
5. **Unfiled.** Empty/whitespace-only text never reaches steps 1–4; it goes
   straight to the singleton Unfiled subject/topic. Confidence `0.0`.

`propose_new_topic(text, themes=None, lda_topics=None)` accepts Team Member
1's `app.nlp.thematic` / `app.nlp.topic_modeling` output when you have it —
neither module is implemented yet, so `organize()` degrades gracefully to the
heuristic without them. Wire it up by passing `organize(db, note, themes=...,
lda_topics=...)` once those modules exist (the parameters are already there).

---

## HTTP API

Base path `/api/v1`.

### Hierarchy — `/hierarchy`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/hierarchy` | The Phase 3 spec's literal endpoint: nested JSON + narration |
| `GET` | `/hierarchy/outline` | Identical payload to the above (same endpoint, discoverable path) |
| `GET` | `/hierarchy/overview` | Just the top-level counts + spoken summary |
| `GET` | `/hierarchy/subjects` | All subjects, nested topics/notes |
| `POST` | `/hierarchy/subjects` | Create a subject `{"name": "..."}` |
| `GET` | `/hierarchy/subjects/{id}/topics` | "What topics are under X?" by id |
| `POST` | `/hierarchy/subjects/{id}/recluster` | Re-run batch DBSCAN clustering over a subject's notes |
| `POST` | `/hierarchy/topics` | Create a topic `{"subject_id", "name", "kind": "topic"|"project"}` |
| `GET` | `/hierarchy/topics/{id}/notes` | "What notes are under X?" by id |
| `POST` | `/hierarchy/topics/{id}/summary` | Force-regenerate one topic's AI summary |
| `POST` | `/hierarchy/notes/{id}/move` | Move by target topic id |
| `POST` | `/hierarchy/notes/{id}/move-by-name` | Move by spoken/typed name, fuzzy-matched, auto-creates a topic if nothing fits |
| `POST` | `/hierarchy/command` | Voice organization commands — see below |

### Summarization — `/summary`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/summary/topics/{id}?refresh=` | The topic's own AI summary (cached unless stale or `refresh=true`) |
| `GET` | `/summary/subjects/{id}` | Subject → Topics → topic summaries → subject roll-up |
| `GET` | `/summary/range?start=&end=&subject_id=&topic_id=` | Roll-up over a time window, optionally scoped |

Interactive docs for all of the above at `/docs`.

---

## Voice-based organization commands

`POST /hierarchy/command` — the one endpoint Team Member 3's voice pipeline
needs for Phase 3's organization commands. Transcribe the utterance, call this
with the resulting text (and, for "move" commands, the note the user currently
has focused), get back something ready to speak.

```jsonc
// request
{"text": "Move this note to Machine Learning.", "focused_note_id": "e9a3134f-..."}
```

Recognizes:

- `"Move this note to Machine Learning."` / `"Move it to X."` / `"Move the
  note to X."` — requires `focused_note_id`; fuzzy-matches `X` against
  existing topics, creating one if nothing close enough exists.
- `"Move this note to my Project Ideas topic."` — same, with the optional
  "my ... topic/project" phrasing spec'd for the second example.
- `"What topics are under Machine Learning?"`
- `"What notes are under Graph Theory?"`

Response shape is always the same regardless of intent:

```jsonc
{
  "intent": "move" | "topics_under" | "notes_under" | "unrecognized",
  "ok": true | false,
  "spoken": "a sentence ready for TTS",
  "data": { /* intent-specific payload, see examples below */ }
}
```

`ok: false` with a `200` status (never a 4xx/5xx) covers every recoverable
failure — an unrecognized utterance, a "move" with no focused note, a subject
or topic name that doesn't exist. Team Member 3's voice loop can always just
speak `spoken` without a separate error-handling branch. The one genuine
`404` in this API surface is calling the id-addressed REST endpoints
(`/hierarchy/notes/{id}/move`, `/hierarchy/topics/{id}/notes`, etc.) with an
id that doesn't exist — those are programmer errors, not user speech, so they
get a real HTTP error status.

---

## Example JSON responses

Captured from a real run against the app (`LLM_PROVIDER=null`, so
`summary`/`method` below show the extractive fallback — with a key configured
these read the same shape with `"method": "llm"`).

### `GET /hierarchy`

```json
{
  "overview": {
    "subject_count": 2,
    "topic_count": 2,
    "note_count": 4,
    "notes_by_type": { "todo": 2, "academic": 2 },
    "spoken": "You have 2 subjects, 2 topics, 4 notes. 2 academic, 2 to-do."
  },
  "subjects": [
    {
      "id": "5c29d886-d0dd-45da-94e8-33db8fbb1823",
      "name": "Groceries",
      "is_unfiled": false,
      "level": 1,
      "topics": [
        {
          "id": "c1952912-1318-4422-bbbb-a4dab91d5020",
          "name": "Groceries",
          "kind": "topic",
          "level": 2,
          "summary": "",
          "summary_stale": true,
          "notes": [
            {
              "id": "1f823c4d-fa0d-4bfe-a210-c3e1bea0662e",
              "topic_id": "c1952912-1318-4422-bbbb-a4dab91d5020",
              "text": "Call the dentist to reschedule. File this under Groceries.",
              "note_type": "todo",
              "source": "manual",
              "created_at": "2026-09-10T17:41:26.785627",
              "updated_at": "2026-09-10T17:41:26.793375",
              "quality_score": 0.6474025
            }
          ]
        }
      ]
    }
  ],
  "narration": "You have 2 subjects, 2 topics, 4 notes. 2 academic, 2 to-do. Under Groceries, there is 1 topic. Under Groceries, there are 2 notes. Under Operating Systems, there is 1 topic. Under Operating Systems, there are 2 notes."
}
```

### `POST /hierarchy/command` — move

```jsonc
// request
{"text": "Move this note to my Project Ideas topic.", "focused_note_id": "e9a3134f-..."}
// response
{
  "intent": "move",
  "ok": true,
  "spoken": "Created a new topic, Project Ideas, and moved the note there.",
  "data": {
    "note_id": "e9a3134f-bcf4-4fc3-935c-08f3fcbf6306",
    "topic_id": "4d4b0c1d-98d5-4d4c-a08e-70cc132489bd",
    "topic_name": "Project Ideas",
    "subject_id": "9d73e5d9-0bc1-464a-ae2a-a82e4edb4deb",
    "subject_name": "Project Ideas",
    "created_new_topic": true
  }
}
```

### `POST /hierarchy/command` — topics under

```jsonc
// request
{"text": "What topics are under Groceries?"}
// response
{
  "intent": "topics_under",
  "ok": true,
  "spoken": "Under Groceries, there is 1 topic: Groceries.",
  "data": {
    "subject_id": "5c29d886-d0dd-45da-94e8-33db8fbb1823",
    "subject_name": "Groceries",
    "topics": ["Groceries"]
  }
}
```

### `GET /summary/subjects/{id}`

```json
{
  "scope": "subject",
  "scope_id": "e3f27a13-c425-41f1-a062-cfbbe847dc96",
  "scope_name": "Operating Systems",
  "note_count": 1,
  "summary": "Operating Systems: A deadlock requires circular wait, hold and wait, no preemption, mutual exclusion....",
  "spoken": "Operating Systems. 1 topic, 1 note. Operating Systems: A deadlock requires circular wait, hold and wait, no preemption, mutual exclusion....",
  "method": "extractive"
}
```

---

## Database schema

Two new tables, one FK'd column added to Team Member 1's `notes` table.
`Base.metadata.create_all` runs on startup, same as Phase 1/2 — no migration
step exists yet anywhere in the project.

### `subjects`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `name` | str | unique |
| `is_unfiled` | bool | exactly one row is `true`, created lazily on first use |
| `created_at` | datetime | |

### `topics`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `subject_id` | fk → `subjects.id`, `CASCADE` | |
| `name` | str | unique within a subject (`UniqueConstraint(subject_id, name)`) |
| `kind` | str | `topic` \| `project` |
| `summary` | text | AI-generated, Idea11y §4.1 |
| `summary_stale` | bool | set `true` whenever a member note is added/edited/moved; regenerated lazily on next read, never blocking the write path |
| `created_at` | datetime | |

### `notes` (Team Member 1's table, four columns added)
See "What changed on `Note`" above.

---

## Tests

```bash
cd backend
python -m pytest tests/ -q
```

208 passed, 1 skipped (pre-existing, Phase 1/2), no network, no LLM key
required — `LLM_PROVIDER=null` throughout, so the suite exercises the
extractive-summary and embedding-match paths by default, with a handful of
tests installing a fake LLM client to exercise the LLM branches without
network access.

| File | Covers |
|---|---|
| `tests/test_hierarchy.py` | The pure in-memory tree/outline/narration structures (`app.hierarchy.tree`, `outline`, `overview`) |
| `tests/test_organizer.py` | Every branch of `organize()`: explicit placement, embedding match, LLM disambiguation (mocked), new-topic creation, Unfiled fallback |
| `tests/test_clustering.py` | The batch DBSCAN re-clustering path, including the Idea11y "subject boundary outranks proximity" precedence |
| `tests/test_hierarchy_api.py` | Every Phase 3 HTTP endpoint, including all four voice-command examples from the spec |
| `tests/test_summarization.py` | `summarize_topic` / `summarize_subject` / `summarize_range`, both extractive and mocked-LLM paths, plus the `/summary/*` HTTP endpoints |

---

## Assumptions and open items

1. **The embedding is a placeholder, by design, per your "ask before adding
   dependencies" instruction.** `app/hierarchy/embeddings.py` is a
   dependency-free deterministic hashed bag-of-words vectorizer (256-dim,
   `blake2b`-hashed buckets) — it captures shared vocabulary, not semantic
   meaning. Two notes phrased very differently about the same thing (e.g.
   "two processes stuck waiting on each other" vs. "a deadlock") won't clear
   the similarity threshold on the embedding alone. The `match_via_llm()` step
   (branch 3 of `organize()`) exists specifically to compensate for this when
   an LLM key is configured; without one, semantically-related-but-differently-worded
   notes may end up as separate topics until reconciled by a recluster or a
   manual move. **If you want real semantic embeddings (e.g.
   `sentence-transformers`, or an embeddings API call), that's a dependency
   decision for the team** — I did not add one unilaterally, per your
   instruction.
2. **`numpy` was added to `requirements.txt`** for the DBSCAN feature-matrix
   math in `hierarchy/clustering.py`. It was already a transitive dependency
   of the project (FastAPI/Pydantic's ecosystem pulls it in indirectly in
   most environments), so this makes an existing dependency explicit rather
   than introducing a new one — flagging it anyway since the instruction was
   to ask first.
3. **No frontend work.** The Phase 3 spec's deliverables are backend-only
   (schema, algorithm, endpoints); `frontend/src/components/Outline/*` and
   related stub files were left untouched.
4. **Python version mismatch found and fixed.** See "A Python 3.10
   compatibility fix" above — `pyproject.toml` says `>=3.11`, the actual dev
   machine runs 3.10.12. Worth the team confirming which is authoritative.
5. **Dev-environment note, not a code issue:** the `backend/.venv` inside the
   OneDrive-synced project folder is broken (a `pip install` there fails with
   `OSError: Operation not permitted` — OneDrive's file-locking conflicts with
   how pip stages package installs). All my testing used a venv created
   outside the synced folder. Recommend deleting `backend/.venv` and
   recreating it outside OneDrive (or excluding `backend/.venv` from sync).
6. **`recluster_subject` is opt-in, not automatic.** Idea11y's clustering is
   surfaced here as an explicit `POST .../recluster` action (matching the
   spec's emphasis on inspectable, non-drifting organization) rather than
   running silently in the background. The incremental `organize()` call on
   every capture is what keeps `topic_id` populated in the steady state.
7. **Explicit-placement phrasing is a fixed set of four patterns** ("file this
   under X", "put this under my X", "this belongs under X", "organize this
   under X"). A user who phrases it differently falls through to embedding/LLM
   matching instead, which is usually fine but won't guarantee landing in the
   named topic the way explicit placement does.
