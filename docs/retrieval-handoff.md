# Retrieval, Voice Query, TTS & Reminders — integration guide

What Phase 4, 5 and 6 deliver, and how to call it.

**In scope here:** embeddings, the vector store, note indexing, semantic +
lexical retrieval, grounded answer generation, the voice-query endpoint,
navigation commands, text-to-speech, reminders, contacts, and the end-to-end
integration of all three phases.

**Not in scope (owned by others):** audio capture, Whisper, transcript cleaning,
entity extraction, classification, quality scoring (Team Member 1) ·
Subject/Topic hierarchy, topic assignment, topic summaries, the hierarchy
endpoint (Team Member 2).

---

## Setup

```bash
cd backend && pip install -r requirements.txt
```

One dependency was added: **`chromadb`** — it was already listed (commented out)
in `requirements.txt` under "RAG vector store", and this uncomments it. Nothing
else is required. `sentence-transformers` and `pyttsx3` are listed as commented
**optional** extras and are deliberately not hard requirements — see
"Assumptions and open items".

No new environment variables are required; every Phase 4/5 setting in
`app/config.py` has a working default.

---

## How this plugs into Phases 1–3

Four integration points. All are additive, and none change existing behaviour.

### 1. `app/pipeline/capture_pipeline.py` — a seventh stage

`_index_and_derive(db, note)` runs after `_organize_note`, in both `run_capture`
(audio) and `run_understanding_on_text` (the `/understand` path):

```python
index_note_safe(db, note)       # make it searchable
create_reminders_safe(db, note) # derive reminders from the extracted entities
link_contacts_safe(db, note)    # link the people the extractor found
```

It runs *after* organization so the indexed metadata carries the topic the note
was just filed under, and *after* understanding so reminders and contacts can
read the entities it produced.

Each of the three is independently wrapped, following the same pattern as
`_run_understanding` and `_organize_note`: **none of them can be the reason a
capture is lost.** A note that fails to index is still stored, still filed and
still readable — only temporarily unfindable by search, which
`POST /retrieval/reindex` repairs.

**You do not need to call anything new.** Any note reaching `persist_capture`
is indexed automatically. If you persist notes outside `capture_pipeline.py`:

```python
from app.rag.indexer import index_note_safe
from app.reminders.service import create_reminders_safe
from app.reminders.contacts import link_contacts_safe
```

### 2. `app/hierarchy/service.py::move_note` — one line

The vector index denormalises each note's subject and topic so retrieval can
filter on them. A move makes that copy stale, and a stale copy means "what did I
write about X in *subject*" filters on where the note used to be.

`move_note` is the single choke point every move goes through — by id, by name,
and by voice command — so the refresh is hooked there:

```python
from app.rag.indexer import reindex_note_metadata
reindex_note_metadata(db, note)
```

Never raises. A stale index is a worse search result, not a failed move.

### 3. `app/api/v1/notes.py::delete_note` — one line

`remove_note(note_id)` drops the note's vectors. SQLite is authoritative, so an
orphaned vector would surface a note that no longer exists. The retriever skips
those defensively as well, but leaving them behind would grow the index forever.

### 4. `app/api/v1/router.py` — four routers mounted

`/retrieval`, `/reminders`, `/contacts`, `/tts`.

### A correctness fix in shared code

`SessionLocal` is built with `expire_on_commit=False`. After
`NoteRepository.move_to_topic` sets the `topic_id` *column*, an already-loaded
`note.topic` *relationship* still points at the old Topic within the same
session — SQLAlchemy will not overwrite a loaded relationship when the row is
selected again.

That silently broke the reindex-on-move hook: `build_metadata` read `note.topic`
and faithfully recorded where the note used to be. `indexer.ensure_fresh_topic`
compares the FK against the loaded object and refreshes only when they disagree,
and both `index_note` and the retriever's `_hierarchy_fields` call it. This is
worth knowing about generally — **anything that reads a relationship after
writing its FK in the same session has this problem.**

---

## The voice-query endpoint

`POST /api/v1/retrieval/query` is the entry point for the whole voice loop.
Every kind of spoken utterance goes here, because they all arrive through one
microphone and the caller cannot know in advance which subsystem will answer.

```jsonc
// request
{
  "utterance": "What did I write about machine learning?",
  "focused_note_id": "e9a3134f-...",   // only needed for "move this note to X"
  "top_k": 5,                           // optional
  "speak": true                         // include a speech directive
}
```

