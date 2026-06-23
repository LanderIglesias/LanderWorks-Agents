"""
mcp_server.py — Servidor MCP del Meeting Intelligence Agent

Expone dos herramientas:
- search_meeting: busca en el contenido de una reunión por semántica
- list_meetings: lista todas las reuniones indexadas
"""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from sqlalchemy import text

from .db.database import get_connection
from .nodes.indexer_node import search_meeting

app = Server("meeting-intel")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Define las herramientas que expone este servidor MCP."""
    return [
        Tool(
            name="search_meeting",
            description="Search for relevant content in a specific meeting using semantic similarity",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {
                        "type": "string",
                        "description": "The UUID of the meeting to search in",
                    },
                    "query": {
                        "type": "string",
                        "description": "The question or topic to search for",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 3)",
                        "default": 3,
                    },
                },
                "required": ["meeting_id", "query"],
            },
        ),
        Tool(
            name="list_meetings",
            description="List all meetings indexed in the database",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Ejecuta la herramienta que Claude solicita."""

    if name == "search_meeting":
        results = search_meeting(
            meeting_id=arguments["meeting_id"],
            query=arguments["query"],
            top_k=arguments.get("top_k", 3),
        )
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

    elif name == "list_meetings":
        with get_connection() as conn:
            rows = conn.execute(
                text("SELECT id, title, created_at FROM meetings ORDER BY created_at DESC")
            ).fetchall()

        meetings = [{"id": str(r[0]), "title": r[1], "created_at": str(r[2])} for r in rows]
        return [TextContent(type="text", text=json.dumps(meetings, ensure_ascii=False, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
