"""
Tests for the spatial layout module, the confidence/review model, and the
regression fixes found during ground-truth benchmarking.

All deterministic: `OcrToken`s are constructed directly, so nothing depends
on a real OCR engine, model download, or network.
"""

from __future__ import annotations

from ocr.engine import OcrResult, OcrToken
from receipt_extraction import (
    ExtractionResult,
    LineItem,
    ReceiptData,
    extract_from_ocr,
    finalize_confidence,
    validate_receipt,
)
from receipt_extraction.confidence import (
    compute_overall_confidence,
    compute_validation_confidence,
)
from receipt_extraction.layout import (
    group_tokens_into_rows,
    infer_column_bands_from_alignment,
    detect_column_bands,
    find_label_value_on_row,
)


def tok(text, left, top, width=40, height=12, conf=90.0) -> OcrToken:
    return OcrToken(text=text, confidence=conf, left=left, top=top, width=width, height=height)


class TestRowGrouping:
    def test_tokens_at_similar_y_group_into_one_row(self):
        tokens = [tok("A", 10, 100), tok("B", 60, 102), tok("C", 120, 101)]

        rows = group_tokens_into_rows(tokens)

        assert len(rows) == 1
        assert rows[0].text == "A B C"

    def test_tokens_at_different_y_form_separate_rows(self):
        tokens = [tok("A", 10, 100), tok("B", 10, 200)]

        assert len(group_tokens_into_rows(tokens)) == 2

    def test_row_tokens_are_ordered_left_to_right(self):
        # Input deliberately out of order: reading order must come from
        # geometry, not from the order the engine happened to emit.
        tokens = [tok("third", 200, 100), tok("first", 10, 100), tok("second", 100, 100)]

        assert group_tokens_into_rows(tokens)[0].text == "first second third"

    def test_empty_input_is_safe(self):
        assert group_tokens_into_rows([]) == []


class TestColumnDetection:
    def test_header_row_defines_column_bands(self):
        tokens = [
            tok("Particulars", 20, 50), tok("Qty", 200, 50),
            tok("Rate", 300, 50), tok("Amount", 400, 50),
        ]

        bands = {b.name for b in detect_column_bands(group_tokens_into_rows(tokens))}

        assert {"description", "quantity", "unit_price", "amount"} <= bands

    def test_single_keyword_row_is_not_treated_as_header(self):
        # A lone "Total" appears in summary rows; it must not seed columns.
        tokens = [tok("Total", 300, 400), tok("500.00", 420, 400)]

        assert detect_column_bands(group_tokens_into_rows(tokens)) == []

    def test_columns_inferred_from_numeric_alignment_without_header(self):
        # Measured on the real dataset: Tesseract often fails to recognise
        # the header line at all, so column inference must work from the
        # aligned data rows alone.
        tokens = []
        for row_index, y in enumerate((100, 130, 160)):
            tokens.append(tok(f"Item{row_index}", 20, y, width=80))
            tokens.append(tok("2", 200, y, width=15))
            tokens.append(tok("50.00", 300, y, width=45))
            tokens.append(tok("100.00", 400, y, width=50))

        bands = {b.name for b in infer_column_bands_from_alignment(group_tokens_into_rows(tokens))}

        assert "amount" in bands
        assert "unit_price" in bands
        assert "quantity" in bands

    def test_too_few_rows_yields_no_inferred_columns(self):
        tokens = [tok("Item", 20, 100), tok("5", 200, 100), tok("10.00", 300, 100)]

        assert infer_column_bands_from_alignment(group_tokens_into_rows(tokens)) == []


class TestLabelValueAssociation:
    def test_label_and_value_on_same_row_are_associated(self):
        # The explicit requirement: "Grand Total" at x=500 and "1121.00" at
        # x=700 belong together regardless of text ordering.
        import re
        tokens = [tok("Grand", 480, 700), tok("Total", 540, 700), tok("1121.00", 700, 700)]

        found = find_label_value_on_row(
            group_tokens_into_rows(tokens), re.compile(r"grand\s*total", re.IGNORECASE)
        )

        assert found is not None
        _, numerics = found
        assert any(t.text == "1121.00" for t in numerics)

    def test_numeric_left_of_label_is_not_taken_as_its_value(self):
        import re
        tokens = [tok("999.00", 100, 700), tok("Total", 400, 700), tok("500.00", 600, 700)]

        _, numerics = find_label_value_on_row(
            group_tokens_into_rows(tokens), re.compile(r"total", re.IGNORECASE)
        )

        assert [t.text for t in numerics] == ["500.00"]