```jsonc
// response — always 200, even for failures
{
  "intent": "search",
  "ok": true,
  "spoken": "Gradient descent minimises the loss function. From Machine Learning, under Coursework.",
  "answer": "Gradient descent minimises the loss function. [1]",
  "sources": ["a5acd515-..."],
  "citations": [{"index": "1", "note_id": "a5acd515-...", "location": "Machine Learning, under Coursework", "created_at": "..."}],
  "results": [{
    "note_id": "a5acd515-...", "text": "...", "snippet": "the chunk that matched",
    "score": 0.72, "subject_name": "Coursework", "topic_name": "Machine Learning",
    "note_type": "academic", "matched_by": ["vector", "lexical"]
  }],
  "confidence": 0.72,
  "method": "extractive",          // "llm" | "extractive" | "empty"
  "filter_description": "",
  "navigate_to": null,              // element id for the client to focus
  "data": {...},
  "speech": {"text": "...", "voice": "default", "rate": 180, "pitch": 1.0,
             "interrupt": false, "earcon": "results_found", "audio_url": null}
}
```

**`spoken` is always populated and always safe to read aloud**, including when
`ok` is false. This is the contract Team Member 2 set for `/hierarchy/command`,
kept uniform across the whole voice surface: a voice loop never needs a separate
error branch to know what to say. `ok: false` with a 200 covers every
recoverable case — nothing found, an unrecognised utterance, a name that doesn't
exist. Real HTTP errors are reserved for programmer errors (an unknown id) and
unusable input (empty audio upload).

### Recognised intents

