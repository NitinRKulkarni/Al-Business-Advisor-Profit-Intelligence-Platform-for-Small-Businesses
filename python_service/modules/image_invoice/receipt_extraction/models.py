"""
models
=======

Typed, JSON-serializable data shapes for the extraction layer.

Design notes
-------------
- Every field that OCR could not reliably determine is `None`/empty,
  never a guessed/fabricated value -- mirrors the "don't invent a
  misleading value" policy already used throughout
  `image_processing.result` (e.g. `skew_angle: None` rather than a guess).
- `ReceiptData` deliberately does not assume a fixed field set applies to
  every document: `document_type` is a free-form best guess and every
  financial field is optional, because a delivery challan, a handwritten
  tailor's bill, and a printed cash memo do not share the same structure.
- Dataclasses (not dicts) so a downstream consumer gets IDE-checked field
  names, matching the pattern already used by
  `image_processing.result.PreprocessingResult` /
  `QualityAnalysisResult`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class LineItem:
    """One row of a receipt's item table."""

    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None

    # Populated only when this item passed through engine reconciliation
    # (see `receipt_extraction.reconciliation`). None for single-engine
    # extraction, matching the "don't invent a number" policy -- an
    # unreconciled item simply has no reconciliation-derived confidence.
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FieldDecision:
    """
    Reconciliation outcome for ONE field, recording not just the selected
    value but the evidence behind it.

    Why this exists
    -----------------
    "OCR confidence is not correctness" is a project-wide rule; the
    natural next question downstream consumers will ask is "why should I
    trust this value?" `FieldDecision` answers that per field: which
    engines produced what, whether they agreed, and why the final value
    was (or was not) selected. `source` is one of:
      "tesseract+easyocr"  - both engines agreed (within tolerance).
      "<engine-name>"      - only one engine produced a usable value.
      "arithmetic"         - engines disagreed, but validation arithmetic
                              (e.g. subtotal - discount + tax) identified
                              which candidate is actually consistent.
      "disagreement"       - engines disagreed and no evidence could
                              resolve it; `value` is None and `candidates`
                              lists what each engine said, for a human or
                              a future (e.g. Azure) pass to resolve.
      "none"                - neither engine produced a value.
    """

    value: object = None
    confidence: float = 0.0
    agreement: bool | None = None
    source: str = "none"
    candidates: list[dict] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "agreement": self.agreement,
            "source": self.source,
            "candidates": list(self.candidates),
            "reason": self.reason,
        }


