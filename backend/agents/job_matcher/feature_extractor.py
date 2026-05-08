"""
Extractor de features para el modelo ML.

Que hace este archivo:
- Recibe texto del CV y texto de la oferta
- Usa Claude para extraer informacion estructurada de ambos
- Calcula las features numericas que espera el modelo sklearn

Por que usamos Claude para extraer features y no regex?
Porque los CVs tienen formatos infinitamente variados.
Un CV puede decir "5 years", "cinco anos", "2019-2024",
"senior desde 2020"... Claude entiende todos esos formatos.
El modelo ML necesita numeros — Claude hace la traduccion.
"""

from __future__ import annotations

import json

import anthropic

client = anthropic.Anthropic()

TECNOLOGIAS_CONOCIDAS = [
    "LangChain",
    "LangGraph",
    "RAG",
    "ChromaDB",
    "pgvector",
    "Langfuse",
    "LlamaIndex",
    "CrewAI",
    "FastAPI",
    "Django",
    "Flask",
    "PostgreSQL",
    "MongoDB",
    "Redis",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "GCP",
    "sklearn",
    "PyTorch",
    "TensorFlow",
    "Pandas",
    "NumPy",
    "Python",
    "SQL",
    "TypeScript",
    "JavaScript",
    "React",
    "Node.js",
]


def extraer_info_cv(texto_cv: str) -> dict:
    """
    Usa Claude para extraer informacion estructurada del CV.
    Devuelve un dict con los campos que necesita el modelo ML.
    """
    prompt = f"""Analiza este CV y extrae la información en formato JSON.
Responde SOLO con el JSON, sin explicaciones ni markdown.

CV:
{texto_cv[:4000]}

IMPORTANTE para anos_experiencia:
- Cuenta SOLO experiencia profesional real en empresas o proyectos con impacto
- NO cuentes años de estudios ni formacion academica
- Si solo tiene proyectos propios recientes (portfolio, github), cuenta desde
  la fecha de inicio real del primer proyecto serio
- Si el CV dice "2025-Present" en un rol reciente, es probable que sea menos
  de 1 año — calcula bien la diferencia con la fecha actual (2026)
- Sé conservador: es mejor subestimar que sobreestimar

Extrae exactamente estos campos:
{{
  "anos_experiencia": <número decimal real, 0 si no hay experiencia profesional>,
  "nivel": <"junior" si <2 años reales, "mid" si 2-5 años, "senior" si >5 años>,
  "stack": <lista de tecnologías del CV, solo las que aparecen>,
  "tiene_cloud": <true si menciona AWS/Azure/GCP/cloud>,
  "tiene_docker": <true si menciona Docker o contenedores>,
  "tiene_sql": <true si menciona SQL/PostgreSQL/MySQL/bases de datos>,
  "ingles_nivel": <"ninguno"/"basico"/"intermedio"/"avanzado"/"nativo">,
  "n_proyectos_produccion": <número estimado de proyectos reales desplegados>,
  "tiene_llm_experience": <true si menciona LLMs/GPT/Claude/LangChain/RAG>,
  "n_agentes_ia": <número de agentes de IA mencionados, 0 si ninguno>
}}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        texto = response.content[0].text.strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except (json.JSONDecodeError, KeyError):
        # Fallback si Claude devuelve algo inesperado
        return {
            "anos_experiencia": 0,
            "nivel": "junior",
            "stack": [],
            "tiene_cloud": False,
            "tiene_docker": False,
            "tiene_sql": False,
            "ingles_nivel": "basico",
            "n_proyectos_produccion": 0,
            "tiene_llm_experience": False,
            "n_agentes_ia": 0,
        }


def extraer_info_oferta(texto_oferta: str) -> dict:
    """
    Usa Claude para extraer informacion estructurada de la oferta.
    """
    prompt = f"""Analiza esta oferta de empleo y extrae la información en formato JSON.
