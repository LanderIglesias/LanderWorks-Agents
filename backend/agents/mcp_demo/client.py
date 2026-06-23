"""
client.py — Cliente MCP de prueba

Llama a las herramientas del servidor MCP directamente
para verificar que funcionan correctamente.
"""

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "backend.agents.mcp_demo.server"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Listar herramientas disponibles
            tools = await session.list_tools()
            print("Herramientas disponibles:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description}")

            print()

            # Llamar a calcular_health_score
            resultado = await session.call_tool(
                "calcular_health_score", {"codigo": 35, "tests": 20, "dependencias": 15, "ci_cd": 8}
            )
            print(f"Health score: {resultado.content[0].text}")  # type: ignore

            # Llamar a limpiar_texto
            resultado = await session.call_tool(
                "limpiar_texto", {"texto": "  Hola Mundo desde MCP  "}
            )
            print(f"Texto limpio: {resultado.content[0].text}")  # type: ignore


if __name__ == "__main__":
    asyncio.run(main())
