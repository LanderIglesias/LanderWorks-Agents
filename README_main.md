# AI Portfolio — Lander Iglesias

Production-ready AI agents built to demonstrate real-world AI engineering skills. Each project is deployed, tested, and documented.

---

## Agents

### 1. AI WhatsApp Agent for Clinics
Conversational AI agent that handles patient inquiries on WhatsApp, collects structured information and helps clinics manage appointment requests automatically.

**Tech:** Python · FastAPI · Twilio · OpenAI · RAG · ChromaDB  
**[View project →](backend/agents/dental_agent/)**

---

### 2. AI Lead Capture SaaS Platform
Multi-tenant SaaS platform that deploys custom AI agents on any website with a single `<script>` tag. Each client gets their own agent trained on their business knowledge, with automatic lead capture and email delivery.

**Tech:** Python · FastAPI · Claude Haiku · SQLite · Resend · Render  
**[View project →](backend/agents/lead_capture_agent/)**  
**[Live demo →](https://dental-agent-bn18.onrender.com/scaffold-agent/demo?token=tok_synapse_demo_001)**

---

### 3. RAG PDF Chat Agent
Conversational agent that answers questions about PDF documents using Retrieval-Augmented Generation. Supports conversation history, expandable cited sources, and a compare mode to query two PDFs simultaneously.

**Tech:** Python · FastAPI · LangChain · Claude Haiku · OpenAI Embeddings · ChromaDB  
**[View project →](backend/agents/rag_pdf_agent/)**

---

### 4. PDF Translator — LangGraph Multi-Agent Pipeline
Translates PDFs to any language while preserving the original layout exactly. Uses a 7-node LangGraph pipeline with a quality gate that verifies translations before reconstructing the document.

**Tech:** Python · LangGraph · PyMuPDF · Claude Haiku · Claude Sonnet Vision · FastAPI  
**[View project →](backend/agents/pdf_translator/)**

---

## Stack

### AI & LLMs
| Tool | Used for |
|---|---|
| Claude Haiku (Anthropic) | Conversational agents, translation, lead capture |
| Claude Sonnet Vision (Anthropic) | PDF image analysis, text detection in images |
| OpenAI GPT | WhatsApp agent, dental FAQ responses |
| OpenAI Embeddings (`text-embedding-3-small`) | RAG vector search |
| LangChain + LCEL | RAG pipeline orchestration |
| LangGraph | Multi-agent pipeline with conditional edges and retry loops |

### Backend
| Tool | Used for |
|---|---|
| Python 3.12 | All agents |
| FastAPI | REST API for all agents |
| Pydantic | Data validation and schemas |
| PyMuPDF (fitz) | PDF parsing, text extraction span-by-span, PDF reconstruction |
| Pillow | Pixel-level image manipulation |
| Twilio | WhatsApp messaging |
| Resend | Transactional email delivery |

### Data & Storage
| Tool | Used for |
|---|---|
| ChromaDB | Vector store for embeddings (RAG) |
| SQLite | Session state, leads, events, tenants |
| PyPDFLoader | PDF loading and chunking for RAG |

### Dev & Deploy
| Tool | Used for |
|---|---|
| Render | Production deployment (auto-deploy from GitHub) |
| GitHub Actions | CI triggered on push |
| pytest | Unit and integration tests |
| Ruff + Black | Linting and formatting |
| gitleaks | Secret scanning in pre-commit hooks |
| pre-commit | Automated code quality checks |
| python-dotenv | Environment variable management |

---

## Repository structure

```
backend/
├── main.py                        # FastAPI app entrypoint
└── agents/
    ├── dental_agent/              # WhatsApp agent for clinics
    ├── lead_capture_agent/        # Multi-tenant lead capture SaaS
    ├── rag_pdf_agent/             # RAG PDF chat agent
    └── pdf_translator/            # LangGraph PDF translation pipeline
tests/
├── dental_agent/
├── lead_capture_agent/
├── rag_pdf_agent/
└── pdf_translator/
scripts/                           # CLI utilities
```

---

## Running locally

```bash
git clone https://github.com/SpicySabeso/ai-portfolio.git
cd ai-portfolio
pip install -r requirements.txt
cp .env.example .env
# Add your API keys to .env
uvicorn backend.main:app --reload --port 8000
```

---

## Environment variables

| Variable | Required for |
|---|---|
| `ANTHROPIC_API_KEY` | Lead capture agent · RAG agent · PDF translator |
| `OPENAI_API_KEY` | RAG agent (embeddings) · Dental agent |
| `ADMIN_TOKEN` | Lead capture agent admin panel |
| `RESEND_API_KEY` | Lead capture agent email delivery |

---

## Contact

**LinkedIn:** [linkedin.com/in/tu-perfil](https://linkedin.com/in/tu-perfil)  
**Email:** landeriglesiasaldecoa@gmail.com
