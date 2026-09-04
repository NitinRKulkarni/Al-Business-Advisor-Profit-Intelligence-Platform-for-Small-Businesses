"""
verify_receipt_pipeline
=========================

Verification for the receipt image-processing handoff layer
(`image_processing/receipt_pipeline.py`).

Runs `process_receipt_images()` (existing preprocess_image, wrapped) over:
  A. 7 images selected BY RULE from the existing 156-image dataset,
     covering: clean handwritten, messy handwritten, dark/underexposed,
     low contrast, noisy, skewed/perspective, numeric-heavy.
  B. 2 synthetic "unseen" receipt images generated with PIL (this sandbox
     has no camera/network image source, so two clean synthetic receipts
     stand in for "a new receipt not in the 156-image dataset" -- this
     substitution is called out explicitly in the run and in the report).

For every image, runs the EXISTING TesseractOcrEngine (no new OCR code)
on both the ORIGINAL image and the PROCESSED image, so preprocessing's
effect on OCR-readable numbers can be judged directly rather than assumed
from visual appearance.

Writes only to data/output/receipt_pipeline_verification/ -- never touches
data/samples/ or any existing report.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from image_processing.receipt_pipeline import process_receipt_images  # noqa: E402
from ocr import TesseractOcrEngine  # noqa: E402
from ocr.reporting import load_collage_map  # noqa: E402

OUT_DIR = Path("data/output/receipt_pipeline_verification")
NEW_DIR = OUT_DIR / "new_receipts"
PROCESSED_DIR = OUT_DIR / "processed"

INDIVIDUAL_DIR = Path("data/samples/batch2/individual")
QUALITY_CSV = Path("data/output/quality_improved_batch2.csv")
BASELINE_CSV = Path("data/output/ocr_full_batch2_baseline.csv")
MANIFEST = Path("data/samples/batch2/manifest.csv")


def _load_map(path: Path, key: str = "filename") -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


def select_representative_subset() -> list[tuple[str, Path]]:
    """Rule-based selection from existing reports (mirrors Phase 3 style)."""
    quality = _load_map(QUALITY_CSV)
    baseline = _load_map(BASELINE_CSV)
    collage_map = load_collage_map(MANIFEST)

    def info(stem: str) -> dict:
        png = f"{stem}.png"
        q = quality.get(png, {})
        b = baseline.get(stem, {})
        warnings = (q.get("warnings") or "").split(";")
        return {
            "stem": stem,
            "collage": collage_map.get(png, ""),
            "warnings": warnings,
            "brightness": float(q["brightness"]) if q.get("brightness") else None,
            "stroke_width": float(q["stroke_width_px"]) if q.get("stroke_width_px") else None,
            "conf": float(b["mean_confidence"]) if b.get("mean_confidence") else None,
            "words": int(b.get("word_count") or 0),
            "chars": int(b.get("character_count") or 0),
        }

    all_info = [info(p.stem) for p in sorted(INDIVIDUAL_DIR.glob("*.png"))]

    def clean_handwritten(i):
        return not any(i["warnings"]) and (i["conf"] or 0) >= 55 and (i["brightness"] or 0) >= 150

    def messy_handwritten(i):
        return (i["stroke_width"] or 0) > 3 and (i["conf"] or 0) < 45 and (i["brightness"] or 0) >= 130

    def dark_underexposed(i):
        return (i["brightness"] or 999) < 120 and "uneven_lighting_or_shadow" in i["warnings"]

    def low_contrast(i):
        return "low_contrast" in i["warnings"]

    def noisy(i):
        return "high_noise" in i["warnings"]

    def skewed_perspective(i):
        return "possible_skew" in i["warnings"]

    def numeric_heavy(i):
        return i["chars"] >= 250 and i["words"] >= 40

    rules = [
        ("clean_handwritten", clean_handwritten),
        ("messy_handwritten", messy_handwritten),
        ("dark_underexposed", dark_underexposed),
        ("low_contrast", low_contrast),
        ("noisy", noisy),
        ("skewed_perspective", skewed_perspective),
        ("numeric_heavy", numeric_heavy),
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
    return chosen


def make_synthetic_receipts() -> list[tuple[str, Path]]:
    """
    Two synthetic "unseen" receipts, standing in for real new photos that
    are not available in this sandbox. Includes a decimal amount with a
    currency symbol specifically to test the "1,250.00 must not become
    1250 or 125" failure mode called out in the task.
    """
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    made: list[tuple[str, Path]] = []

    # Receipt 1: clean, straight, printed-style text with a decimal total.
    path1 = NEW_DIR / "unseen_receipt_clean.png"
    img1 = Image.new("RGB", (600, 420), color=(255, 255, 255))
    draw1 = ImageDraw.Draw(img1)
    lines1 = [
        "GREEN LEAF SUPERMARKET",
        "Invoice No: INV-88231",
        "Date: 14/02/2025",
        "",
        "Item              Qty   Price",
        "Rice 5kg            1   350.00",
        "Cooking Oil 1L      2   180.00",
        "Sugar 1kg           1    45.00",
        "",
        "Subtotal          755.00",
        "Discount           10.00",
        "TOTAL RS. 1,250.00",
    ]
    y = 20
    for line in lines1:
        draw1.text((20, y), line, fill=(0, 0, 0))
        y += 32
    img1.save(path1)
    made.append(("unseen_clean_printed", path1))

    # Receipt 2: same content, rotated ~8 degrees + mild noise, to exercise
    # deskew + denoise on an image the pipeline has never seen.
    path2 = NEW_DIR / "unseen_receipt_skewed.png"
    img2 = img1.rotate(8, expand=True, fillcolor=(255, 255, 255))
    img2.save(path2)
    made.append(("unseen_skewed_printed", path2))

    return made


def run_ocr(engine: TesseractOcrEngine, path: Path) -> dict:
    result = engine.recognize(path)
    return {
        "success": result.success,
        "mean_confidence": result.mean_confidence,
        "word_count": result.word_count,
        "text": result.text,
        "error": result.error,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = TesseractOcrEngine(language="eng", psm=6, oem=3)
    print(f"OCR engine: {engine.name}")

    print("\nSelecting representative subset from existing reports...")
    subset = select_representative_subset()
    for label, path in subset:
        print(f"  {label:<20} {path.name}")

    print("\nGenerating 2 synthetic 'unseen' receipts (no camera/network source available)...")
    unseen = make_synthetic_receipts()
    for label, path in unseen:
        print(f"  {label:<20} {path.name}")

    all_images = subset + unseen
    paths = [p for _, p in all_images]

    print(f"\nRunning process_receipt_images() on {len(paths)} images -> {PROCESSED_DIR}")
    records = process_receipt_images(paths, PROCESSED_DIR)

    rows = []
    for (label, src_path), record in zip(all_images, records):
        print(f"\n=== {label}: {src_path.name} ===")
        print(f"  ops={record['operations_applied']} warnings={record['warnings']} "
              f"orig={record['original_dimensions']} final={record['final_dimensions']} "
              f"t={record['processing_time']}s success={record['processing_success']}")

        ocr_before = run_ocr(engine, src_path)
        ocr_after = (
            run_ocr(engine, Path(record["processed_image_path"]))
            if record["processed_image_path"]
            else {"success": False, "mean_confidence": None, "word_count": 0, "text": "", "error": "no processed image"}
        )

        print(f"  BEFORE conf={ocr_before['mean_confidence']} words={ocr_before['word_count']}")
        print(f"  AFTER  conf={ocr_after['mean_confidence']} words={ocr_after['word_count']}")

        rows.append({
            "label": label,
            "input_path": record["input_path"],
            "processed_image_path": record["processed_image_path"],
            "processing_success": record["processing_success"],
            "operations_applied": ";".join(record["operations_applied"]),
            "warnings": ";".join(record["warnings"]),
            "original_dimensions": f"{record['original_dimensions'][0]}x{record['original_dimensions'][1]}",
            "final_dimensions": f"{record['final_dimensions'][0]}x{record['final_dimensions'][1]}",
            "processing_time": record["processing_time"],
            "ocr_before_confidence": ocr_before["mean_confidence"],
            "ocr_before_words": ocr_before["word_count"],
            "ocr_after_confidence": ocr_after["mean_confidence"],
            "ocr_after_words": ocr_after["word_count"],
        })

        # Save both raw texts for manual inspection in the report.
        (OUT_DIR / f"{src_path.stem}__before.txt").write_text(ocr_before["text"], encoding="utf-8")
        (OUT_DIR / f"{src_path.stem}__after.txt").write_text(ocr_after["text"], encoding="utf-8")

    csv_path = OUT_DIR / "verification_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows -> {csv_path}")


if __name__ == "__main__":
    main()
