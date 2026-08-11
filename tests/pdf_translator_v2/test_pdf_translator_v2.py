"""
tests/pdf_translator_v2/test_pdf_translator_v2.py

Tests para el agente PDF Translator v2.

Testeamos la lógica de negocio pura — sin llamadas a la API de Anthropic
ni ficheros PDF reales. Los nodos que llaman a la API se mockean.

Qué cubrimos:
- language_classifier: clasificación correcta de scripts Unicode
- image_strategy: decisiones de estrategia por script y geometría
- quality_gate: detección de traducciones malas (ratio, CJK en latino, etc.)
- analyzer: filtro numérico (_is_numeric_or_untranslatable)
- reconstructor: _select_font elige la fuente correcta
"""

import pytest

# ── Helpers para crear elementos de prueba ────────────────────────────────────


def make_element(
    original_text="Hello world",
    translated_text="Hola mundo",
    font_size=12.0,
    bbox_w=200.0,
    bbox_h=20.0,
    is_bold=False,
    language_script=None,
    image_strategy=None,
    font_flags=0,
    element_type=None,
):
    """Crea un PDFElement mínimo para tests sin necesitar ficheros."""
    from backend.agents.pdf_translator_v2.state import (
        BBox,
        ElementType,
        PDFElement,
        QualityStatus,
    )

    elem = PDFElement(
        element_id="test_p0_s0",
        page_num=0,
        element_type=element_type or ElementType.NATIVE_TEXT,
        bbox=BBox(0, 0, bbox_w, bbox_h),
        page_width=595.0,
        page_height=842.0,
        original_text=original_text,
        translated_text=translated_text,
        font_size=font_size,
        font_flags=font_flags,
        is_bold=is_bold,
        text_color=0,
        bg_color="#ffffff",
        quality_status=QualityStatus.OK,
    )
    if language_script:
        elem.language_script = language_script
    if image_strategy:
        elem.image_strategy = image_strategy
    return elem


# ══════════════════════════════════════════════════════════════════════════════
# LANGUAGE CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════


