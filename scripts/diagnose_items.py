"""Temporary diagnostic: batch2_invoice_001 line items score 7/15 with
Tesseract alone but only 4/15 reconciled -- investigate why reconciliation
regresses below the best single engine. Deleted after use."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import EasyOcrEngine, TesseractOcrEngine  # noqa: E402
from receipt_extraction import (  # noqa: E402
    EngineExtraction, extract_from_ocr, reconcile_extractions,
)
from image_processing.receipt_pipeline import process_receipt_images  # noqa: E402

image_path = Path("data/samples/batch2/individual/batch2_invoice_001.png")
[prep] = process_receipt_images([image_path], Path("data/output/ocr_benchmark/processed"))

tess = TesseractOcrEngine()
easy = EasyOcrEngine()

ocr_tess = tess.recognize(prep["processed_image_path"])
ocr_easy = easy.recognize(prep["processed_image_path"])

tess_res = extract_from_ocr(ocr_tess)
easy_res = extract_from_ocr(ocr_easy)

print("TESSERACT items:")
for i in tess_res.receipt.items:
    print(f"  {i.description!r:<30} qty={i.quantity} price={i.unit_price} amount={i.amount}")

print("\nEASYOCR items:")
for i in easy_res.receipt.items:
    print(f"  {i.description!r:<30} qty={i.quantity} price={i.unit_price} amount={i.amount}")

per_engine = [
    EngineExtraction(engine=ocr_tess.engine, ocr_confidence=ocr_tess.mean_confidence,
                      receipt=tess_res.receipt, raw_text=ocr_tess.text, warnings=tess_res.warnings),
    EngineExtraction(engine=ocr_easy.engine, ocr_confidence=ocr_easy.mean_confidence,
                      receipt=easy_res.receipt, raw_text=ocr_easy.text, warnings=easy_res.warnings),
]
recon_receipt, _, warnings = reconcile_extractions(per_engine)
print("\nRECONCILED items:")
for i in recon_receipt.items:
    print(f"  {i.description!r:<30} qty={i.quantity} price={i.unit_price} amount={i.amount}  warnings={i.warnings}")

print("\nGROUND TRUTH items:")
import json
truth = json.loads(Path("ground_truth/batch2_invoice_001.json").read_text(encoding="utf-8"))
for i in truth["items"]:
    print(f"  {i}")
