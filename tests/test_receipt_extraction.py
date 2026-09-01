"""
Tests for `receipt_extraction`.

All tests construct `OcrResult` directly (no real OCR call, no external
API, no network) so they are deterministic and fast, and exercise
`extract_from_ocr` + `validate_receipt` in isolation from the OCR engines
-- exactly the decoupling the extraction layer is designed around.

`process_receipts` (which does call a real OcrEngine) is covered by one
integration test using the existing `TesseractOcrEngine` on a tiny
synthetic image, skipped if Tesseract is not installed on the machine
running the tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ocr.engine import OcrResult
from receipt_extraction import (
    ExtractionResult,
    LineItem,
    ReceiptData,
    extract_from_ocr,
    process_receipt,
    process_receipts,
    validate_receipt,
)


def make_ocr(text: str, confidence: float | None = 70.0, success: bool = True,
             error: str | None = None) -> OcrResult:
    return OcrResult(
        filename="test.png", success=success, engine="tesseract-test",
        text=text, mean_confidence=confidence, word_count=len(text.split()),
        error=error,
    )


CLEAN_PRINTED_TEXT = """Green Leaf Supermarket
Invoice No: INV-1023
Date: 30/08/2026

Notebook          2   40.00   80.00
Pen                5   10.00   50.00

Subtotal 130.00
Discount 10.00
GST 6.50
Grand Total 126.50
"""

HANDWRITTEN_TEXT = """Sudha Tailors
No. 385  Date: 26/04/22

