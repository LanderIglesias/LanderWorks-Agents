from backend.agents.doc_intel_agent.document_processor import (
    CHUNK_SIZE_WORDS,
    OVERLAP_WORDS,
    split_into_chunks,
)


def _pagina(n_palabras: int, numero: int = 1, prefijo: str = "w") -> dict:
    return {
        "text": " ".join(f"{prefijo}{i}" for i in range(n_palabras)),
        "page_number": numero,
    }


def test_sin_texto_no_hay_chunks():
    assert split_into_chunks([]) == []
    assert split_into_chunks([{"text": "   ", "page_number": 1}]) == []


def test_documento_corto_es_un_solo_chunk():
    chunks = split_into_chunks([_pagina(10)])
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["page_number"] == 1
    assert len(chunks[0]["content"].split()) == 10


def test_chunks_consecutivos_se_solapan():
    primero, segundo = split_into_chunks([_pagina(CHUNK_SIZE_WORDS + 100)])
    assert len(primero["content"].split()) == CHUNK_SIZE_WORDS
    assert primero["content"].split()[-OVERLAP_WORDS:] == segundo["content"].split()[:OVERLAP_WORDS]
    assert (primero["chunk_index"], segundo["chunk_index"]) == (0, 1)


def test_no_se_pierde_ninguna_palabra():
    pagina = _pagina(CHUNK_SIZE_WORDS * 3 + 7)
    chunks = split_into_chunks([pagina])
    contenido = {palabra for chunk in chunks for palabra in chunk["content"].split()}
    assert contenido == set(pagina["text"].split())


def test_el_ultimo_chunk_no_repite_solo_lo_ya_cubierto():
    """Cada chunk se embebe y se paga: uno contenido en el anterior es coste y ruido."""
    chunks = split_into_chunks([_pagina(CHUNK_SIZE_WORDS)])
    assert len(chunks) == 1


def test_el_chunk_guarda_la_pagina_de_su_primera_palabra():
    chunks = split_into_chunks(
        [_pagina(CHUNK_SIZE_WORDS - OVERLAP_WORDS, 1, "a"), _pagina(CHUNK_SIZE_WORDS, 2, "b")]
    )
    assert [c["page_number"] for c in chunks] == [1, 2]
