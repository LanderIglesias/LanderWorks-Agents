# RAG PDF Chat Agent

Conversational agent that answers questions about PDF documents using Retrieval-Augmented Generation. Upload any PDF and ask questions in natural language — the agent responds using only the document content, with cited sources.

See [eval/README.md](eval/README.md) for the local vs. API model evaluation experiment.

---

## What it does

- Upload any PDF (up to 20 MB) and ask questions about it
- Answers grounded exclusively in the document — no hallucinations
- Cites the exact page and text fragment used to answer
- Remembers conversation history — supports follow-up questions
- Compare mode: upload two PDFs and ask questions about both simultaneously

---

## How RAG works

```
PDF → chunks (1000 chars) → embeddings (OpenAI) → ChromaDB
                                                        │
Question → embedding → similarity search → top 4 chunks
                                                        │
                                          prompt + chunks → Claude → answer + sources
```

1. **Ingestion (once):** the PDF is split into overlapping chunks, converted to embeddings via OpenAI and stored in ChromaDB.
2. **Query (each question):** the question is embedded, the 4 most similar chunks are retrieved, injected into the prompt alongside the conversation history, and Claude generates a grounded answer.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| AI — generation | Anthropic Claude Haiku |
| AI — embeddings | OpenAI text-embedding-3-small |
| Orchestration | LangChain (LCEL) |
| Vector store | ChromaDB |
| PDF parsing | PyPDFLoader |

---

## Running locally

```bash
# From project root
uvicorn backend.main:app --reload --port 8000
```

Open the demo:
```
http://localhost:8000/rag-agent/demo
```

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | /rag-agent/upload | Upload and index a PDF |
| POST | /rag-agent/chat | Ask a question with history |
| POST | /rag-agent/compare | Query two PDFs simultaneously |
| GET | /rag-agent/session/{id} | Check session status |
| DELETE | /rag-agent/session/{id} | Delete session data |
| GET | /rag-agent/demo | Demo UI |

---

## Environment variables

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

---

## Key design decisions

**Stateless history:** the client sends the full conversation history in each request. The backend converts it to LangChain HumanMessage/AIMessage objects and injects them via MessagesPlaceholder. No server-side session storage needed.

**Per-session ChromaDB:** each uploaded PDF gets its own ChromaDB directory identified by a UUID session ID. Sessions are isolated and can be deleted independently.

**Compare mode:** queries two vectorstores in parallel, formats the results as Document A and Document B contexts, and uses a dedicated prompt that instructs Claude to attribute information to the correct source.

---

## Running tests

```bash
pytest tests/rag_pdf_agent/ -v
```