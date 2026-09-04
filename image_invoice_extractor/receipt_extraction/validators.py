"""
validators
============

Post-extraction sanity checks. Every check here APPENDS a warning to
`ExtractionResult.warnings` -- none of them "correct", rescale, or replace
a value. This is deliberate: a validator that silently fixes a suspicious
number would reintroduce exactly the risk this project has spent multiple
phases measuring (OCR confidently returning a plausible-but-wrong digit).
Flagging is the only safe action available without a second, independent
source of truth.

Tolerances below are intentionally loose (a few percent / a few rupees)
because every input number here already passed through OCR and regex
parsing; a tight tolerance would mostly just flag OCR/rounding noise
rather than genuine data problems.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import ExtractionResult

_AMOUNT_TOLERANCE_ABS = 1.0  # rupees
_AMOUNT_TOLERANCE_REL = 0.02  # 2%
_MAX_REASONABLE_TOTAL = 10_000_000.0
_FUTURE_DATE_GRACE_DAYS = 3


def _approx_equal(a: float, b: float) -> bool:
    return abs(a - b) <= max(_AMOUNT_TOLERANCE_ABS, abs(b) * _AMOUNT_TOLERANCE_REL)


def validate_receipt(result: ExtractionResult) -> ExtractionResult:
    """
    Run all checks against `result.receipt` and return the SAME result
    with additional warnings appended (mutates and returns `result` for
    convenient chaining: `validate_receipt(extract_from_ocr(...))`).

    No field on `result.receipt` is ever changed.
    """
    if not result.success:
        return result

    receipt = result.receipt
    warnings = result.warnings

    _check_line_items(receipt, warnings)
    _check_amount_consistency(receipt, warnings)
    _check_totals_consistency(receipt, warnings)
    _check_date(receipt, warnings)
    _check_total_magnitude(receipt, warnings)

    # Recompute extraction_confidence now that validation's own warnings
    # (mismatches/inconsistencies) are part of `result.warnings` -- see
    # `extractor.recompute_extraction_confidence`. Imported lazily to
    # avoid a circular import (extractor imports validate_receipt).
    from .extractor import recompute_extraction_confidence
    recompute_extraction_confidence(result)

    return result


def _check_line_items(receipt, warnings: list[str]) -> None:
    for index, item in enumerate(receipt.items):
        if item.quantity is not None and item.quantity <= 0:
            warnings.append(f"item_{index}_non_positive_quantity")
        if item.unit_price is not None and item.unit_price < 0:
            warnings.append(f"item_{index}_negative_unit_price")
        if item.amount is not None and item.amount < 0:
            warnings.append(f"item_{index}_negative_amount")


def _check_amount_consistency(receipt, warnings: list[str]) -> None:
    """quantity * unit_price should roughly equal amount, when all three exist."""
    for index, item in enumerate(receipt.items):
        if item.quantity is None or item.unit_price is None or item.amount is None:
            continue
        expected = item.quantity * item.unit_price
        if not _approx_equal(expected, item.amount):
            warnings.append(
                f"item_{index}_amount_mismatch:expected~{round(expected, 2)}_got_{item.amount}"
            )


def _check_totals_consistency(receipt, warnings: list[str]) -> None:
    """subtotal - discount + tax should roughly equal total, when available."""
    if receipt.subtotal is None or receipt.total is None:
        return

    expected = receipt.subtotal - (receipt.discount or 0.0) + (receipt.tax or 0.0)
    if not _approx_equal(expected, receipt.total):
        warnings.append(
            f"total_inconsistent_with_subtotal_discount_tax:"
            f"expected~{round(expected, 2)}_got_{receipt.total}"
        )

    if receipt.items:
        items_sum = sum(item.amount for item in receipt.items if item.amount is not None)
        counted = sum(1 for item in receipt.items if item.amount is not None)
        if counted == len(receipt.items) and not _approx_equal(items_sum, receipt.subtotal):
            warnings.append(
                f"subtotal_inconsistent_with_line_items:"
                f"items_sum~{round(items_sum, 2)}_subtotal_{receipt.subtotal}"
            )


def _check_total_magnitude(receipt, warnings: list[str]) -> None:
    if receipt.total is not None:
        if receipt.total < 0:
            warnings.append("negative_total")
        elif receipt.total > _MAX_REASONABLE_TOTAL:
            warnings.append("suspiciously_large_total")
        elif receipt.total == 0 and receipt.items:
            warnings.append("zero_total_with_line_items_present")


def _check_date(receipt, warnings: list[str]) -> None:
    if receipt.date is None:
        return
    try:
        parsed = date.fromisoformat(receipt.date)
    except ValueError:
        warnings.append("malformed_date")
        return

    if parsed > date.today() + timedelta(days=_FUTURE_DATE_GRACE_DAYS):
        warnings.append("date_in_future")
    if parsed.year < 2000:
        warnings.append("suspiciously_old_date")