Responde SOLO con el JSON, sin explicaciones ni markdown.

OFERTA:
{texto_oferta[:4000]}

Extrae exactamente estos campos:
{{
  "nivel_pedido": <"junior"/"mid"/"senior" segun el nivel requerido>,
  "anos_experiencia_min": <años mínimos requeridos, 0 si no especifica>,
  "tecnologias_requeridas": <lista de tecnologías mencionadas como requisito>,
  "pide_cloud": <true si requiere experiencia en cloud>,
  "pide_docker": <true si requiere Docker o contenedores>,
  "pide_sql": <true si requiere SQL o bases de datos>,
  "pide_ingles": <true si requiere inglés>,
  "pide_llm_experience": <true si requiere experiencia con LLMs/IA generativa>,
  "sector": <sector de la empresa>,
  "remoto": <true si es remoto o hibrido>
}}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        texto = response.content[0].text.strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except (json.JSONDecodeError, KeyError):
        return {
            "nivel_pedido": "mid",
            "anos_experiencia_min": 0,
            "tecnologias_requeridas": [],
            "pide_cloud": False,
            "pide_docker": False,
            "pide_sql": False,
            "pide_ingles": False,
            "pide_llm_experience": False,
            "sector": "tecnologia",
            "remoto": False,
        }


# Mapa de sinonimos — tecnologias equivalentes se agrupan bajo un nombre comun
SINONIMOS = {
    # Vector databases
    "vector databases": [
        "chromadb",
        "pgvector",
        "pinecone",
        "weaviate",
        "qdrant",
        "faiss",
        "milvus",
        "vector search",
    ],
    "chromadb": ["chromadb", "vector databases", "vector search"],
    "pgvector": ["pgvector", "vector databases", "vector search"],
    # LLMs
    "llm": [
        "llm",
        "gpt",
        "claude",
        "claude api",
        "openai api",
        "openai",
        "anthropic",
        "gemini",
        "llms",
    ],
    "openai": ["openai", "openai api", "gpt", "gpt-4", "gpt-3"],
    "claude": ["claude", "claude api", "anthropic"],
    # RAG
    "rag": ["rag", "retrieval augmented generation", "vector search", "semantic search"],
    # Cloud
    "aws": ["aws", "aws ec2", "ec2", "aws s3", "aws lambda", "iam", "ecr"],
    "azure": ["azure", "azure app service", "acr", "azure functions"],
    "gcp": ["gcp", "google cloud", "cloud run", "bigquery"],
    "cloud": ["aws", "azure", "gcp", "aws ec2", "azure app service", "cloud"],
    # Bases de datos
    "sql": ["sql", "postgresql", "mysql", "sqlite", "sqlalchemy", "postgres"],
    "postgresql": ["postgresql", "postgres", "sql", "pgvector"],
    "nosql": ["mongodb", "redis", "dynamodb", "firestore"],
    # Frameworks
    "langchain": ["langchain", "lcel", "langchain/lcel"],
    "fastapi": ["fastapi", "flask", "django"],
    "python": ["python", "python 3.12", "python3", "python 3.11", "python 3.10"],
    "apis": ["apis", "fastapi", "flask", "django", "rest api", "api rest", "api"],
    # Orquestacion
    "langraph": ["langgraph", "langraph"],
    "ai agents": ["langraph", "langgraph", "crewai", "autogen", "agents", "agentic"],
    # Observabilidad
    "llmops": ["langfuse", "llmops", "mlflow", "weights & biases"],
    "langfuse": ["langfuse", "llmops"],
    # Contenedores
    "docker": ["docker", "docker-compose", "containers", "contenedores"],
    "kubernetes": ["kubernetes", "k8s"],
}


def normalizar_tech(tech: str) -> str:
    """Convierte una tecnologia a su nombre normalizado en minusculas."""
    return tech.lower().strip()


