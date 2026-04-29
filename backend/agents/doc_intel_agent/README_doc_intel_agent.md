# Document Intelligence Agent

Production-grade document Q&A system. Upload PDFs, ask questions in natural language, and get answers with exact citations — powered by PostgreSQL + pgvector for semantic search, Cloudflare R2 for persistent storage, and Claude for generation. Fully containerized with Docker.

**Live demo:** [coming soon]  
**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)

---

## The problem

Companies accumulate hundreds of documents — contracts, reports, manuals, invoices — that nobody can search intelligently. Ctrl+F finds keywords but misses meaning. ChatGPT doesn't know your internal documents. Traditional search can't understand "what were the payment terms in the 2024 supplier agreements?" without reading every contract.

---

## Solution

A RAG (Retrieval-Augmented Generation) pipeline that indexes documents into a production-grade vector database and answers questions by finding semantically relevant passages — not keyword matches.

**What makes it production-ready vs a prototype:**
- PostgreSQL + pgvector instead of ChromaDB — a real database that scales, supports concurrent connections, and allows combining vector search with SQL filters
- Cloudflare R2 for PDF storage — files survive server restarts and redeployments (unlike local filesystem on ephemeral cloud servers)
- Docker + docker-compose — the entire system (API + database) runs with a single command on any machine
- Multi-document support — index any number of documents, search across all simultaneously or filter to a specific one

---

## Architecture

```
User uploads PDF
       │
       ▼
  FastAPI endpoint
       │
  ┌────┴───────────────────────────────┐
  │                                    │
  ▼                                    ▼
Cloudflare R2                  document_processor.py
(PDF stored permanently)              │
                              ┌───────┴────────┐
                              │                │
                         pypdf extracts   split into chunks
                         text by page     (~500 words +
                                          50 word overlap)
                                               │
                                        OpenAI embeddings
                                        text-embedding-3-small
                                        1536-dimensional vectors
                                               │
                                        PostgreSQL + pgvector
                                        (chunks + vectors stored)

User asks a question
       │
       ▼
  OpenAI embeddings (question → vector)
       │
       ▼
  pgvector cosine similarity search
  (top 5 most relevant chunks)
       │
       ▼
  Claude Haiku
  (answer grounded in chunks, with citations)
       │
       ▼
  Response with:
  - Natural language answer
  - Source pills [filename · page]
  - Expandable raw chunk text
```

---

## Key features

**Semantic search**
Questions are converted to embeddings and matched against chunk embeddings using cosine distance. "What were the payment conditions?" finds chunks about "invoice terms" and "billing schedule" — no keyword overlap needed.

**Exact citations**
Every answer includes which document and page number the information comes from. Source pills appear below each response. Claude is instructed to never use outside knowledge — only what's in the indexed chunks.

**Expandable source chunks**
Each response includes a "Show source chunks" toggle that reveals the exact text passages Claude used to generate the answer. Full transparency into the retrieval process.

**Compare mode**
A "Compare all" button sends the same question to every indexed document simultaneously and returns one response card per document. Useful for finding how different contracts, reports, or papers answer the same question. Scales to any number of documents — responses are stacked vertically.

**Multi-document scope**
Search across all indexed documents simultaneously, or filter to a specific one using the scope selector in the sidebar.

**Persistent storage**
PDFs are stored in Cloudflare R2 — they survive server restarts and container recreation. Embeddings are stored in PostgreSQL with a persistent Docker volume.

**Fully containerized**
Two containers managed by docker-compose: the FastAPI service and PostgreSQL with pgvector. Any developer can run the full system with `docker-compose up --build` — no local PostgreSQL installation needed.

**Chunk overlap**
Text is split with 50-word overlap between consecutive chunks. Information at the boundary between chunks is never lost — each chunk shares context with its neighbors.

---

## Tech stack

| Layer | Technology |
|---|---|
| Containerization | Docker + docker-compose |
| Vector database | PostgreSQL 16 + pgvector |
| PDF storage | Cloudflare R2 (S3-compatible API) |
| Embeddings | OpenAI text-embedding-3-small (1536 dimensions) |
| LLM | Anthropic Claude Haiku |
| PDF text extraction | pypdf |
| ORM | SQLAlchemy |
| Storage client | boto3 (S3-compatible, pointing to R2) |
| Backend | FastAPI, Python 3.12 |
| Deployment | Render |

---

## Key technical decisions

**Why PostgreSQL + pgvector instead of ChromaDB?**
ChromaDB is a purpose-built vector store — great for prototypes. PostgreSQL with pgvector does the same semantic search but inside a production database that also handles concurrent connections, transactions, backups, and SQL queries on metadata. In production you'd often want to filter by metadata (e.g., "contracts from 2024") and do semantic search simultaneously — that's trivial in PostgreSQL and awkward in ChromaDB.