@dataclass
class ReceiptData:
    """
    Structured fields extracted from one receipt/invoice's OCR text.

    Every field is optional. A field is left as its default (None / empty
    list) rather than guessed when the OCR text does not contain enough
    signal to determine it -- this is the extraction layer's equivalent of
    `QualityAnalysisResult`'s "no fallback estimate" policy.
    """

    document_type: str | None = None  # e.g. "receipt", "invoice", "delivery_challan"
    vendor_name: str | None = None
    customer_name: str | None = None
    invoice_number: str | None = None
    receipt_number: str | None = None
    date: str | None = None  # ISO 8601 (YYYY-MM-DD) when confidently parsed
    time: str | None = None
    currency: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    discount: float | None = None
    total: float | None = None
    payment_method: str | None = None
    items: list[LineItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


@dataclass
class EngineExtraction:
    """
    One engine's independent extraction pass over its own OCR text.

    Used only internally by the reconciliation layer (`reconciliation.py`)
    to compare candidates before producing the final merged `ReceiptData`.
    Not part of the public `ExtractionResult` contract.
    """

    engine: str
    ocr_confidence: float | None
    receipt: ReceiptData
    raw_text: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """
    Full per-image result returned to callers: OCR provenance +
    structured fields + confidence + warnings.

    This is the boundary object handed to the rest of the application
    (business analytics, UI). It never carries image arrays or engine
    internals -- only plain, JSON-serializable data, matching the existing
    `PreprocessingResult.to_dict()` / `OcrResult.to_dict()` convention.
    """

    source: str
    success: bool

    receipt: ReceiptData = field(default_factory=ReceiptData)

    raw_text: str = ""
    ocr_engine: str = ""
    ocr_confidence: float | None = None
    extraction_confidence: float | None = None

    # Fraction (0-100) of applicable financial cross-checks that passed.
    # None when there were not enough fields present to check anything --
    # deliberately distinct from 0.0, which means "checks ran and failed".
    validation_confidence: float | None = None

    # Combined signal for downstream consumers. Never a substitute for
    # reading `warnings`; see `confidence.compute_overall_confidence`.
    overall_confidence: float | None = None

    # True when a human should look at this receipt before its financial
    # data is trusted. The reasons list is machine-readable so the
    # downstream application can route/prioritise review.
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)

    # Preprocessing provenance, carried through from
    # `receipt_pipeline.process_receipt_images` so a caller can see what
    # was done to the image without a second lookup.
    operations_applied: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    # --- Multi-engine reconciliation provenance (all optional; empty
    # when only one engine ran, so single-engine callers are unaffected).
    engines_used: list[str] = field(default_factory=list)
    reconciliation_performed: bool = False
    raw_ocr_by_engine: dict[str, str] = field(default_factory=dict)
    field_decisions: dict[str, FieldDecision] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """
        Flatten to the plain dict shape described in the project's
        conceptual output contract (vendor_name/invoice_number/items/... at
        the top level, alongside source/success/raw_text/confidences).

        Kept flat and backward compatible: every field present before
        reconciliation was added still appears with the same name/shape.
        New reconciliation data is ADDITIVE (`field_decisions`,
        `engines_used`, `reconciliation_performed`, `raw_ocr_by_engine`),
        so an existing consumer reading only the old keys is unaffected.
        """
        data = {
            "source": self.source,
            "success": self.success,
            **self.receipt.to_dict(),
            "items": [item.to_dict() for item in self.receipt.items],
            "raw_text": self.raw_text,
            "ocr_engine": self.ocr_engine,
            "ocr_confidence": self.ocr_confidence,
            "extraction_confidence": self.extraction_confidence,
            "validation_confidence": self.validation_confidence,
            "overall_confidence": self.overall_confidence,
            "needs_review": self.needs_review,
            "review_reasons": list(self.review_reasons),
            "operations_applied": list(self.operations_applied),
            "warnings": list(self.warnings),
            "error": self.error,
            "engines_used": list(self.engines_used),
            "reconciliation_performed": self.reconciliation_performed,
            "raw_ocr_by_engine": dict(self.raw_ocr_by_engine),
            "field_decisions": {k: v.to_dict() for k, v in self.field_decisions.items()},
        }
        return data

    def to_grouped_dict(self) -> dict:
        """
        The nested/grouped contract requested for the DB handoff (document/
        financials/items/payment/quality/validation/provenance/raw_ocr
        sections), built from the SAME data as `to_dict()` -- no duplicate
        extraction logic, just a different JSON shape for a consumer that
        prefers grouped sections over a flat record.
        """
        r = self.receipt
        return {
            "source": self.source,
            "success": self.success,
            "document": {
                "document_type": r.document_type,
                "vendor_name": r.vendor_name,
                "customer_name": r.customer_name,
                "invoice_number": r.invoice_number,
                "receipt_number": r.receipt_number,
                "date": r.date,
                "time": r.time,
                "currency": r.currency,
            },
            "financials": {
                "subtotal": r.subtotal,
                "tax": r.tax,
                "discount": r.discount,
                "total": r.total,
            },
            "items": [item.to_dict() for item in r.items],
            "payment": {"payment_method": r.payment_method},
            "quality": {
                "ocr_confidence": self.ocr_confidence,
                "extraction_confidence": self.extraction_confidence,
                "validation_confidence": self.validation_confidence,
                "overall_reliability": self.overall_confidence,
            },
            "validation": {
                "is_valid": self.success and not self.needs_review,
                "warnings": list(self.warnings),
            },
            "provenance": {
                "engines_used": list(self.engines_used),
                "reconciliation_performed": self.reconciliation_performed,
                "operations_applied": list(self.operations_applied),
            },
            "raw_ocr": dict(self.raw_ocr_by_engine) if self.raw_ocr_by_engine else {self.ocr_engine: self.raw_text},
            "field_decisions": {k: v.to_dict() for k, v in self.field_decisions.items()},
            "needs_review": self.needs_review,
            "review_reasons": list(self.review_reasons),
            "error": self.error,
        }
