# Capture & Understanding pipeline — integration guide

What Phase 1 and Phase 2 deliver, and how to call it.

**In scope here:** audio capture, transcription, transcript cleaning, entity
extraction, note classification, quality scoring, SQLite persistence, and the
shared LLM abstraction.

**Not in scope (owned by others):** Subject/Topic hierarchy, topic assignment,
RAG / vector search, TTS, reminders UI, frontend.

---

## Setup

```bash
cd backend
pip install -r requirements.txt
python scripts/make_fixture_audio.py     # creates the dummy capture fixture
uvicorn app.main:app --reload
```

Nothing else is required. There is no API key to set, no ffmpeg to install, and
no microphone needed — the default `dummy` capture source replays a fixture, so
`POST /trigger` works end to end on a fresh machine.

The Whisper model (~140 MB for `base`) downloads on the first real
transcription and is cached afterwards.

---

## Calling the pipeline from Python

The one function most callers need:

```python
from app.understanding.service import understand

result = understand(cleaned_text, transcription_confidence=0.82)

result.note_type    # "academic" | "brainstorm" | "todo"
result.people       # ["Raman", "Sarah"]
result.dates        # ["2027-03-03"]          ISO-8601
result.deadlines    # ["2026-09-11"]
result.tasks        # ["Submit the operating systems assignment ..."]
result.key_phrases  # ["deadlock detection and recovery", ...]
result.quality      # .readability .coherence .transcription_confidence .quality_score
result.entities     # every extraction, each with kind/value/normalized/confidence/span
result.llm_used     # whether the LLM fallback was consulted

result.to_dict()    # plain dict
result.to_schema()  # pydantic UnderstandingOut
```

The whole audio path, if you want it:

```python
from app.db.session import session_scope
from app.pipeline.capture_pipeline import run_capture

with session_scope() as db:
    note = run_capture(db, source="dummy", run_understanding=True)
    print(note.id, note.cleaned_text, note.understanding.note_type)
```

`run_capture` flushes but does **not** commit — the caller owns the transaction.
`session_scope()` commits on clean exit.

Individual stages are callable on their own:

| Stage | Call |
|---|---|
| capture | `app.capture.sources.get_capture_source(name).capture()` |
| transcribe | `app.asr.transcriber.get_transcriber().transcribe(path)` |
| clean | `app.nlp.preprocess.clean_transcript(text)` |
| extract | `app.understanding.entities.extract_all(text, reference)` |
| classify | `app.understanding.classifier.classify(text, task_count, deadline_count)` |
| score | `app.quality.score.score_text(text, transcription_confidence)` |

---

## HTTP API

Base path `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trigger` | Capture → transcribe → clean → understand → store |
| `POST` | `/understand` | Run Phase 2 on supplied text (no audio) |
| `GET` | `/capture/sources` | Which capture sources exist and are usable now |
| `GET` | `/notes` | Recent notes, newest first (`limit`, `offset`) |
| `GET` | `/notes/{note_id}` | One note, with transcripts and understanding |
| `DELETE` | `/notes/{note_id}` | Delete a note and its entities |
| `GET` | `/health` | Status, capture availability, ASR model, LLM availability |

Interactive docs at `/docs`.

### `POST /trigger`

An empty body is valid — that is what a hardware button sends.

```jsonc
// request (all fields optional)
{
  "source": "dummy",          // override CAPTURE_SOURCE
  "language": "en",           // omit to auto-detect
  "max_seconds": 60,          // recording cap for live sources
  "run_understanding": true   // false = transcript only
}
```

