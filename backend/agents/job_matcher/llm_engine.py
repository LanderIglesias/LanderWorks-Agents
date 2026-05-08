"""
Motor LLM del Job Matcher.

Claude recibe el score del modelo ML y la informacion extraida
del CV y la oferta, y genera un informe accionable con:
- Explicacion del score
- Gaps criticos identificados
- Recomendaciones concretas para mejorar el CV
- Probabilidad estimada de pasar el primer filtro
"""

from __future__ import annotations

import anthropic

client = anthropic.Anthropic()


def generar_informe(
    score: float,
    info_cv: dict,
    info_oferta: dict,
    features: dict,
) -> str:
    """Genera informe de encaje CV/oferta usando Claude."""

    # Identificamos gaps criticos para el prompt
    gaps = []
    if features["falta_cloud"]:
        gaps.append("experiencia en cloud (requerida, no presente en CV)")
    if features["falta_docker"]:
        gaps.append("Docker/contenedores (requerido, no presente en CV)")
    if features["falta_sql"]:
        gaps.append("SQL/bases de datos (requerido, no presente en CV)")
    if features["diff_nivel"] < -1:
        gaps.append(
            f"nivel de experiencia (piden {info_oferta.get('nivel_pedido')} y el candidato es {info_cv.get('nivel')})"
        )
    if features["diff_anos"] < -2:
        gaps.append(
            f"años de experiencia (piden {info_oferta.get('anos_experiencia_min')} años mínimo)"
        )
    if not features["ingles_ok"] and info_oferta.get("pide_ingles"):
        gaps.append("nivel de inglés (requerido, nivel insuficiente en CV)")

    stack_oferta = set(info_oferta.get("tecnologias_requeridas", []))
    stack_cv = set(info_cv.get("stack", []))
    techs_faltantes = stack_oferta - stack_cv

    prompt = f"""Eres un experto en selección de personal técnico y coach de carrera.
Analiza el encaje entre este candidato y esta oferta y genera un informe accionable.

## Puntuacion del modelo: {score:.0f}/100

## Perfil del candidato
- Nivel: {info_cv.get('nivel', 'desconocido')}
- Años de experiencia: {info_cv.get('anos_experiencia', 0)}
- Stack: {', '.join(info_cv.get('stack', [])) or 'No detectado'}
- Cloud: {'Sí' if info_cv.get('tiene_cloud') else 'No'}
- Docker: {'Sí' if info_cv.get('tiene_docker') else 'No'}
- SQL: {'Sí' if info_cv.get('tiene_sql') else 'No'}
- Inglés: {info_cv.get('ingles_nivel', 'desconocido')}
- Proyectos en producción: {info_cv.get('n_proyectos_produccion', 0)}
- Experiencia LLMs: {'Sí' if info_cv.get('tiene_llm_experience') else 'No'}

## Requisitos de la oferta
- Nivel pedido: {info_oferta.get('nivel_pedido', 'desconocido')}
- Años mínimos: {info_oferta.get('anos_experiencia_min', 0)}
- Tecnologías requeridas: {', '.join(info_oferta.get('tecnologias_requeridas', [])) or 'No especificadas'}
- Requiere cloud: {'Sí' if info_oferta.get('pide_cloud') else 'No'}
- Requiere Docker: {'Sí' if info_oferta.get('pide_docker') else 'No'}
- Requiere SQL: {'Sí' if info_oferta.get('pide_sql') else 'No'}
- Requiere inglés: {'Sí' if info_oferta.get('pide_ingles') else 'No'}
- Experiencia LLM requerida: {'Sí' if info_oferta.get('pide_llm_experience') else 'No'}

## Gaps identificados
{chr(10).join(f"- {g}" for g in gaps) if gaps else "- No se detectaron gaps criticos"}

## Tecnologias requeridas que faltan en el CV
{', '.join(techs_faltantes) if techs_faltantes else 'Ninguna'}

Genera un informe con estas secciones:

### Veredicto
Una frase directa: si aplicar o no y por que.

### Puntos fuertes
2-3 aspectos del CV que encajan bien con la oferta.

### Gaps criticos
Los gaps mas importantes ordenados por impacto. Se especifico.

### Recomendaciones
3-4 acciones concretas para mejorar el encaje con esta oferta especifica.
Por ejemplo: "Añade un proyecto con Docker al portfolio",
"Reformula la experiencia X para destacar el uso de SQL".

### Probabilidad de pasar el primer filtro
Estimacion realista: Alta / Media / Baja con una frase explicando por que.

Se directo y honesto. No endulces la realidad."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text