def techs_hacen_match(tech_oferta: str, stack_candidato: list[str]) -> bool:
    """
    Comprueba si una tecnologia de la oferta esta cubierta por el stack del candidato.

    Usa sinonimos para detectar equivalencias:
    "Vector databases" -> match con "ChromaDB", "pgvector", "vector search"
    "LLM" -> match con "Claude API", "OpenAI API", "GPT"
    "AI agents" -> match con "LangGraph", "CrewAI"
    """
    tech_norm = normalizar_tech(tech_oferta)
    stack_norm = [normalizar_tech(t) for t in stack_candidato]

    # Match directo
    if tech_norm in stack_norm:
        return True

    # Match por sinonimos — buscamos si la tech de la oferta tiene sinonimos
    # y si alguno de esos sinonimos esta en el stack del candidato
    sinonimos_oferta = SINONIMOS.get(tech_norm, [tech_norm])
    for s in sinonimos_oferta:
        if s in stack_norm:
            return True

    # Match inverso — buscamos si alguna tech del candidato tiene sinonimos
    # que incluyan la tech de la oferta
    for tech_candidato in stack_norm:
        sinonimos_candidato = SINONIMOS.get(tech_candidato, [tech_candidato])
        if tech_norm in sinonimos_candidato:
            return True

    return False


def calcular_features(info_cv: dict, info_oferta: dict) -> dict:
    """
    Calcula las features numericas para el modelo ML.
    Usa matching con sinonimos para mejor cobertura tecnica.
    """
    stack_candidato = info_cv.get("stack", [])
    techs_oferta = info_oferta.get("tecnologias_requeridas", [])

    # Calculamos overlap con sinonimos
    matches = [tech for tech in techs_oferta if techs_hacen_match(tech, stack_candidato)]
    overlap = len(matches)
    cobertura = overlap / len(techs_oferta) if techs_oferta else 0

    nivel_map = {"junior": 0, "mid": 1, "senior": 2}
    nivel_candidato = nivel_map.get(info_cv.get("nivel", "junior"), 0)
    nivel_oferta = nivel_map.get(info_oferta.get("nivel_pedido", "mid"), 1)
    diff_nivel = nivel_candidato - nivel_oferta

    diff_anos = info_cv.get("anos_experiencia", 0) - info_oferta.get("anos_experiencia_min", 0)

    tiene_cloud = info_cv.get("tiene_cloud", False)
    pide_cloud = info_oferta.get("pide_cloud", False)
    tiene_docker = info_cv.get("tiene_docker", False)
    pide_docker = info_oferta.get("pide_docker", False)
    tiene_sql = info_cv.get("tiene_sql", False)
    pide_sql = info_oferta.get("pide_sql", False)
    ingles = info_cv.get("ingles_nivel", "basico")
    pide_ingles = info_oferta.get("pide_ingles", False)

    return {
        "cobertura_tech": round(cobertura, 3),
        "n_techs_match": overlap,
        "techs_match_detalle": matches,  # extra para el informe
        "diff_nivel": diff_nivel,
        "diff_anos": round(diff_anos, 1),
        "tiene_cloud_si_pide": int(tiene_cloud and pide_cloud),
        "falta_cloud": int(not tiene_cloud and pide_cloud),
        "tiene_docker_si_pide": int(tiene_docker and pide_docker),
        "falta_docker": int(not tiene_docker and pide_docker),
        "tiene_sql_si_pide": int(tiene_sql and pide_sql),
        "falta_sql": int(not tiene_sql and pide_sql),
        "ingles_ok": int(ingles in ["avanzado", "nativo"] and pide_ingles or not pide_ingles),
        "llm_match": int(
            info_cv.get("tiene_llm_experience", False)
            and info_oferta.get("pide_llm_experience", False)
        ),
        "n_proyectos": info_cv.get("n_proyectos_produccion", 0),
        "anos_experiencia": info_cv.get("anos_experiencia", 0),
    }
