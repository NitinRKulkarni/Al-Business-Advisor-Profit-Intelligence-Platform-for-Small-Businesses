"""
generalization_regression
============================

Small, targeted regression set for the extraction layer's generalization
fixes (underscore normalization applied consistently, fuzzy financial-
keyword fallback, OCR/warning-aware extraction confidence).

Selects ONE image per condition from the existing 156-image dataset (not
all 156 -- that dataset is the validation reference, not something to
re-run in full for every change) plus the externally-provided Meenakshi
Traders receipt as ONE regression case among ten, not the design target.

Categories:
    1. clean handwritten        6. skewed
    2. messy handwritten        7. numeric-heavy
    3. printed receipt          8. has tax
    4. dark receipt             9. has discount
    5. low-contrast receipt    10. multiple line items
    (+ Meenakshi receipt: external, unseen, real-world regression case)

Writes only to data/output/generalization_regression/ -- does not modify
any source image (the 156-image dataset or test/1.png).
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
MEENAKSHI_RECEIPT = Path("test/1.png")

OUT_DIR = Path("data/output/generalization_regression")
PROCESSED_DIR = OUT_DIR / "processed"
REPORT_JSON = OUT_DIR / "regression_report.json"
REPORT_CSV = OUT_DIR / "regression_report.csv"


def _load_csv_map(path: Path, key: str = "filename") -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


def select_regression_set() -> list[tuple[str, Path]]:
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

    rules = [
        ("clean_handwritten", lambda i: not any(i["warnings"]) and (i["conf"] or 0) >= 60 and (i["brightness"] or 0) >= 150),
        ("messy_handwritten", lambda i: (i["stroke_width"] or 0) > 3 and (i["conf"] or 0) < 45 and (i["brightness"] or 0) >= 130),
        ("printed_receipt", lambda i: "GST" in i["text"] or "Invoice" in i["text"]),
        ("dark_receipt", lambda i: (i["brightness"] or 999) < 110 and "uneven_lighting_or_shadow" in i["warnings"]),
        ("low_contrast_receipt", lambda i: "low_contrast" in i["warnings"]),
        ("skewed_receipt", lambda i: "possible_skew" in i["warnings"]),
        ("numeric_heavy_receipt", lambda i: i["chars"] >= 300 and i["words"] >= 55),
        ("receipt_with_tax", lambda i: "GST" in i["text"] or "Tax" in i["text"]),
        ("receipt_with_discount", lambda i: "Discount" in i["text"] or "Disc" in i["text"]),
        ("multiple_line_items", lambda i: i["text"].count("\n") >= 8 and (i["conf"] or 0) >= 40),
    ]

    chosen: list[tuple[str, Path]] = []
    used: set[str] = set()
    for label, predicate in rules:
        candidates = sorted(
            (i for i in all_info if predicate(i) and i["stem"] not in used),
            key=lambda i: i["stem"],
        )
        if candidates:
            stem = candidates[0]["stem"]
            used.add(stem)
            chosen.append((label, INDIVIDUAL_DIR / f"{stem}.png"))
        else:
            print(f"  NOTE: no candidate found for '{label}'")

    if MEENAKSHI_RECEIPT.is_file():
        chosen.append(("unseen_real_world_regression", MEENAKSHI_RECEIPT))
    else:
        print(f"  NOTE: regression image not found at {MEENAKSHI_RECEIPT}")

    return chosen


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subset = select_regression_set()

    rows = []
    all_results = []
    for label, path in subset:
        result = process_receipt(path, PROCESSED_DIR)
        d = result.to_dict()
        all_results.append({"category": label, **d})

        rows.append({
            "category": label,
            "source": d["source"],
            "success": d["success"],
            "vendor_name": d["vendor_name"],
            "date": d["date"],
            "invoice_number": d["invoice_number"],
            "receipt_number": d["receipt_number"],
            "item_count": len(d["items"]),
            "subtotal": d["subtotal"],
            "discount": d["discount"],
            "tax": d["tax"],
            "total": d["total"],
            "ocr_confidence": d["ocr_confidence"],
            "extraction_confidence": d["extraction_confidence"],
            "warnings": ";".join(d["warnings"]),
        })

        print(f"\n=== {label}: {d['source']} ===")
        print(f"  vendor={d['vendor_name']!r} date={d['date']!r} "
              f"receipt_no={d['receipt_number']!r} invoice_no={d['invoice_number']!r}")
        print(f"  subtotal={d['subtotal']} discount={d['discount']} tax={d['tax']} total={d['total']}")
        print(f"  items={len(d['items'])} ocr_conf={d['ocr_confidence']} "
              f"extraction_conf={d['extraction_confidence']}")
        print(f"  warnings={d['warnings']}")

    with REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    REPORT_JSON.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\nwrote {len(rows)} rows -> {REPORT_CSV}")
    print(f"wrote full results -> {REPORT_JSON}")


if __name__ == "__main__":
    main()