```jsonc
// 201 response (abridged)
{
  "note_id": "a5acd515-962d-49a2-bfbb-344745acde27",
  "source": "dummy",
  "raw_transcript": "Reminder to myself. I need to submit the operating systems assignment to Professor Raman by next Friday. Also, call Sarah about the database project meeting on March 3rd. The key topic is deadlock detection and recovery.",
  "cleaned_text": "Reminder to myself. I need to submit the operating systems assignment to Professor Raman by next Friday. ...",
  "duration_seconds": 16.25,
  "audio_path": "D:\\DP2\\backend\\data\\audio_raw\\c11aac47ef62.wav",
  "created_at": "2026-09-10T15:58:16.914146",
  "transcription": {
    "model": "faster_whisper:base",
    "language": "en",
    "language_probability": 0.998,
    "confidence": 0.766,
    "no_speech_probability": 0.006,
    "segment_count": 3
  },
  "understanding": {
    "note_type": "todo",
    "classification": {
      "note_type": "todo",
      "confidence": 0.765,
      "method": "rules",
      "rationale": "matched i need to, submit, 2 task(s) extracted, 1 deadline(s) extracted"
    },
    "quality": {
      "readability": 0.473,
      "coherence": 0.133,
      "transcription_confidence": 0.766,
      "quality_score": 0.488,
      "word_count": 36,
      "sentence_count": 4
    },
    "entities": [
      {
        "kind": "deadline",
        "value": "next Friday",
        "normalized": "2026-09-11",
        "confidence": 0.85,
        "extractor": "rules",
        "span_start": 92,
        "span_end": 103
      }
    ],
    "people": ["Raman", "Sarah"],
    "dates": ["2027-03-03"],
    "deadlines": ["2026-09-11"],
    "tasks": ["Submit the operating systems assignment to Professor Raman by next Friday"],
    "key_phrases": ["deadlock detection and recovery", "operating systems assignment"],
    "llm_used": false
  }
}
```

Status codes: `201` created, `422` unusable audio or invalid body, `503` the
capture source cannot run (unknown name, missing fixture, no microphone).

### `POST /understand`

Runs Phase 2 on text — the easiest way to exercise the understanding stage
without audio.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/understand \
  -H "Content-Type: application/json" \
  -d '{"text": "I need to email Professor Chen the report by Monday."}'
```

Set `"persist": true` to also store it as a note.

---

## Database schema

Three new tables. `Base.metadata.create_all` runs on startup, so no migration
step exists yet.

### `notes`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `raw_transcript` | text | ASR output, untouched |
| `cleaned_text` | text | readable cleaned form |
| `source` | str | `dummy` \| `microphone` \| `upload` \| `text` |
| `audio_path` | str? | wav on disk |
| `duration_seconds` | float? | |
| `asr_model` | str? | e.g. `faster_whisper:base` |
| `language`, `language_probability` | str?, float? | detected by Whisper |
| `asr_avg_logprob`, `asr_no_speech_prob`, `asr_segment_count` | float?, float?, int? | feed the confidence metric |
| `topic_id` | str? | **left for the hierarchy work** — always null here |
| `created_at`, `updated_at` | datetime | |

### `note_understanding` (1:1 with a note)
`note_id` fk · `note_type` · `note_type_confidence` · `classification_method`
(`rules` \| `llm`) · `classification_rationale` · `readability` · `coherence` ·
`transcription_confidence` · `quality_score` · `word_count` · `sentence_count`

### `note_entities` (many per note)
`note_id` fk · `kind` (`person` \| `date` \| `deadline` \| `task` \|
`key_phrase`) · `value` · `normalized` · `confidence` · `extractor` (`rules` \|
`llm`) · `span_start` · `span_end`

`topic_id` on `notes` is the hand-off point for the hierarchy work: it is a
plain nullable column with no FK, so a Subject/Topic table can be added and the
FK attached without altering rows this pipeline wrote.

---

## The shared LLM abstraction

Anything that needs an LLM goes through this. Nothing outside `app/llm/`
imports a vendor SDK.

```python
from app.llm import get_llm_client, LLMUnavailableError

client = get_llm_client()          # never None
if client.available:               # False when no key is configured
    data = client.complete_json(prompt, system=SYSTEM, max_tokens=500)
    text = client.complete(prompt, system=SYSTEM).text
