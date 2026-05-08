"""
Fase 1: Generacion de datos de entrenamiento.

Estrategia:
- Generamos 500 pares candidato/oferta sinteticos con variedad realista
- Claude puntua cada par del 0-100 con criterio experto
- Guardamos en CSV para entrenar sklearn en la Fase 2

Por que Claude genera los labels?
Porque no tenemos datos historicos reales de "esta persona
consiguio esta oferta". Claude actua como experto en RRHH
que evalua el encaje. El modelo ML aprende a imitar ese criterio
pero responde en milisegundos en lugar de segundos.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

# ── Pools de datos sinteticos ─────────────────────────────────────────────────

TECNOLOGIAS_AI = [
    "LangChain",
    "LangGraph",
    "RAG",
    "ChromaDB",
    "pgvector",
    "Langfuse",
    "LlamaIndex",
    "CrewAI",
    "AutoGen",
    "Haystack",
]

TECNOLOGIAS_BACKEND = [
    "FastAPI",
    "Django",
    "Flask",
    "PostgreSQL",
    "MongoDB",
    "Redis",
    "Docker",
    "Kubernetes",
    "SQLAlchemy",
    "Celery",
]

TECNOLOGIAS_CLOUD = [
    "AWS EC2",
    "AWS Lambda",
    "Azure App Service",
    "GCP Cloud Run",
    "AWS S3",
    "Azure Functions",
    "GCP BigQuery",
]

TECNOLOGIAS_ML = [
    "sklearn",
    "PyTorch",
    "TensorFlow",
    "Pandas",
    "NumPy",
    "Matplotlib",
    "XGBoost",
    "HuggingFace",
]

NIVELES = ["junior", "mid", "senior"]
SECTORES = ["fintech", "healthtech", "edtech", "ecommerce", "consultoría", "startup"]


def generar_candidato() -> dict:
    """Genera un perfil de candidato sintetico con variedad realista."""
    nivel_idx = random.choices([0, 1, 2], weights=[0.4, 0.4, 0.2])[0]
    nivel = NIVELES[nivel_idx]

    # Años de experiencia correlacionados con nivel
    if nivel == "junior":
        anos = random.uniform(0, 2)
        random.randint(3, 8)
        n_proyectos = random.randint(1, 4)
    elif nivel == "mid":
        anos = random.uniform(2, 5)
        random.randint(6, 14)
        n_proyectos = random.randint(3, 8)
    else:
        anos = random.uniform(5, 12)
        random.randint(10, 20)
        n_proyectos = random.randint(6, 15)

    # Stack del candidato
    stack = random.sample(TECNOLOGIAS_AI, min(random.randint(0, 4), len(TECNOLOGIAS_AI)))
    stack += random.sample(TECNOLOGIAS_BACKEND, random.randint(1, 4))
    stack += random.sample(TECNOLOGIAS_ML, random.randint(0, 3))

    tiene_cloud = random.random() > 0.4
    if tiene_cloud:
        stack += random.sample(TECNOLOGIAS_CLOUD, random.randint(1, 2))

    return {
        "nivel": nivel,
        "anos_experiencia": round(anos, 1),
        "stack": stack,
        "tiene_cloud": tiene_cloud,
        "tiene_docker": random.random() > 0.45,
        "tiene_sql": random.random() > 0.35,
        "ingles_nivel": random.choice(["ninguno", "basico", "intermedio", "avanzado", "nativo"]),
        "n_proyectos_produccion": n_proyectos,
        "n_agentes_ia": random.randint(0, 6) if "LangChain" in stack else 0,
        "tiene_llm_experience": "LangChain" in stack or "LangGraph" in stack or "RAG" in stack,
    }


def generar_oferta() -> dict:
    """Genera una oferta de empleo sintetica."""
    nivel_idx = random.choices([0, 1, 2], weights=[0.35, 0.45, 0.2])[0]
    nivel = NIVELES[nivel_idx]

    # Requisitos correlacionados con nivel
    if nivel == "junior":
        n_requisitos = random.randint(3, 6)
        anos_min = random.uniform(0, 1)
    elif nivel == "mid":
        n_requisitos = random.randint(5, 10)
        anos_min = random.uniform(1, 3)
    else:
        n_requisitos = random.randint(8, 15)
        anos_min = random.uniform(3, 7)

    tecnologias_requeridas = random.sample(
        TECNOLOGIAS_AI + TECNOLOGIAS_BACKEND,
        min(n_requisitos, len(TECNOLOGIAS_AI + TECNOLOGIAS_BACKEND)),
    )

    return {
        "nivel_pedido": nivel,
        "anos_experiencia_min": round(anos_min, 1),
        "tecnologias_requeridas": tecnologias_requeridas,
        "pide_cloud": random.random() > 0.45,
        "pide_docker": random.random() > 0.5,
        "pide_sql": random.random() > 0.4,
        "pide_ingles": random.random() > 0.5,
        "pide_llm_experience": random.random() > 0.4,
        "sector": random.choice(SECTORES),
        "remoto": random.random() > 0.4,
    }


def calcular_features(candidato: dict, oferta: dict) -> dict:
    """
    Calcula features numericas del cruce candidato/oferta.
    Estas son las features que usara el modelo ML.
    """
    stack_candidato = set(candidato["stack"])
    techs_oferta = set(oferta["tecnologias_requeridas"])

    overlap = len(stack_candidato & techs_oferta)
    cobertura_tech = overlap / len(techs_oferta) if techs_oferta else 0

    # Diferencia de nivel: positivo = candidato supera el nivel pedido
    nivel_map = {"junior": 0, "mid": 1, "senior": 2}
    diff_nivel = nivel_map[candidato["nivel"]] - nivel_map[oferta["nivel_pedido"]]

    # Diferencia de años: positivo = candidato tiene mas experiencia
    diff_anos = candidato["anos_experiencia"] - oferta["anos_experiencia_min"]

    return {
        "cobertura_tech": round(cobertura_tech, 3),
        "n_techs_match": overlap,
        "diff_nivel": diff_nivel,
        "diff_anos": round(diff_anos, 1),
        "tiene_cloud_si_pide": int(candidato["tiene_cloud"] and oferta["pide_cloud"]),
        "falta_cloud": int(not candidato["tiene_cloud"] and oferta["pide_cloud"]),
        "tiene_docker_si_pide": int(candidato["tiene_docker"] and oferta["pide_docker"]),
        "falta_docker": int(not candidato["tiene_docker"] and oferta["pide_docker"]),
        "tiene_sql_si_pide": int(candidato["tiene_sql"] and oferta["pide_sql"]),
        "falta_sql": int(not candidato["tiene_sql"] and oferta["pide_sql"]),
        "ingles_ok": int(
            candidato["ingles_nivel"] in ["avanzado", "nativo"]
            and oferta["pide_ingles"]
            or not oferta["pide_ingles"]
        ),
        "llm_match": int(candidato["tiene_llm_experience"] and oferta["pide_llm_experience"]),
        "n_proyectos": candidato["n_proyectos_produccion"],
        "anos_experiencia": candidato["anos_experiencia"],
    }


def pedir_score_a_claude(candidato: dict, oferta: dict) -> int:
    """
    Le pide a Claude que puntue el encaje candidato/oferta del 0-100.
    Claude actua como experto en RRHH con criterio consistente.
    """
    prompt = f"""Eres un experto en selección de personal técnico para roles de AI Engineer.
