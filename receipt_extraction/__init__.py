"""
receipt_extraction
====================

Structured field extraction from OCR text, sitting after the OCR stage
and before business-analytics consumers.

Pipeline position
-------------------
    image path
        -> image_processing.receipt_pipeline.process_receipt_images()  (existing)
        -> ocr.OcrEngine.recognize()                                    (existing)
        -> receipt_extraction.extract_from_ocr()                        (this package)
        -> ExtractionResult (structured, JSON-serializable)

This package does not implement OCR or preprocessing itself -- it reuses
`image_processing.receipt_pipeline.process_receipt_images` and any
`ocr.OcrEngine` implementation as-is. `extract_from_ocr()` depends only on
`ocr.engine.OcrResult` (a plain dataclass), not on Tesseract or EasyOCR
directly, so a future Azure-backed `OcrEngine` can be substituted into
`process_receipt(s)` without any change here.
"""

from .confidence import finalize_confidence
from .extractor import extract_from_ocr, process_receipt, process_receipts
from .models import EngineExtraction, ExtractionResult, FieldDecision, LineItem, ReceiptData
from .reconciliation import classify_numeric_disagreement, reconcile_extractions
from .validators import validate_receipt
from .variants import (
    VariantCandidate,
    choose_best_per_engine,
    score_candidate,
    select_variant_stages,
)

__all__ = [
    "extract_from_ocr",
    "process_receipt",
    "process_receipts",
    "finalize_confidence",
    "reconcile_extractions",
    "classify_numeric_disagreement",
    "ExtractionResult",
    "LineItem",
    "ReceiptData",
    "EngineExtraction",
    "FieldDecision",
    "validate_receipt",
    "VariantCandidate",
    "select_variant_stages",
    "score_candidate",
    "choose_best_per_engine",
]
