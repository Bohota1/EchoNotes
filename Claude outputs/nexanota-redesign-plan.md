# NexaNota-Aligned Redesign Plan for EchoNotes

This is a plan only — **no project files have been changed.** It covers everything from right after speech-to-text onward, redesigned to match the NexaNota paper (Jiang et al., *NexaNota: An AI-Powered Smart Linked Lecture Note-Taking System Leveraging Large Language Models*, ICBDIE 2025) exactly, using your existing Anthropic LLM integration in place of the paper's GLM-4-Plus/DeepSeek-V3.

## 0. What stays exactly as it is

Per your instruction, nothing here changes: `app/capture/*` (recording), `app/asr/*` (Whisper transcription), `app/nlp/preprocess.py` (transcript cleaning). Speech-to-text still produces `Note.raw_transcript` / `Note.cleaned_text` exactly as today, and the frontend `CapturePanel.tsx` is untouched.

## 1. An important boundary I need you to confirm

NexaNota's paper (Sections 4.1–4.3) describes **only**: turning a transcript into 2–3 topics, building a knowledge graph of topics + connections, generating a 3-area note (Note-Taking / Link / Edit), lecture replay, and external web-resource links per topic.

It says **nothing** about several things your project already has, built from *other* sources:

- `app/nlp/*` — tokenization, lemmatization, Word2Vec, PageRank, LDA (a *different* academic paper, "LNT," Section 3.4 — this looks like Team Member 1's work)
- `app/rag/*` — semantic search / "ask your notes" (Team Member 3)
- `app/reminders/*`, contacts (Team Member 3)
- `app/tts/*` — text-to-speech (Team Member 3)
- `app/quality/*` — the readability/coherence/quality scoring (Phase 2)

**My plan below leaves all of these running, adapted only where needed so they still work against the new schema** (e.g., RAG's indexer currently reads `note.topic.subject`; it will keep doing that against the redesigned graph). I am *not* deleting or rewriting them to match NexaNota, because NexaNota doesn't describe them at all — there is nothing in the paper to rewrite them *to*. If you actually want those rewritten too, based on some other paper or spec, tell me which one and I'll fold it in — but that's a different, additional instruction, not something "don't skip any part of this paper" can mean on its own, since the paper is silent on them.

If you're fine with that boundary, the rest of this plan is ready to build. If not, tell me what should change about it before I start.

## 2. What "downstream pipeline redesigned to match NexaNota" concretely means

### Current design (being replaced)
`Subject → Topic → Note`, three-level tree. A note is placed one topic at a time via: explicit placement → embedding-similarity match → LLM disambiguation → new-topic creation → "Unfiled" fallback (`app/understanding/organizer.py`). Topics get one AI summary each, lazily regenerated (`app/hierarchy/cluster_summary.py`). Subjects/topics can be rolled up into bigger summaries (`app/hierarchy/summarization.py`). DBSCAN batch re-clustering exists as an admin action (`app/hierarchy/clustering.py`).

### New design (NexaNota, Sections 4.1–4.3)
- **Topic extraction (4.1):** every captured note is sent to the LLM, which extracts **2–3 topics** from it directly (not "find the closest existing topic" — the paper always asks the LLM fresh).
- **Cross-disciplinary recommendation (4.3.2):** for each upload, the LLM is also asked for **2 relevant cross-disciplinary topics** *outside* the note's own subject, which get added to the graph too.
- **Knowledge graph (4.3.2, D3):** all topics (extracted + recommended) become graph **nodes**; the LLM identifies **connections between topics**, which become graph **edges**. This graph accumulates across every note in a subject/course — it is not a strict tree, a topic can connect to several others.
- **Note-taking (4.3.3, D2):** every note's content is generated in **three fixed areas**:
  1. **Note-Taking Area** — the paper's needfinding names three required subsections: **Definition of the topic**, **Example analysis**, and **Summary**.
  2. **Link Area** — two link types: **relevant website URLs**, and **links to associated topic notes** (other notes/topics in the graph this one connects to).
  3. **Edit Area** — lets the student edit the note directly, in **markdown**.
- **Lecture replay (4.3.1):** the transcript is replayed as a **timestamped, segmented view**, each segment tagged with its classification label, so a student can jump to a specific moment instead of re-reading the whole thing.
- **Web resources (4.3.2, System overview):** the LLM is also asked to suggest **external online resources** (an academic paper or a professional blog) per topic, surfaced as links.

## 3. Data model changes — `app/db/models.py`

**Removed:** `Topic.summary` / `summary_stale` (replaced by the 3-area note content), the strict `Subject → Topic` containment as the *only* structure (Subject is kept as the "course" grouping the graph lives inside — NexaNota's graph is per-course, and Subject is the closest thing your app already has to "course").

**Added:**
- `TopicConnection` table — the graph edges: `id`, `subject_id` (which course-graph this edge belongs to), `topic_a_id`, `topic_b_id`, `label` (what the LLM says connects them), `confidence`, `created_at`. This is genuinely new — nothing like it exists today.
- `WebResource` table — `id`, `topic_id`, `title`, `url`, `resource_type` ("paper" | "blog"), `created_at`. **Flagged risk, see §6.**
- `NoteContent` table (one-to-one with `Note`) — the 3-area structure: `definition`, `example_analysis`, `summary` (Note-Taking Area, each LLM-generated), `related_note_ids` (JSON list, Link Area), `edit_markdown` (Edit Area — starts as a copy of the generated content, then diverges once the student edits it — **the student's edits must never be silently overwritten by regeneration**), `generated_at`.
- `Note.topic_ids` — changed from a single `topic_id` FK to a **many-to-many** `NoteTopic` link table, since one note now maps to 2–3 topics, not one.

**Kept as-is:** `Understanding`, `Entity`, `Reminder`, `Contact`, `NoteContact`, `LntAnalysisRow` — untouched, per §1.

## 4. New backend modules, replacing `app/hierarchy/*`

A new `app/graph/` package:

- `topic_extraction.py` — replaces `app/understanding/organizer.py`'s matching logic. Prompts the LLM: "extract 2–3 topics from this text." Direct extraction every time, per the paper — no embedding-similarity shortcut.
- `cross_disciplinary.py` — the "2 recommended topics" step (4.3.2).
- `connections.py` — asks the LLM which topics connect to which, writes `TopicConnection` rows; replaces `app/hierarchy/clustering.py`'s DBSCAN approach entirely (NexaNota's connections are LLM-judged, not embedding-distance-clustered).
- `note_generator.py` — replaces `app/hierarchy/cluster_summary.py` and `app/hierarchy/summarization.py`. One LLM call per note that returns the three Note-Taking Area subsections.
- `web_resources.py` — the per-topic external-link suggestions (4.3.2). **See §6 before building this one.**
- `replay.py` — new. Builds the timestamped segment view from the note's ASR segments (the transcriber already produces per-segment timing — `asr_segment_count` on `Note` confirms segment-level data exists; I'll need to check `app/asr/transcriber.py` for whether segment-level timestamps are already stored or only counted, since `replay.py` needs the timestamps themselves, not just a count).
- `service.py` — orchestrates the above (mirrors what `app/hierarchy/service.py` does today), so `app/pipeline/capture_pipeline.py`'s `_organize_note` calls one function here instead of `organize()`.

`app/understanding/organizer.py`, `app/hierarchy/embeddings.py`, `app/hierarchy/clustering.py`, `app/hierarchy/cluster_summary.py`, `app/hierarchy/summarization.py`, `app/hierarchy/tree.py`, `app/hierarchy/outline.py`, `app/hierarchy/overview.py`, `app/hierarchy/commands.py` are all **removed** (their logic has no equivalent in NexaNota's design, or is directly replaced above).

## 5. API changes

- `api/v1/hierarchy.py` → replaced by `api/v1/graph.py`: `GET /api/v1/graph/{subject_id}` (nodes + edges), `POST /api/v1/graph/subjects`, topic CRUD.
- `api/v1/summarization.py` → **removed** (topic/subject roll-up summaries don't exist in NexaNota's design; each *note* has its own generated content instead).
- `api/v1/notes.py` → extended: `GET /api/v1/notes/{id}` now returns the 3-area `NoteContent`; `PATCH /api/v1/notes/{id}/edit` saves Edit Area markdown.
- New `GET /api/v1/notes/{id}/replay` — the timestamped transcript view.
- `schemas/hierarchy.py` → replaced by `schemas/graph.py` and an extended `schemas/note.py`.

**Downstream adaptation (not rewrite):** `app/rag/indexer.py`'s `build_metadata()` currently reads `note.topic.subject` (single topic) — becomes "for each of the note's 2–3 topics, write one metadata copy," a small, mechanical change. `app/reminders/*` doesn't touch topics at all, so no change needed there. Voice commands (`app/hierarchy/commands.py`) that say "what notes are under X" get rebuilt against the graph API instead of the tree.

## 6. Two things I need a decision on before writing any code

**Web-resource links (§4.3.2, `WebResource` table).** The paper's system genuinely searched the web via its LLMs for real academic papers/blogs. Your backend's Anthropic integration, as currently wired (`app/llm/anthropic_client.py`), makes plain text-generation calls with no web access — asking it for a URL risks the model **inventing a plausible-looking but fake link**, which would be actively misleading in a note-taking app. Options: (a) give the LLM real web search (would need a search API/tool wired in — real scope, real cost); (b) have it suggest resource *topics/titles* without a URL, clearly labeled "suggested search: ___", so nothing is fabricated as if verified; (c) skip this one piece and build everything else. Tell me which.

**Lecture replay's time unit.** NexaNota's replay is designed around 30–45 minute lecture videos with a scrubbable timeline. Your app's unit is a short voice note (seconds to a few minutes), captured one at a time. I'd build replay per-note (a timestamped view of that one capture's segments) rather than per-course, which is the faithful equivalent at your app's scale — flagging this mapping so it isn't a silent assumption.

## 7. Frontend changes

- `HierarchyPanel.tsx` → replaced with a `GraphPanel.tsx`. Note: NexaNota's own accessibility case for a visual graph is weak for this project's blind/visually-impaired users (a node-and-edge diagram is inherently a sighted-first UI) — I'd keep it screen-reader-first by rendering the graph as **structured headings + a "connects to" list per topic** (same accessible pattern as today's `HierarchyPanel`), not a canvas/SVG diagram, unless you want an actual visual graph too.
- `NotesPanel.tsx` → extended to show the three areas per note (Note-Taking / Link / Edit), with the Edit Area as an actual editable markdown field.
- New `ReplayPanel.tsx` for the timestamped transcript view.
- `types.ts` → `Outline`/`HierarchyTopic`/`HierarchySubject` replaced with `Graph`/`GraphTopic`/`GraphEdge`; new `NoteContent` type.

## 8. Test impact

Every test file under `tests/` that covers `app/hierarchy/*` or `app/understanding/organizer.py` (a large fraction of your 514 passing tests) will need rewriting against the new modules — this is expected and unavoidable given "replace the current design," not a sign of something going wrong.

## 9. Suggested build order

1. New DB models + migration path (delete `backend/data/echonotes.db` once, since this is a breaking schema change — not `create_all`-compatible).
2. `app/graph/topic_extraction.py` + `connections.py` + `service.py`, wired into `capture_pipeline.py`.
3. `app/graph/note_generator.py` (3-area content).
4. `app/graph/replay.py`.
5. `app/graph/web_resources.py` (pending your §6 decision).
6. New/updated API routes + schemas.
7. Frontend: `GraphPanel`, extended `NotesPanel`, new `ReplayPanel`.
8. Rewrite the affected tests.

I'd do this on its own git branch given the size of the change, so your current working `master` stays demoable while this is in progress — happy to walk you through creating one when you're ready to start.
