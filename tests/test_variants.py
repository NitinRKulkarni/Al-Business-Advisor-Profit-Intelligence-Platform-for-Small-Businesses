"""
Tests for `receipt_extraction.variants` (multi-variant OCR gating and
evidence-based candidate selection) and its integration into
`process_receipts(..., use_variants=True)`.

All deterministic: variant selection is pure logic over stage names and
warnings, scoring is pure logic over an `ExtractionResult`, and the
integration tests use fake `OcrEngine`s that return scripted text per
image path. No real Tesseract/EasyOCR call, no model download, no network.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ocr.engine import OcrResult
from receipt_extraction import (
    VariantCandidate,
    choose_best_per_engine,
    extract_from_ocr,
    finalize_confidence,
    process_receipt,
    score_candidate,
    select_variant_stages,
    validate_receipt,
)


def _extraction(text: str, confidence: float = 70.0):
    result = extract_from_ocr(OcrResult(
        filename="x.png", success=True, engine="fake",
        text=text, mean_confidence=confidence, word_count=len(text.split()),
    ))
    validate_receipt(result)
    finalize_confidence(result)
    return result


def _candidate(variant: str, text: str, confidence: float = 70.0,
               engine: str = "fake", word_count: int | None = None) -> VariantCandidate:
    extraction = _extraction(text, confidence)
    return VariantCandidate(
        engine=engine, variant=variant, extraction=extraction,
        ocr_confidence=confidence,
        word_count=len(text.split()) if word_count is None else word_count,
    )


# A self-consistent receipt: 2*40=80, 1*20=20, items sum 100 == subtotal,
# 100 - 0 + 0 == total. Every arithmetic check passes.
CONSISTENT_TEXT = (
    "ABC Store\n"
    "Date: 01/06/2024\n"
    "Widget A 2 40.00 80.00\n"
    "Widget B 1 20.00 20.00\n"
    "Subtotal 100.00\n"
    "Grand Total 100.00\n"
)

# Same receipt but with the decimal points destroyed on the amount column,
# the characteristic damage over-aggressive binarization causes. Arithmetic
# no longer holds.
BROKEN_ARITHMETIC_TEXT = (
    "ABC Store\n"
    "Date: 01/06/2024\n"
    "Widget A 2 40.00 8000.00\n"
    "Widget B 1 20.00 2000.00\n"
    "Subtotal 100.00\n"
    "Grand Total 100.00\n"
)


class TestVariantStageGating:
    def test_clean_image_selects_only_the_pipeline_default(self):
        # No intensity-rewriting operation ran and no quality warning
        # fired, so there is no reason to pay for extra OCR passes.
        assert select_variant_stages(["grayscale_conversion"], []) == ["final"]

    def test_intensity_rewriting_operation_adds_unenhanced_control(self):
        # When an enhancement rewrote pixels, the un-enhanced grayscale is
        # worth OCR-ing as a control in case the enhancement hurt.
        stages = select_variant_stages(
            ["grayscale_conversion", "shadow_correction"], [],
        )
        assert "grayscale" in stages
        assert "final" in stages

    def test_faded_ink_warning_adds_binarized_candidate(self):
        stages = select_variant_stages(["grayscale_conversion"], ["low_contrast"])
        assert "thresholded" in stages

    def test_final_is_always_present_and_first(self):
        stages = select_variant_stages(
            ["grayscale_conversion", "contrast_enhancement"],
            ["low_contrast", "uneven_lighting_or_shadow"],
        )
        assert stages[0] == "final"

    def test_unknown_operations_and_warnings_are_ignored_safely(self):
        assert select_variant_stages(["something_new"], ["unheard_of"]) == ["final"]

    def test_empty_inputs_are_safe(self):
        assert select_variant_stages([], []) == ["final"]


class TestCandidateScoring:
    def test_arithmetically_consistent_candidate_scores_above_broken_one(self):
        good = score_candidate(_candidate("final", CONSISTENT_TEXT))
        bad = score_candidate(_candidate("thresholded", BROKEN_ARITHMETIC_TEXT))

        assert good.score > bad.score

    def test_high_confidence_but_almost_no_text_loses_to_low_confidence_rich_text(self):
        # This is the documented, measured failure mode the whole module
        # exists for: on a real dataset image the pipeline's chosen variant
        # scored 87.5 OCR confidence while recognising only 3 words, and a
        # discarded variant recognised far more at a much lower confidence.
        # Confidence must not be able to win that comparison.
        sparse = _candidate("final", "Thank You !", confidence=87.5)
        rich = _candidate("grayscale", CONSISTENT_TEXT, confidence=34.9)

        assert score_candidate(rich).score > score_candidate(sparse).score

    def test_ocr_confidence_alone_cannot_flip_the_winner(self):
        # Identical extractions, wildly different confidence. Confidence is
        # allowed to break the tie, but its total contribution is small --
        # so it can never overturn a real evidence difference.
        low = score_candidate(_candidate("final", CONSISTENT_TEXT, confidence=1.0))
        high = score_candidate(_candidate("grayscale", CONSISTENT_TEXT, confidence=99.0))

        assert high.score >= low.score
        assert (high.score - low.score) <= 2.0

    def test_text_volume_saturates_so_noise_cannot_win_on_bulk(self):
        # Same (empty) extracted structure, absurd word count. The text
        # term is capped, so a garbage-heavy variant cannot outscore a
        # variant that actually recovered a consistent receipt.
        noise = _candidate("thresholded", "zz " * 500, confidence=50.0)
        real = _candidate("final", CONSISTENT_TEXT, confidence=50.0)

        assert score_candidate(real).score > score_candidate(noise).score

    def test_failed_extraction_scores_zero(self):
        from receipt_extraction import ExtractionResult
        candidate = VariantCandidate(
            engine="fake", variant="final",
            extraction=ExtractionResult(source="x.png", success=False, error="boom"),
            ocr_confidence=90.0, word_count=100,
        )

        assert score_candidate(candidate).score == 0.0

    def test_score_breakdown_is_populated_for_transparency(self):
        candidate = score_candidate(_candidate("final", CONSISTENT_TEXT))

        assert set(candidate.score_breakdown) == {
            "arithmetic", "field_coverage", "item_structure",
            "text_coverage", "ocr_confidence",
        }


class TestChooseBestPerEngine:
    def test_one_winner_per_engine_not_one_global_winner(self):
        # Two variants per engine must collapse to exactly one candidate
        # per engine, so cross-engine reconciliation still receives
        # independent voices rather than inflated agreement.
        candidates = [
            _candidate("final", CONSISTENT_TEXT, engine="tesseract"),
            _candidate("thresholded", BROKEN_ARITHMETIC_TEXT, engine="tesseract"),
            _candidate("final", CONSISTENT_TEXT, engine="easyocr"),
            _candidate("thresholded", BROKEN_ARITHMETIC_TEXT, engine="easyocr"),
        ]

        winners, _ = choose_best_per_engine(candidates)

        assert len(winners) == 2
        assert {w.engine for w in winners} == {"tesseract", "easyocr"}

    def test_better_variant_is_selected_over_the_pipeline_default(self):
        candidates = [
            _candidate("final", "Thank You !", confidence=87.5),
            _candidate("grayscale", CONSISTENT_TEXT, confidence=34.9),
        ]

        winners, notes = choose_best_per_engine(candidates)

        assert winners[0].variant == "grayscale"
        assert any("non_default_variant_preferred" in n for n in notes)

    def test_tie_resolves_to_the_first_candidate_so_default_is_never_displaced(self):
        # Identical evidence AND identical confidence: `final` is passed
        # first by the caller and must keep winning, so a variant only
        # displaces the adaptive pipeline choice on strictly better data.
        candidates = [
            _candidate("final", CONSISTENT_TEXT, confidence=50.0),
            _candidate("thresholded", CONSISTENT_TEXT, confidence=50.0),
        ]

        winners, _ = choose_best_per_engine(candidates)

        assert winners[0].variant == "final"

    def test_selection_note_records_what_was_considered(self):
        candidates = [
            _candidate("final", CONSISTENT_TEXT),
            _candidate("thresholded", BROKEN_ARITHMETIC_TEXT),
        ]

        _, notes = choose_best_per_engine(candidates)

        assert any("variant_selected" in n and "considered=2" in n for n in notes)

    def test_variant_without_arithmetic_evidence_cannot_displace_the_default(self):
        # Regression, measured on batch2_invoice_105: on a sparse receipt
        # (a single Total, no subtotal/tax/qty columns) NO arithmetic check
        # is applicable, so the coverage term alone decided the winner --
        # and it promoted a binarized variant that misread the total as 352
        # when the receipt says 850, i.e. it replaced a correct null with a
        # plausible WRONG number. A challenger with no arithmetic
        # corroboration must never displace `final`.
        sparse_default = _candidate("final", "Salon\nHair Cut\n", confidence=30.0)
        # Richer-looking, but nothing here is arithmetically checkable:
        # no quantity/unit_price triple and no subtotal to reconcile.
        hallucinating = _candidate(
            "thresholded", "Salon\nHair Cut\nTotal 352\n", confidence=40.0,
        )

        winners, notes = choose_best_per_engine([sparse_default, hallucinating])

        assert winners[0].variant == "final"
        assert any("variant_switch_declined_no_arithmetic_evidence" in n for n in notes)

    def test_variant_with_arithmetic_evidence_may_still_displace_the_default(self):
        # The guard must not block the genuine upside: a challenger whose
        # extraction is arithmetically self-consistent is corroborated by
        # evidence independent of OCR confidence, so it is allowed to win.
        weak_default = _candidate("final", "Thank You !", confidence=95.0)
        corroborated = _candidate("grayscale", CONSISTENT_TEXT, confidence=20.0)

        winners, notes = choose_best_per_engine([weak_default, corroborated])

        assert winners[0].variant == "grayscale"
        assert any("non_default_variant_preferred" in n for n in notes)

    def test_single_candidate_produces_no_selection_noise(self):
        winners, notes = choose_best_per_engine([_candidate("final", CONSISTENT_TEXT)])

        assert len(winners) == 1
        assert notes == []

    def test_all_failed_candidates_still_return_a_winner_without_raising(self):
        from receipt_extraction import ExtractionResult
        candidates = [
            VariantCandidate(
                engine="fake", variant=v,
                extraction=ExtractionResult(source="x.png", success=False, error="boom"),
                ocr_confidence=None, word_count=0,
            )
            for v in ("final", "thresholded")
        ]

        winners, _ = choose_best_per_engine(candidates)

        assert len(winners) == 1


# ------------------------------------------------- integration (fake OCR)

class _PathAwareFakeEngine:
    """
    Fake engine returning different scripted text depending on which
    variant image path it is handed, so multi-variant selection can be
    exercised end-to-end through `process_receipts` without real OCR.
    """

    def __init__(self, name: str, text_by_marker: dict[str, str], default_text: str):
        self._name = name
        self._text_by_marker = text_by_marker
        self._default_text = default_text
        self.seen_paths: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def recognize(self, image_path) -> OcrResult:
        path_str = str(image_path)
        self.seen_paths.append(path_str)
        # Match on the FILE NAME only, never the full path: pytest's
        # tmp_path is derived from the test function name, and a test named
        # "..._variant_..." would otherwise make every path look like a
        # variant image and defeat the fixture.
        name = Path(path_str).name
        text = self._default_text
        confidence = 40.0
        for marker, marker_text in self._text_by_marker.items():
            if marker in name:
                text = marker_text
                confidence = 90.0  # deliberately HIGH on the bad variant
                break
        return OcrResult(
            filename=name, success=True, engine=self._name,
            text=text, mean_confidence=confidence, word_count=len(text.split()),
        )


def _write_low_contrast_receipt(path: Path) -> None:
    """
    An image whose quality analysis will flag low contrast / uneven
    lighting, so the variant gate actually opens. Faint ink on mid-grey
    paper, written via numpy so no font dependency is involved.
    """
    arr = np.full((260, 380), 165, dtype=np.uint8)
    for i in range(7):
        y = 25 + i * 32
        arr[y:y + 3, 20:360] = 140  # very low ink/paper separation
    Image.fromarray(arr, mode="L").save(path)


class TestProcessReceiptsWithVariants:
    def test_default_call_does_not_enable_variants(self, tmp_path: Path):
        # Backward compatibility: without use_variants the engine must be
        # asked to read exactly one image, as before.
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        engine = _PathAwareFakeEngine("fake", {}, CONSISTENT_TEXT)

        process_receipt(image, tmp_path / "out", ocr_engine=engine)

        assert len(engine.seen_paths) == 1
        assert "_variant_" not in engine.seen_paths[0]

    def test_variant_mode_reads_more_than_one_image_when_quality_warrants(self, tmp_path: Path):
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        engine = _PathAwareFakeEngine("fake", {}, CONSISTENT_TEXT)

        process_receipt(image, tmp_path / "out", ocr_engine=engine, use_variants=True)

        # The low-contrast image should have opened the gate for at least
        # one additional variant beyond `final`.
        assert len(engine.seen_paths) >= 2

    def test_variant_mode_prefers_evidence_over_high_confidence_variant(self, tmp_path: Path):
        # The `thresholded` variant returns near-empty text at HIGH
        # confidence; `final` returns a fully consistent receipt at LOW
        # confidence. The consistent one must win, and the total must come
        # from it.
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        engine = _PathAwareFakeEngine(
            "fake",
            {"_variant_thresholded": "Thank You !"},
            CONSISTENT_TEXT,
        )

        result = process_receipt(
            image, tmp_path / "out", ocr_engine=engine, use_variants=True,
        )

        assert result.receipt.total == 100.0

    def test_variant_mode_output_contract_is_unchanged(self, tmp_path: Path):
        # Downstream (DB/analytics) consumers must see the same keys
        # whether or not variants were used.
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        engine = _PathAwareFakeEngine("fake", {}, CONSISTENT_TEXT)

        plain = process_receipt(image, tmp_path / "out1", ocr_engine=engine).to_dict()
        varied = process_receipt(
            image, tmp_path / "out2", ocr_engine=engine, use_variants=True,
        ).to_dict()

        assert set(plain) == set(varied)

    def test_variant_selection_is_recorded_in_warnings(self, tmp_path: Path):
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        engine = _PathAwareFakeEngine(
            "fake", {"_variant_thresholded": "Thank You !"}, CONSISTENT_TEXT,
        )

        result = process_receipt(
            image, tmp_path / "out", ocr_engine=engine, use_variants=True,
        )

        # The decision must be visible, not silent.
        assert any("variant_selected" in w for w in result.warnings)

    def test_crashing_variant_does_not_lose_the_other_variants(self, tmp_path: Path):
        class _PartiallyCrashingEngine(_PathAwareFakeEngine):
            def recognize(self, image_path):
                # File name only, not the full path -- see the note in
                # _PathAwareFakeEngine.recognize.
                if "_variant_" in Path(image_path).name:
                    raise RuntimeError("simulated variant OCR crash")
                return super().recognize(image_path)

        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        engine = _PartiallyCrashingEngine("fake", {}, CONSISTENT_TEXT)

        result = process_receipt(
            image, tmp_path / "out", ocr_engine=engine, use_variants=True,
        )

        # `final` still succeeded, so the receipt is still extracted.
        assert result.success
        assert result.receipt.total == 100.0

    def test_multi_image_batch_works_with_variants(self, tmp_path: Path):
        from receipt_extraction import process_receipts
        image1 = tmp_path / "a.png"
        image2 = tmp_path / "b.png"
        _write_low_contrast_receipt(image1)
        _write_low_contrast_receipt(image2)
        engine = _PathAwareFakeEngine("fake", {}, CONSISTENT_TEXT)

        results = process_receipts(
            [image1, image2], tmp_path / "out", ocr_engine=engine, use_variants=True,
        )

        assert [r.source for r in results] == ["a.png", "b.png"]
        assert all(r.success for r in results)

    def test_source_images_are_never_modified_in_variant_mode(self, tmp_path: Path):
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)
        before = image.read_bytes()
        engine = _PathAwareFakeEngine("fake", {}, CONSISTENT_TEXT)

        process_receipt(image, tmp_path / "out", ocr_engine=engine, use_variants=True)

        assert image.read_bytes() == before


class TestHandoffRecordBackwardCompatibility:
    def test_variant_key_absent_unless_requested(self, tmp_path: Path):
        from image_processing.receipt_pipeline import process_receipt_images
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)

        [record] = process_receipt_images([image], tmp_path / "out")

        assert "variant_image_paths" not in record

    def test_variant_key_present_when_requested(self, tmp_path: Path):
        from image_processing.receipt_pipeline import process_receipt_images
        image = tmp_path / "r.png"
        _write_low_contrast_receipt(image)

        [record] = process_receipt_images(
            [image], tmp_path / "out", variant_stages=["grayscale", "thresholded"],
        )

        assert "variant_image_paths" in record
        assert isinstance(record["variant_image_paths"], dict)
