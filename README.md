# AI Portfolio — Lander Iglesias

Production-ready AI agents built to demonstrate real-world AI engineering skills. Each project is deployed, tested, and documented.

**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)  
**LinkedIn:** [linkedin.com/in/lander-iglesias-aldecoa-](https://www.linkedin.com/in/lander-iglesias-aldecoa-/)  
**Email:** landeriglesiasaldecoa@gmail.com

---

## Agents

### 1. AI WhatsApp Agent for Clinics
Conversational AI agent that handles patient inquiries on WhatsApp, collects structured information (name, treatment, urgency) and escalates automatically to a human agent when needed.

**Tech:** Python · FastAPI · Twilio · OpenAI · RAG · ChromaDB  
**[View project →](backend/agents/dental_agent/)**

---

### 2. AI Lead Capture SaaS Platform
Multi-tenant SaaS platform that deploys custom AI agents on any website with a single `<script>` tag. Features streaming responses (SSE), LLM observability via Langfuse, and is deployed on both AWS EC2 and Azure App Service.

**Tech:** Python · FastAPI · Claude Haiku · SQLite · Resend · Langfuse · Streaming SSE · AWS EC2 · Azure App Service  
**[View project →](backend/agents/lead_capture_agent/)**

---

### 3. RAG PDF Chat Agent
Conversational agent that answers questions about PDF documents using Retrieval-Augmented Generation. Supports conversation history, expandable cited sources, and a compare mode to query two PDFs simultaneously.

**Tech:** Python · FastAPI · LangChain · Claude Haiku · OpenAI Embeddings · ChromaDB  
**[View project →](backend/agents/rag_pdf_agent/)**

---

### 4. PDF Translator — LangGraph Multi-Agent Pipeline
Translates PDFs to any language while preserving the original layout exactly. Uses a 7-node LangGraph pipeline with a quality gate that verifies translations before reconstructing the document. Handles both native text PDFs and image-based PDFs via pixel-level patching.

**Tech:** Python · LangGraph · PyMuPDF · Pillow · Claude Haiku · Claude Sonnet Vision · FastAPI  
**[View project →](backend/agents/pdf_translator_v2/)**

---

### 5. BI Agent — Multi-Agent Analytics
Natural language analytics for any CSV dataset. A 7-node LangGraph pipeline with SQL and Pandas specialists, a quality gate with automatic retry, statistical anomaly detection interpreted by Claude, and automatic chart generation.

**Tech:** Python · LangGraph · Claude Haiku · Pandas · SQLite · Matplotlib · FastAPI  
**[View project →](backend/agents/bi_agent/)**

---

### 6. Document Intelligence Agent
Production-grade document Q&A system. Upload PDFs, ask questions in natural language, get answers with exact citations. Compare mode sends the same question to all indexed documents simultaneously. Fully containerized with Docker.

**Tech:** Python · Docker · docker-compose · PostgreSQL + pgvector · Cloudflare R2 · OpenAI Embeddings · Claude Haiku · FastAPI  
**[View project →](backend/agents/doc_intel_agent/)**

---

### 7. Job Matcher Agent
Hybrid ML + LLM system that scores the fit between a CV and a job offer. Claude labels 500 synthetic training pairs, a GradientBoostingRegressor learns the scoring pattern, and Claude generates a qualitative gap report. Accepts PDF/DOCX/URL input.

**Tech:** Python · scikit-learn · GradientBoostingRegressor · Claude Haiku · PyMuPDF · python-docx · httpx · BeautifulSoup · FastAPI  
**[View project →](backend/agents/job_matcher_agent/)**

---

## Stack

### AI & LLMs
| Tool | Used for |
|---|---|
| Claude Haiku (Anthropic) | Conversational agents, translation, lead capture, analytics, gap reports |
| Claude Sonnet Vision (Anthropic) | PDF image analysis, text detection in images |
| OpenAI Embeddings (`text-embedding-3-small`) | RAG vector search, document indexing |
| LangChain + LCEL | RAG pipeline orchestration |
| LangGraph | Multi-agent pipelines with conditional edges and retry loops |
| Langfuse | LLM observability — traces, token tracking, conversation metadata |
| scikit-learn | GradientBoosting, RandomForest, LinearRegression — Job Matcher Agent |

### Backend
| Tool | Used for |
|---|---|
| Python 3.12 | All agents |
| FastAPI | REST API for all agents |
| Streaming SSE | Progressive streaming responses (Lead Capture Agent) |
| Pydantic | Data validation and schemas |
| PyMuPDF | PDF parsing, text extraction, PDF reconstruction |
| Pillow | Pixel-level image manipulation |
| pypdf | PDF text extraction for RAG |
| python-docx | DOCX extraction — Job Matcher Agent |
| httpx + BeautifulSoup | URL scraping — Job Matcher Agent |
| SQLAlchemy | ORM for PostgreSQL |
| boto3 | S3-compatible storage client (Cloudflare R2) |
| Twilio | WhatsApp messaging |
| Resend | Transactional email delivery |

### Data & Storage
| Tool | Used for |
|---|---|
| PostgreSQL + pgvector | Production vector store — Document Intelligence Agent |
| ChromaDB | Vector store for RAG agents |
| SQLite | Session state, leads, events, tenants |
| Pandas + NumPy | Data analysis — BI Agent |
| Matplotlib | Chart generation — BI Agent |

### Infrastructure & Cloud
| Tool | Used for |
|---|---|
| Docker + docker-compose | Containerization — Document Intelligence Agent |
| AWS EC2 | Cloud deployment — t3.micro (eu-west-1) |
| AWS IAM | User management and access control |
| AWS ECR | Container registry |
| Azure App Service | PaaS deployment — Lead Capture Agent (B1, West Europe) |
| Azure Container Registry (ACR) | Private Docker image registry |
| Cloudflare R2 | S3-compatible persistent PDF storage |
| Render | Production deployment for non-containerized agents |
| GitHub Actions | CI/CD — auto-deploy on push |

### Dev & Quality
| Tool | Used for |
|---|---|
| pytest | Unit and integration tests |
| Ruff + Black | Linting and formatting |
| gitleaks | Secret scanning in pre-commit hooks |
| pre-commit | Automated code quality checks |
| python-dotenv | Environment variable management |

---

## Repository structure

```
backend/
├── main.py                  # FastAPI app entrypoint
└── agents/
    ├── dental_agent/        # WhatsApp agent for clinics
    ├── lead_capture_agent/  # Multi-tenant lead capture SaaS + Langfuse + SSE
    ├── rag_pdf_agent/       # RAG PDF chat agent
    ├── pdf_translator_v2/   # LangGraph PDF translation pipeline
    ├── bi_agent/            # Multi-agent BI analytics (LangGraph)
    ├── doc_intel_agent/     # Document intelligence (Docker + PostgreSQL)
    └── job_matcher_agent/   # ML + LLM CV/job fit scorer
ml_intro/                    # Classical ML fundamentals (sklearn)
tests/
scripts/
docker-compose.yml
Dockerfile
```

---

## Running locally

```bash
git clone https://github.com/LanderIglesias/LanderWorks-Agents.git
cd LanderWorks-Agents
pip install -r requirements.txt
cp .env.example .env  # Add your API keys
uvicorn backend.main:app --reload --port 8000
```

For the Document Intelligence Agent (requires Docker):

```bash
docker-compose up --build
# Demo available at http://localhost:8001/doc-intel/demo
```

---

## Environment variables

| Variable | Required for |
|---|---|
| `ANTHROPIC_API_KEY` | All Claude-powered agents |
| `OPENAI_API_KEY` | RAG agents (embeddings) · Dental agent |
| `LANGFUSE_PUBLIC_KEY` | Lead capture agent (LLM observability) |
| `LANGFUSE_SECRET_KEY` | Lead capture agent (LLM observability) |
| `ADMIN_TOKEN` | Lead capture agent admin panel |
| `RESEND_API_KEY` | Lead capture agent email delivery |
| `TWILIO_ACCOUNT_SID` | WhatsApp agent |
| `TWILIO_AUTH_TOKEN` | WhatsApp agent |
| `DATABASE_URL` | Document Intelligence Agent (PostgreSQL) |
| `R2_ACCESS_KEY_ID` | Document Intelligence Agent (Cloudflare R2) |
| `R2_SECRET_ACCESS_KEY` | Document Intelligence Agent (Cloudflare R2) |
| `R2_ENDPOINT_URL` | Document Intelligence Agent (Cloudflare R2) |
| `R2_BUCKET_NAME` | Document Intelligence Agent (Cloudflare R2) |
