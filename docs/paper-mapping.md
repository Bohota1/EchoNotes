# Paper → Code traceability

Every module below cites the exact section of the source paper it implements. Keep this table
accurate: it is the contract that says the implementation follows the papers rather than
improvising.

---

## Paper 1 — LNT (Saini et al. 2023)

*"Artificial intelligence inspired multilanguage framework for note-taking and qualitative
content-based analysis of lectures", Education and Information Technologies 28:1141–1163.*

Implemented **exactly as described**. Where the paper names a library or an algorithm, we use that
library or algorithm.

| Paper section | What the paper specifies | Module |
|---|---|---|
| §3.1 Fig. 1 | Overall LNT layout: record → normalize → chunk → recognize → translate → analyze | `app/pipeline/loop.py` |
| §3.2 | Audio collection; multilanguage input; conversion of every language to **English** as the single standard analysis language | `app/capture/recorder.py`, `app/asr/language.py`, `app/asr/translation.py` |
| §3.3 | Pitch **normalization** with `pydub` (Fig. 2 raw → Fig. 3 normalized waveform); suppresses applause and outlier noise | `app/audio/normalization.py`, `app/audio/waveform.py` |
| §3.3 | **Chunking on silence** using a threshold in dBFS and a minimum silence duration in ms; a `.` is appended at the end of each recognized chunk | `app/audio/chunking.py` |
| §3.3 | Speech→text per chunk via the `SpeechRecognition` library + Google API, language specified, detected text appended to the file | `app/asr/recognizer.py` |
| §3.3 | Translation to English with `googletrans` when the source is not English | `app/asr/translation.py` |
| §3.3 | Text cleaning: strip extra whitespace, remove periods inside multi-period abbreviations, remove punctuation, plural→singular, lowercase | `app/nlp/preprocess.py` |
| §3.4.1 | **White-space tokenization** with space as delimiter; word / frequency / length dictionary; stop-word and noise-word removal | `app/nlp/tokenization.py` |
| §3.4.2 | **Lemmatization** with the NLTK `WordNetLemmatizer` (Morphy) — not stemming | `app/nlp/lemmatization.py` |
| §3.4.3 | **Word2Vec**, both **CBOW** and **continuous skip-gram** (Fig. 4), softmax output | `app/nlp/embeddings_w2v.py` |
| §3.4.4 | **Word frequency** table used for sentence scoring; Zipf's law; stop words ignored; root-word keys for the word cloud and thematic analysis | `app/nlp/word_frequency.py` |
| §3.4.5 | **Extractive summarization**: clean → sentence tokenize → build sentence vectors by averaging word2vec word vectors → **cosine similarity matrix** (Eq. 1) → similarity graph, nodes = sentences and edges = similarities → PageRank-style **sentence ranking** → emit the first **K** ranked sentences. Scoring features named by the paper: word frequency, sentence position, cue words, similarity to other sentences, sentence length, proper nouns, sentence reduction | `app/nlp/summarization.py` |
| §3.4.6 | **Thematic analysis** — themes extracted via **hapaxes, collocations and bigrams** | `app/nlp/thematic.py` |
| §3.4.7 | **Topic modeling with LDA** (Eq. 2, Eq. 3); topics grouped under themes as in Table 5 | `app/nlp/topic_modeling.py` |
| §3.5 Table 2 | Quality metrics: **Flesch reading ease**, **Cohesion**, **Coherence**, **Entropy** | `app/quality/metrics.py` |
| §3.5 Eq. 4 | **Min–max normalization** of every metric onto 0–1, equal weight per metric | `app/quality/scaling.py` |
| §3.5 Eq. 5 | `Quality Score (Qi) = Flesch_reading_ease + Cohesion + Coherence + Entropy`, normalized to 0–1. Higher Qi = more readable, more thematic integrity, less chaos | `app/quality/score.py` |
| §4.1 | Runtime order of operations for a whole lecture | `app/pipeline/loop.py` |
| §4.2, Tables 3–4 | Validation harness: ASR accuracy (~92% reported) and quality metrics against manual notes | `tests/test_quality_validation.py` |

