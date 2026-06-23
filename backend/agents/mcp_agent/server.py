"""
server.py — Servidor MCP del portfolio de Lander Iglesias

Expone las herramientas reales del Meeting Intelligence Agent
para que Claude Desktop pueda usarlas autónomamente.
"""

import asyncio
import json
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from dotenv import load_dotenv

load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"
    )
)

from sqlalchemy import text  # noqa: E402

from backend.agents.meeting_intel_agent.db.database import get_connection  # noqa: E402
from backend.agents.meeting_intel_agent.nodes.indexer_node import search_meeting  # noqa: E402

app = Server("portfolio-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_meetings",
            description="Lista todas las reuniones analizadas y guardadas en la base de datos",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_meeting_extractions",
            description="Obtiene las decisiones, action items, preguntas abiertas y temas pendientes de una reunión específica",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string", "description": "UUID de la reunión"}
                },
                "required": ["meeting_id"],
            },
        ),
        Tool(
            name="search_meeting",
            description="Busca contenido relevante en una reunión usando búsqueda semántica",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string", "description": "UUID de la reunión"},
                    "query": {"type": "string", "description": "Pregunta o tema a buscar"},
                    "top_k": {
                        "type": "integer",
                        "description": "Número de resultados (default: 3)",
                        "default": 3,
                    },
                },
                "required": ["meeting_id", "query"],
            },
        ),
        Tool(
            name="ask_meeting",
            description="Responde una pregunta sobre una reunión usando RAG — busca los chunks más relevantes y genera una respuesta",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string", "description": "UUID de la reunión"},
                    "question": {"type": "string", "description": "Pregunta sobre la reunión"},
                },
                "required": ["meeting_id", "question"],
            },
        ),
        Tool(
            name="get_meeting_summary",
            description="Obtiene el resumen ejecutivo y los temas clave de una reunión",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string", "description": "UUID de la reunión"}
                },
                "required": ["meeting_id"],
            },
        ),
        Tool(
            name="list_action_items_by_owner",
            description="Lista todos los action items de una reunión filtrados por responsable",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string", "description": "UUID de la reunión"},
                    "owner": {"type": "string", "description": "Nombre del responsable"},
                },
                "required": ["meeting_id", "owner"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "list_meetings":
        with get_connection() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, title, created_at, language FROM meetings ORDER BY created_at DESC"
                )
            ).fetchall()
        meetings = [
            {"id": str(r[0]), "title": r[1], "created_at": str(r[2]), "language": r[3]}
            for r in rows
        ]
        return [TextContent(type="text", text=json.dumps(meetings, ensure_ascii=False, indent=2))]

    elif name == "get_meeting_extractions":
        with get_connection() as conn:
            row = conn.execute(
                text(
                    "SELECT decisions, action_items, open_questions, pending_topics FROM meeting_extractions WHERE meeting_id = :id"
                ),
                {"id": arguments["meeting_id"]},
            ).fetchone()
        if not row:
            return [TextContent(type="text", text="Reunión no encontrada")]
        result = {
            "decisions": row[0],
            "action_items": row[1],
            "open_questions": row[2],
            "pending_topics": row[3],
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "search_meeting":
        results = search_meeting(
            meeting_id=arguments["meeting_id"],
            query=arguments["query"],
            top_k=arguments.get("top_k", 3),
        )
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

    elif name == "ask_meeting":
        import anthropic

        chunks = search_meeting(
            meeting_id=arguments["meeting_id"], query=arguments["question"], top_k=5
        )
        if not chunks:
            return [
                TextContent(type="text", text="No se encontró contenido relevante en la reunión")
            ]
        context = "\n\n---\n\n".join([c["content"] for c in chunks])
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="Eres un asistente de reuniones. Responde preguntas basándote ÚNICAMENTE en el contexto de la transcripción proporcionada. Si la respuesta no está en el contexto, dilo claramente.",
            messages=[
                {
                    "role": "user",
                    "content": f"CONTEXTO DE LA REUNIÓN:\n{context}\n\nPREGUNTA: {arguments['question']}",
                }
            ],
        )
        return [TextContent(type="text", text=response.content[0].text)]  # type: ignore

    elif name == "get_meeting_summary":
        with get_connection() as conn:
            row = conn.execute(
                text("SELECT title, executive_summary, key_topics FROM meetings WHERE id = :id"),
                {"id": arguments["meeting_id"]},
            ).fetchone()
        if not row:
            return [TextContent(type="text", text="Reunión no encontrada")]
        result = {
            "title": row[0],
            "executive_summary": row[1],
            "key_topics": row[2],
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "list_action_items_by_owner":
        with get_connection() as conn:
            row = conn.execute(
                text("SELECT action_items FROM meeting_extractions WHERE meeting_id = :id"),
                {"id": arguments["meeting_id"]},
            ).fetchone()
        if not row:
            return [TextContent(type="text", text="Reunión no encontrada")]

        all_items = row[0] or []
        owner = arguments["owner"].lower()
        filtered = [item for item in all_items if owner in item.get("owner", "").lower()]
        return [TextContent(type="text", text=json.dumps(filtered, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"Herramienta desconocida: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