**Why Cloudflare R2 instead of local storage?**
Render and most cloud platforms use ephemeral filesystems — any file written to disk disappears on redeploy. R2 is S3-compatible persistent object storage with 10GB free permanently. Using boto3 (the AWS S3 client) with R2's endpoint URL means zero code changes if you later migrate to actual S3.

**Why Docker?**
Without Docker, setting up this agent requires installing PostgreSQL, running the pgvector extension, configuring users and databases, and making sure versions match. With docker-compose, all of that is codified in two files. `docker-compose up --build` gives any developer the full working system in under 3 minutes.

**Why chunk overlap?**
When splitting text into fixed-size chunks, important information often falls at the boundary between two chunks. With 50-word overlap, each chunk shares its last 50 words with the beginning of the next chunk. This ensures boundary information is captured by at least one chunk during retrieval.

**Why separate statistical embedding from LLM generation?**
Embeddings are computed once at index time and stored. At query time, only the question is embedded (one fast API call). Claude is only invoked after retrieval — it receives a small, focused context rather than the entire document. This keeps latency low and cost predictable regardless of document size.

---

## Limitations

- **pypdf only extracts native text.** Scanned PDFs or image-based documents (where text is embedded in images) return little or no text. For those, OCR would be needed (e.g., AWS Textract, Tesseract). The agent detects this and raises a clear error.
- **Render uses ephemeral storage.** The PostgreSQL container on a free Render instance would need to be replaced with a managed PostgreSQL service (Render Postgres, Supabase, Neon) for true persistence in cloud deployment.
- **No re-indexing on update.** If a document is updated, you must delete it and re-upload. Partial chunk updates are not supported.
- **Context window limits.** top_k=5 chunks × ~500 words = ~2500 words of context per query. For very large documents with dispersed information, some relevant passages may not make the top 5.
- **Embedding cost.** OpenAI text-embedding-3-small costs ~$0.02 per million tokens. A 100-page document generates roughly 200 chunks × 500 words ≈ 100,000 tokens ≈ $0.002. Negligible at this scale.

---

## Running locally

```bash
# Clone the repo
git clone https://github.com/LanderIglesias/LanderWorks-Agents
cd LanderWorks-Agents

# Add environment variables
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY,
#          R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
#          R2_ENDPOINT_URL, R2_BUCKET_NAME

# Start both containers (PostgreSQL + FastAPI)
docker-compose up --build

# Open the demo
open http://localhost:8001/doc-intel/demo
```

**When to rebuild vs restart:**

| Changed | Command |
|---|---|
| Python code only | `docker-compose restart api` |
| requirements.txt | `docker-compose up --build` |
| Dockerfile or docker-compose.yml | `docker-compose up --build` |

---

## API

```
POST /doc-intel/upload
     Body: multipart/form-data — file (PDF, max 20MB)
     Response: {
       filename, r2_key, chunk_count, pages_processed, message
     }

POST /doc-intel/ask
     Body: { question: str, filename?: str, top_k?: int }
     Response: {
       answer: str,              — natural language answer
       sources: [{filename, page}],  — cited pages
       chunks_used: int,
       chunks_text: [{filename, page, content}]  — raw chunk text
     }

POST /doc-intel/compare
     Body: { question: str, top_k?: int }
     Searches all indexed documents simultaneously.
     Response: {
       question: str,
       results: [{
         filename, answer, sources, chunks_used, chunks_text
       }]  — one entry per indexed document
     }

GET  /doc-intel/documents
     Response: { documents: [{filename, r2_key, chunk_count, indexed_at}] }

GET  /doc-intel/document/{filename}/url
     Returns a presigned R2 URL valid for 1 hour.

DELETE /doc-intel/document/{filename}
     Removes chunks from PostgreSQL and PDF from R2.

GET  /doc-intel/demo
     Demo UI (light pastel theme, DM Serif Display + DM Sans).
```

---

## Project structure

```
backend/agents/doc_intel_agent/
├── api.py                  # FastAPI endpoints and Pydantic schemas
├── engine.py               # Orchestrator: index, ask, compare
├── database.py             # PostgreSQL + pgvector setup, CRUD operations
├── storage.py              # Cloudflare R2 upload/download/delete
├── document_processor.py   # PDF text extraction, chunking, embeddings
└── demo_template.py        # Demo UI — light pastel, compare mode, chunk viewer

docker-compose.yml          # PostgreSQL + FastAPI containers
Dockerfile                  # Python 3.12-slim image
.dockerignore               # Excludes .venv, chroma, __pycache__, etc.
```