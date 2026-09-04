"""config_presupuesto.py — configuración de negocio del Presupuestador (hito 7).

Valores centralizados aquí, no hardcodeados en el prompt del agente ni
repetidos en el código de validación de `presupuestador.py` — un único
lugar para ajustar la política de márgenes/descuentos del taller. Todos
los porcentajes se expresan como fracción (0.35 == 35%).
"""

from __future__ import annotations

MARGEN_DEFECTO = 0.35
"""Margen bruto aplicado por defecto sobre el coste de las piezas
(sobre el precio de venta: (venta - coste) / venta), antes de cualquier
descuento."""

MARGEN_MINIMO_BRUTO = 0.25
"""Suelo de margen bruto que el presupuesto BASE (sin ningún descuento)
debe cumplir siempre. Con MARGEN_DEFECTO aplicado tal cual, este suelo se
cumple por construcción — existe como validación explícita, no como
parámetro que se espere ajustar caso a caso."""

MARGEN_NETO_MINIMO_TRAS_DESCUENTO = 0.10
"""Límite absoluto de margen neto tras aplicar CUALQUIER descuento
(estándar o excepcional). Ningún descuento, sea cual sea su
justificación, puede dejar el margen por debajo de este suelo."""

TARIFA_HORA_MANO_OBRA = 45.0
"""€/hora de mano de obra. Se factura directo, sin margen aplicado (a
diferencia de las piezas) — el coste ya incluye lo que se cobra."""

DESCUENTO_FIDELIDAD_ESTANDAR = 0.05
"""Descuento automático por fidelidad si el cliente cumple
UMBRAL_VISITAS_FIDELIDAD_ESTANDAR y la intención original no fue
'urgencia' (urgencia y descuento son mutuamente excluyentes)."""

DESCUENTO_EXCEPCIONAL_MAXIMO = 0.10
"""Tope superior de cualquier descuento excepcional propuesto por el
Presupuestador — nunca puede superar este valor, sin importar cuál de
los 4 criterios objetivos se invoque."""

UMBRAL_VISITAS_FIDELIDAD_ESTANDAR = 3
"""Visitas completadas (ver crm.contar_visitas_completadas_cliente)
mínimas para CUALQUIER descuento, estándar o excepcional -- por debajo
de este umbral, ningún descuento es válido pase lo que pase."""

UMBRAL_VISITAS_FIDELIDAD_EXCEPCIONAL = 10
"""Visitas completadas que por sí solas constituyen uno de los 4
criterios objetivos válidos para un descuento excepcional."""

UMBRAL_PRESUPUESTO_ALTO = 1000.0
"""€. Un presupuesto base (antes de descuento) que supere este valor
constituye, por sí solo, uno de los 4 criterios objetivos válidos para
un descuento excepcional."""

CRITERIOS_DESCUENTO_EXCEPCIONAL_VALIDOS = (
    "queja_no_resuelta",
    "presupuesto_alto",
    "visitas_excepcionales",
    "promocion_vigente",
)
"""Los 4 criterios objetivos que el Presupuestador puede citar para un
descuento excepcional -- cada uno se verifica contra datos reales
(crm.py/config), nunca se acepta solo porque el modelo lo afirme:
- "queja_no_resuelta": crm.tiene_queja_no_resuelta(cliente_id) es True.
- "presupuesto_alto": el total base (sin descuento) supera UMBRAL_PRESUPUESTO_ALTO.
- "visitas_excepcionales": crm.contar_visitas_completadas_cliente(cliente_id)
  supera UMBRAL_VISITAS_FIDELIDAD_EXCEPCIONAL.
- "promocion_vigente": PROMOCION_VIGENTE es True en este mismo módulo.
"""

PROMOCION_VIGENTE = False
"""Interruptor manual de promoción activa en todo el taller -- criterio
objetivo #4. No hay UI ni endpoint para cambiarlo en este hito; se edita
aquí directamente cuando el taller decide lanzar una promoción."""

INTENCIONES_VALIDAS = ("cita", "presupuesto", "urgencia", "consulta_tecnica", "queja", "otro")
"""Mismo catálogo que router.INTENCIONES_VALIDAS -- DUPLICADO a propósito,
no importado: presupuestador.py debe seguir aislado de router.py (test
AST). presupuestador.py valida `intencion_original` contra este catálogo
antes de decidir la exclusión mutua urgencia/descuento -- un valor fuera
de catálogo (typo, texto arbitrario de un llamante) debe fallar alto y
claro, no desactivar la regla en silencio."""

CANTIDAD_MAXIMA_POR_LINEA = 20
"""Tope superior de `cantidad` por línea de pieza en un presupuesto. Sin
este límite, una cantidad arbitrariamente grande propuesta por el modelo
podría inflar el presupuesto base lo suficiente como para autosatisfacer
el criterio excepcional "presupuesto_alto" -- a diferencia de
visitas/queja/promoción (verificados contra datos que el modelo no
controla), la cantidad si sale del propio modelo, así que necesita su
propio tope explícito."""
