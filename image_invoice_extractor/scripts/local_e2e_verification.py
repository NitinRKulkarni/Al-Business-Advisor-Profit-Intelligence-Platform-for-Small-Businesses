"""
local_e2e_verification
=========================

End-to-end verification of the full local pipeline:
    image -> preprocessing -> OCR -> extraction -> validation -> structured result

Runs `receipt_extraction.process_receipt()` (the real public entry point,
unmodified) over a small, rule-selected subset of the existing 156-image
dataset -- NOT all 156, and NOT selected for good OCR. Selection rules are
predicates over the already-computed quality/OCR reports, chosen to
surface failure modes (dark, noisy, low-contrast, messy handwriting,
numeric-heavy) rather than to showcase clean results.

Writes only to data/output/local_e2e_verification/ (isolated from the
source dataset and from every prior report).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.reporting import load_collage_map, read_records_csv  # noqa: E402
from receipt_extraction import process_receipt  # noqa: E402

INDIVIDUAL_DIR = Path("data/samples/batch2/individual")
QUALITY_CSV = Path("data/output/quality_improved_batch2.csv")
BASELINE_CSV = Path("data/output/ocr_full_batch2_baseline.csv")
MANIFEST = Path("data/samples/batch2/manifest.csv")

OUT_DIR = Path("data/output/local_e2e_verification")
PROCESSED_DIR = OUT_DIR / "processed"
REPORT_CSV = OUT_DIR / "report.csv"
SUMMARY_MD = OUT_DIR / "summary.md"

CSV_FIELDS = [
    "category", "source_filename", "source_collage", "pipeline_success",
    "ocr_engine", "ocr_confidence", "extraction_confidence",
    "vendor_name", "document_type", "invoice_number", "receipt_number", "date",
    "item_count", "items_summary",
    "subtotal", "discount", "tax", "total",
    "warnings", "processing_time", "error", "raw_text",
]


def _load_csv_map(path: Path, key: str = "filename") -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


def select_subset() -> list[tuple[str, str]]:
    """Rule-based selection covering failure-prone categories, not good OCR."""
    quality = _load_csv_map(QUALITY_CSV)
    baseline = {r["filename"]: r for r in read_records_csv(BASELINE_CSV)}
    collage_map = load_collage_map(MANIFEST)

    def info(stem: str) -> dict:
        png = f"{stem}.png"
        q = quality.get(png, {})
        b = baseline.get(stem, {})
        return {
            "stem": stem, "collage": collage_map.get(png, ""),
            "warnings": (q.get("warnings") or "").split(";"),
            "brightness": float(q["brightness"]) if q.get("brightness") else None,
            "stroke_width": float(q["stroke_width_px"]) if q.get("stroke_width_px") else None,
            "conf": b.get("mean_confidence"),
            "words": int(b.get("word_count") or 0),
            "chars": int(b.get("character_count") or 0),
            "text": (b.get("extracted_text") or "").replace("\\n", "\n"),
        }

    all_info = [info(p.stem) for p in sorted(INDIVIDUAL_DIR.glob("*.png"))]

    def clean_handwritten(i):
        return not any(i["warnings"]) and (i["conf"] or 0) >= 60 and (i["brightness"] or 0) >= 150

    def messy_handwritten(i):
        return (i["stroke_width"] or 0) > 3 and (i["conf"] or 0) < 45 and (i["brightness"] or 0) >= 130

    def printed_style(i):
        return "GST" in i["text"] or "Invoice" in i["text"]

    def dark_underexposed(i):
        return (i["brightness"] or 999) < 110 and "uneven_lighting_or_shadow" in i["warnings"]

    def low_contrast(i):
        return "low_contrast" in i["warnings"]

    def noisy(i):
        return "high_noise" in i["warnings"]

    def skewed_perspective(i):
        return "possible_skew" in i["warnings"]

    def numeric_heavy(i):
        return i["chars"] >= 300 and i["words"] >= 55

    def multi_item(i):
        return i["text"].count("\n") >= 8 and (i["conf"] or 0) >= 40

    def has_tax(i):
        return "GST" in i["text"] or "Tax" in i["text"]

    def has_discount(i):
        return "Discount" in i["text"] or "Disc" in i["text"]

    def missing_fields(i):
        return 0 < i["words"] < 12

    def difficult_unreadable(i):
        return (i["conf"] or 999) < 20 and i["words"] > 0

    def different_layout(i):
        return "Challan" in i["text"] or "School" in i["text"] or "Rent" in i["text"]

    def challenging_real_world(i):
        # Lowest non-zero confidence with a non-trivial amount of text --
        # a genuinely hard case, not a synthetic worst-case.
        return i["words"] >= 15 and (i["conf"] or 999) < 35

    rules = [
        ("clean_handwritten", clean_handwritten),
        ("messy_handwritten", messy_handwritten),
        ("printed_style", printed_style),
        ("dark_underexposed", dark_underexposed),
        ("low_contrast", low_contrast),
        ("noisy", noisy),
        ("skewed_perspective", skewed_perspective),
        ("numeric_heavy", numeric_heavy),
        ("multiple_line_items", multi_item),
        ("has_tax", has_tax),
        ("has_discount", has_discount),
        ("missing_fields", missing_fields),
        ("difficult_unreadable", difficult_unreadable),
        ("different_layout", different_layout),
        ("challenging_real_world", challenging_real_world),
    ]

    chosen: list[tuple[str, str]] = []
    used: set[str] = set()
    for label, predicate in rules:
        candidates = sorted(
            (i for i in all_info if predicate(i) and i["stem"] not in used),
            key=lambda i: i["stem"],
        )
        if candidates:
            stem = candidates[0]["stem"]
            used.add(stem)
            chosen.append((label, stem))
        else:
            print(f"  NOTE: no candidate found for '{label}'")
    return chosen


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    collage_map = load_collage_map(MANIFEST)

    subset = select_subset()
    print(f"selected {len(subset)} images:")
    for label, stem in subset:
        print(f"  {label:<22} {stem}")

    rows = []
    for label, stem in subset:
        src = INDIVIDUAL_DIR / f"{stem}.png"
        result = process_receipt(src, PROCESSED_DIR)
        d = result.to_dict()

        items_summary = "; ".join(
            f"{it['description']}|qty={it['quantity']}|price={it['unit_price']}|amt={it['amount']}"
            for it in d["items"]
        )

        row = {
            "category": label,
            "source_filename": stem,
            "source_collage": collage_map.get(f"{stem}.png", ""),
            "pipeline_success": d["success"],
            "ocr_engine": d["ocr_engine"],
            "ocr_confidence": d["ocr_confidence"],
            "extraction_confidence": d["extraction_confidence"],
            "vendor_name": d["vendor_name"],
            "document_type": d["document_type"],
            "invoice_number": d["invoice_number"],
            "receipt_number": d["receipt_number"],
            "date": d["date"],
            "item_count": len(d["items"]),
            "items_summary": items_summary,
            "subtotal": d["subtotal"],
            "discount": d["discount"],
            "tax": d["tax"],
            "total": d["total"],
            "warnings": ";".join(d["warnings"]),
            "processing_time": None,  # filled below from operations timing if available
            "error": d["error"],
            "raw_text": (d["raw_text"] or "").replace("\r\n", "\n").replace("\n", "\\n"),
        }
        rows.append(row)

        print(f"\n=== {label}: {stem} ===")
        print(f"  success={d['success']} ocr_conf={d['ocr_confidence']} "
              f"extraction_conf={d['extraction_confidence']}")
        print(f"  vendor={d['vendor_name']!r} date={d['date']!r} "
              f"invoice_no={d['invoice_number']!r} receipt_no={d['receipt_number']!r}")
        print(f"  subtotal={d['subtotal']} discount={d['discount']} "
              f"tax={d['tax']} total={d['total']} items={len(d['items'])}")
        print(f"  warnings={d['warnings']}")

    with REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows -> {REPORT_CSV}")


if __name__ == "__main__":
    main()
