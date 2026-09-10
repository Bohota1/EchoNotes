# EchoNotes

Voice-first, screen-reader-first note-taking for blind and low-vision users.

EchoNotes implements two research papers:

1. **LNT — "Artificial intelligence inspired multilanguage framework for note-taking and
   qualitative content-based analysis of lectures"** (Saini et al., *Education and Information
   Technologies*, 2023, 28:1141–1163). Implemented **exactly as specified in the paper**: the
   audio → text → NLP → analysis pipeline, its summarization method, thematic analysis, topic
   modeling, and the content-quality score `Qi`.
2. **Idea11y — "Enhancing Accessibility in Collaborative Ideation for Blind or Low Vision Screen
   Reader Users"** (Li et al., CHI '26). Only **Design Goal 1 and 2** are adopted: the
   hierarchical, editable, screen-reader navigable **header–subheader–bullet outline**, the
   AI-generated per-cluster summaries, and the overview section. **The whiteboard / Miro canvas
   half of Idea11y is deliberately not implemented** — EchoNotes has no 2D canvas, so there is no
   gestalt-on-coordinates clustering and no two-way canvas sync.

## Core features

| # | Feature | Where it lives |
|---|---------|----------------|
| 1 | Voice-based note capture (spacebar trigger → speech to text) | `backend/app/capture`, `backend/app/audio`, `backend/app/asr` |
| 2 | AI-powered note understanding (clean, classify, extract) | `backend/app/understanding` |
| 3 | Intelligent classification & hierarchical organization | `backend/app/understanding/classifier.py`, `backend/app/hierarchy` |
| 4 | Voice-based AI retrieval & assistance (RAG) + TTS | `backend/app/rag`, `backend/app/tts` |
| 5 | Smart reminders & contacts | `backend/app/reminders` |
| 6 | AI summarization | `backend/app/nlp/summarization.py`, `backend/app/hierarchy/cluster_summary.py` |
| 7 | Image / OCR note capture | `backend/app/ocr` |

**Interaction loop:** Trigger → Record → Transcribe → Understand → Organize → Store → Retrieve →
Respond. Encoded literally in `backend/app/pipeline/loop.py`.

## Stack

- **Backend** — Python 3.11+, FastAPI. LNT pipeline uses the paper's own libraries: `pydub`,
  `SpeechRecognition` (Google Web Speech API), `googletrans`, `nltk`, `gensim` (Word2Vec),
  `scikit-learn` (LDA, MinMaxScaler), `textstat`.
- **Frontend** — React + TypeScript + Vite. Screen-reader-first: semantic headings, ARIA live
  regions, full keyboard operation, no mouse-only affordances.
- **Storage** — SQLite for the note hierarchy, ChromaDB for the RAG vector index.

## Layout

```
EchoNotes/
├── docs/           architecture, paper-to-code traceability, a11y contract, data model
├── backend/        FastAPI service + the LNT pipeline
│   └── app/
│       ├── pipeline/       the 8-stage interaction loop
│       ├── capture/        spacebar trigger + recorder      (Feature 1)
│       ├── audio/          normalization + silence chunking (LNT §3.3)
│       ├── asr/            speech recognition, language detect, translate (LNT §3.2)
│       ├── nlp/            tokenize, lemmatize, word2vec, summarize, themes, LDA (LNT §3.4)
│       ├── quality/        readability, cohesion, coherence, entropy, Qi (LNT §3.5)
│       ├── understanding/  clean, classify, extract entities (Feature 2)
│       ├── hierarchy/      Subject → Topic/Project → Note outline (Idea11y DG1/DG2)
│       ├── rag/            embeddings, Chroma store, intent, retriever, answerer (Feature 4)
│       ├── tts/            speech output, voice profiles, earcons
│       ├── reminders/      tasks, dates, contacts (Feature 5)
│       ├── ocr/            camera/image note capture (Feature 7)
│       └── db/             SQLAlchemy models + repositories
└── frontend/       accessible outline UI
```

## Getting started

```bash
cd backend && python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt
```

```bash
cp .env.example backend/.env
```

```bash
cd backend && python scripts/bootstrap_nltk.py
```

```bash
cd backend && uvicorn app.main:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

See [docs/architecture.md](docs/architecture.md) and [docs/paper-mapping.md](docs/paper-mapping.md).
