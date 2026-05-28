# Meeting Intelligence Agent

Production-grade meeting analyzer that converts audio recordings or transcripts into structured intelligence. Upload an MP3 or paste a transcript — the agent extracts decisions, action items, open questions and pending topics, indexes everything in PostgreSQL for semantic search, and lets you ask questions about the meeting in natural language.

**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)

---

## The problem

After every meeting someone takes incomplete notes, action items get lost, and a week later nobody remembers what was decided. Existing tools (Otter.ai, Teams transcription) give you a wall of text. Nobody reads it. There's no open-source tool that converts a meeting recording into structured, queryable intelligence.

---

## Solution

A 6-node LangGraph pipeline that transcribes audio with faster-whisper, segments the transcript, extracts structured data with Claude, indexes everything in PostgreSQL with pgvector for RAG, and generates a downloadable markdown report.

**Two input modes:**
- Upload an audio file (MP3, WAV, M4A, OGG, FLAC) → faster-whisper transcribes it
- Paste a transcript directly → skip transcription, go straight to extraction

**RAG on every meeting:**
After analysis you can ask natural language questions about the meeting — "Who is responsible for the budget review?" — and the system searches the indexed chunks with semantic similarity to answer accurately.

---

## Architecture

```
Audio / Transcript
        │
        ▼
┌──────────────────┐
│ Transcriber Node │  faster-whisper converts audio to text
│    (Node 1)      │  Supports MP3, WAV, M4A, OGG, FLAC, WEBM
│                  │  VAD filter removes silences automatically
│                  │  OR accepts raw text directly
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Segmenter Node   │  Splits transcript into ~600-word chunks
│    (Node 2)      │  with 50-word overlap between segments
│                  │  Same chunking principle as RAG PDF Agent
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Extractor Node  │  Claude processes each segment separately
│    (Node 3)      │  Extracts: decisions, action items (with
│                  │  owner + deadline + priority), open questions,
│                  │  pending topics
│                  │  Results deduplicated across segments
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Indexer Node    │  Saves meeting metadata to PostgreSQL
│    (Node 4)      │  Saves structured extractions as JSONB
│                  │  Generates OpenAI embeddings for each chunk
│                  │  Stores vectors in pgvector for RAG
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Synthesizer Node │  Claude receives all extractions as JSON
│    (Node 5)      │  (not the raw transcript) and generates
│                  │  3-5 sentence executive summary + key topics
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Report Generator │  Builds markdown report + structured JSON
│    (Node 6)      │  No LLM needed — formats existing data
│                  │  Priority-colored action items (🔴🟡🟢)
│                  │  Downloadable .md file
└──────────────────┘
```

---

## Key features

**faster-whisper transcription**
4x faster than openai-whisper with the same model quality. Uses CTranslate2 as backend instead of PyTorch directly. VAD (Voice Activity Detection) filter automatically removes silences and background noise. Supports auto language detection across 99 languages.

**Segment-level extraction**
Claude processes each ~600-word chunk separately instead of the full transcript. More precise, cheaper, and avoids context window limits on long meetings. Results are merged and deduplicated at the end.

**Synthesizer sees JSON, not raw text**
The executive summary is generated from structured extractions (decisions, action items as JSON), not from 15,000 words of transcript. Claude can focus on synthesizing instead of re-extracting.

**RAG on meeting content**
Every meeting is indexed in PostgreSQL with pgvector. The `/ask` endpoint accepts natural language questions and uses cosine similarity search to find the relevant chunks before calling Claude to answer. Questions are answered from the actual meeting content, not from memory.

**Atomic PostgreSQL transactions**
Meeting metadata, structured extractions, and vector chunks are saved in a single transaction. If anything fails, the rollback is automatic — no partial data.

**SSE streaming progress**
Analysis takes 20-60 seconds. The UI shows real-time progress for each node: transcribing → segmenting → extracting → indexing → summarizing → generating report.

**Glassmorphism UI**
Light background with blur effects — visually distinct from the other agents in the portfolio. Two-column layout with the form in the sidebar and results on the right.

---

## Tech stack

| Layer | Technology |
|---|---|
| Pipeline orchestration | LangGraph (6-node stateful graph) |
| Audio transcription | faster-whisper (base model, CPU) |
| Audio preprocessing | pydub |
| LLM | Anthropic Claude Haiku |
| Embeddings | OpenAI text-embedding-3-small |
| Vector storage | PostgreSQL 16 + pgvector |
| Database | PostgreSQL (separate instance from Doc Intel Agent) |
| Streaming | Server-Sent Events (SSE) |
| Backend | FastAPI, Python 3.12 |

