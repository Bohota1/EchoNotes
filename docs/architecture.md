# Architecture

## The interaction loop

EchoNotes' core feature list defines the loop:

```
Trigger → Record → Transcribe → Understand → Organize → Store → Retrieve → Respond
```

`backend/app/pipeline/loop.py` implements it as eight named stages over a shared
`PipelineContext`, so any stage can be tested, replaced or replayed on its own.

```
 ┌──────────┐   spacebar (hold)          ┌───────────────────────────────────────┐
 │ TRIGGER  │ ──────────────────────────▶│ capture/trigger.py                    │
 └──────────┘                            └───────────────────────────────────────┘
      │
      ▼
 ┌──────────┐  wav on disk               ┌───────────────────────────────────────┐
 │ RECORD   │ ──────────────────────────▶│ capture/recorder.py                   │
 └──────────┘                            └───────────────────────────────────────┘
      │
      ▼
 ┌────────────┐  LNT §3.3                ┌───────────────────────────────────────┐
 │ TRANSCRIBE │ ────────────────────────▶│ audio/normalization.py   (pydub)      │
 │            │                          │ audio/chunking.py  (split_on_silence) │
 │            │                          │ asr/recognizer.py   (Google API)      │
 │            │                          │ asr/language.py + asr/translation.py  │
 └────────────┘                          └───────────────────────────────────────┘
      │  English transcript
      ▼
 ┌────────────┐  LNT §3.4 + Feature 2    ┌───────────────────────────────────────┐
 │ UNDERSTAND │ ────────────────────────▶│ nlp/preprocess, tokenization,         │
 │            │                          │ lemmatization, word_frequency,        │
 │            │                          │ embeddings_w2v, summarization,        │
 │            │                          │ thematic, topic_modeling              │
 │            │                          │ quality/*  →  Qi                      │
 │            │                          │ understanding/classifier, extractor   │
 └────────────┘                          └───────────────────────────────────────┘
      │  summary + themes + topics + type + entities + Qi
      ▼
 ┌──────────┐  Idea11y DG1               ┌───────────────────────────────────────┐
 │ ORGANIZE │ ──────────────────────────▶│ hierarchy/clustering.py   (DBSCAN)    │
 │          │                            │ hierarchy/tree.py                     │
 │          │                            │ hierarchy/cluster_summary.py          │
 └──────────┘                            └───────────────────────────────────────┘
      │
      ▼
 ┌──────────┐                            ┌───────────────────────────────────────┐
 │ STORE    │ ──────────────────────────▶│ db/  (SQLite)  +  rag/indexer.py      │
 └──────────┘                            │                  (ChromaDB)           │
      │                                  └───────────────────────────────────────┘
      ▼
 ┌──────────┐  Feature 4                 ┌───────────────────────────────────────┐
 │ RETRIEVE │ ──────────────────────────▶│ rag/intent.py → retriever → answerer  │
 └──────────┘                            └───────────────────────────────────────┘
      │
      ▼
 ┌──────────┐                            ┌───────────────────────────────────────┐
 │ RESPOND  │ ──────────────────────────▶│ tts/speaker.py + earcons + outline    │
 └──────────┘                            │ ARIA live region in the React UI      │
                                         └───────────────────────────────────────┘
```

The OCR path (Feature 7) joins the same loop at **Understand**: `ocr/engine.py` produces text that
is handed to the identical understand → organize → store stages.

## Backend layering

- `api/v1/*` — thin HTTP layer. No logic: validate a schema, call a service, return a schema.
- `pipeline/*` — orchestration of the eight stages.
- `audio`, `asr`, `nlp`, `quality` — the LNT paper, one module per paper section. These are pure
  functions over audio and text with no database or HTTP awareness, so they can be unit-tested
  directly against the numbers the paper reports.
- `understanding`, `hierarchy`, `rag`, `reminders`, `ocr`, `tts` — the EchoNotes features built on
  top of that pipeline.
- `db` — SQLAlchemy models and repositories. The only package that touches SQLite.

Dependencies point one way only: `api` → `pipeline` → feature packages → `nlp`/`audio`/`asr`. A
paper module never imports a feature module.

## Frontend

A single accessible page with three landmark regions:

1. **Library Overview** — counts, read first, the Idea11y "board overview" analogue.
2. **Outline** — real headings and lists, not a `role="tree"`: H1 Subject, H2 Topic/Project,
   `ul`/`li` notes. Idea11y DG1 chose headings precisely because screen-reader users already have
   heading navigation in muscle memory.
3. **Assistant** — voice query bar, answer panel, and the ARIA live region that carries every
   announcement.

State comes from the backend. The UI holds no derived hierarchy of its own, so what a screen
reader announces and what the server stores can never drift.

## Why FastAPI rather than Flask

Idea11y's backend was Flask. FastAPI gives typed request and response schemas that mirror the
TypeScript types in `frontend/src/types`, plus native async for the streaming ASR endpoint.
Nothing in either paper depends on the web framework.

## Data flow for a single spoken note

1. User holds `Space`. `SpacebarTrigger` starts `MediaRecorder`, an earcon confirms the start.
2. On release, the blob is POSTed to `/api/v1/capture/audio`.
3. The pipeline runs stages 2–6 synchronously for short captures, or as a background task with
   progress announced through the live region for lecture-length audio.
4. The response carries the new note, its assigned Subject and Topic, the refreshed cluster
   summary, and the text to announce.
5. The outline re-renders; focus moves to the new note; the announcement is spoken.
