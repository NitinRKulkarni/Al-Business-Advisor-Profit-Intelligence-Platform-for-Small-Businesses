"""
confidence
============

Separate confidence signals plus the `needs_review` decision.

Design rule
-------------
OCR confidence is NOT correctness. This project has measured the
decoupling directly: one dataset image scored the highest OCR confidence
in the whole set (87.5) while recognising only three words. So no single
number here is allowed to stand in for reliability:

- `ocr_confidence`        - the engine's own token-level score.
- `extraction_confidence` - how much structure was recovered, scaled by
                            OCR quality and reduced by data-quality
                            warnings (computed in `extractor`).
- `validation_confidence` - fraction of applicable arithmetic cross-checks
                            that actually passed.
- `overall_confidence`    - conservative combination of the above.

`needs_review` is deliberately biased toward flagging: for this project a
wrong financial number is far worse than an unnecessary review request, so
any arithmetic mismatch, engine disagreement, or missing-total condition
raises it.
"""

from __future__ import annotations

from .models import ExtractionResult

# Warning substrings that indicate a genuine financial/data problem (as
# opposed to informational provenance notes like "located_spatially").
_REVIEW_WARNING_MARKERS: tuple[tuple[str, str], ...] = (
    ("mismatch", "financial_mismatch"),
    ("inconsistent", "financial_inconsistency"),
    ("disagreement", "engine_or_method_disagreement"),
    ("unparseable", "unparseable_financial_value"),
    ("malformed", "malformed_value"),
    ("negative", "negative_value"),
    ("suspicious", "suspicious_value"),
    ("low_ocr_confidence", "low_ocr_confidence"),
    ("insufficient_text", "insufficient_text"),
    ("fuzzy_keyword", "keyword_matched_only_fuzzily"),
)

_LOW_OVERALL_CONFIDENCE_THRESHOLD = 50.0


def compute_validation_confidence(result: ExtractionResult) -> float | None:
    """
    Fraction (0-100) of applicable arithmetic checks that passed.

    Returns None when no check was applicable (too few fields present) --
    distinct from 0.0, which means checks ran and every one failed. This
    mirrors the project-wide "don't report a number you cannot support"
    policy.
    """
    receipt = result.receipt
    checks_run = 0
    checks_failed = 0

    # Per-item quantity x unit_price ~= amount.
    for item in receipt.items:
        if item.quantity is None or item.unit_price is None or item.amount is None:
            continue
        checks_run += 1
        expected = item.quantity * item.unit_price
        if abs(expected - item.amount) > max(1.0, abs(item.amount) * 0.02):
            checks_failed += 1

    # subtotal - discount + tax ~= total.
    if receipt.subtotal is not None and receipt.total is not None:
        checks_run += 1
        expected = receipt.subtotal - (receipt.discount or 0.0) + (receipt.tax or 0.0)
        if abs(expected - receipt.total) > max(1.0, abs(receipt.total) * 0.02):
            checks_failed += 1

    # sum(item amounts) ~= subtotal (only when every item has an amount).
    item_amounts = [i.amount for i in receipt.items if i.amount is not None]
    if receipt.subtotal is not None and item_amounts and len(item_amounts) == len(receipt.items):
        checks_run += 1
        items_sum = sum(item_amounts)
        if abs(items_sum - receipt.subtotal) > max(1.0, abs(receipt.subtotal) * 0.02):
            checks_failed += 1

    if checks_run == 0:
        return None
    return round((checks_run - checks_failed) / checks_run * 100.0, 2)


def compute_overall_confidence(result: ExtractionResult) -> float:
    """
    Conservative combination of OCR, extraction and validation signals.

    Uses the MINIMUM of extraction and validation confidence as the base
    (rather than an average) so a receipt that parsed a lot of structure
    but failed its arithmetic cannot score highly -- the arithmetic
    failure is the more important fact for a financial consumer.
    """
    extraction = result.extraction_confidence or 0.0

    if result.validation_confidence is None:
        # No arithmetic could be checked. That is itself a reason for
        # caution, so extraction confidence is damped rather than trusted
        # at face value.
        return round(extraction * 0.8, 2)

    base = min(extraction, result.validation_confidence)
    # Small bonus when both signals agree and are healthy, so a fully
    # consistent receipt is distinguishable from a merely parseable one.
    if extraction >= 60 and result.validation_confidence >= 95:
        base = min(100.0, base + 5.0)
    return round(base, 2)


def assess_review_need(result: ExtractionResult) -> None:
    """
    Set `needs_review` / `review_reasons` in place.

    Biased toward flagging (see module docstring). Reasons are deduplicated
    and stable so downstream code can match on them.
    """
    reasons: list[str] = []

    if not result.success:
        result.needs_review = True
        result.review_reasons = ["processing_failed"]
        return

    for marker, reason in _REVIEW_WARNING_MARKERS:
        if any(marker in warning for warning in result.warnings):
            if reason not in reasons:
                reasons.append(reason)

    # A receipt with no recoverable total cannot be used for financial
    # analysis, so it needs a human regardless of other signals.
    if result.receipt.total is None:
        reasons.append("total_not_extracted")

    if result.receipt.date is None:
        reasons.append("date_not_extracted")

    if not result.receipt.items:
        reasons.append("no_line_items_extracted")

    if result.validation_confidence is not None and result.validation_confidence < 100.0:
        if "financial_mismatch" not in reasons:
            reasons.append("failed_arithmetic_check")

    if (result.overall_confidence or 0.0) < _LOW_OVERALL_CONFIDENCE_THRESHOLD:
        reasons.append("low_overall_confidence")

    result.review_reasons = reasons
    result.needs_review = bool(reasons)


def finalize_confidence(result: ExtractionResult) -> ExtractionResult:
    """
    Compute validation/overall confidence and the review signal, in order.
    Called after extraction and validation have both run.
    """
    if not result.success:
        assess_review_need(result)
        return result

    result.validation_confidence = compute_validation_confidence(result)
    result.overall_confidence = compute_overall_confidence(result)
    assess_review_need(result)
    return result