---

## Key technical decisions

**Why faster-whisper instead of openai-whisper?**
openai-whisper requires FFmpeg installed at system level and has frequent dependency conflicts. faster-whisper uses CTranslate2 — same Whisper model weights, same output quality, 4x faster inference, fewer installation issues. The `get_transcriber()` singleton loads the model once at startup and reuses it across all requests — loading Whisper on every request would add 3-5 seconds of latency.

**Why segment before extracting?**
A 1-hour meeting transcript is ~15,000 words (~20,000 tokens). Sending that to Claude in one call would consume almost the entire context window, reducing precision on details mentioned early in the meeting. Segmenting into 600-word chunks with 50-word overlap gives Claude focused, manageable context for each extraction.

**Why 50-word overlap between segments?**
A decision or action item mentioned at the boundary between two segments would be split — incomplete in both. The overlap guarantees that any phrase spanning a boundary is fully present in at least one segment. Same principle as the Document Intelligence Agent's chunking.

**Why does the synthesizer receive JSON instead of the transcript?**
By the time the synthesizer runs, all decisions and action items are already structured. Sending 15,000 words of raw transcript to generate a 5-sentence summary is wasteful and imprecise. The synthesizer receives a clean JSON summary of ~50 lines — Claude can focus entirely on synthesis.

**Why a separate PostgreSQL instance from the Document Intelligence Agent?**
Each agent should be independently deployable. If the Meeting Intelligence Agent needs to be restarted or migrated, it shouldn't affect the Document Intelligence Agent's data. Port 5432 for Doc Intel, port 5433 for Meeting Intel.

**Why store extractions as JSONB instead of separate tables?**
The structure of decisions and action items may evolve — adding a `confidence` field or changing how deadlines are stored. JSONB allows schema changes without ALTER TABLE migrations on the database.

---

## Limitations

- **CPU-only by default.** `WHISPER_DEVICE=cpu` in `.env`. On CPU, transcription takes roughly 1x the audio duration (a 10-minute meeting takes ~10 minutes). Set `WHISPER_DEVICE=cuda` for GPU acceleration.
- **No speaker diarization.** The agent transcribes what was said but doesn't identify who said it. Owner assignment in action items relies on Claude inferring from context ("Carlos will...").
- **Extraction is approximate.** Claude may miss items that are implied but not explicitly stated, or merge similar items that should be separate.
- **English-optimized prompts.** The extraction prompts are in English. Results are good for Spanish and English meetings but may be less precise for other languages.

---

## Running locally

```bash
# Start PostgreSQL for this agent (separate from Doc Intel)
docker run -d \
  --name meeting_intel_db \
  -e POSTGRES_USER=your_user \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=meeting_intel \
  -p 5433:5432 \
  --restart unless-stopped \
  pgvector/pgvector:pg16

# Add to .env
MEETING_DATABASE_URL=postgresql://your_user:your_password@localhost:5433/meeting_intel
WHISPER_MODEL_SIZE=base
WHISPER_DEVICE=cpu

# Start server
uvicorn backend.main:app --reload --port 8000
open http://localhost:8000/meeting-intel/demo
```

---

## API

```
POST /meeting-intel/analyze/stream
     Body: multipart/form-data
       file: audio file (optional)
       raw_text: transcript text (optional)
       meeting_title: string
       language: "auto" | "es" | "en"
     Response: SSE stream
     Events: { step, message, progress }
     Final: { step: "done", report: { ... } }

POST /meeting-intel/ask
     Body: { meeting_id, question, top_k? }
     Response: { answer, chunks_used, meeting_id }

GET  /meeting-intel/demo
     Glassmorphism UI with audio upload and RAG Q&A
```

---

## Project structure

```
backend/agents/meeting_intel_agent/
├── state.py                    # LangGraph TypedDict state
├── graph.py                    # LangGraph orchestrator
├── api.py                      # FastAPI endpoints + SSE
├── nodes/
│   ├── transcriber_node.py     # faster-whisper audio → text
│   ├── segmenter_node.py       # Split transcript into chunks
│   ├── extractor_node.py       # Claude extracts structured data
│   ├── indexer_node.py         # PostgreSQL + pgvector indexing
│   ├── synthesizer_node.py     # Claude executive summary
│   └── report_generator_node.py # Markdown + JSON report
├── transcription/
│   └── whisper_transcriber.py  # faster-whisper singleton
├── db/
│   └── database.py             # PostgreSQL tables + connection
└── frontend/
    └── index.py                # Glassmorphism UI
```