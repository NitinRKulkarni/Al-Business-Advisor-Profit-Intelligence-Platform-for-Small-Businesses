"""
Tests for the OCR engine contract and the Tesseract implementation.

Scope
------
These tests cover the OCR stage's *interface guarantees* -- the things the
rest of the pipeline relies on and that must not regress when the engine is
swapped in a later phase:

- `OcrResult` shape and serialization behaviour.
- `TesseractOcrEngine` satisfying the `OcrEngine` protocol structurally.
- Engine initialization, including failing loudly when the binary is absent.
- A successful recognition returning a well-formed result.
- Per-image problems (missing file, undecodable file) coming back as
  `success=False` data rather than raising, since batch runs depend on that.

Deliberately NOT tested: recognition accuracy. There is no ground truth,
and asserting on exact OCR output would make these tests brittle against
Tesseract version changes without testing anything we actually depend on.
Assertions are therefore about structure and error handling.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr import OcrEngine, OcrResult, TesseractOcrEngine
from ocr.tesseract_engine import (
    TesseractNotAvailableError,
    _resolve_tesseract_cmd,
)


def _tesseract_available() -> bool:
    try:
        _resolve_tesseract_cmd()
    except TesseractNotAvailableError:
        return False
    return True


requires_tesseract = pytest.mark.skipif(
    not _tesseract_available(),
    reason="Tesseract binary not installed on this machine",
)


@pytest.fixture(scope="module")
def engine() -> TesseractOcrEngine:
    return TesseractOcrEngine(language="eng", psm=6, oem=3)


@pytest.fixture
def text_image(tmp_path: Path) -> Path:
    """
    A synthetic high-contrast image containing clearly printed text.

    Generated rather than loaded from data/ so the tests are self-contained
    and do not depend on the sample dataset being present.
    """
    path = tmp_path / "sample.png"
    image = Image.new("L", (420, 90), color=255)
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "INVOICE 12345", fill=0)
    draw.text((12, 48), "TOTAL 250.00", fill=0)
    image.save(path)
    return path


# ------------------------------------------------------------ OcrResult

class TestOcrResult:
    def test_defaults_are_safe_for_a_failed_result(self):
        result = OcrResult(filename="x.png", success=False, error="boom")

        assert result.text == ""
        assert result.mean_confidence is None
        assert result.word_count == 0
        assert result.word_confidences == []
        assert result.processing_time_seconds == 0.0
        assert result.error == "boom"

    def test_word_confidences_are_not_shared_between_instances(self):
        # Guards against the classic mutable-default bug: a shared list
        # would silently accumulate confidences across every image in a
        # batch run.
        first = OcrResult(filename="a.png", success=True)
        second = OcrResult(filename="b.png", success=True)

        first.word_confidences.append(50.0)

        assert second.word_confidences == []

    def test_to_dict_includes_everything(self):
        result = OcrResult(
            filename="a.png", success=True, text="hi",
            word_confidences=[90.0], word_count=1,
        )
        data = result.to_dict()

        assert data["text"] == "hi"
        assert data["word_confidences"] == [90.0]

    def test_to_dict_summary_drops_verbose_fields_for_csv_rows(self):
        result = OcrResult(
            filename="a.png", success=True, text="multi\nline",
            word_confidences=[90.0, 80.0], word_count=2,
        )
        data = result.to_dict_summary()

        assert "word_confidences" not in data
        assert "text" not in data
        assert data["word_count"] == 2
        assert data["filename"] == "a.png"


# ------------------------------------------------------- engine interface

class TestEngineInterface:
    @requires_tesseract
    def test_tesseract_engine_satisfies_ocr_engine_protocol(self, engine):
        # `OcrEngine` is runtime_checkable, so this verifies the structural
        # contract a replacement engine would also have to meet.
        assert isinstance(engine, OcrEngine)

    @requires_tesseract
    def test_engine_exposes_name_and_recognize(self, engine):
        assert isinstance(engine.name, str)
        assert callable(engine.recognize)

    def test_a_minimal_duck_typed_engine_also_satisfies_the_protocol(self):
        # Confirms the protocol is genuinely structural: a future engine does
        # not need to import or subclass anything from this package.
        class FakeEngine:
            @property
            def name(self) -> str:
                return "fake-1.0"

            def recognize(self, image_path):
                return OcrResult(filename="f.png", success=True, engine=self.name)

        assert isinstance(FakeEngine(), OcrEngine)


# --------------------------------------------------------- initialization

class TestTesseractInitialization:
    @requires_tesseract
    def test_name_reports_engine_and_version(self, engine):
        assert engine.name.startswith("tesseract-")
        # Version must be a real value, not the "unknown" placeholder.
        assert engine.name != "tesseract-"
        assert "unknown" not in engine.name

    @requires_tesseract
    def test_config_string_reflects_psm_and_oem(self):
        custom = TesseractOcrEngine(language="eng", psm=4, oem=1)

        assert "--psm 4" in custom.config
        assert "--oem 1" in custom.config

    def test_raises_at_construction_when_binary_cannot_be_found(self, monkeypatch):
        # Setup failure must be loud and immediate rather than producing 156
        # identical failed results later in a batch run.
        monkeypatch.setattr("ocr.tesseract_engine.shutil.which", lambda _: None)
        monkeypatch.setattr("ocr.tesseract_engine._WINDOWS_FALLBACK_PATHS", ())

        with pytest.raises(TesseractNotAvailableError):
            TesseractOcrEngine()


# ------------------------------------------------------ successful result

class TestSuccessfulRecognition:
    @requires_tesseract
    def test_result_structure_is_well_formed(self, engine, text_image):
        result = engine.recognize(text_image)

        assert result.success is True
        assert result.error is None
        assert result.filename == "sample.png"
        assert result.engine.startswith("tesseract-")
        assert result.text.strip() != ""
        assert result.word_count > 0
        assert result.processing_time_seconds > 0

    @requires_tesseract
    def test_confidence_is_within_range_and_matches_word_count(self, engine, text_image):
        result = engine.recognize(text_image)

        assert result.mean_confidence is not None
        assert 0.0 <= result.mean_confidence <= 100.0
        # Every counted word must have a confidence, and vice versa --
        # otherwise the mean would be computed over a different population
        # than word_count reports.
        assert len(result.word_confidences) == result.word_count
        assert all(0.0 <= c <= 100.0 for c in result.word_confidences)

    @requires_tesseract
    def test_accepts_a_string_path_as_well_as_a_path_object(self, engine, text_image):
        result = engine.recognize(str(text_image))

        assert result.success is True

    @requires_tesseract
    def test_recognizes_the_digits_in_the_synthetic_image(self, engine, text_image):
        # A deliberately weak assertion: only that clean, large, printed
        # digits survive at all. This is an engine-sanity check, not an
        # accuracy measurement.
        result = engine.recognize(text_image)

        assert any(char.isdigit() for char in result.text)


# --------------------------------------------------------- error handling

class TestFailureHandling:
    @requires_tesseract
    def test_missing_file_returns_failed_result_without_raising(self, engine, tmp_path):
        result = engine.recognize(tmp_path / "does_not_exist.png")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert result.text == ""
        assert result.word_count == 0
        assert result.mean_confidence is None

    @requires_tesseract
    def test_failed_result_still_records_the_engine_name(self, engine, tmp_path):
        # Needed so a failure row in a multi-engine report is still
        # attributable to a specific engine.
        result = engine.recognize(tmp_path / "missing.png")

        assert result.engine.startswith("tesseract-")

    @requires_tesseract
    def test_undecodable_file_returns_failed_result_without_raising(self, engine, tmp_path):
        bogus = tmp_path / "not_an_image.png"
        bogus.write_bytes(b"this is definitely not PNG data")

        result = engine.recognize(bogus)

        assert result.success is False
        assert result.error
        assert result.text == ""

    @requires_tesseract
    def test_directory_path_returns_failed_result_without_raising(self, engine, tmp_path):
        result = engine.recognize(tmp_path)

        assert result.success is False
        assert result.error


# ------------------------------------------------------------ TSV parsing

class TestTsvParsing:
    def test_negative_confidence_rows_are_excluded(self):
        # Tesseract emits conf=-1 for structural/non-word rows. Averaging
        # those in as 0% would understate the quality of what was actually
        # read, so they must be dropped entirely.
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\tHello\n"
            "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t-1\t\n"
            "5\t1\t1\t1\t1\t3\t0\t0\t10\t10\t85\tWorld\n"
        )

        text, confidences, tokens = TesseractOcrEngine._parse_tsv(tsv)

        assert confidences == [95.0, 85.0]
        assert text == "Hello World"

    def test_words_are_grouped_into_lines_by_line_index(self):
        # Row structure carries meaning on an invoice (a number's row is what
        # associates it with a line item), so it must survive parsing.
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\tItem\n"
            "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t90\tA\n"
            "5\t1\t1\t1\t2\t1\t0\t0\t10\t10\t90\tTotal\n"
            "5\t1\t1\t1\t2\t2\t0\t0\t10\t10\t90\t250\n"
        )

        text, confidences, tokens = TesseractOcrEngine._parse_tsv(tsv)

        assert text == "Item A\nTotal 250"
        assert len(confidences) == 4

    def test_empty_tsv_yields_no_text_and_no_confidences(self):
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext\n"
        )

        text, confidences, tokens = TesseractOcrEngine._parse_tsv(tsv)

        assert text == ""
        assert confidences == []

    def test_whitespace_only_words_are_ignored(self):
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\t   \n"
            "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t80\tReal\n"
        )

        text, confidences, tokens = TesseractOcrEngine._parse_tsv(tsv)

        assert text == "Real"
        assert confidences == [80.0]

