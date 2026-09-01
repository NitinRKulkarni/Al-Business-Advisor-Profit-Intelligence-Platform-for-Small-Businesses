"""
Tests for `EasyOcrEngine`.

Regression context
--------------------
When `OcrToken`/geometry support was added to `OcrResult`, EasyOCR's
internal `_assemble()` row-grouping loop was left unpacking the OLD 5-tuple
entry shape while entries had grown to 7 fields -- a `ValueError` on every
single call. This went unnoticed because no test exercised
`EasyOcrEngine.recognize()` end-to-end; every existing test covered
Tesseract only. The engine was therefore completely non-functional despite
being part of the documented architecture ("Tesseract + EasyOCR").

These tests build synthetic images (no dependency on the 156-image
dataset) and are skipped, not failed, when EasyOCR/torch cannot be
constructed in the current environment (e.g. missing model download,
offline CI) -- consistent with how `tests/test_ocr_engine.py` skips when
Tesseract is not installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr.engine import OcrEngine, OcrResult


def _easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401
    except ImportError:
        return False
    return True


requires_easyocr = pytest.mark.skipif(
    not _easyocr_available(), reason="easyocr package not installed"
)


@pytest.fixture(scope="module")
def engine():
    if not _easyocr_available():
        pytest.skip("easyocr not installed")
    from ocr import EasyOcrEngine
    try:
        return EasyOcrEngine(languages=("en",), gpu=False)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"EasyOCR could not initialise in this environment: {exc}")


@pytest.fixture
def text_image(tmp_path: Path) -> Path:
    path = tmp_path / "sample.png"
    image = Image.new("L", (420, 90), color=255)
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "INVOICE 12345", fill=0)
    draw.text((12, 48), "TOTAL 250.00", fill=0)
    image.save(path)
    return path


class TestEasyOcrEngineBasics:
    @requires_easyocr
    def test_satisfies_ocr_engine_protocol(self, engine):
        assert isinstance(engine, OcrEngine)

    @requires_easyocr
    def test_name_reports_engine_and_version(self, engine):
        assert engine.name.startswith("easyocr-")


class TestEasyOcrRecognition:
    @requires_easyocr
    def test_recognize_does_not_raise_and_returns_ocr_result(self, engine, text_image):
        # THE regression check: this call used to raise ValueError
        # unconditionally ("too many values to unpack") on every image.
        result = engine.recognize(text_image)

        assert isinstance(result, OcrResult)
        assert result.success is True
        assert result.error is None

    @requires_easyocr
    def test_recognized_text_is_non_empty_on_a_clear_image(self, engine, text_image):
        result = engine.recognize(text_image)

        assert result.text.strip() != ""
        assert result.word_count > 0

    @requires_easyocr
    def test_confidence_is_on_the_0_to_100_scale(self, engine, text_image):
        # EasyOCR reports confidence 0-1 internally; the engine must
        # rescale to 0-100 to match OcrResult's documented contract.
        result = engine.recognize(text_image)

        assert result.mean_confidence is not None
        assert 0.0 <= result.mean_confidence <= 100.0
        assert all(0.0 <= c <= 100.0 for c in result.word_confidences)

    @requires_easyocr
    def test_tokens_are_populated_with_valid_geometry(self, engine, text_image):
        result = engine.recognize(text_image)

        assert len(result.tokens) > 0
        for token in result.tokens:
            assert token.width >= 0
            assert token.height >= 0
            assert 0.0 <= token.confidence <= 100.0

    @requires_easyocr
    def test_missing_file_returns_failed_result_without_raising(self, engine, tmp_path):
        result = engine.recognize(tmp_path / "does_not_exist.png")

        assert result.success is False
        assert result.error is not None
        assert result.text == ""

    @requires_easyocr
    def test_result_flows_through_receipt_extraction_without_crashing(self, engine, text_image):
        # End-to-end guard: EasyOcrEngine must be usable as a drop-in
        # OcrEngine for the extraction layer, not just in isolation.
        from receipt_extraction import extract_from_ocr

        ocr_result = engine.recognize(text_image)
        extraction = extract_from_ocr(ocr_result)

        assert extraction.success is True
