import io

import fitz
import httpx
import pytest
from docx import Document

from backend.agents.job_matcher import extractor
from backend.agents.job_matcher.extractor import (
    _validar_url_publica,
    extraer_texto_docx,
    extraer_texto_pdf,
    limpiar_texto,
    scrapeear_url,
)
from backend.agents.job_matcher.feature_extractor import calcular_features, techs_hacen_match

# ── Matching de tecnologias ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("oferta", "stack", "esperado"),
    [
        ("Python", ["python"], True),  # directo, sin distinguir mayusculas
        ("SQL", ["PostgreSQL"], True),  # sinonimo de la oferta
        ("Flask", ["FastAPI"], True),  # sinonimo inverso, desde el candidato
        ("Kubernetes", ["Docker"], False),
        ("Python", [], False),
    ],
)
def test_techs_hacen_match(oferta, stack, esperado):
    assert techs_hacen_match(oferta, stack) is esperado


# ── Features del modelo ──────────────────────────────────────────────────────


def test_calcular_features_cobertura_y_diferencias():
    features = calcular_features(
        {"stack": ["Python"], "nivel": "senior", "anos_experiencia": 5},
        {
            "tecnologias_requeridas": ["Python", "Kubernetes"],
            "nivel_pedido": "mid",
            "anos_experiencia_min": 3,
        },
    )
    assert features["cobertura_tech"] == 0.5
    assert features["techs_match_detalle"] == ["Python"]
    assert features["diff_nivel"] == 1
    assert features["diff_anos"] == 2


def test_calcular_features_detecta_lo_que_pide_la_oferta_y_falta():
    features = calcular_features(
        {"tiene_cloud": True, "tiene_docker": False},
        {"pide_cloud": True, "pide_docker": True},
    )
    assert features["tiene_cloud_si_pide"] == 1
    assert features["falta_cloud"] == 0
    assert features["tiene_docker_si_pide"] == 0
    assert features["falta_docker"] == 1


def test_calcular_features_oferta_sin_tecnologias_no_divide_por_cero():
    assert calcular_features({}, {})["cobertura_tech"] == 0


@pytest.mark.parametrize(
    ("ingles", "pide", "esperado"),
    [("basico", False, 1), ("basico", True, 0), ("avanzado", True, 1), ("nativo", True, 1)],
)
def test_ingles_ok(ingles, pide, esperado):
    features = calcular_features({"ingles_nivel": ingles}, {"pide_ingles": pide})
    assert features["ingles_ok"] == esperado


# ── Extraccion de texto ──────────────────────────────────────────────────────


def test_limpiar_texto_normaliza_saltos_espacios_y_control():
    assert limpiar_texto("  hola   mundo\n\n\n\nfin\x00\x07  ") == "hola mundo\n\nfin"


def test_extraer_texto_pdf():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Ingeniero Python")
    assert "Ingeniero Python" in extraer_texto_pdf(doc.tobytes())


def test_extraer_texto_docx():
    doc = Document()
    doc.add_paragraph("Ingeniero Python")
    buffer = io.BytesIO()
    doc.save(buffer)
    assert "Ingeniero Python" in extraer_texto_docx(buffer.getvalue())


# ── Anti-SSRF ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",  # metadatos de la nube
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",  # loopback camuflado como IPv6
    ],
)
def test_validar_url_rechaza_esquemas_y_redes_internas(url):
    with pytest.raises(ValueError):
        _validar_url_publica(url)


def test_validar_url_rechaza_dominio_que_resuelve_a_red_interna(monkeypatch):
    monkeypatch.setattr(
        extractor.socket, "getaddrinfo", lambda *_: [(2, 1, 6, "", ("10.0.0.5", 0))]
    )
    with pytest.raises(ValueError, match="red interna"):
        _validar_url_publica("https://parece-publico.example")


def test_validar_url_acepta_host_publico(monkeypatch):
    monkeypatch.setattr(
        extractor.socket, "getaddrinfo", lambda *_: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    _validar_url_publica("https://example.com/oferta")


def test_scrapeear_url_no_hace_peticion_si_la_url_es_interna(monkeypatch):
    def falla_si_se_llama(*_, **__):
        raise AssertionError("no debe llegar a la red")

    monkeypatch.setattr(extractor.httpx, "get", falla_si_se_llama)
    with pytest.raises(ValueError):
        scrapeear_url("http://127.0.0.1:8000/admin")


def _servidor_falso(monkeypatch, respuestas: dict) -> list[str]:
    """Todo host resuelve a una IP publica salvo interno.example; responde por URL."""

    def resolver(host, *_):
        ip = "10.0.0.5" if host == "interno.example" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    pedidas = []

    def get(url, **kwargs):
        assert kwargs.get("follow_redirects") is False
        pedidas.append(url)
        return respuestas[url]

    monkeypatch.setattr(extractor.socket, "getaddrinfo", resolver)
    monkeypatch.setattr(extractor.httpx, "get", get)
    return pedidas


def _redirect(origen: str, destino: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": destino}, request=httpx.Request("GET", origen))


def _html(url: str, cuerpo: str) -> httpx.Response:
    html = f"<html><body><article>{cuerpo}</article></body></html>"
    return httpx.Response(200, text=html, request=httpx.Request("GET", url))


def test_scrapeear_url_revalida_cada_redireccion(monkeypatch):
    origen = "https://publico.example/oferta"
    pedidas = _servidor_falso(
        monkeypatch, {origen: _redirect(origen, "http://interno.example/admin")}
    )
    with pytest.raises(ValueError, match="red interna"):
        scrapeear_url(origen)
    assert pedidas == [origen]


def test_scrapeear_url_sigue_redirecciones_publicas_relativas(monkeypatch):
    _servidor_falso(
        monkeypatch,
        {
            "https://publico.example/a": _redirect("https://publico.example/a", "/b"),
            "https://publico.example/b": _html("https://publico.example/b", "Ingeniero Python"),
        },
    )
    assert "Ingeniero Python" in scrapeear_url("https://publico.example/a")


def test_scrapeear_url_corta_bucles_de_redireccion(monkeypatch):
    url = "https://publico.example/a"
    _servidor_falso(monkeypatch, {url: _redirect(url, "/a")})
    with pytest.raises(ValueError, match="redirecciones"):
        scrapeear_url(url)