```

- `get_llm_client()` always returns an `LLMClient`. With no key it returns a
  `NullLLMClient` whose `available` is `False`, so callers have one branch to
  write instead of a `None` check everywhere.
- `complete_json()` repairs fenced and prose-wrapped JSON before parsing.
- Add a provider by subclassing `LLMClient` in `app/llm/` and registering it in
  `app/llm/factory.py`.

**Always keep a non-LLM path.** The deployment may legitimately have no key.

---

## How rules and the LLM interact

Rules run first everywhere and are the only thing that runs when confident.
The LLM is consulted only when a rule result falls below its confidence floor,
and **any** failure from it (no key, no network, bad JSON, unknown label)
returns `None` so the rule result survives. The LLM can never be the reason a
capture fails.

- classification escalates below `CLASSIFICATION_CONFIDENCE_FLOOR` (0.55)
- extraction escalates when no person/date/deadline/task was found, or all of
  them are below `EXTRACTION_CONFIDENCE_FLOOR` (0.50)

Set `LLM_PROVIDER=null` to disable escalation entirely.

---

## Tests

```bash
cd backend
python -m pytest -m "not slow"   # 149 tests, ~9s, no model download, no network
python -m pytest -m slow         # the real Whisper path
```

| File | Covers |
|---|---|
| `tests/test_preprocess.py` | cleaning, normalisation, tokenisation |
| `tests/test_entities.py` | people, dates, deadlines, tasks, key phrases, spans |
| `tests/test_classifier.py` | classification, confidence, LLM escalation |
| `tests/test_quality.py` | readability, coherence, composite score |
| `tests/test_capture.py` | capture sources, registry, LLM abstraction |
| `tests/test_api.py` | every endpoint against the real app and database |
| `tests/test_transcriber.py` | confidence mapping; real Whisper under `-m slow` |

The suite replaces only Whisper (`FakeTranscriber`); routing, persistence and
serialisation are exercised for real against a temporary SQLite file.

---

## Adding a hardware trigger later

The capture layer is an interface, so hardware plugs in without touching the
pipeline:

```python
from app.capture.sources import AudioCaptureSource, CapturedAudio, register_source

class GPIOCaptureSource(AudioCaptureSource):
    name = "gpio"

    def is_available(self) -> tuple[bool, str]:
        ...   # report a reason instead of raising

    def capture(self, max_seconds: int | None = None) -> CapturedAudio:
        ...   # block on the button, record, return a wav on disk

register_source(GPIOCaptureSource)
```

Then set `CAPTURE_SOURCE=gpio`. `POST /trigger` needs no change — it already
asks the configured source for audio.

---

## Assumptions and open items

1. **Two cleaned forms, not one.** `cleaned_text` keeps capitalisation and
   punctuation; `to_analysis_text()` produces the lower-cased, punctuation-free
   form for statistics. Lower-casing the stored transcript would destroy the
   only signal that finds people.
2. **"next Friday" means the coming Friday.** `dateparser` returns nothing for
   the phrase, and the coming occurrence is the more common colloquial reading.
   Change `normalize_date` if your users mean the following week.
3. **Relative dates resolve against the capture time**, not processing time.
   Pass `reference=` when reprocessing old audio.
4. **Coherence is not purely lexical.** Adjacent-word-overlap alone scores an
   ordinary three-item to-do at zero, so the metric blends leave-one-out lexical
   overlap (0.6) with explicit discourse connectives and anaphors (0.4).
5. **Transcription confidence carries the largest quality weight (0.40)**
   because readability and coherence are computed *from* the transcript — if the
   transcript is wrong, they measure the wrong text.
6. **An empty transcript is stored, not rejected.** A trigger that caught no
   speech is a normal user mistake; the empty note plus a low quality score says
   so honestly.
7. **Google-based ASR was removed.** `app/asr/recognizer.py` (SpeechRecognition
   + Google API) was deleted when the project moved to Whisper.
   `app/asr/language.py` and `translation.py` remain unused by this pipeline —
   Whisper detects language itself.
8. **No migrations.** Schema changes currently need the SQLite file deleted.
   Worth adding Alembic before anyone depends on stored data.
9. **`POST /trigger` is synchronous.** A long lecture blocks the request for the
   duration of transcription. Fine for short captures; a background task with a
   status endpoint is the next step if long recordings are needed.
10. **Person extraction is capitalisation-dependent** and will miss names
    Whisper failed to capitalise. The LLM fallback covers this when a key is
    configured.
11. **Coherence measures surface cohesion, not meaning.** It sees shared words
    and discourse markers, so two genuinely related sentences that share no
    vocabulary and use no connective ("A deadlock is defined as... The theorem
    gives four conditions.") score 0. Real semantic coherence needs sentence
    embeddings; that is a deliberate trade to keep this dependency-free and fast
    enough to run on every capture. Treat the number as relative, not absolute.
