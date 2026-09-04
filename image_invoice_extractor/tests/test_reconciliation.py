"""
Tests for `receipt_extraction.reconciliation` and the multi-engine
`process_receipts(..., ocr_engines=[...])` path.

All tests use FAKE `OcrEngine` implementations (no real Tesseract/EasyOCR
call, no network, no model download) so reconciliation logic is tested
deterministically in isolation. Real-engine integration is covered by the
ground-truth benchmark script, not by pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr.engine import OcrResult
from receipt_extraction import (
    EngineExtraction,
    ExtractionResult,
    LineItem,
    ReceiptData,
    classify_numeric_disagreement,
    extract_from_ocr,
    process_receipt,
    process_receipts,
    reconcile_extractions,
)


def make_ocr(engine: str, text: str, confidence: float = 70.0, success: bool = True,
             error: str | None = None) -> OcrResult:
    return OcrResult(
        filename="test.png", success=success, engine=engine,
        text=text, mean_confidence=confidence, word_count=len(text.split()),
        error=error,
    )


def engine_extraction(engine: str, text: str, confidence: float = 70.0) -> EngineExtraction:
    ocr = make_ocr(engine, text, confidence)
    single = extract_from_ocr(ocr)
    return EngineExtraction(
        engine=engine, ocr_confidence=confidence, receipt=single.receipt,
        raw_text=text, warnings=single.warnings,
    )


class FakeEngine:
    """Deterministic stand-in OcrEngine returning a scripted OcrResult."""

    def __init__(self, engine_name: str, text: str, confidence: float = 70.0,
                 success: bool = True, error: str | None = None):
        self._name = engine_name
        self._text = text
        self._confidence = confidence
        self._success = success
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    def recognize(self, image_path) -> OcrResult:
        return make_ocr(self._name, self._text, self._confidence, self._success, self._error)


class CrashingEngine:
    """An engine that always fails, to test batch/engine isolation."""

    @property
    def name(self) -> str:
        return "crashing-engine"

    def recognize(self, image_path) -> OcrResult:
        return OcrResult(filename="x", success=False, engine=self.name, error="simulated crash")


# ------------------------------------------------------------- fixtures

CLEAN_TEXT_A = "ABC Store\nInvoice No: INV-500\nDate: 01/06/2024\nWidget 2 40.00 80.00\nGrand Total 80.00\n"
CLEAN_TEXT_B = "ABC Store\nInvoice No: INV-500\nDate: 01/06/2024\nWidget 2 40.00 80.00\nGrand Total 80.00\n"


class TestReconcileExtractionsAgreement:
    def test_word_boundary_difference_between_engines_still_counts_as_agreement(self):
        # Regression: measured on real data. Tesseract read "New Star
        # Electricals"; EasyOCR read "NewStar   Electricals" -- same
        # vendor, EasyOCR just merged two words. This must still count as
        # agreement rather than falling to "disagreement" (which would
        # discard a value both engines actually got right).
        text_a = "New Star Electricals\nGrand Total 100.00\n"
        text_b = "NewStar   Electricals\nGrand Total 100.00\n"
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        _, decisions, _ = reconcile_extractions(extractions)

        assert decisions["vendor_name"].agreement is True
        assert decisions["vendor_name"].value is not None

    def test_agreeing_scalar_and_numeric_fields_produce_high_confidence(self):
        extractions = [
            engine_extraction("tesseract", CLEAN_TEXT_A),
            engine_extraction("easyocr", CLEAN_TEXT_B),
        ]
        receipt, decisions, warnings = reconcile_extractions(extractions)

        assert receipt.total == 80.0
        assert decisions["total"].agreement is True
        assert decisions["total"].source == "tesseract+easyocr"
        assert decisions["total"].confidence >= 90.0

    def test_agreeing_vendor_name_is_selected_with_high_confidence(self):
        extractions = [
            engine_extraction("tesseract", CLEAN_TEXT_A),
            engine_extraction("easyocr", CLEAN_TEXT_B),
        ]
        _, decisions, _ = reconcile_extractions(extractions)

        assert decisions["vendor_name"].value == "ABC Store"
        assert decisions["vendor_name"].agreement is True


class TestReconcileExtractionsDisagreement:
    def test_conflicting_totals_with_no_arithmetic_evidence_return_null(self):
        text_a = "Shop\nGrand Total 430.00\n"
        text_b = "Shop\nGrand Total 999.00\n"
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, decisions, warnings = reconcile_extractions(extractions)

        assert receipt.total is None
        assert decisions["total"].agreement is False
        assert decisions["total"].source == "disagreement"
        assert len(decisions["total"].candidates) == 2
        assert any("total" in w for w in warnings)

    def test_conflicting_totals_resolved_by_arithmetic_evidence(self):
        # Tesseract sees the pre-discount figure (430); EasyOCR sees the
        # correct post-discount figure (410). Both engines also agree on
        # subtotal=430 and discount=20, so 430 - 20 = 410 identifies which
        # candidate is actually correct -- this must be selected on
        # evidence, not because one engine "sounds more confident".
        text_tess = "Shop\nSubtotal 430.00\nDiscount 20.00\nGrand Total 430.00\n"
        text_easy = "Shop\nSubtotal 430.00\nDiscount 20.00\nGrand Total 410.00\n"
        extractions = [
            engine_extraction("tesseract", text_tess),
            engine_extraction("easyocr", text_easy),
        ]
        receipt, decisions, warnings = reconcile_extractions(extractions)

        assert receipt.total == 410.0
        assert decisions["total"].source == "arithmetic"
        assert decisions["total"].agreement is False

    def test_item_sum_arithmetic_fallback_applies_discount_before_comparing_to_total(self):
        # Regression: `item_amount_sum` approximates the receipt's
        # SUBTOTAL (items before discount/tax), not the final total
        # directly. Previously the arithmetic fallback compared
        # `item_amount_sum` to each `total` candidate WITHOUT applying
        # discount/tax first, so a candidate that merely matched the
        # unadjusted item sum (a pre-discount figure) could be mistaken
        # for a confirmed total. Here no "Subtotal" line exists at all
        # (so the subtotal-based check is unavailable and this test
        # exercises the item-sum path exclusively): items sum to 430,
        # discount is 20, and the two engines disagree on total (430 vs
        # 410). The correct, discount-adjusted total is 410 -- picking
        # 430 (matching the unadjusted item sum) would be exactly the bug
        # this guards against.
        text_tess = (
            "Shop\nWidget A 1 200.00 200.00\nWidget B 1 230.00 230.00\n"
            "Discount 20.00\nGrand Total 430.00\n"
        )
        text_easy = (
            "Shop\nWidget A 1 200.00 200.00\nWidget B 1 230.00 230.00\n"
            "Discount 20.00\nGrand Total 410.00\n"
        )
        extractions = [
            engine_extraction("tesseract", text_tess),
            engine_extraction("easyocr", text_easy),
        ]
        receipt, decisions, _ = reconcile_extractions(extractions)

        assert receipt.total == 410.0
        assert decisions["total"].source == "arithmetic"
        assert decisions["total"].reason == "arithmetic_match_item_sum"

    def test_quantity_price_amount_mismatch_is_never_silently_fixed(self):
        # Tesseract: qty=4 (misread), price=200, amount=200 -- arithmetic
        # does not hold (4*200 != 200). This must be flagged, not "fixed"
        # to qty=1 just because that would make the math work.
        text = "Shop\nBack Cover 4 200.00 200.00\n"
        extractions = [engine_extraction("tesseract", text)]
        receipt, _, _ = reconcile_extractions(extractions)

        assert receipt.items[0].quantity == 4
        assert receipt.items[0].amount == 200.0
        # The value must be preserved exactly as OCR'd -- no silent "fix".


class TestSuspiciousNumericDisagreement:
    """
    Digit-level classification of numeric disagreements. Purely
    diagnostic: these must add a REASON, never change a value.
    """

    def test_trailing_digit_loss_is_named(self):
        # The measured "1550 -> 155" OCR failure signature.
        assert classify_numeric_disagreement(1550.0, 155.0) == "trailing_digit_lost"

    def test_leading_digit_loss_is_named(self):
        # Measured on a real receipt: 1121.00 read as 121.00.
        assert classify_numeric_disagreement(1121.0, 121.0) == "leading_digit_lost"

    def test_decimal_place_shift_is_named(self):
        # Same digit sequence, different magnitude: the decimal point
        # itself moved ("12.50" read as "125.00").
        assert classify_numeric_disagreement(12.50, 125.0) == "decimal_place_shift"

    def test_dropped_trailing_zero_prefers_the_digit_loss_label(self):
        # 1250 -> 125 differs by a factor of ten AND has a changed digit
        # sequence. The mechanically specific description ("a trailing
        # digit went missing") is the more useful one for a reviewer, so
        # the classifier must not label it a decimal shift.
        assert classify_numeric_disagreement(1250.0, 125.0) == "trailing_digit_lost"

    def test_single_digit_substitution_is_named(self):
        assert classify_numeric_disagreement(430.0, 410.0) == "single_digit_substitution"

    def test_digit_transposition_is_named(self):
        assert classify_numeric_disagreement(1250.0, 1205.0) == "digit_transposition"

    def test_identical_values_have_no_pattern(self):
        assert classify_numeric_disagreement(500.0, 500.0) is None

    def test_decimal_formatting_difference_is_not_a_corruption(self):
        # "850" vs "850.00" is a formatting difference, not digit damage.
        assert classify_numeric_disagreement(850.0, 850.00) is None

    def test_unrelated_values_report_no_false_pattern(self):
        # Two genuinely different numbers must not be forced into a
        # category -- a spurious "suspicious pattern" label would mislead
        # whoever reviews the queue.
        assert classify_numeric_disagreement(37.0, 8421.0) is None

    def test_zero_values_do_not_raise(self):
        # Guards the division in the decimal-shift check.
        classify_numeric_disagreement(0.0, 500.0)
        classify_numeric_disagreement(0.0, 0.0)

    def test_pattern_is_surfaced_on_a_real_total_disagreement(self):
        # End-to-end: engines disagree on total with no arithmetic to
        # resolve it, so the value must still be null -- but the reason
        # now names the digit pattern for the reviewer.
        text_a = "Shop\nGrand Total 1550.00\n"
        text_b = "Shop\nGrand Total 155.00\n"
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, decisions, _ = reconcile_extractions(extractions)

        assert receipt.total is None  # unchanged safety behaviour
        assert "trailing_digit_lost" in decisions["total"].reason

    def test_pattern_does_not_change_the_selected_value(self):
        # Safety invariant: adding diagnostics must not make the module
        # start picking a value it previously refused to pick.
        text_a = "Shop\nSub Total 1550.00\n"
        text_b = "Shop\nSub Total 155.00\n"
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, decisions, _ = reconcile_extractions(extractions)

        assert receipt.subtotal is None
        assert decisions["subtotal"].source == "disagreement"


class TestReconcileExtractionsSingleEngine:
    def test_single_engine_passes_through_with_decisions_populated(self):
        extractions = [engine_extraction("tesseract", CLEAN_TEXT_A)]
        receipt, decisions, warnings = reconcile_extractions(extractions)

        assert receipt.total == 80.0
        assert decisions["total"].source == "tesseract"
        assert decisions["total"].agreement is None
        assert warnings == []

    def test_no_extractions_returns_empty_receipt_without_raising(self):
        receipt, decisions, warnings = reconcile_extractions([])

        assert receipt == ReceiptData()
        assert warnings


class TestLineItemReconciliation:
    def test_matching_items_across_engines_merge_by_description_similarity(self):
        text_a = "Shop\nBack Cover 1 200.00 200.00\n"
        text_b = "Shop\nBack Covr 1 200.00 200.00\n"  # OCR typo, same row
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, _, _ = reconcile_extractions(extractions)

        assert len(receipt.items) == 1
        assert receipt.items[0].amount == 200.0
        assert receipt.items[0].confidence is not None

    def test_item_only_detected_by_one_engine_is_still_kept(self):
        text_a = "Shop\nWidget A 1 10.00 10.00\nWidget B 1 20.00 20.00\n"
        text_b = "Shop\nWidget A 1 10.00 10.00\n"  # missed the second row
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, _, _ = reconcile_extractions(extractions)

        descriptions = {i.description for i in receipt.items}
        assert "Widget A" in descriptions
        assert any("Widget B" in d for d in descriptions if d)

    def test_position_drift_from_a_dropped_row_still_merges_via_containment(self):
        # Regression: measured on a real receipt. Tesseract dropped the
        # FIRST item entirely, shifting every later item's index down by
        # one relative to EasyOCR -- so the same-position fast path no
        # longer applies to any of them, and the strict text-only
        # threshold (0.85) is too high to merge legitimate OCR variants
        # like "Sugac" / "Sugac kg" (~0.77) or "Tea Powder" / "Tea Powder
        # 250,gm" (~0.74). Before the fix, these rows stayed unmerged and
        # duplicated, with the wrong (Tesseract) amount surviving instead
        # of being reconciled against EasyOCR's correct one.
        text_a = (  # Tesseract: missed "Rice", everything else shifted
            "Shop\nToor Dal 1 120.00 120.00\nSugac 2 45.00 90.00\n"
            "Tea Powder 250,gm 90.00 40.00\n"
        )
        text_b = (  # EasyOCR: has all rows, correct Tea Powder amount
            "Shop\nRice Sona Masoori) 60.00 300.00\nToor Dal 120.00 120.00\n"
            "Sugac kg 45.00 90.00\nTea Powder 250.0 90.00 90.00\n"
        )
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, _, _ = reconcile_extractions(extractions)

        descriptions = [i.description for i in receipt.items]
        # "Sugac" and "Sugac kg" must merge into ONE row, not two.
        sugac_rows = [d for d in descriptions if d and "sugac" in d.lower()]
        assert len(sugac_rows) == 1
        # "Tea Powder" and "Tea Powder 250,gm" must merge into ONE row.
        tea_rows = [d for d in descriptions if d and "tea powder" in d.lower()]
        assert len(tea_rows) == 1
        # The two engines' OWN amounts for this row genuinely disagree
        # (40.0 vs 90.0 -- Tesseract's is itself OCR-corrupted), so once
        # merged into a single row the reconciled amount must be null
        # with a disagreement warning -- never silently pick one side.
        # The fix under test is that they merge into ONE row at all,
        # rather than surviving as two separate unmerged rows (which
        # would silently keep the wrong value with no disagreement
        # warning at all).
        tea_item = next(i for i in receipt.items if i.description and "tea powder" in i.description.lower())
        assert tea_item.amount is None
        assert any("amount_disagreement" in w for w in tea_item.warnings)

    def test_disagreeing_item_quantity_across_engines_is_nulled_with_warning(self):
        text_a = "Shop\nBack Cover 4 200.00 200.00\n"
        text_b = "Shop\nBack Cover 1 200.00 200.00\n"
        extractions = [
            engine_extraction("tesseract", text_a),
            engine_extraction("easyocr", text_b),
        ]
        receipt, _, warnings = reconcile_extractions(extractions)

        assert receipt.items[0].quantity is None
        assert any("quantity_disagreement" in w for w in receipt.items[0].warnings)


class TestMultiEngineProcessReceipts:
    def _make_receipt_image(self, path: Path) -> None:
        img = Image.new("L", (400, 200), color=255)
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "TEST STORE", fill=0)
        draw.text((10, 40), "Total 100.00", fill=0)
        img.save(path)

    def test_two_agreeing_fake_engines_reconcile_successfully(self, tmp_path: Path):
        image_path = tmp_path / "r.png"
        self._make_receipt_image(image_path)
        text = "TEST STORE\nTotal 100.00\n"
        engines = [FakeEngine("engineA", text), FakeEngine("engineB", text)]

        result = process_receipt(image_path, tmp_path / "out", ocr_engines=engines)

        assert result.success is True
        assert result.reconciliation_performed is True
        assert set(result.engines_used) == {"engineA", "engineB"}
        assert result.receipt.total == 100.0

    def test_one_crashing_engine_does_not_break_the_other(self, tmp_path: Path):
        image_path = tmp_path / "r.png"
        self._make_receipt_image(image_path)
        text = "TEST STORE\nTotal 100.00\n"
        engines = [FakeEngine("engineA", text), CrashingEngine()]

        result = process_receipt(image_path, tmp_path / "out", ocr_engines=engines)

        assert result.success is True
        assert "engineA" in result.engines_used
        assert any("engine_failed" in w for w in result.warnings)

    def test_all_engines_failing_reports_failure_not_a_crash(self, tmp_path: Path):
        image_path = tmp_path / "r.png"
        self._make_receipt_image(image_path)

        result = process_receipt(image_path, tmp_path / "out", ocr_engines=[CrashingEngine()])

        assert result.success is False
        assert result.error is not None

    def test_backward_compatible_single_engine_api_unchanged(self, tmp_path: Path):
        # The original ocr_engine= (singular) parameter must still work
        # exactly as before -- no reconciliation, no behavior change.
        image_path = tmp_path / "r.png"
        self._make_receipt_image(image_path)
        engine = FakeEngine("solo", "TEST STORE\nTotal 100.00\n")

        result = process_receipt(image_path, tmp_path / "out", ocr_engine=engine)

        assert result.success is True
        assert result.reconciliation_performed is False
        assert result.receipt.total == 100.0

    def test_multiple_images_each_get_independent_results(self, tmp_path: Path):
        path1 = tmp_path / "r1.png"
        path2 = tmp_path / "r2.png"
        self._make_receipt_image(path1)
        self._make_receipt_image(path2)
        engines = [
            FakeEngine("engineA", "STORE ONE\nTotal 100.00\n"),
            FakeEngine("engineB", "STORE ONE\nTotal 100.00\n"),
        ]

        results = process_receipts([path1, path2], tmp_path / "out", ocr_engines=engines)

        assert len(results) == 2
        assert results[0].source == "r1.png"
        assert results[1].source == "r2.png"

    def test_result_is_json_serializable_including_reconciliation_fields(self, tmp_path: Path):
        image_path = tmp_path / "r.png"
        self._make_receipt_image(image_path)
        text = "TEST STORE\nTotal 100.00\n"
        engines = [FakeEngine("engineA", text), FakeEngine("engineB", text)]

        result = process_receipt(image_path, tmp_path / "out", ocr_engines=engines)
        data = result.to_dict()

        assert data["engines_used"] == ["engineA", "engineB"]
        assert data["reconciliation_performed"] is True
        assert isinstance(data["field_decisions"], dict)
        assert "total" in data["field_decisions"]
        assert data["field_decisions"]["total"]["value"] == 100.0

    def test_grouped_dict_contract_matches_requested_shape(self, tmp_path: Path):
        image_path = tmp_path / "r.png"
        self._make_receipt_image(image_path)
        text = "TEST STORE\nTotal 100.00\n"
        engines = [FakeEngine("engineA", text), FakeEngine("engineB", text)]

        result = process_receipt(image_path, tmp_path / "out", ocr_engines=engines)
        grouped = result.to_grouped_dict()

        assert set(grouped) >= {
            "source", "success", "document", "financials", "items", "payment",
            "quality", "validation", "provenance", "raw_ocr",
        }
        assert grouped["financials"]["total"] == 100.0
        assert grouped["provenance"]["engines_used"] == ["engineA", "engineB"]
        assert grouped["provenance"]["reconciliation_performed"] is True
