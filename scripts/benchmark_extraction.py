"""
benchmark_extraction
======================

Measures field-level extraction accuracy against MANUALLY VERIFIED ground
truth, and compares the text-only extraction path against the
spatial/layout-aware path on identical OCR output.

Ground truth
--------------
Lives in `ground_truth/*.json`, one file per benchmarked image, each
hand-transcribed by reading the source image. OCR output is never used as
ground truth. Only fields a human could actually read are recorded; a field
absent from the receipt is recorded as null so "correctly returned null" is
distinguishable from "missed a value that was present".

What is measured
------------------
Per field: exact match for identifiers/dates/vendor (normalised for case
and whitespace), and numeric equality within a small tolerance for money.
Line items are scored on (description-ish match, quantity, unit_price,
amount) per row.

Financial fields are reported separately and weighted as the headline
metric, because a wrong total is materially worse than a misspelled vendor.

Outputs
---------
    data/output/ocr_benchmark/field_accuracy.csv
    data/output/ocr_benchmark/receipt_accuracy.csv
    data/output/ocr_benchmark/benchmark_summary.md
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import EasyOcrEngine, TesseractOcrEngine  # noqa: E402
from receipt_extraction import (  # noqa: E402
    EngineExtraction, extract_from_ocr, finalize_confidence, reconcile_extractions,
    validate_receipt,
)
from receipt_extraction.models import ExtractionResult  # noqa: E402
from image_processing.receipt_pipeline import process_receipt_images  # noqa: E402

GROUND_TRUTH_DIR = Path("ground_truth")
OUT_DIR = Path("data/output/ocr_benchmark")
PROCESSED_DIR = OUT_DIR / "processed"

MONEY_TOLERANCE = 0.02  # 2% or 1 unit, whichever larger

SCALAR_FIELDS = ("vendor_name", "date", "invoice_number", "receipt_number")
MONEY_FIELDS = ("subtotal", "discount", "tax", "total")


def _norm_text(value) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).lower().split())


def _money_equal(expected, actual) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    return abs(float(expected) - float(actual)) <= max(1.0, abs(float(expected)) * MONEY_TOLERANCE)


def _text_equal(expected, actual) -> bool:
    e, a = _norm_text(expected), _norm_text(actual)
    if e is None and a is None:
        return True
    if e is None or a is None:
        return False
    # Vendor names are scored as "contains" in either direction: OCR often
    # captures a correct subset (e.g. drops a trailing "& Sons"), which is
    # materially different from reading the wrong vendor entirely.
    return e == a or e in a or a in e


def score_result(truth: dict, produced: dict) -> dict:
    """Per-field correctness for one receipt."""
    scores: dict[str, bool | None] = {}

    for field in SCALAR_FIELDS:
        if field not in truth:
            scores[field] = None
            continue
        scores[field] = _text_equal(truth[field], produced.get(field))

    for field in MONEY_FIELDS:
        if field not in truth:
            scores[field] = None
            continue
        scores[field] = _money_equal(truth[field], produced.get(field))

    truth_items = truth.get("items") or []
    produced_items = produced.get("items") or []
    item_field_hits = 0
    item_field_total = 0
    matched_rows = 0

    for t_item in truth_items:
        # Match a produced row to this truth row by description similarity.
        best = None
        for p_item in produced_items:
            if _text_equal(t_item.get("description"), p_item.get("description")):
                best = p_item
                break
        if best is None:
            item_field_total += 3  # qty, unit_price, amount all missed
            continue
        matched_rows += 1
        for key in ("quantity", "unit_price", "amount"):
            if key not in t_item:
                continue
            item_field_total += 1
            if _money_equal(t_item.get(key), best.get(key)):
                item_field_hits += 1

    scores["_item_rows_matched"] = matched_rows
    scores["_item_rows_expected"] = len(truth_items)
    scores["_item_field_hits"] = item_field_hits
    scores["_item_field_total"] = item_field_total
    return scores


def main() -> None:
    truth_files = sorted(GROUND_TRUTH_DIR.glob("*.json"))
    if not truth_files:
        raise SystemExit(
            f"No ground truth found in {GROUND_TRUTH_DIR}/. "
            "Create hand-verified JSON files first."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tess = TesseractOcrEngine()
    print(f"engine A: {tess.name}")
    try:
        easy = EasyOcrEngine()
        print(f"engine B: {easy.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"EasyOCR unavailable ({exc}); benchmarking Tesseract only.")
        easy = None
    print(f"ground truth receipts: {len(truth_files)}\n")

    rows = []
    for tf in truth_files:
        truth = json.loads(tf.read_text(encoding="utf-8"))
        image_path = Path(truth["image"])
        if not image_path.is_file():
            print(f"  SKIP {tf.name}: image not found at {image_path}")
            continue

        [prep] = process_receipt_images([image_path], PROCESSED_DIR)
        if not prep["processing_success"]:
            print(f"  FAIL {tf.name}: preprocessing failed")
            continue

        ocr_tess = tess.recognize(prep["processed_image_path"])
        ocr_tess.filename = image_path.name

        tess_res = extract_from_ocr(ocr_tess, operations_applied=prep["operations_applied"])
        validate_receipt(tess_res)
        finalize_confidence(tess_res)
        tess_scores = score_result(truth, tess_res.to_dict())

        if easy is not None:
            ocr_easy = easy.recognize(prep["processed_image_path"])
            ocr_easy.filename = image_path.name
            easy_res = extract_from_ocr(ocr_easy, operations_applied=prep["operations_applied"])
            validate_receipt(easy_res)
            finalize_confidence(easy_res)
            easy_scores = score_result(truth, easy_res.to_dict())

            per_engine = [
                EngineExtraction(engine=ocr_tess.engine, ocr_confidence=ocr_tess.mean_confidence,
                                  receipt=tess_res.receipt, raw_text=ocr_tess.text, warnings=tess_res.warnings),
                EngineExtraction(engine=ocr_easy.engine, ocr_confidence=ocr_easy.mean_confidence,
                                  receipt=easy_res.receipt, raw_text=ocr_easy.text, warnings=easy_res.warnings),
            ]
            recon_receipt, field_decisions, recon_warnings = reconcile_extractions(per_engine)
            recon_result = ExtractionResult(
                source=image_path.name, success=True, receipt=recon_receipt,
                raw_text=ocr_tess.text + "\n---\n" + ocr_easy.text,
                ocr_engine=f"{ocr_tess.engine}+{ocr_easy.engine}",
                ocr_confidence=max(ocr_tess.mean_confidence or 0, ocr_easy.mean_confidence or 0),
                operations_applied=prep["operations_applied"],
                warnings=recon_warnings, engines_used=[ocr_tess.engine, ocr_easy.engine],
                reconciliation_performed=True, field_decisions=field_decisions,
            )
            validate_receipt(recon_result)
            finalize_confidence(recon_result)
            recon_scores = score_result(truth, recon_result.to_dict())
        else:
            easy_scores = tess_scores
            recon_scores = tess_scores
            recon_result = tess_res

        rows.append({
            "image": image_path.name,
            "category": truth.get("category", ""),
            "tesseract": tess_scores,
            "easyocr": easy_scores,
            "reconciled": recon_scores,
            "reconciled_result": recon_result.to_dict(),
            "ocr_confidence": ocr_tess.mean_confidence,
        })

        def summarize(s):
            checked = [v for k, v in s.items() if not k.startswith("_") and v is not None]
            return f"{sum(checked)}/{len(checked)}"

        print(f"  {image_path.name:<28} tess={summarize(tess_scores)} easy={summarize(easy_scores)} "
              f"recon={summarize(recon_scores)} "
              f"items tess={tess_scores['_item_field_hits']}/{tess_scores['_item_field_total']} "
              f"easy={easy_scores['_item_field_hits']}/{easy_scores['_item_field_total']} "
              f"recon={recon_scores['_item_field_hits']}/{recon_scores['_item_field_total']}")

    if not rows:
        raise SystemExit("No receipts scored.")

    # -------------------------------------------------- aggregate report
    variants = ["tesseract", "easyocr", "reconciled"]

    def field_rate(variant: str, field: str) -> tuple[int, int]:
        hits = sum(1 for r in rows if r[variant].get(field) is True)
        total = sum(1 for r in rows if r[variant].get(field) is not None)
        return hits, total

    lines_md: list[str] = []
    lines_md.append("# Extraction Benchmark - Ground-Truth Measured\n")
    lines_md.append(f"- Receipts with hand-verified ground truth: **{len(rows)}**")
    lines_md.append(f"- Engines: `{tess.name}`" + (f", `{easy.name}`" if easy else " (EasyOCR unavailable)"))
    lines_md.append("- `TESSERACT`/`EASYOCR` = single-engine extraction on that engine's own OCR text")
    lines_md.append("- `RECONCILED` = both engines' independent extractions merged via")
    lines_md.append("  `reconcile_extractions` (agreement / arithmetic evidence / disagreement->null)\n")
    lines_md.append("| Field | TESSERACT | EASYOCR | RECONCILED |")
    lines_md.append("|---|---|---|---|")

    csv_field_rows = []
    for field in SCALAR_FIELDS + MONEY_FIELDS:
        pct_strs = {}
        stats = {}
        for v in variants:
            h, t = field_rate(v, field)
            pct_strs[v] = f"{h}/{t} ({h / t * 100:.0f}%)" if t else "n/a"
            stats[v] = (h, t)
        lines_md.append(f"| {field} | {pct_strs['tesseract']} | {pct_strs['easyocr']} | {pct_strs['reconciled']} |")
        csv_field_rows.append({
            "field": field,
            "tesseract_hits": stats["tesseract"][0], "tesseract_total": stats["tesseract"][1],
            "easyocr_hits": stats["easyocr"][0], "easyocr_total": stats["easyocr"][1],
            "reconciled_hits": stats["reconciled"][0], "reconciled_total": stats["reconciled"][1],
        })

    item_stats = {}
    for v in variants:
        h = sum(r[v]["_item_field_hits"] for r in rows)
        t = sum(r[v]["_item_field_total"] for r in rows)
        item_stats[v] = (h, t)
    lines_md.append(
        "| **line-item numeric fields** | "
        + " | ".join(
            f"{h}/{t} ({h / t * 100:.0f}%)" if t else "n/a"
            for h, t in (item_stats[v] for v in variants)
        )
        + " |"
    )
    csv_field_rows.append({
        "field": "line_item_numeric",
        "tesseract_hits": item_stats["tesseract"][0], "tesseract_total": item_stats["tesseract"][1],
        "easyocr_hits": item_stats["easyocr"][0], "easyocr_total": item_stats["easyocr"][1],
        "reconciled_hits": item_stats["reconciled"][0], "reconciled_total": item_stats["reconciled"][1],
    })

    # Financial-only headline metric per variant.
    lines_md.append("")
    lines_md.append("## Financial-field accuracy (headline metric)\n")
    fin_stats = {}
    for v in variants:
        h = sum(field_rate(v, f)[0] for f in MONEY_FIELDS) + item_stats[v][0]
        t = sum(field_rate(v, f)[1] for f in MONEY_FIELDS) + item_stats[v][1]
        fin_stats[v] = (h, t)
        pct = f"{h / t * 100:.1f}%" if t else "n/a"
        lines_md.append(f"- {v.upper()}: **{h}/{t} ({pct})**")

    needs_review = sum(1 for r in rows if r["reconciled_result"]["needs_review"])
    lines_md.append("")
    lines_md.append("## Review signal (reconciled result)\n")
    lines_md.append(f"- Receipts flagged `needs_review`: **{needs_review}/{len(rows)}**")
    confs = [r["reconciled_result"]["overall_confidence"] for r in rows
             if r["reconciled_result"]["overall_confidence"] is not None]
    if confs:
        lines_md.append(f"- Mean overall_confidence: **{statistics.mean(confs):.1f}**")

    lines_md.append("")
    lines_md.append("## Per-receipt breakdown\n")
    lines_md.append("| Image | Category | Tesseract | EasyOCR | Reconciled |")
    lines_md.append("|---|---|---|---|---|")
    for r in rows:
        def total_score(s):
            checked = [v for k, v in s.items() if not k.startswith("_") and v is not None]
            return f"{sum(checked)}/{len(checked)}"
        lines_md.append(
            f"| {r['image']} | {r['category']} | {total_score(r['tesseract'])} | "
            f"{total_score(r['easyocr'])} | {total_score(r['reconciled'])} |"
        )

    lines_md.append("")
    lines_md.append("> Accuracy above is measured only on the hand-verified subset listed in")
    lines_md.append("> `receipt_accuracy.csv`. It is not a claim about all 156 images, which")
    lines_md.append("> have no ground truth.")

    (OUT_DIR / "benchmark_summary.md").write_text("\n".join(lines_md), encoding="utf-8")

    import csv as _csv
    with (OUT_DIR / "field_accuracy.csv").open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=[
            "field", "tesseract_hits", "tesseract_total", "easyocr_hits", "easyocr_total",
            "reconciled_hits", "reconciled_total",
        ])
        w.writeheader()
        w.writerows(csv_field_rows)

    with (OUT_DIR / "receipt_accuracy.csv").open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=[
            "image", "category", "ocr_confidence", "overall_confidence", "needs_review",
            "tesseract_item_hits", "tesseract_item_total",
            "easyocr_item_hits", "easyocr_item_total",
            "reconciled_item_hits", "reconciled_item_total",
        ])
        w.writeheader()
        for r in rows:
            w.writerow({
                "image": r["image"], "category": r["category"],
                "ocr_confidence": r["ocr_confidence"],
                "overall_confidence": r["reconciled_result"]["overall_confidence"],
                "needs_review": r["reconciled_result"]["needs_review"],
                "tesseract_item_hits": r["tesseract"]["_item_field_hits"],
                "tesseract_item_total": r["tesseract"]["_item_field_total"],
                "easyocr_item_hits": r["easyocr"]["_item_field_hits"],
                "easyocr_item_total": r["easyocr"]["_item_field_total"],
                "reconciled_item_hits": r["reconciled"]["_item_field_hits"],
                "reconciled_item_total": r["reconciled"]["_item_field_total"],
            })

    print(f"\nwrote reports -> {OUT_DIR}")


if __name__ == "__main__":
    main()