Evalúa el encaje entre este candidato y esta oferta. Devuelve SOLO un número entero del 0 al 100.

0-20: No encaja. Gaps críticos insalvables.
21-40: Encaje bajo. Faltan habilidades fundamentales.
41-60: Encaje medio. Cubre lo básico pero con gaps importantes.
61-80: Buen encaje. Cubre la mayoría de requisitos.
81-100: Encaje excelente. Candidato muy sólido para el rol.

CANDIDATO:
- Nivel: {candidato['nivel']}
- Años de experiencia: {candidato['anos_experiencia']}
- Stack: {', '.join(candidato['stack'])}
- Cloud: {'Sí' if candidato['tiene_cloud'] else 'No'}
- Docker: {'Sí' if candidato['tiene_docker'] else 'No'}
- SQL: {'Sí' if candidato['tiene_sql'] else 'No'}
- Inglés: {candidato['ingles_nivel']}
- Proyectos en producción: {candidato['n_proyectos_produccion']}
- Experiencia con LLMs: {'Sí' if candidato['tiene_llm_experience'] else 'No'}

OFERTA:
- Nivel pedido: {oferta['nivel_pedido']}
- Años mínimos: {oferta['anos_experiencia_min']}
- Tecnologías requeridas: {', '.join(oferta['tecnologias_requeridas'])}
- Requiere cloud: {'Sí' if oferta['pide_cloud'] else 'No'}
- Requiere Docker: {'Sí' if oferta['pide_docker'] else 'No'}
- Requiere SQL: {'Sí' if oferta['pide_sql'] else 'No'}
- Requiere inglés: {'Sí' if oferta['pide_ingles'] else 'No'}
- Experiencia LLM requerida: {'Sí' if oferta['pide_llm_experience'] else 'No'}

Responde SOLO con el número. Nada más."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        score = int(response.content[0].text.strip())
        return max(0, min(100, score))
    except ValueError:
        return 50


def generar_dataset(n: int = 500) -> pd.DataFrame:
    """
    Genera n pares candidato/oferta, los puntua con Claude,
    y devuelve un DataFrame listo para entrenar.
    """
    registros = []

    print(f"Generando {n} pares candidato/oferta...")
    print("Cada punto = 10 pares procesados\n")

    for i in range(n):
        candidato = generar_candidato()
        oferta = generar_oferta()
        features = calcular_features(candidato, oferta)
        score = pedir_score_a_claude(candidato, oferta)

        registro = {
            **features,
            "score_claude": score,
            "candidato_json": json.dumps(candidato),
            "oferta_json": json.dumps(oferta),
        }
        registros.append(registro)

        if (i + 1) % 10 == 0:
            print(".", end="", flush=True)

        if (i + 1) % 100 == 0:
            print(f" {i+1}/{n}")

        # Rate limiting — evitamos saturar la API
        time.sleep(0.1)

    print("\n\nGeneracion completada.")
    return pd.DataFrame(registros)


if __name__ == "__main__":
    output_path = Path("backend/agents/job_matcher/training/training_data.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = generar_dataset(n=500)
    df.to_csv(output_path, index=False)

    print(f"\nDataset guardado en {output_path}")
    print(f"Shape: {df.shape}")
    print("\nDistribucion de scores:")
    print(df["score_claude"].describe())
    print("\nPrimeras filas:")
    print(df[["cobertura_tech", "diff_nivel", "diff_anos", "score_claude"]].head(10))
