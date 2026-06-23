"""
server.py — Servidor MCP de demostración

Un servidor MCP simple con dos herramientas:
- calcular_health_score: calcula el score de un repo
- limpiar_texto: limpia y normaliza texto
"""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("demo-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="calcular_health_score",
            description="Calcula el health score de un repositorio basado en métricas de calidad",
            inputSchema={
                "type": "object",
                "properties": {
                    "codigo": {"type": "number", "description": "Puntuación de código (0-40)"},
                    "tests": {"type": "number", "description": "Puntuación de tests (0-30)"},
                    "dependencias": {
                        "type": "number",
                        "description": "Puntuación de dependencias (0-20)",
                    },
                    "ci_cd": {"type": "number", "description": "Puntuación de CI/CD (0-10)"},
                },
                "required": ["codigo", "tests", "dependencias"],
            },
        ),
        Tool(
            name="limpiar_texto",
            description="Limpia y normaliza un texto: elimina espacios, convierte a minúsculas",
            inputSchema={
                "type": "object",
                "properties": {"texto": {"type": "string", "description": "Texto a limpiar"}},
                "required": ["texto"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "calcular_health_score":
        total = (
            arguments["codigo"]
            + arguments["tests"]
            + arguments["dependencias"]
            + arguments.get("ci_cd", 0)
        )
        if total >= 80:
            label = "🟢 Healthy"
        elif total >= 50:
            label = "🟡 Moderate"
        else:
            label = "🔴 Critical"

        resultado = {"score": total, "label": label}
        return [TextContent(type="text", text=json.dumps(resultado, ensure_ascii=False))]

    elif name == "limpiar_texto":
        texto = arguments["texto"]
        limpio = texto.strip().lower()
        resultado = {"original": texto, "limpio": limpio}
        return [TextContent(type="text", text=json.dumps(resultado, ensure_ascii=False))]

    else:
        return [TextContent(type="text", text=f"Herramienta desconocida: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
