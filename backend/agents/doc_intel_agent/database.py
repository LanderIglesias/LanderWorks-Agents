"""
database.py — Conexión a PostgreSQL y configuración de pgvector.

¿Qué hace este archivo?
1. Conecta con PostgreSQL usando SQLAlchemy
2. Activa la extensión pgvector en la base de datos
3. Define la tabla donde guardamos los chunks de documentos
4. Expone funciones para guardar y buscar chunks

¿Qué es SQLAlchemy?
Es un ORM (Object Relational Mapper) — te permite trabajar con la base
de datos usando objetos Python en vez de escribir SQL puro. Por ejemplo,
en vez de escribir "INSERT INTO chunks VALUES (...)" haces chunk = Chunk(...)
y SQLAlchemy lo convierte a SQL automáticamente.

¿Por qué psycopg2?
Es el driver que SQLAlchemy usa internamente para hablar con PostgreSQL.
Sin él, SQLAlchemy no sabe cómo comunicarse con Postgres.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql import func

load_dotenv(override=False)

# ── Conexión ────────────────────────────────────────────────────────────────

# La URL de conexión viene de la variable de entorno DATABASE_URL
# Formato: postgresql://usuario:contraseña@host:puerto/nombre_db
# Cuando corre en Docker: host = "db" (nombre del servicio en docker-compose)
# Cuando corre en local sin Docker: host = "localhost"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://lander:lander123@localhost:5432/doc_intel")

# create_engine crea el "motor" de conexión
# pool_pre_ping=True: antes de usar una conexión del pool, verifica que sigue viva
# Esto evita errores cuando la conexión ha estado inactiva mucho tiempo
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# sessionmaker crea una "fábrica" de sesiones
# Una sesión es una unidad de trabajo con la base de datos:
# abres sesión → haces operaciones → commit o rollback → cierras sesión
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Modelo de datos ─────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Clase base de la que heredan todos los modelos."""

    pass


class DocumentChunk(Base):
    """
    Tabla que almacena los chunks de documentos con sus embeddings.

    Cada fila representa un fragmento de texto de un documento.
    El campo 'embedding' es un vector de 1536 dimensiones (OpenAI).
    pgvector permite buscar los vectores más similares a una query.
    """

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Metadatos del documento
    filename = Column(String(255), nullable=False)  # nombre del PDF
    r2_key = Column(String(500), nullable=True)  # clave en Cloudflare R2
    page_number = Column(Integer, nullable=True)  # página del PDF
    chunk_index = Column(Integer, nullable=False)  # orden del chunk en el doc

    # Contenido
    content = Column(Text, nullable=False)  # texto del chunk

    # Embedding — vector de 1536 dimensiones (tamaño de text-embedding-3-small)
    # pgvector añade el tipo Vector a SQLAlchemy
    embedding = Column(Vector(1536), nullable=True)

    # Timestamps automáticos
    created_at = Column(DateTime, server_default=func.now())


# ── Inicialización ──────────────────────────────────────────────────────────


def init_db() -> None:
    """
    Inicializa la base de datos:
    1. Activa la extensión pgvector (necesario hacerlo una vez)
    2. Crea las tablas si no existen

    Se llama al arrancar el servidor (en api.py con lifespan).
    """
    with engine.connect() as conn:
        # Activa pgvector — sin esto el tipo Vector no existe en PostgreSQL
        # "CREATE EXTENSION IF NOT EXISTS" no falla si ya está activada
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Crea todas las tablas definidas con Base
    # Si ya existen, no hace nada (checkfirst=True es el comportamiento por defecto)
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    Generador que crea una sesión de base de datos por petición HTTP.

    Uso en FastAPI con Depends:
        def mi_endpoint(db: Session = Depends(get_db)):

    El 'finally' garantiza que la sesión se cierra aunque haya un error.
    Así no dejamos conexiones abiertas que saturen el pool.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Operaciones de base de datos ────────────────────────────────────────────


def save_chunks(
    db: Session,
    filename: str,
    chunks: list[dict],
    r2_key: str | None = None,
) -> int:
    """
    Guarda una lista de chunks en la base de datos.

    Args:
        db: sesión de base de datos
        filename: nombre del PDF
        chunks: lista de dicts con 'content', 'embedding', 'page_number', 'chunk_index'
        r2_key: clave del archivo en Cloudflare R2 (opcional)

    Returns:
        Número de chunks guardados
    """
    db_chunks = []
    for chunk in chunks:
        db_chunk = DocumentChunk(
            filename=filename,
            r2_key=r2_key,
            page_number=chunk.get("page_number"),
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            embedding=chunk.get("embedding"),
        )
        db_chunks.append(db_chunk)

    db.add_all(db_chunks)
    db.commit()
    return len(db_chunks)


def search_similar_chunks(
    db: Session,
    query_embedding: list[float],
    filename: str | None = None,
    limit: int = 5,
) -> list[DocumentChunk]:
    """
    Busca los chunks más similares a un embedding de query.

    Usa distancia coseno (<=> en pgvector) que mide similitud semántica.
    Cuanto menor la distancia, más similar el significado.

    Args:
        db: sesión de base de datos
        query_embedding: vector de la pregunta del usuario
        filename: si se especifica, solo busca en ese documento
        limit: cuántos chunks devolver (por defecto 5)
    """
    from sqlalchemy import select

    # Construimos la query de búsqueda por similitud
    # El operador <=> de pgvector calcula distancia coseno entre vectores
    query = (
        select(DocumentChunk)
        .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )

    # Si se especifica filename, filtramos solo ese documento
    if filename:
        query = query.where(DocumentChunk.filename == filename)

    return list(db.execute(query).scalars().all())


def get_all_documents(db: Session) -> list[dict]:
    """
    Devuelve la lista de documentos únicos indexados.
    Agrupa por filename para no repetir el mismo doc.
    """
    from sqlalchemy import func as sqlfunc
    from sqlalchemy import select

    result = db.execute(
        select(
            DocumentChunk.filename,
            DocumentChunk.r2_key,
            sqlfunc.count(DocumentChunk.id).label("chunk_count"),
            sqlfunc.max(DocumentChunk.created_at).label("indexed_at"),
        )
        .group_by(DocumentChunk.filename, DocumentChunk.r2_key)
        .order_by(sqlfunc.max(DocumentChunk.created_at).desc())
    ).all()

    return [
        {
            "filename": row.filename,
            "r2_key": row.r2_key,
            "chunk_count": row.chunk_count,
            "indexed_at": str(row.indexed_at),
        }
        for row in result
    ]


def delete_document(db: Session, filename: str) -> int:
    """
    Elimina todos los chunks de un documento.
    Returns: número de chunks eliminados.
    """
    deleted = db.query(DocumentChunk).filter(DocumentChunk.filename == filename).delete()
    db.commit()
    return deleted