class TestConfidenceModel:
    def test_validation_confidence_is_none_when_nothing_checkable(self):
        result = ExtractionResult(source="x.png", success=True, receipt=ReceiptData())

        assert compute_validation_confidence(result) is None

    def test_validation_confidence_detects_failed_arithmetic(self):
        receipt = ReceiptData(
            items=[LineItem(description="A", quantity=2, unit_price=40.0, amount=100.0)]
        )
        result = ExtractionResult(source="x.png", success=True, receipt=receipt)

        assert compute_validation_confidence(result) == 0.0

    def test_validation_confidence_full_when_arithmetic_holds(self):
        receipt = ReceiptData(
            items=[LineItem(description="A", quantity=2, unit_price=40.0, amount=80.0)]
        )
        result = ExtractionResult(source="x.png", success=True, receipt=receipt)

        assert compute_validation_confidence(result) == 100.0

    def test_overall_confidence_is_capped_by_failed_validation(self):
        # High extraction completeness must NOT produce high overall
        # confidence when the arithmetic disagrees.
        result = ExtractionResult(source="x.png", success=True)
        result.extraction_confidence = 90.0
        result.validation_confidence = 0.0

        assert compute_overall_confidence(result) == 0.0

    def test_needs_review_set_when_total_missing(self):
        result = extract_from_ocr(OcrResult(
            filename="x.png", success=True, engine="test",
            text="Some Shop\nSomething 5 10.00 50.00\n", mean_confidence=80.0,
        ))
        validate_receipt(result)
        finalize_confidence(result)

        assert result.needs_review is True
        assert "total_not_extracted" in result.review_reasons

    def test_needs_review_reports_arithmetic_failure(self):
        result = extract_from_ocr(OcrResult(
            filename="x.png", success=True, engine="test",
            text="Shop\nWidget 2 40.00 100.00\nGrand Total 100.00\n", mean_confidence=85.0,
        ))
        validate_receipt(result)
        finalize_confidence(result)

        assert result.needs_review is True
        assert any("mismatch" in r or "arithmetic" in r for r in result.review_reasons)

    def test_failed_result_needs_review_without_crashing(self):
        result = ExtractionResult(source="x.png", success=False, error="boom")

        finalize_confidence(result)

        assert result.needs_review is True
        assert result.review_reasons == ["processing_failed"]


class TestPhantomRowRegression:
    def test_corrupted_summary_label_does_not_become_a_line_item(self):
        # Regression: OCR read "Discount 10.00" as "Diseamtt 10.00", which
        # became a FABRICATED line item carrying real money. When the
        # receipt clearly has a structured table, a lone single-amount row
        # must be dropped rather than emitted as an item.
        text = (
            "Some Store\n"
            "Widget A 2 50.00 100.00\n"
            "Widget B 1 30.00 30.00\n"
            "Diseamtt 10.00\n"
        )
        result = extract_from_ocr(OcrResult(
            filename="x.png", success=True, engine="test",
            text=text, mean_confidence=70.0,
        ))

        descriptions = [i.description for i in result.receipt.items]
        assert not any("Diseamtt" in (d or "") for d in descriptions)
        assert len(result.receipt.items) == 2

    def test_single_amount_rows_kept_when_no_structured_table_exists(self):
        # A receipt with no qty/rate columns at all: single-amount rows are
        # the only item evidence available, so they must be preserved.
        text = "Salon\nHair Cut 250\nThreading 100\n"
        result = extract_from_ocr(OcrResult(
            filename="x.png", success=True, engine="test",
            text=text, mean_confidence=70.0,
        ))

        assert len(result.receipt.items) == 2

    def test_row_index_with_bracket_separator_is_stripped(self):
        # Regression: OCR renders the serial-number cell rule as "]" (e.g.
        # "4] Wire ..."), which previously failed the item regex outright
        # and silently dropped a real row.
        text = "Store\n4] Wire 1.5 sq.mm 20mtr 18.00 360.00\n"
        result = extract_from_ocr(OcrResult(
            filename="x.png", success=True, engine="test",
            text=text, mean_confidence=70.0,
        ))

        assert result.receipt.items
        assert result.receipt.items[0].amount == 360.0


class TestTokensFlowThrough:
    def test_tokens_absent_falls_back_to_text_extraction(self):
        result = extract_from_ocr(OcrResult(
            filename="x.png", success=True, engine="test",
            text="Shop\nGrand Total 500.00\n", mean_confidence=80.0, tokens=[],
        ))

        assert result.receipt.total == 500.0
        assert "no_token_geometry_available_text_only_extraction" in result.warnings
