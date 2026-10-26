"""
Motor RAG con LangChain — versión 2.

Mejoras sobre v1:
1. HISTORIAL DE CONVERSACIÓN: el agente recuerda preguntas anteriores
   usando MessagesPlaceholder para incluir el historial en el prompt.

2. FUENTES CON TEXTO EXACTO: devolvemos el fragmento exacto del PDF
   que se usó para responder, no solo el número de página.

3. MODO COMPARAR: acepta dos session_ids y busca en ambos vectorstores,
   combinando los chunks más relevantes de cada PDF para responder.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
TOP_K_CHUNKS = 4
CHROMA_BASE_DIR = Path(__file__).resolve().parent / "data" / "chroma"

# ── Prompts ───────────────────────────────────────────────────────────────────

# Prompt para una sola fuente — incluye historial de conversación.
SINGLE_PDF_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Eres un asistente que responde preguntas sobre un documento PDF.
Responde ÚNICAMENTE basándote en el siguiente contexto extraído del documento.
Si la respuesta no está en el contexto, di "No encontré esa información en el documento."
Responde en el mismo idioma que la pregunta.
Sé conciso y cita el número de página cuando sea posible.

Contexto del documento:
{context}""",
        ),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ]
)

# Prompt para modo comparar — dos PDFs a la vez.
COMPARE_PDF_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an assistant that compares and analyzes two PDF documents simultaneously.
Answer based ONLY on the provided contexts.
Always attribute information to the correct document (Document A or Document B).
If information is not found in either document, say so explicitly.
IMPORTANT: Always respond in the same language as the user's question.

When comparing the two documents, structure your response as:
1. A brief summary of each document's approach
2. A markdown comparison table with the key differences
3. A short conclusion

Contexto del Documento A:
{context_a}

