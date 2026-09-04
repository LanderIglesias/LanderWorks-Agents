from backend.agents.taller_mecanico import config_presupuesto as cfg


def test_valores_por_defecto_documentados_en_el_encargo():
    assert cfg.MARGEN_DEFECTO == 0.35
    assert cfg.MARGEN_MINIMO_BRUTO == 0.25
    assert cfg.MARGEN_NETO_MINIMO_TRAS_DESCUENTO == 0.10
    assert cfg.TARIFA_HORA_MANO_OBRA == 45.0
    assert cfg.DESCUENTO_FIDELIDAD_ESTANDAR == 0.05
    assert cfg.DESCUENTO_EXCEPCIONAL_MAXIMO == 0.10
    assert cfg.UMBRAL_VISITAS_FIDELIDAD_ESTANDAR == 3
    assert cfg.UMBRAL_VISITAS_FIDELIDAD_EXCEPCIONAL == 10
    assert cfg.UMBRAL_PRESUPUESTO_ALTO == 1000.0


def test_margen_defecto_respeta_el_minimo_bruto():
    # Invariante de coherencia entre los propios valores de config: el
    # margen por defecto nunca debería estar por debajo de su propio suelo.
    assert cfg.MARGEN_DEFECTO >= cfg.MARGEN_MINIMO_BRUTO


def test_criterios_excepcionales_son_exactamente_cuatro():
    assert set(cfg.CRITERIOS_DESCUENTO_EXCEPCIONAL_VALIDOS) == {
        "queja_no_resuelta",
        "presupuesto_alto",
        "visitas_excepcionales",
        "promocion_vigente",
    }
