# EchoNotes

Voice-first, screen-reader-first note-taking for blind and low-vision users.

Speak a note. It is transcribed, cleaned, classified, filed into a hierarchy, indexed, and made
answerable by voice — and everything the system does is said out loud, because the people it is
built for cannot see a screen change.

```
Trigger → Record → Transcribe → Understand → Classify → Organize → Store → Index → Retrieve → Respond
```

---

## Contents

- [What it does](#what-it-does)
- [Setup](#setup)
- [System architecture](#system-architecture)
- [RAG flow](#rag-flow)
- [API endpoints](#api-endpoints)
- [Database structure](#database-structure)
- [Configuration](#configuration)
- [Tests](#tests)
- [How this maps to LNT and Idea11y](#how-this-maps-to-lnt-and-idea11y)

---

## What it does

| # | Feature | Where it lives |
|---|---------|----------------|
| 1 | Voice-based note capture — trigger, record, transcribe | `app/capture`, `app/asr` |
| 2 | AI note understanding — clean, extract people/dates/tasks | `app/nlp/preprocess.py`, `app/understanding` |
| 3 | Classification & hierarchical organization | `app/understanding/classifier.py`, `app/understanding/organizer.py`, `app/hierarchy` |
| 4 | Voice retrieval & assistance (RAG) + TTS | `app/rag`, `app/tts` |
| 5 | Smart reminders & contacts | `app/reminders` |
| 6 | AI summarization by topic, subject, time range | `app/hierarchy/summarization.py` |
| 7 | Image / OCR note capture | `app/ocr` *(stub — not implemented)* |

**It runs fully offline on the defaults.** No API key, no model download, no microphone. The LLM
is an optional enhancement everywhere it appears, never a dependency: rules run first, and any
LLM failure falls back rather than propagating. Retrieval, classification, summarization and
answering all have a working non-LLM path.

---

## Setup

```bash
cd backend && pip install -r requirements.txt
```

```bash
cd backend && uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server proxies `/api` and `/health` to the
backend on port 8000, so run the backend first.

```bash
cd frontend
npm run build     # production bundle into dist/
npx vitest run    # component smoke tests
```

### If the notes list returns 500

`create_all()` creates missing tables but never adds a column to an existing
one, so a database file created before a column was added will fail every query
against that table. Fix it without losing notes:

```bash
cd backend
python scripts/sync_db_schema.py --apply
```

That is all that is required. `POST /api/v1/trigger` works immediately on a fresh machine: the
default `dummy` capture source replays a fixture wav, so no microphone is needed. Interactive API
docs are at http://127.0.0.1:8000/docs.

If the fixture is missing, regenerate it:

```bash
cd backend && python scripts/make_fixture_audio.py
```

The Whisper model (~140 MB for `base`) downloads on the first *real* transcription and is cached
afterwards.

### Optional extras

Neither is required, and both are commented out in `requirements.txt`:

- **`sentence-transformers`** — semantic embeddings for retrieval. The default hashed backend
  matches shared vocabulary, not meaning. Installing this pulls in torch (~500 MB–2 GB). Then set
  `EMBEDDING_BACKEND=sentence-transformers` and run `POST /api/v1/retrieval/reindex`.
- **`pyttsx3`** — server-side speech synthesis to a wav file, for headless demos. Then set
  `TTS_ENGINE=pyttsx3`.

---

## System architecture

Three phases of work by three people, sharing one pipeline and one database.

```
                          POST /api/v1/trigger
                                   │
   ┌───────────────────────────────▼───────────────────────────────┐
   │  app/pipeline/capture_pipeline.py                             │
   │                                                               │
   │  1. capture      app/capture/sources.py    dummy | microphone │
   │                                            | upload | text    │
   │  2. transcribe   app/asr/transcriber.py    faster-whisper     │
   │  3. clean        app/nlp/preprocess.py                        │
   │  4. store        app/db/repositories.py    → notes            │
   │  5. understand   app/understanding/        → classification,  │
   │                    service.py                entities, quality│
   │  6. organize     app/understanding/        → Subject/Topic    │
   │                    organizer.py                               │
   │  7. index+derive app/rag/indexer.py        → vectors          │
   │                  app/reminders/service.py  → reminders        │
   │                  app/reminders/contacts.py → contacts         │
   └───────────────────────────────────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
   ┌──────────────────────┐                  ┌──────────────────────┐
   │ SQLite               │                  │ ChromaDB             │
   │ authoritative        │  ── rebuildable ▸│ derived index        │
   └──────────────────────┘                  └──────────────────────┘
              │                                         │
              └────────────────────┬────────────────────┘
                                   ▼
                      POST /api/v1/retrieval/query
                       app/rag/service.py
```

**Stages 5, 6 and 7 are each independently wrapped in try/except.** A capture the user already
spoke is never lost because something downstream of it failed. A note that fails to index is still
stored, still filed, and still readable — only temporarily unfindable by search, and
`POST /retrieval/reindex` repairs that.

**SQLite is authoritative; the vector index is derived.** Anything in Chroma can be rebuilt from
the notes table, which is what makes an indexing failure a degradation rather than data loss.

### Ownership

| Phase | Scope | Owner |
|---|---|---|
| 1–2 | Capture, Whisper transcription, cleaning, entity extraction, classification, quality scoring, LLM abstraction | Team Member 1 · [docs/pipeline-handoff.md](docs/pipeline-handoff.md) |
| 3 | Subject/Topic/Note hierarchy, topic assignment, outline & narration, organization commands, summarization | Team Member 2 · [docs/hierarchy-handoff.md](docs/hierarchy-handoff.md) |
| 4–6 | RAG retrieval, voice query, TTS, reminders, contacts, end-to-end integration | Team Member 3 · [docs/retrieval-handoff.md](docs/retrieval-handoff.md) |

---

## RAG flow

```
  utterance (text, or audio → Whisper)
        │
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 1. INTENT          app/rag/intent.py                     │
  │    search | ask | when | summarize | list_subjects |      │
  │    topics_under | count_notes | navigate | organize |     │
  │    reminders                                             │
  │    + slots: query text, note type, date range, target    │
  └──────────────────────────────────────────────────────────┘
        │
        ├─ hierarchy / navigation ─▸ app/hierarchy (Team Member 2)
        ├─ organization command   ─▸ app/hierarchy/commands.py
        ├─ reminders              ─▸ app/reminders/service.py
        │
        ▼ content question
  ┌──────────────────────────────────────────────────────────┐
  │ 2. FILTER          app/rag/retriever.py                  │
  │    Spoken names resolved against the real hierarchy;      │
  │    note type and date range become a RetrievalFilter      │
  │    applied INSIDE the vector query, not after it.         │
  └──────────────────────────────────────────────────────────┘
        │
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 3. HYBRID SEARCH                                          │
  │    vector  — cosine over note chunks (Chroma or memory)   │
  │    lexical — normalised keyword scan over the same set    │
  │    fused by RAG_VECTOR_WEIGHT; chunks collapse to notes,  │
  │    each scored by its best chunk, which is kept as the    │
  │    quotable evidence.                                     │
  └──────────────────────────────────────────────────────────┘
        │
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 4. GROUNDED ANSWER app/rag/answerer.py                   │
  │    LLM constrained to the retrieved notes, or an          │
  │    extractive fallback that quotes them directly.         │
  │    Nothing retrieved  →  "I don't have any notes about X" │
  └──────────────────────────────────────────────────────────┘
        │
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 5. SPEAK           app/tts/engine.py                     │
  │    SpeechDirective: text, voice, rate, interrupt, earcon  │
  └──────────────────────────────────────────────────────────┘
```

Three properties this flow is built to guarantee:

1. **Nothing is invented.** The model only ever sees the retrieved notes, and is told to say so
   when they do not contain the answer. A note-taking assistant that invents a deadline is worse
   than one that admits it does not know.
2. **Every answer is attributable.** Responses carry the note ids they came from, and the spoken
   form names where those notes live — a user who cannot see a citation list needs the provenance
   in the sentence.
3. **`spoken` is always safe to read aloud**, including when `ok` is false. A voice loop never
   needs an error branch to know what to say.

---

## API endpoints

Base path `/api/v1`. Interactive docs at `/docs`.

### Capture and notes — Phase 1/2

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trigger` | Capture → transcribe → clean → understand → organize → index |
| `POST` | `/understand` | Run understanding on supplied text, no audio |
| `GET` | `/capture/sources` | Which capture sources exist and are usable |
| `GET` | `/notes` · `/notes/{id}` | Read notes |
| `DELETE` | `/notes/{id}` | Delete a note, its entities, reminders and vectors |
| `GET` | `/health` | Status, capture availability, ASR model, LLM availability |

### Hierarchy and summaries — Phase 3

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/hierarchy` · `/hierarchy/outline` | Nested Subject → Topic → Note JSON plus narration |
| `GET` | `/hierarchy/overview` | Top-level counts and a spoken summary |
| `GET`/`POST` | `/hierarchy/subjects` · `/hierarchy/topics` | Read and create |
| `POST` | `/hierarchy/notes/{id}/move` · `/move-by-name` | Re-file a note |
| `POST` | `/hierarchy/subjects/{id}/recluster` | Batch DBSCAN re-clustering |
| `POST` | `/hierarchy/command` | Voice organization commands |
| `GET` | `/summary/topics/{id}` · `/summary/subjects/{id}` · `/summary/range` | Summaries |

### Retrieval and voice — Phase 4

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/retrieval/query` | **Answer a transcribed utterance.** The whole voice loop runs here |
| `POST` | `/retrieval/voice` | Upload audio → transcribe → answer |
| `POST` | `/retrieval/reindex` | Rebuild the vector index from SQLite |
| `GET` | `/retrieval/status` | Vector store, embedding backend, chunk and note counts |
| `POST` | `/tts/speak` | Turn text into a speech directive |
| `GET` | `/tts/audio/{filename}` | Fetch audio a server-side engine produced |

### Reminders and contacts — Phase 5

| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/reminders` | List (narrated) and create |
| `GET` | `/reminders/due` · `/reminders/upcoming` | Due now, or within a window |
| `GET` | `/reminders/notes/{id}/detected` | What a note implies, including low-confidence suggestions |
| `PATCH`/`DELETE` | `/reminders/{id}` | Edit, delete |
| `POST` | `/reminders/{id}/done` · `/dismiss` | Change status |
| `GET`/`POST` | `/contacts` | List and create |
| `GET` | `/contacts/{id}` | One contact, with suggested actions |
| `GET` | `/contacts/{id}/notes` · `/contacts/notes/{id}` | Both directions of the link |

### Example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/retrieval/query \
  -H "Content-Type: application/json" \
  -d '{"utterance": "What did I write about deadlocks?"}'
```

```jsonc
{
  "intent": "search",
  "ok": true,
  "spoken": "A deadlock requires circular wait, hold and wait, no preemption and mutual exclusion. From Deadlock, under Operating Systems.",
  "answer": "A deadlock requires circular wait, hold and wait, no preemption and mutual exclusion. [1]",
  "sources": ["a5acd515-962d-49a2-bfbb-344745acde27"],
  "citations": [{"index": "1", "note_id": "a5acd515-...", "location": "Deadlock, under Operating Systems"}],
  "results": [{"note_id": "a5acd515-...", "snippet": "...", "score": 0.72, "matched_by": ["vector", "lexical"]}],
  "confidence": 0.72,
  "method": "extractive",
  "speech": {"text": "...", "voice": "default", "rate": 180, "interrupt": false, "earcon": "results_found"}
}
```

---

## Database structure

SQLite, created on startup by `Base.metadata.create_all`. **There are no migrations yet** — a
schema change currently needs the file deleted.

```
subjects ──< topics ──< notes ──┬── note_understanding  (1:1)
                                ├──< note_entities
                                ├──< reminders
                                └──< note_contacts >── contacts
```

| Table | Holds | Phase |
|---|---|---|
| `notes` | Transcripts, capture provenance, ASR detail, topic placement and why | 1 / 3 |
| `note_understanding` | Classification, confidence, method, quality metrics | 2 |
| `note_entities` | People, dates, deadlines, tasks, key phrases, with spans | 2 |
| `subjects` | Top level. Exactly one `is_unfiled` row | 3 |
| `topics` | Second level, with the AI-generated cluster summary and its stale flag | 3 |
| `reminders` | Title, due date, status, source, confidence, detected phrase | 5 |
| `contacts` | Name, normalized match key, optional email and phone | 5 |
| `note_contacts` | Which notes mention which people, with the surface form | 5 |

Everything hanging off `notes` cascades on delete: removing a note takes its understanding,
entities, reminders and contact links with it. Contacts survive, since a person outlives any one
note about them.

### Vector index

One Chroma collection, `echonotes_notes`, one document per note chunk, id `<note_id>::<n>`.
Metadata carries `note_id`, `subject_id`, `subject_name`, `topic_id`, `topic_name`, `note_type`,
`source`, `created_epoch` and `quality_score` — which is what lets "about databases, from last
week" be a filtered search rather than a re-ranking hack.

---

## Configuration

Everything has a working default. See `app/config.py` for the full set.

| Variable | Default | What it does |
|---|---|---|
| `CAPTURE_SOURCE` | `dummy` | `dummy` \| `microphone` \| `upload` |
| `WHISPER_MODEL` | `base` | faster-whisper model size |
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `null`. Falls back to `null` with no key |
| `ANTHROPIC_API_KEY` | *(empty)* | Without it, everything uses its non-LLM path |
| `VECTOR_STORE` | `chroma` | `chroma` \| `memory` |
| `EMBEDDING_BACKEND` | `hashed` | `hashed` \| `sentence-transformers` |
| `RAG_TOP_K` | `5` | Notes returned per query |
| `RAG_VECTOR_WEIGHT` | `0.65` | Vector vs lexical split in the hybrid score |
| `TTS_ENGINE` | `directive` | `directive` \| `pyttsx3` |
| `TTS_VOICE_CODING` | `consistent` | `consistent` \| `by_type` (Idea11y §4.3) |
| `REMINDER_AUTO_CREATE_CONFIDENCE` | `0.60` | Below this, a detection is suggested, not created |

Changing `EMBEDDING_BACKEND` invalidates the index — run `POST /retrieval/reindex` afterwards.
Vectors from two different models are not comparable, and a half-migrated index returns confident
nonsense instead of failing loudly.

---

## Tests

```bash
cd backend && python -m pytest -m "not slow"
```

400 tests, ~9 seconds, no network, no API key, no model download.

```bash
cd backend && python -m pytest -m slow
```

| File | Covers | Phase |
|---|---|---|
| `test_preprocess.py` · `test_entities.py` · `test_classifier.py` · `test_quality.py` | Cleaning, extraction, classification, quality scoring | 1–2 |
| `test_capture.py` · `test_transcriber.py` · `test_api.py` | Capture sources, ASR confidence, every Phase 1/2 endpoint | 1–2 |
| `test_hierarchy.py` · `test_organizer.py` · `test_clustering.py` · `test_hierarchy_api.py` · `test_summarization.py` | Tree, topic assignment, DBSCAN, endpoints, summaries | 3 |
| `test_intent.py` | Intent routing, time ranges, note-type detection | 4 |
| `test_rag_retrieval.py` | Embeddings, **both** vector backends, chunking, indexing, retrieval, answering | 4 |
| `test_voice_query.py` | Every voice-query branch plus the HTTP surface | 4 |
| `test_reminders.py` | Detection, pairing, CRUD, windows, narration, contacts | 5 |
| `test_end_to_end.py` | The complete loop, and the seams between all three phases | 6 |

The suite fakes only Whisper. Routing, persistence, classification, topic assignment, indexing,
retrieval and serialization all run for real against a temporary SQLite file and an in-memory
vector store. ChromaDB is exercised directly by `test_rag_retrieval.py` against a tmp directory,
so the backend that actually ships is not left untested.

---

## How this maps to LNT and Idea11y

Full traceability in [docs/paper-mapping.md](docs/paper-mapping.md). In summary:

### LNT — Saini et al. 2023

The paper's pipeline shape is implemented in full: **record → normalize → transcribe → translate
to a single analysis language → preprocess → analyze → score quality**, as
`app/pipeline/capture_pipeline.py`.

Two deliberate substitutions, both documented:

- **Whisper replaces `SpeechRecognition` + Google API.** The paper reports ~92% accuracy from the
  Google API and needs a network round trip per chunk; faster-whisper runs offline, and exposes
  per-segment `avg_logprob` and `no_speech_prob`, which is what the transcription-confidence
  metric is built on. Whisper also detects language itself, which subsumes the paper's separate
  detect-then-translate step.
- **Quality metrics are readability, coherence and transcription confidence**, composited by
  configurable weights (`app/quality/`). The paper's `Qi` sums Flesch reading ease, cohesion,
  coherence and entropy; transcription confidence carries the largest weight here because
  readability and coherence are computed *from* the transcript — if the transcript is wrong, they
  are measuring the wrong text.

The paper's summarization, thematic analysis (hapaxes/collocations/bigrams) and LDA topic
modeling are **not implemented**; `app/nlp/thematic.py` and `app/nlp/topic_modeling.py` remain
stubs. `organizer.propose_new_topic` already accepts their output (`themes=`, `lda_topics=`) and
degrades to a heuristic without them, so wiring them up later needs no restructuring.

### Idea11y — Li et al., CHI '26

**Design Goal 1 and 2 are adopted. The whiteboard is deliberately out of scope**, and so is the
collaboration half (DG3) and voting (DG4) — EchoNotes is single-user.

| Idea11y | EchoNotes |
|---|---|
| Frame → Cluster → Note | **Subject → Topic/Project → Note** (`app/hierarchy/tree.py`) |
| Header–subheader–bullet outline for screen-reader heading navigation | `GET /hierarchy` returns the same structure plus a narration string |
| DBSCAN over canvas **coordinates**, gestalt proximity/colour/region | DBSCAN over **embeddings**; the gestalt precedence (bounded region > colour > proximity) becomes **subject > note type > semantic proximity** (`app/hierarchy/clustering.py`) |
| AI-generated per-cluster summary, refreshed in real time | `topics.summary` with a `summary_stale` flag, regenerated lazily so a write never blocks on an LLM call |
| Board overview: counts of frames, clusters, colours | Library overview: counts of subjects, topics, notes, and the note-type breakdown |
| Add/edit/delete/move a note from inside the outline | `POST /hierarchy/notes/{id}/move`, `/move-by-name`, and the voice command |
| **Voice coding** — distinct synthesized voices as a second information channel | Distinct voices per **note type** rather than per collaborator, opt-in, default consistent — exactly the paper's own default (`app/tts/voice_profiles.py`) |
| **Earcons**, configurable earcon/speech/both/none | Same four-way setting, repurposed for capture and note state (`app/tts/earcons.py`) |
| Two-way canvas ↔ outline sync | Not applicable — no canvas. The outline is the single source of truth |
| Voting mode (DG4), collaboration awareness (DG3) | Not implemented — single-user |

---

## Known gaps

- **No migrations.** Schema changes need the SQLite file deleted. Worth adding Alembic before
  anyone depends on stored data.
- **`POST /trigger` is synchronous.** A long lecture blocks the request for the duration of
  transcription.
- **OCR (Feature 7) is a stub.** `app/ocr/` is unimplemented and unmounted.
- **The LNT NLP modules are stubs** — summarization, thematic analysis, topic modeling.
- **The frontend is a basic shell.** `frontend/` now has a working UI wired to the
  API (capture, ask, notes, reminders), but not the Subject/Topic outline — the
  hierarchy endpoints exist and are unused by the UI.
- **Default retrieval is lexical, not semantic.** See
  [docs/retrieval-handoff.md](docs/retrieval-handoff.md), "Assumptions and open items".