**Reference values from the paper, used as regression targets in tests.** On the sample 30-minute
lecture: 1947 words, 9 themes, ~55 topics, a 284-word summary, one theme per ~217 words, one topic
per ~36 words, Readability 0.8, Cohesion 0.625, Coherence 0.592, Entropy 0.12, **Qi = 0.727**.

---

## Paper 2 — Idea11y (Li et al., CHI '26)

*Only the hierarchy and outline half is adopted. The whiteboard is out of scope.*

| Paper section | Adopted? | How it maps to EchoNotes |
|---|---|---|
| §4.1 DG1 — hierarchical, text-based representation | **Yes** | Three levels. Idea11y: Frame → Cluster → Note. EchoNotes: **Subject → Topic/Project → Note**, rendered as a **header–subheader–bullet list** (H1 / H2 / H3 + `ul`) so screen-reader users navigate with `H` and `Shift+H`. `app/hierarchy/tree.py`, `app/hierarchy/outline.py` |
| §4.1 — gestalt clustering by proximity / colour / bounded region, DBSCAN over canvas **coordinates** | **No canvas, so adapted** | EchoNotes has no x/y coordinates. Clustering runs **DBSCAN over sentence embeddings** (semantic proximity), plus the note's classified type and its subject. The three gestalt rules become: semantic proximity, note-type similarity (the analogue of colour), and explicit subject or project membership (the analogue of a bounded frame). `app/hierarchy/clustering.py` |
| §4.1 — AI-generated per-cluster summary, updated in real time | **Yes** | Every Topic/Project node carries a one-line generated summary, regenerated when a note beneath it changes. Idea11y used `gpt-4o-mini`; the provider is configurable here. `app/hierarchy/cluster_summary.py` |
| §4.1 — Board Overview: counts of frames, clusters, colours, collaborators | **Yes, adapted** | **Library Overview**: number of subjects, topics/projects and notes, plus the note-type breakdown, announced first in the outline. `app/hierarchy/overview.py` |
| §4.2 DG2 — add / edit / delete / move a note and change its colour **from inside the outline** | **Yes, adapted** | Add, edit, delete and **re-file** a note (move it to another Topic/Project through a drop-down of current clusters) directly in the outline. Inline input, `Enter` submits, `Escape` cancels — exactly the paper's interaction. "Colour" becomes **note type**: Academic, Brainstorm, To-Do. `frontend/src/components/Outline/` |
| §4.2 — two-way manipulation between canvas and outline | **No** | No canvas exists. The outline is the single source of truth. |
| §4.3 DG3 — collaboration awareness, collaborator location, jump shortcuts, co-presence earcons | **Not implemented** | EchoNotes is single-user. The **earcon and voice-coding machinery is kept** (`app/tts/earcons.py`, `app/tts/voice_profiles.py`) and repurposed for note type and capture-state feedback. |
| §4.3 — **voice coding**: distinct synthesized voices carrying a second channel of information | **Yes, adapted** | Distinct voices per **note type** rather than per collaborator, so a listener hears "this is a to-do" without an extra spoken clause. Configurable; the default is a single consistent voice, as in the paper. `app/tts/voice_profiles.py` |
| §4.3 — note-info shortcut announcing creator and colour | **Yes, adapted** | The shortcut announces note **type, subject, capture time and source** (voice or OCR). |
| §4.4 DG4 — brainstorming versus voting mode, accessible voting | **Not implemented** | Voting is a group-ideation feature; EchoNotes is single-user. Left out deliberately. |
| §4.5 — React + TypeScript front end, Web Speech API TTS, DBSCAN, LLM summaries | **Yes** | Same stack. Flask → FastAPI and Firebase → SQLite, since there is no real-time collaboration to synchronize. |

---

## Where the two papers join

For one capture the LNT pipeline produces: a cleaned English transcript, an extractive summary, a
theme list, an LDA topic list, and a quality score `Qi`. Those outputs are what fill the
Idea11y-style hierarchy.

- LNT **themes / topics** → candidate **Topic** nodes under a Subject.
- LNT **extractive summary** → the note body stored at the leaf.
- Idea11y **cluster summary** → the generated one-liner on the Topic node above those leaves.
- LNT **`Qi`** → announced on request per note, and aggregated per subject.
