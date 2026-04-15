# AI Portfolio — Lander Iglesias

Production-ready AI agents built to demonstrate real-world AI engineering skills. Each project is deployed, documented, and includes tests.

**Stack:** Python · FastAPI · LangChain · LangGraph · Claude (Anthropic) · OpenAI · ChromaDB · PyMuPDF · SQLite · Render

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

### 4. PDF Translator Agent — LangGraph Pipeline
Translates PDFs to any language while preserving layout, fonts, and document structure. Built as a LangGraph multi-agent pipeline with an iterative quality gate that verifies translations before reconstructing the document. Per-element language classification and strategy routing decide how each text region is handled.

**Tech:** Python · FastAPI · LangGraph · PyMuPDF · Claude Haiku · Claude Sonnet Vision  
**[View project →](backend/agents/pdf_translator_v2/)**

---

## Repository structure

```
backend/
├── main.py                        # FastAPI app entrypoint
└── agents/
    ├── dental_agent/              # WhatsApp agent for clinics
    ├── lead_capture_agent/        # Multi-tenant lead capture SaaS
    ├── rag_pdf_agent/             # RAG PDF chat agent
    └── pdf_translator_v2/         # LangGraph PDF translation pipeline
tests/
├── dental_agent/
├── lead_capture_agent/
└── rag_pdf_agent/
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
| `ANTHROPIC_API_KEY` | Lead capture agent · RAG agent · PDF Translator |
| `OPENAI_API_KEY` | RAG agent (embeddings) · Dental agent |
| `ADMIN_TOKEN` | Lead capture agent admin panel |
| `RESEND_API_KEY` | Lead capture agent email delivery |

---

## Contact

**LinkedIn:** [[https://linkedin.com/in/lander-iglesias-aldecoa](https://www.linkedin.com/in/lander-iglesias-aldecoa-/)] **Email:** landeriglesiasaldecoa@gmail.com