| Intent | Example | Answered by |
|---|---|---|
| `search` | "What did I write about machine learning?" | Vector index |
| `when` | "When did I mention the assignment deadline?" | Vector index, answer led by the date |
| `summarize` | "Summarize my notes about databases." | Vector index → summary |
| `ask` | any other question | Vector index |
| `list_subjects` | "What subjects do I have?" | Hierarchy |
| `topics_under` | "What's under Machine Learning?" | Hierarchy (Team Member 2's handler) |
| `count_notes` | "How many notes are under Graph Theory?" | Hierarchy |
| `navigate` | "Take me to my Project Ideas." | Hierarchy, returns `navigate_to` |
| `organize` | "Move this note to Machine Learning." | **Delegated verbatim** to `app.hierarchy.commands` |
| `reminders` | "What's due tomorrow?" | Reminder service |

Slots are extracted alongside the intent: a topic to search for, a note type, a
date range. "What ideas did I have this week?" is `note_type=brainstorm` plus a
7-day window — *not* a similarity search for the word "ideas".

Resolving intent before retrieval is what stops "what subjects do I have" being
answered by semantic search over note text, which would produce a confident,
wrong list assembled from whatever notes happened to mention a subject name.

### Delegation to Team Member 2

Hierarchy questions are executed by `app.hierarchy.commands.handle_command` and
Team Member 2's repositories. This module recognises phrasings their regexes do
not cover ("What's under X?", "How many notes are under X?") and **reformulates
them into the canonical wording their handler already implements**, trying a
name as a subject first and then as a topic. The hierarchy therefore keeps
exactly one execution path and one narration style.

`"What subjects do I have?"` is the one hierarchy question answered here
directly, through their repositories, because no equivalent command exists.

### The audio path

`POST /api/v1/retrieval/voice` takes a `multipart/form-data` upload, transcribes
it through **Team Member 1's** `UploadCaptureSource` + `transcribe_audio`, and
answers it. There is no second audio path into the system.

---

## RAG architecture

```
utterance → intent+slots → filter → vector search + lexical scan → fuse
          → collapse chunks to notes → grounded answer → speech directive
```

### Embeddings — `app/rag/embeddings.py`

`EmbeddingProvider` with two backends, chosen by `EMBEDDING_BACKEND`:

- **`hashed`** (default) — wraps Team Member 2's `app.hierarchy.embeddings`
  vectorizer. Zero install, zero download, deterministic across restarts.
- **`sentence-transformers`** — real semantic embeddings, opt-in.

A missing optional dependency logs a warning and falls back to `hashed` rather
than failing to start.

### Vector store — `app/rag/vector_store.py`

`VectorStore` with two backends, chosen by `VECTOR_STORE`:

- **`chroma`** (default) — persisted under `CHROMA_DIR`, filtering done in the
  engine.
- **`memory`** — brute-force cosine over numpy. No persistence, instant startup.
  What the test suite uses, and a working fallback if Chroma cannot start.

Filtering is a `RetrievalFilter` (subject ids, topic ids, note types, note ids,
date range), not raw backend query syntax. Each backend translates it. This
matters: "what did I write about databases *last week*" has to filter *before*
ranking, or the date constraint degenerates into a hint that top-k ignores.

Every score leaving the store is a **similarity in 0–1, higher is better**.
Chroma returns cosine *distance*, and that conversion happens inside the store
so no caller has to remember which convention a backend used.

### Indexing — `app/rag/indexer.py`

One document per **chunk**, id `<note_id>::<n>`. A short voice note is one
chunk; a lecture is windowed with overlap, because embedding 2000 words into a
single vector averages away the specifics that make a note findable.

Metadata denormalises the hierarchy (`subject_id`, `subject_name`, `topic_id`,
`topic_name`, `note_type`, `created_epoch`, `quality_score`), which is what
makes hierarchy- and date-scoped search a pre-filter.

`reindex_all(db)` rebuilds everything from SQLite. **Required after changing
`EMBEDDING_BACKEND`** — vectors from two different models are not comparable,
and a half-migrated index returns confident nonsense instead of failing loudly.

### Retrieval — `app/rag/retriever.py`

Hybrid, and both halves earn their place:

- With the **hashed** backend, vectors *are* lexical, but hashing collides and
  drops rare tokens, so a direct keyword hit is useful independent evidence.
- With **sentence-transformers**, the failure mode is the opposite: semantic
  vectors reliably miss exact rare strings — a name like "Professor Raman", a
  course code — which are exactly what people search their own notes for.

Two measured problems drove specific defences:

1. **Plurals.** "deadlocks" scored *exactly 0.0* against a note saying
   "deadlock" — different strings, different hash buckets, orthogonal vectors.
   `app/rag/text.py` singularises both sides. Applied in the retrieval provider,
   **not** in `app.nlp.preprocess` or `app.hierarchy.embeddings`, so topic
   assignment keeps the behaviour it was tuned against. The LNT paper
   (Section 3.3) specifies this step; it is not implemented in the shared
   preprocessing.
2. **Hash collisions.** "quantum tunnelling" scored 0.13 against notes about
   deadlocks *and* about gradient descent — above the score floor, enough to be
   cited as a source. When the provider `is_lexical`, a vector match sharing no
   normalised token with the query is dropped. That removes the class of false
   match structurally rather than by tuning a threshold. Semantic backends are
   exempt: matching without shared words is the point of one.

### Answering — `app/rag/answerer.py`

The LLM sees only the numbered retrieved notes and is told to say so when they
do not contain the answer. With no key configured, an extractive fallback picks
the sentences from the retrieved notes that overlap the question most — lower
quality, still grounded, still sourced, and structurally incapable of
hallucinating because it never writes a new sentence.

Nothing retrieved produces `method: "empty"`, `confidence: 0.0`, and a response
that names what was searched: *"I don't have any notes about mutexes in last
week"* is actionable; *"I found nothing"* is a dead end.

Bracketed citations are stripped from `spoken` — a screen reader reads "[1]" as
"bracket one" — and replaced with one spoken provenance clause.

---

## Text to speech — `app/tts/`

`TTS_ENGINE=directive` (default) returns a `SpeechDirective` the browser speaks
with the Web Speech API. **This is the default deliberately**: experienced
screen reader users run their synthesiser at rates that sound absurd to everyone
else, and overriding that with a server-side voice makes an accessible app
worse. `TTS_ENGINE=pyttsx3` additionally synthesises a wav and returns
`audio_url`, for headless demos; output is content-addressed so repeated phrases
are synthesised once.

**Voice coding** (Idea11y §4.3) is adapted from per-collaborator to per-note-type
and is **off by default**, as in the paper. **Earcons** keep the paper's exact
four-way earcon/speech/both/none setting.

---

## Reminders and contacts

### Reminders — `app/reminders/service.py`

Detection reads the `note_entities` rows Team Member 1's extractor wrote. It
does **not** re-parse dates: a second date parser could disagree with the first,
which is the one thing a reminder system must never do.

A reminder needs a *what* and a *when*, which arrive as separate entities.
Pairing is **one-to-one greedy over text distance**, with a small bonus for
`deadline` over a bare `date`. Absolute precedence for deadlines was the first
implementation and it was wrong: it attached the single deadline in a note to
*every* task in it, so "submit the assignment by next Friday, also call Sarah on
March 3rd" produced two reminders on the same day. A reminder on the wrong day
is worse than none, because the user acts on it.

Below `REMINDER_AUTO_CREATE_CONFIDENCE` (0.60) a detection is returned as a
**suggestion** and not written. `GET /reminders/notes/{id}/detected` exposes
those for confirmation.

`create_from_note` is idempotent — reprocessing a capture does not duplicate.

Dates are spoken the way people say them: "tomorrow at 4 pm", not
`2026-09-12T16:00:00`. Lookahead windows are taken from the question — "what's
due this week" searches a week, not the default 24 hours.

### Contacts — `app/reminders/contacts.py`

People from the extractor become contacts, matched fuzzily on a title-stripped,
lowercased key, so "Professor Raman", "Prof. Raman" and "Raman" are one person.
ASR spells names inconsistently, and four near-identical entries in a spoken
list is worse than none.

An email or phone in a note is absorbed **only when exactly one person is named**
— with several it is a guess, so it is skipped.

`suggest_actions` returns actions the user can choose. **EchoNotes never places
a call or sends a message on its own:** an accidental outbound message cannot be
recalled, and cannot be spotted by glancing at a screen.

---

## Tests

```bash
cd backend && python -m pytest -m "not slow"      # 400 tests, ~9s
```

| File | Covers |
|---|---|
| `tests/test_intent.py` | Intent routing, time ranges, note-type detection. All eight spec examples |
| `tests/test_rag_retrieval.py` | Embeddings, **both** vector backends against one shared contract, chunking, indexing, retrieval, answering |
| `tests/test_voice_query.py` | Every voice-query branch, plus `/retrieval`, `/reminders`, `/contacts`, `/tts` |
| `tests/test_reminders.py` | Detection, pairing, CRUD, windows, spoken dates, contacts |
| `tests/test_end_to_end.py` | The complete loop, all eight spec examples over HTTP, and the seams between phases |

`conftest.py` gained `VECTOR_STORE=memory` (fast, hermetic), a vector-store
clear in the autouse `clean_database` fixture — the store is a process-level
singleton, so unlike the database it is not reset by clearing tables — and a
`make_note` fixture that runs text through the real pipeline.

ChromaDB is exercised directly against a tmp path, so the backend that ships is
not left untested.

---

## Assumptions and open items

1. **Default retrieval is lexical, not semantic.** `EMBEDDING_BACKEND=hashed`
   matches shared vocabulary. A query for "machine learning" will **not**
   retrieve a note that only says "neural nets and gradient descent" — there is
   no token overlap. Singularisation and the hybrid lexical pass widen this
   considerably, but they do not make it semantic. `sentence-transformers` was
   left as an opt-in extra rather than a hard dependency because it pulls in
   torch (~500 MB–2 GB) plus a ~90 MB model download, which would end the
   project's "installs small, runs offline" property. **This is the single
   biggest quality lever available**, and it would also fix the recall limit
   Team Member 2 flagged in their topic matching, since both now route through
   one provider. Turning it on is a team decision, not a code change.
2. **`chromadb` was added to `requirements.txt`.** It was already listed
   commented-out under "RAG vector store", so this activates a planned
   dependency rather than introducing a new one. `VECTOR_STORE=memory` runs
   without it.
3. **Reminders are stored, not delivered.** There is no scheduler, no
   notification, no calendar integration — the brief explicitly scoped those
   out. `GET /reminders/due` is the polling surface a delivery mechanism would
   sit on.
4. **`app/reminders/` stubs were deleted.** `task_detector.py`, `date_parser.py`
   and `scheduler.py` were unreferenced scaffolding, and keeping them would have
   invited a second date parser competing with Team Member 1's. Detection now
   reads their entities.
5. **Re-indexing on move is a full re-embed.** The text is unchanged so only
   metadata needs rewriting, but neither backend exposes a metadata-only update.
   Cheap on both backends today; worth revisiting with a heavier embedding model.
6. **Chunk overlap is character-based, not token-aware.** Fine for the hashed
   backend. With a real model, chunking on token boundaries would be better.
7. **Confidence is retrieval confidence, not answer confidence.** It is derived
   from similarity and corroboration, and says nothing about whether the LLM
   used the retrieved notes correctly. It is reported separately from the answer
   for that reason.
8. **Auto-generated topic names read poorly when spoken.** Team Member 2's
   heuristic branch produces names like "Today'S Operating Systems L" from the
   first salient words of a note, and these end up in spoken provenance ("From
   Today'S Operating Systems L"). Not changed — it is their component — but
   worth a look, since it is only audible through this phase's output.
9. **`POST /retrieval/query` commits.** Organization commands can write, and a
   single commit covers the read-only branches harmlessly.
10. **Contact phone matching is a loose regex**, not `phonenumbers`. Spoken
    numbers arrive from ASR in many shapes, and a missed number is worse here
    than a false positive the user can ignore. No new dependency was added for
    it.