Saree Fall          100
Blouse Stitching     300
Total 830/-
"""


class TestExtractFromOcr:
    def test_clean_printed_receipt_extracts_full_structure(self):
        result = extract_from_ocr(make_ocr(CLEAN_PRINTED_TEXT, confidence=85.0))

        assert result.success is True
        assert result.receipt.vendor_name == "Green Leaf Supermarket"
        assert result.receipt.invoice_number == "INV-1023"
        assert result.receipt.date == "2026-08-30"
        assert result.receipt.document_type == "invoice"
        assert result.receipt.subtotal == 130.0
        assert result.receipt.discount == 10.0
        assert result.receipt.tax == 6.5
        assert result.receipt.total == 126.5
        assert len(result.receipt.items) == 2
        assert result.receipt.items[0].description == "Notebook"
        assert result.receipt.items[0].quantity == 2
        assert result.receipt.items[0].unit_price == 40.0
        assert result.receipt.items[0].amount == 80.0
        assert "low_ocr_confidence" not in result.warnings

    def test_handwritten_receipt_extracts_available_fields_without_hallucinating(self):
        result = extract_from_ocr(make_ocr(HANDWRITTEN_TEXT, confidence=45.0))

        assert result.success is True
        assert result.receipt.vendor_name == "Sudha Tailors"
        assert result.receipt.receipt_number == "385"
        assert result.receipt.date == "2022-04-26"
        assert result.receipt.total == 830.0
        # No unit price/quantity structure in this text -> must stay None,
        # not guessed at.
        assert result.receipt.subtotal is None
        assert result.receipt.tax is None

    def test_missing_fields_stay_none_rather_than_guessed(self):
        result = extract_from_ocr(make_ocr("Thank You! Visit Again", confidence=60.0))

        assert result.receipt.total is None
        assert result.receipt.invoice_number is None
        assert result.receipt.items == []

    def test_malformed_numeric_amount_is_not_silently_coerced(self):
        # "4a50/-5" is a real corrupted OCR token observed in this project's
        # earlier phases. It must not become 450 or 4.5 -- it must fail to
        # parse and be absent.
        text = "Total 4a50/-5\n"
        result = extract_from_ocr(make_ocr(text, confidence=30.0))

        assert result.receipt.total is None
        assert "total_line_found_but_amount_unparseable" in result.warnings

    def test_multiple_line_items_with_discount_and_tax(self):
        text = (
            "ABC Traders\n"
            "Rice 5kg    1   350.00   350.00\n"
            "Sugar 1kg   2    45.00    90.00\n"
            "Subtotal 440.00\n"
            "Discount 20.00\n"
            "GST 8.00\n"
            "Total 428.00\n"
        )
        result = extract_from_ocr(make_ocr(text, confidence=75.0))

        assert len(result.receipt.items) == 2
        assert result.receipt.subtotal == 440.0
        assert result.receipt.discount == 20.0
        assert result.receipt.tax == 8.0
        assert result.receipt.total == 428.0

    def test_total_before_discount_is_not_treated_as_final_payable_total(self):
        # Regression test for a real bug found during E2E verification:
        # "Total 430.00" / "Discount 20.00" / "410.00" was silently
        # returning total=430.0 (the pre-discount figure) because the
        # unlabeled 410.00 line has no keyword to attach to. The correct
        # behavior is to recognize that a labeled "Total" followed by a
        # discount/tax line cannot be the final payable amount, reclassify
        # it as subtotal, and mark total as unknown rather than wrong.
        text = (
            "Vijay Book Depot\n"
            "Classmate Notebook 5 40.00 200.00\n"
            "Total 430.00\n"
            "Discount 20.00\n"
            "410.00\n"
        )
        result = extract_from_ocr(make_ocr(text, confidence=80.0))

        assert result.receipt.total is None
        assert result.receipt.subtotal == 430.0
        assert any("total_line_precedes_discount_or_tax_adjustment" in w for w in result.warnings)

    def test_underscore_in_id_label_does_not_block_bill_number_detection(self):
        # Generalization regression: the underscore-normalization fix
        # (originally applied only to financial keywords) must also apply
        # to id/date/document-type scanning. "Bill No_ 1198" mirrors a
        # real OCR artifact seen on an external, unseen receipt used only
        # as a regression trigger -- no vendor name, date, or price from
        # that receipt is referenced anywhere in this test or the
        # implementation.
        text = "Some Store\nBill No_ 9042 Date: 01/01/25\n"
        result = extract_from_ocr(make_ocr(text, confidence=60.0))

        assert result.receipt.receipt_number == "9042"
        assert result.receipt.date == "2025-01-01"

    def test_fuzzy_keyword_recovers_single_letter_ocr_corruption(self):
        # "Grand Totol"/"Discoumt" are exactly the kind of single-letter
        # OCR substitution the fuzzy fallback exists for -- generic to any
        # receipt with this corruption pattern, not tied to one vendor.
        # Uses "Grand Totol" (rather than a plain "Totol") so the result
        # is not also subject to the separate total-before-discount
        # reclassification rule, keeping this test isolated to the fuzzy
        # match behavior specifically.
        text = "Discoumt 50.00\nGrand Totol 500.00\n"
        result = extract_from_ocr(make_ocr(text, confidence=55.0))

        assert result.receipt.total == 500.0
        assert result.receipt.discount == 50.0
        assert any("matched_via_fuzzy_keyword" in w for w in result.warnings)

    def test_fuzzy_keyword_does_not_force_a_match_on_severe_corruption(self):
        # "tert" is too corrupted (similarity ~0.44) to safely resolve as
        # "total" -- must stay None rather than guess. This is the
        # deliberate boundary: some OCR damage is unrecoverable and must
        # be reported as unknown, not forced through.
        text = "Some Store\ntert 5800/-\n"
        result = extract_from_ocr(make_ocr(text, confidence=40.0))

        assert result.receipt.total is None

    def test_alphabetic_garbage_is_not_published_as_a_receipt_number(self):
        # Regression, found on a HELD-OUT receipt: a corrupted "No." was
        # captured as receipt_number "Ne" -- a two-letter word published
        # as a financial-document identifier. An identifier must contain
        # at least one digit; otherwise null (unknown) is the safe answer.
        text = "Fresh Fruits Mart\nNo: Ne\nGrand Total 350.00\n"
        result = extract_from_ocr(make_ocr(text, confidence=60.0))

        assert result.receipt.receipt_number is None
        assert result.receipt.total == 350.0  # the rest still extracts

    def test_alphanumeric_identifiers_are_still_accepted(self):
        # The digit requirement must not reject real-world mixed schemes.
        for raw, expected in (
            ("Invoice No: INV-500", "INV-500"),
            ("Invoice No: 2024/A/17", "2024/A/17"),
        ):
            result = extract_from_ocr(make_ocr(f"Shop\n{raw}\n", confidence=70.0))
            assert result.receipt.invoice_number == expected, raw

    def test_underscore_glued_to_keyword_does_not_block_detection(self):
        # Regression test for a real bug found during E2E verification on
        # batch2_invoice_004: Tesseract rendered an underlined table cell
        # as "Grand Total_| 685.00" and "Discount__|_15.00" -- the "_"
        # breaks \bTotal\b's word boundary, so the keyword silently failed
        # to match and both fields were dropped even though the numbers
        # were perfectly legible.
        text = (
            "Total 700.00\n"
            "Discount__|_15.00\n"
            "Grand Total_| 685.00\n"
        )
        result = extract_from_ocr(make_ocr(text, confidence=63.0))

        assert result.receipt.discount == 15.0
        assert result.receipt.total == 685.0

    def test_grand_total_after_discount_is_still_used_normally(self):
        # Ensures the fix does not disturb the already-working case where
        # a proper "Grand Total" line follows the discount.
        text = (
            "Total 430.00\n"
            "Discount 20.00\n"
            "Grand Total 410.00\n"
        )
        result = extract_from_ocr(make_ocr(text, confidence=80.0))

        assert result.receipt.total == 410.0

    def test_uncertain_ocr_result_is_flagged_low_confidence(self):
        result = extract_from_ocr(make_ocr(CLEAN_PRINTED_TEXT, confidence=25.0))

        assert "low_ocr_confidence" in result.warnings
        # Structure can still be present -- low confidence is a flag, not a
        # reason to discard already-parsed fields.
        assert result.receipt.total == 126.5

    def test_extraction_confidence_is_lower_when_ocr_confidence_is_lower(self):
        # Same extractable structure, different OCR confidence -> the
        # lower-OCR-confidence case must score lower. Per the project
        # requirement, OCR confidence alone must not be treated as the
        # extraction score, but it must still be a FACTOR in it.
        high_ocr = extract_from_ocr(make_ocr(CLEAN_PRINTED_TEXT, confidence=90.0))
        low_ocr = extract_from_ocr(make_ocr(CLEAN_PRINTED_TEXT, confidence=45.0))

        assert low_ocr.extraction_confidence < high_ocr.extraction_confidence

    def test_high_ocr_confidence_with_almost_no_structure_scores_low(self):
        # Regression for the previously-observed "invoice_087" pattern:
        # very high OCR confidence but almost nothing usable extracted
        # must NOT translate into a high extraction confidence.
        result = extract_from_ocr(make_ocr("Thank You !", confidence=95.0))

        assert result.extraction_confidence < 20.0

    def test_validation_warnings_reduce_extraction_confidence(self):
        # A mismatch found only by the VALIDATOR (after extraction already
        # ran) must still lower extraction_confidence -- confirms the two
        # stages are wired together, not independent.
        mismatched = extract_from_ocr(make_ocr(
            "ABC Store\nWidget 2 40.00 100.00\n", confidence=80.0
        ))
        clean = extract_from_ocr(make_ocr(
            "ABC Store\nWidget 2 40.00 80.00\n", confidence=80.0
        ))
        validate_receipt(mismatched)
        validate_receipt(clean)

        assert any("amount_mismatch" in w for w in mismatched.warnings)
        assert not any("amount_mismatch" in w for w in clean.warnings)
        assert mismatched.extraction_confidence < clean.extraction_confidence

    def test_completely_unreadable_ocr_result_returns_empty_receipt_not_failure(self):
        result = extract_from_ocr(make_ocr("", confidence=None))

        assert result.success is True
        assert result.receipt == ReceiptData()
        assert result.extraction_confidence == 0.0
        assert "insufficient_text_for_extraction" in result.warnings

    def test_failed_ocr_produces_failed_extraction_result(self):
        result = extract_from_ocr(make_ocr("", success=False, confidence=None, error="engine crashed"))

        assert result.success is False
        assert result.error == "engine crashed"
        assert result.receipt.total is None
        assert "ocr_failed" in result.warnings

    def test_result_is_json_serializable_dict(self):
        result = extract_from_ocr(make_ocr(CLEAN_PRINTED_TEXT, confidence=85.0))
        data = result.to_dict()

        assert data["vendor_name"] == "Green Leaf Supermarket"
        assert data["total"] == 126.5
        assert isinstance(data["items"], list)
        assert data["items"][0]["description"] == "Notebook"


class TestValidateReceipt:
    def test_flags_amount_mismatch_without_correcting_it(self):
        receipt = ReceiptData(items=[LineItem(description="X", quantity=2, unit_price=40.0, amount=100.0)])
        result = ExtractionResult(source="t.png", success=True, receipt=receipt)

        validate_receipt(result)

        assert any("amount_mismatch" in w for w in result.warnings)
        # Value must remain exactly as extracted -- validators never "fix".
        assert result.receipt.items[0].amount == 100.0

    def test_flags_totals_inconsistency(self):
        receipt = ReceiptData(subtotal=100.0, discount=10.0, tax=5.0, total=200.0)
        result = ExtractionResult(source="t.png", success=True, receipt=receipt)

        validate_receipt(result)

        assert any("total_inconsistent_with_subtotal_discount_tax" in w for w in result.warnings)

    def test_consistent_totals_produce_no_warning(self):
        receipt = ReceiptData(subtotal=100.0, discount=10.0, tax=5.0, total=95.0)
        result = ExtractionResult(source="t.png", success=True, receipt=receipt)

        validate_receipt(result)

        assert not any("total_inconsistent" in w for w in result.warnings)

    def test_flags_non_positive_quantity(self):
        receipt = ReceiptData(items=[LineItem(description="X", quantity=0, amount=10.0)])
        result = ExtractionResult(source="t.png", success=True, receipt=receipt)

        validate_receipt(result)

        assert "item_0_non_positive_quantity" in result.warnings

    def test_flags_malformed_date_without_raising(self):
        receipt = ReceiptData()
        result = ExtractionResult(source="t.png", success=True, receipt=receipt)
        result.receipt.date = "not-a-date"

        validate_receipt(result)

        assert "malformed_date" in result.warnings

    def test_skips_validation_entirely_when_extraction_failed(self):
        result = ExtractionResult(source="t.png", success=False, error="boom")

        returned = validate_receipt(result)

        assert returned is result
        assert result.warnings == []


class TestProcessReceiptsIntegration:
    """One real end-to-end pass through preprocessing + OCR + extraction."""

    def test_single_and_multiple_images_via_real_pipeline(self, tmp_path: Path):
        pytest.importorskip("pytesseract")
        from ocr.tesseract_engine import TesseractNotAvailableError, _resolve_tesseract_cmd

        try:
            _resolve_tesseract_cmd()
        except TesseractNotAvailableError:
            pytest.skip("Tesseract binary not installed on this machine")

        path1 = tmp_path / "receipt1.png"
        path2 = tmp_path / "receipt2.png"
        for path in (path1, path2):
            img = Image.new("L", (400, 200), color=255)
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "TEST STORE", fill=0)
            draw.text((10, 40), "Total 100.00", fill=0)
            img.save(path)

        single = process_receipt(path1, tmp_path / "out")
        assert isinstance(single, ExtractionResult)
        assert single.source == "receipt1.png"

        multiple = process_receipts([path1, path2], tmp_path / "out")
        assert len(multiple) == 2
        assert [r.source for r in multiple] == ["receipt1.png", "receipt2.png"]
        for r in multiple:
            assert r.success is True
            assert r.ocr_engine.startswith("tesseract")

    def test_missing_image_does_not_raise_and_reports_failure(self, tmp_path: Path):
        [result] = process_receipts([tmp_path / "missing.png"], tmp_path / "out")

        assert result.success is False
        assert result.error is not None
