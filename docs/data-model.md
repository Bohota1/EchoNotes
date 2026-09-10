# Data model

SQLite holds the hierarchy and every analysis artefact. ChromaDB holds one embedding per note for
retrieval. SQLite is authoritative; the Chroma index is always rebuildable from it.

## The three levels (Idea11y DG1)

Idea11y decomposed a board into **Frame → Cluster → Note**. EchoNotes keeps three levels and no
more, because the outline's readability for a screen reader depends on a shallow, predictable
depth:

| Idea11y | EchoNotes | Outline rendering |
|---|---|---|
| Frame | **Subject** (e.g. "Operating Systems", "Thesis") | `h1` |
| Cluster | **Topic / Project** (e.g. "Deadlock", "Chapter 3 rewrite") | `h2` + generated summary |
| Note | **Note** | `li` under the topic |

A note that cannot yet be filed goes to the **Unfiled** subject — the analogue of Idea11y's
"Unframed Section". Every note always has exactly one parent topic.

## Tables

### `subjects`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `name` | text | unique, case-insensitive |
| `created_at` | datetime | |
| `is_unfiled` | bool | exactly one row is true |

### `topics`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `subject_id` | fk → subjects | |
| `name` | text | |
| `kind` | enum | `topic` \| `project` |
| `summary` | text | AI-generated cluster summary, Idea11y §4.1 |
| `summary_stale` | bool | set when a child note changes; triggers regeneration |
| `created_at` | datetime | |

### `notes`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `topic_id` | fk → topics | |
| `note_type` | enum | `academic` \| `brainstorm` \| `todo` — EchoNotes Feature 3 |
| `source` | enum | `voice` \| `ocr` \| `manual` |
| `text` | text | cleaned, English, what is announced |
| `raw_transcript` | text | pre-cleaning ASR output |
| `source_language` | text | detected language before translation (LNT §3.2) |
| `summary` | text | LNT extractive summary when the capture was long |
| `audio_path` | text | nullable |
| `image_path` | text | nullable, OCR captures |
| `created_at` | datetime | |
| `updated_at` | datetime | |

### `analyses` — one row per capture (LNT §3.4, §3.5)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `note_id` | fk → notes | |
| `word_count` | int | |
| `word_frequencies` | json | LNT §3.4.4 |
| `themes` | json | LNT §3.4.6, from hapaxes / collocations / bigrams |
| `topics_lda` | json | LNT §3.4.7, topic → top terms + weight |
| `readability` | float | Flesch reading ease, normalized 0–1 |
| `cohesion` | float | normalized 0–1 |
| `coherence` | float | normalized 0–1 |
| `entropy` | float | normalized 0–1 |
| `quality_score` | float | `Qi`, LNT Eq. 5 |

### `entities` — LNT-adjacent extraction, EchoNotes Feature 5
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `note_id` | fk → notes | |
| `kind` | enum | `person` \| `date` \| `deadline` \| `task` \| `contact` |
| `value` | text | surface form as spoken |
| `normalized` | text | ISO-8601 for dates, E.164 for phone numbers |
| `span_start`, `span_end` | int | offsets into `notes.text` |

### `reminders` — EchoNotes Feature 5
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `note_id` | fk → notes | |
| `entity_id` | fk → entities | nullable |
| `title` | text | |
| `due_at` | datetime | |
| `status` | enum | `pending` \| `done` \| `dismissed` |

### `settings` — single row, the Idea11y settings section
| Column | Type | Notes |
|---|---|---|
| `voice_coding` | enum | `consistent` \| `by_type` |
| `feedback_mode` | enum | `earcon` \| `speech` \| `both` \| `none` |
| `announce_summaries` | bool | |
| `announce_quality` | bool | |
| `capture_trigger` | text | `spacebar` \| `hotkey` \| `gpio` |

## Vector index (ChromaDB)

One collection, `notes`. One document per note.

```
id:        note.id
document:  note.text
embedding: EMBEDDING_MODEL over note.text
metadata:  { subject, subject_id, topic, topic_id, note_type, source,
             created_at, quality_score }
```

Metadata carries the hierarchy so a voice query such as *"what did I note about deadlock in
Operating Systems last week"* becomes a filtered vector search rather than a pure similarity
search. Re-embedding happens on note create and on note text edit; a move only rewrites metadata.

## Clustering inputs (Idea11y §4.1 adapted)

The paper ran DBSCAN over canvas coordinates. With no canvas, `hierarchy/clustering.py` runs
DBSCAN over the note embeddings, so the feature vector for one note is:

```
embedding(note.text)              # semantic proximity  ~ gestalt proximity
+ one-hot(note_type)   * w_type   # note type           ~ gestalt colour similarity
+ one-hot(subject_id)  * w_subject # explicit subject   ~ gestalt bounded region
```

`w_type` and `w_subject` are configurable weights. Idea11y's precedence rule carries over: an
explicit boundary wins over colour, which wins over proximity — so a note with a user-assigned
subject is never pulled out of it by semantic similarity alone.