class TestLanguageClassifier:
    """
    _classify_script usa rangos Unicode para detectar el script.
    No llama a ninguna API — es lógica pura.
    """

    def test_latin_text(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        assert _classify_script("Anniversary Sale") == LanguageScript.LATIN

    def test_chinese_text(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        assert _classify_script("极光科技") == LanguageScript.ASIAN

    def test_japanese_text(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        assert _classify_script("東京スカイツリー") == LanguageScript.ASIAN

    def test_cyrillic_text(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        assert _classify_script("Привет мир") == LanguageScript.CYRILLIC

    def test_arabic_text(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        assert _classify_script("مرحبا بالعالم") == LanguageScript.ARABIC

    def test_mixed_mostly_latin(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        # Texto latino con algún número — debe clasificarse como LATIN
        assert _classify_script("Product 3000") == LanguageScript.LATIN

    def test_empty_text_returns_unknown(self):
        from backend.agents.pdf_translator_v2.language_classifier_node import _classify_script
        from backend.agents.pdf_translator_v2.state import LanguageScript

        assert _classify_script("") == LanguageScript.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE STRATEGY
# ══════════════════════════════════════════════════════════════════════════════


class TestImageStrategy:
    """
    _decide_strategy toma decisiones basadas en script y geometría.
    Lógica pura, sin API.
    """

    def test_latin_short_text_fits_full_style(self):
        """Texto corto latino cabe al 100% → FULL_STYLE."""
        from backend.agents.pdf_translator_v2.image_strategy_node import _decide_strategy
        from backend.agents.pdf_translator_v2.state import (
            ElementType,
            ImageStrategy,
            LanguageScript,
        )

        elem = make_element(
            original_text="SALE",
            translated_text="SALE",  # igual longitud
            font_size=20.0,
            bbox_w=200.0,
            element_type=ElementType.IMAGE_TEXT,
        )
        elem.language_script = LanguageScript.LATIN
        assert _decide_strategy(elem) == ImageStrategy.FULL_STYLE

    def test_latin_long_translation_best_effort(self):
        """Traducción muy larga → BEST_EFFORT."""
        from backend.agents.pdf_translator_v2.image_strategy_node import _decide_strategy
        from backend.agents.pdf_translator_v2.state import (
            ElementType,
            ImageStrategy,
            LanguageScript,
        )

        elem = make_element(
            original_text="OK",
            translated_text="This is a very long translation that will not fit",
            font_size=20.0,
            bbox_w=60.0,  # bbox estrecho
            element_type=ElementType.IMAGE_TEXT,
        )
        elem.language_script = LanguageScript.LATIN
        assert _decide_strategy(elem) == ImageStrategy.BEST_EFFORT

    def test_asian_small_bbox_skip(self):
        """Bbox asiático muy pequeño → SKIP (ilegible)."""
        from backend.agents.pdf_translator_v2.image_strategy_node import _decide_strategy
        from backend.agents.pdf_translator_v2.state import (
            ElementType,
            ImageStrategy,
            LanguageScript,
        )

        elem = make_element(
            original_text="字",
            translated_text="Character",
            font_size=6.0,
            bbox_h=7.0,
            element_type=ElementType.IMAGE_TEXT,
        )
        elem.language_script = LanguageScript.ASIAN
        assert _decide_strategy(elem) == ImageStrategy.SKIP

    def test_asian_reasonable_bbox_best_effort(self):
        """Bbox asiático razonable → BEST_EFFORT."""
        from backend.agents.pdf_translator_v2.image_strategy_node import _decide_strategy
        from backend.agents.pdf_translator_v2.state import (
            ElementType,
            ImageStrategy,
            LanguageScript,
        )

        elem = make_element(
            original_text="极光科技",
            translated_text="Aurora Technology",
            font_size=14.0,
            bbox_h=18.0,
            element_type=ElementType.IMAGE_TEXT,
        )
        elem.language_script = LanguageScript.ASIAN
        assert _decide_strategy(elem) == ImageStrategy.BEST_EFFORT

    def test_numeric_text_skip(self):
        """Texto numérico → SKIP (no necesita traducción)."""
        from backend.agents.pdf_translator_v2.image_strategy_node import _decide_strategy
        from backend.agents.pdf_translator_v2.state import (
            ElementType,
            ImageStrategy,
            LanguageScript,
        )

        elem = make_element(
            original_text="999.-",
            translated_text="999.-",
            font_size=14.0,
            element_type=ElementType.IMAGE_TEXT,
        )
        elem.language_script = LanguageScript.LATIN
        assert _decide_strategy(elem) == ImageStrategy.SKIP

    def test_compute_font_size_full_style_returns_original(self):
        """FULL_STYLE devuelve el font size original sin reducir."""
        from backend.agents.pdf_translator_v2.image_strategy_node import (
            compute_font_size_for_strategy,
        )
        from backend.agents.pdf_translator_v2.state import ElementType, ImageStrategy

        elem = make_element(font_size=24.0, element_type=ElementType.IMAGE_TEXT)
        elem.image_strategy = ImageStrategy.FULL_STYLE
        assert compute_font_size_for_strategy(elem) == 24.0

    def test_compute_font_size_reduced_is_80_percent(self):
        """REDUCED_SIZE devuelve el 80% del original."""
        from backend.agents.pdf_translator_v2.image_strategy_node import (
            compute_font_size_for_strategy,
        )
        from backend.agents.pdf_translator_v2.state import ElementType, ImageStrategy

        elem = make_element(font_size=20.0, element_type=ElementType.IMAGE_TEXT)
        elem.image_strategy = ImageStrategy.REDUCED_SIZE
        result = compute_font_size_for_strategy(elem)
        assert result == pytest.approx(16.0, rel=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# QUALITY GATE
# ══════════════════════════════════════════════════════════════════════════════


class TestQualityGate:
    """
    _check_element_quality detecta traducciones malas.
    Lógica pura, sin API.
    """

    def test_good_translation_no_issues(self):
        from backend.agents.pdf_translator_v2.quality_gate_node import _check_element_quality

        elem = make_element("Hello", "Hola")
        assert _check_element_quality(elem, "spanish") == []

    def test_empty_translation_flagged(self):
        from backend.agents.pdf_translator_v2.quality_gate_node import _check_element_quality

        elem = make_element("Hello", "")
        issues = _check_element_quality(elem, "spanish")
        assert any("empty" in i for i in issues)

    def test_too_long_translation_flagged(self):
        """Traducción 5x más larga que el original → issue. orig_len debe ser > 5."""
        from backend.agents.pdf_translator_v2.quality_gate_node import _check_element_quality

        elem = make_element(
            original_text="Oferta",  # 6 chars — supera el mínimo de 5
            translated_text="This is an extremely verbose translation that is way too long for this",
        )
        issues = _check_element_quality(elem, "spanish")
        assert any("too long" in i for i in issues)

    def test_cjk_in_latin_target_flagged(self):
        """Target es inglés pero la traducción tiene CJK → issue."""
        from backend.agents.pdf_translator_v2.quality_gate_node import _check_element_quality

        elem = make_element(
            original_text="极光科技",
            translated_text="极光科技",  # sin traducir
        )
        issues = _check_element_quality(elem, "english")
        assert any("CJK" in i or "not translated" in i for i in issues)

    def test_identical_to_cjk_original_flagged(self):
        """Traducción idéntica al original CJK → no se tradujo."""
        from backend.agents.pdf_translator_v2.quality_gate_node import _check_element_quality

        elem = make_element("公司简介", "公司简介")
        issues = _check_element_quality(elem, "english")
        assert len(issues) > 0

    def test_acceptable_length_ratio_ok(self):
        """Ratio bajo es aceptable — texto corto con traducción razonable."""
        from backend.agents.pdf_translator_v2.quality_gate_node import _check_element_quality

        elem = make_element(
            original_text="Oferta",  # 6 chars
            translated_text="Offer",  # 5 chars — ratio < 1, claramente OK
        )
        issues = _check_element_quality(elem, "english")
        length_issues = [i for i in issues if "too long" in i]
        assert len(length_issues) == 0


# ══════════════════════════════════════════════════════════════════════════════
# NUMERIC FILTER (analyzer)
# ══════════════════════════════════════════════════════════════════════════════


class TestNumericFilter:
    """
    _is_numeric_or_untranslatable filtra texto que no necesita traducción.
    """

    def _fn(self, text):
        from backend.agents.pdf_translator_v2.analyzer_node import _is_numeric_or_untranslatable

        return _is_numeric_or_untranslatable(text)

    def test_price_filtered(self):
        assert self._fn("999.-") is True

    def test_price_with_thousands(self):
        assert self._fn("1.299.-") is True

    def test_measurement_filtered(self):
        assert self._fn("100 W") is True

    def test_rpm_filtered(self):
        assert self._fn("1400 r.p.m.") is True

    def test_product_ref_filtered(self):
        assert self._fn("Ref.: 1579408") is True

    def test_model_code_filtered(self):
        assert self._fn("WW90T4042CE") is True

    def test_price_no_suffix_filtered(self):
        assert self._fn("129.99") is True

    def test_real_word_not_filtered(self):
        assert self._fn("ANNIVERSARY") is False

    def test_sentence_not_filtered(self):
        assert self._fn("The party of the best offers") is False

    def test_offer_not_filtered(self):
        assert self._fn("OFFER") is False

    def test_description_not_filtered(self):
        assert self._fn("Función Vapor Refresh") is False

    def test_mixed_text_with_price_not_filtered(self):
        # Texto real con precio al final — tiene >30% alfa → no filtrar
        assert self._fn("AddWash Drum 449.-") is False


# ══════════════════════════════════════════════════════════════════════════════
# RECONSTRUCTOR — font selection
# ══════════════════════════════════════════════════════════════════════════════


class TestFontSelection:
    """
    _select_font elige la fuente correcta según flags y contenido.
    """

    def _fn(self, elem):
        from backend.agents.pdf_translator_v2.reconstructor_node import _select_font

        return _select_font(elem)

    def test_bold_flag_returns_hebo(self):
        elem = make_element(font_flags=16)  # flag 16 = bold en PyMuPDF
        assert self._fn(elem) == "hebo"

    def test_italic_flag_returns_heit(self):
        elem = make_element(font_flags=2)
        assert self._fn(elem) == "heit"

    def test_regular_returns_helv(self):
        elem = make_element(font_flags=0)
        assert self._fn(elem) == "helv"

    def test_cjk_text_returns_cjk_font(self):
        elem = make_element(translated_text="极光科技")
        assert self._fn(elem) == "cjk"

    def test_bold_flag_overrides_italic(self):
        """Bold (16) + Italic (2) = 18 → bold gana."""
        elem = make_element(font_flags=18)
        assert self._fn(elem) == "hebo"