Contexto del Documento B:
{context_b}""",
        ),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ]
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_session_id(session_id: str) -> str:
    """Valida que session_id sea un UUID válido para evitar path traversal."""
    try:
        return str(uuid.UUID(session_id))
    except (ValueError, AttributeError, TypeError) as e:
        raise ValueError(f"session_id inválido: {session_id!r}") from e


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model="text-embedding-3-small")


def _load_vectorstore(session_id: str) -> Chroma:
    session_id = _validate_session_id(session_id)
    persist_dir = str(CHROMA_BASE_DIR / session_id)
    return Chroma(
        persist_directory=persist_dir,
        embedding_function=_get_embeddings(),
    )


def _format_docs(docs) -> str:
    """Formatea chunks con número de página para incluirlos en el prompt."""
    return "\n\n---\n\n".join(
        f"[Página {doc.metadata.get('page', '?') + 1}]\n{doc.page_content}" for doc in docs
    )


def _build_history(chat_history: list[dict]) -> list:
    """
    Convierte el historial del frontend [{role, content}]
    al formato de LangChain [HumanMessage, AIMessage].

    LangChain necesita sus propias clases de mensaje, no diccionarios simples,
    para que MessagesPlaceholder las entienda correctamente.
    """
    messages = []
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    return messages


def _clean_chunk_text(text: str) -> str:
    """Elimina líneas de bibliografía, listas de autores y URLs."""
    lines = text.split("\n")
    clean = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 20:
            continue
        if stripped.replace(".", "").replace(" ", "").isdigit():
            continue
        if stripped.startswith("[") and "]" in stripped:
            continue  # citas tipo [Autor, 2022]
        if stripped.startswith("http"):
            continue  # URLs
        if stripped.count(",") > 4:
            continue  # listas de autores separados por comas
        if "@" in stripped:
            continue  # emails
        clean.append(stripped)
    return " ".join(clean[:6])


def _build_sources(docs) -> list[dict]:
    """
    Construye la lista de fuentes con el texto exacto del chunk usado.
    Devolvemos hasta 300 caracteres — suficiente para entender el contexto
    sin saturar la UI.
    """
    return [
        {
            "page": doc.metadata.get("page", 0) + 1,
            "content": _clean_chunk_text(doc.page_content),
            "source": doc.metadata.get("source", ""),
        }
        for doc in docs
    ]


# ── Funciones principales ─────────────────────────────────────────────────────


def process_pdf(pdf_path: str, session_id: str) -> dict:
    """Procesa un PDF y lo guarda en ChromaDB."""
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)

    Chroma.from_documents(
        documents=chunks,
        embedding=_get_embeddings(),
        persist_directory=str(CHROMA_BASE_DIR / session_id),
    )

    return {
        "session_id": session_id,
        "pages": len(documents),
        "chunks": len(chunks),
    }


def get_answer(
    question: str,
    session_id: str,
    chat_history: list[dict] | None = None,
) -> dict:
    """
    Responde una pregunta sobre un PDF con historial de conversación.

    El historial permite preguntas de seguimiento como:
    - "¿Y en qué página está eso?"
    - "Explícame más sobre el punto 2"
    - "¿Cómo se relaciona eso con lo que dijiste antes?"

    Args:
        question: Pregunta del usuario
        session_id: ID de la sesión (PDF indexado)
        chat_history: Lista [{role: "user"|"assistant", content: "..."}]
                      Vacía o None si es la primera pregunta.
    """
    vectorstore = _load_vectorstore(session_id)
    retriever = vectorstore.as_retriever(search_kwargs={"k": TOP_K_CHUNKS})
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", max_tokens=1024)

    history_messages = _build_history(chat_history or [])
    source_docs = retriever.invoke(question)

    chain = (
        {
            "context": lambda _: _format_docs(source_docs),
            "history": lambda _: history_messages,
            "question": RunnablePassthrough(),
        }
        | SINGLE_PDF_PROMPT
        | llm
        | StrOutputParser()
    )

    answer = chain.invoke(question)

    return {
        "answer": answer,
        "sources": _build_sources(source_docs),
    }


def get_answer_compare(
    question: str,
    session_id_a: str,
    session_id_b: str,
    chat_history: list[dict] | None = None,
) -> dict:
    """
    Responde una pregunta buscando en DOS PDFs simultáneamente.

    Útil para:
    - "¿Cuál de los dos habla más de X?"
    - "¿En qué se diferencian en la cláusula de garantía?"
    - "Resume las diferencias principales"

    Estrategia:
    1. Buscar los TOP_K chunks más relevantes en cada PDF por separado
    2. Incluirlos en el prompt como Documento A y Documento B
    3. Claude compara y responde citando de qué documento viene cada cosa
    """
    docs_a = (
        _load_vectorstore(session_id_a)
        .as_retriever(search_kwargs={"k": TOP_K_CHUNKS})
        .invoke(question)
    )

    docs_b = (
        _load_vectorstore(session_id_b)
        .as_retriever(search_kwargs={"k": TOP_K_CHUNKS})
        .invoke(question)
    )

    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", max_tokens=1500)
    history_messages = _build_history(chat_history or [])

    chain = (
        {
            "context_a": lambda _: _format_docs(docs_a),
            "context_b": lambda _: _format_docs(docs_b),
            "history": lambda _: history_messages,
            "question": RunnablePassthrough(),
        }
        | COMPARE_PDF_PROMPT
        | llm
        | StrOutputParser()
    )

    return {
        "answer": chain.invoke(question),
        "sources_a": _build_sources(docs_a),
        "sources_b": _build_sources(docs_b),
    }


def session_exists(session_id: str) -> bool:
    try:
        session_id = _validate_session_id(session_id)
    except ValueError:
        return False
    persist_dir = CHROMA_BASE_DIR / session_id
    return persist_dir.exists() and any(persist_dir.iterdir())


def create_session_id() -> str:
    return str(uuid.uuid4())


def cleanup_session(session_id: str) -> None:
    import shutil

    session_id = _validate_session_id(session_id)
    persist_dir = CHROMA_BASE_DIR / session_id
    if persist_dir.exists():
        shutil.rmtree(persist_dir)
