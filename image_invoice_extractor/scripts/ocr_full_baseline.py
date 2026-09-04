"""
ocr_full_baseline
==================

TASK 1 -- Run the existing, unmodified Tesseract engine against all 156
preprocessed images and write a durable per-image report.

Input
------
    data/processed/full_batch2_preprocessing/<image_name>/final.png

Output
-------
    data/output/ocr_full_batch2_baseline.csv          one row per image
    data/output/ocr_full_batch2_baseline/text/*.txt   raw OCR text per image

Scope guards (deliberate)
--------------------------
- Reads only already-generated `final.png` files; preprocessing is NOT
  re-run and `image_processing/` is not imported at all.
- Source images in data/samples/ are never opened.
- No cloud/Azure code, credentials, or network calls.
- Writes to new paths only; existing preprocessing and quality reports and
  the earlier 5-image experiment outputs are left intact.
- Does NOT do invoice field extraction.

On confidence
--------------
`mean_confidence` here is Tesseract's own per-word confidence averaged
across the words it returned. It is a *triage signal* for deciding which
images to inspect, not evidence that the text is correct. This script
deliberately computes no accuracy figure, because the dataset has no
ground-truth transcriptions.

Usage
-----
    python scripts/ocr_full_baseline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import OcrEngine, TesseractOcrEngine  # noqa: E402
from ocr.reporting import (  # noqa: E402
    BASELINE_CSV_FIELDS,
    escape_text,
    load_collage_map,
    summarize,
    write_records_csv,
)

PREPROCESSED_DIR = Path("data/processed/full_batch2_preprocessing")
MANIFEST = Path("data/samples/batch2/manifest.csv")
SOURCE_DIR = Path("data/samples/batch2/individual")

OUT_CSV = Path("data/output/ocr_full_batch2_baseline.csv")
TEXT_DIR = Path("data/output/ocr_full_batch2_baseline/text")

STAGE_FILENAME = "final.png"


def build_engine() -> OcrEngine:
    """
    Construct the baseline engine.

    Single swap point. Kept identical to the settings used in the earlier
    5-image experiment (`scripts/ocr_experiment_5.py`) so the full-dataset
    numbers are directly comparable with those already-recorded
    observations rather than being a different configuration.
    """
    return TesseractOcrEngine(language="eng", psm=6, oem=3)


def main() -> None:
    if not PREPROCESSED_DIR.is_dir():
        raise SystemExit(f"Preprocessed directory not found: {PREPROCESSED_DIR}")

    collage_map = load_collage_map(MANIFEST)
    engine = build_engine()
    print(f"engine: {engine.name}")

    image_dirs = sorted(p for p in PREPROCESSED_DIR.iterdir() if p.is_dir())
    print(f"image directories found: {len(image_dirs)}")

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    for index, image_dir in enumerate(image_dirs, start=1):
        source_filename = f"{image_dir.name}.png"
        stage_path = image_dir / STAGE_FILENAME

        if not stage_path.is_file():
            # Recorded as a failure row rather than skipped, so the report
            # always accounts for every directory found.
            records.append({
                "filename": image_dir.name,
                "source_image": str(SOURCE_DIR / source_filename).replace("\\", "/"),
                "source_collage": collage_map.get(source_filename, ""),
                "preprocessing_output": str(stage_path).replace("\\", "/"),
                "success": False,
                "mean_confidence": None,
                "word_count": 0,
                "character_count": 0,
                "processing_time": 0.0,
                "extracted_text": "",
                "error": f"missing {STAGE_FILENAME}",
            })
            print(f"[{index:3}/{len(image_dirs)}] {image_dir.name}: MISSING {STAGE_FILENAME}")
            continue

        result = engine.recognize(stage_path)

        (TEXT_DIR / f"{image_dir.name}.txt").write_text(result.text, encoding="utf-8")

        records.append({
            "filename": image_dir.name,
            "source_image": str(SOURCE_DIR / source_filename).replace("\\", "/"),
            "source_collage": collage_map.get(source_filename, ""),
            "preprocessing_output": str(stage_path).replace("\\", "/"),
            "success": result.success,
            "mean_confidence": result.mean_confidence,
            "word_count": result.word_count,
            "character_count": len(result.text),
            "processing_time": result.processing_time_seconds,
            "extracted_text": escape_text(result.text),
            "error": result.error or "",
        })

        print(
            f"[{index:3}/{len(image_dirs)}] {image_dir.name}: "
            f"conf={result.mean_confidence} words={result.word_count} "
            f"chars={len(result.text)} t={result.processing_time_seconds}s"
            + (f" ERROR={result.error}" if result.error else "")
        )

    write_records_csv(records, OUT_CSV, BASELINE_CSV_FIELDS)
    print(f"\nwrote {len(records)} rows -> {OUT_CSV}")
    print(f"per-image text -> {TEXT_DIR}")

    # ------------------------------------------------- TASK 2 statistics
    stats = summarize(records)

    print("\n================ OCR EVALUATION (TASK 2) ================")
    print(f"total images      : {stats['total_images']}")
    print(f"successful        : {stats['successful']}")
    print(f"failed            : {stats['failed']}")
    if stats["failed_filenames"]:
        print(f"  failed files    : {', '.join(stats['failed_filenames'])}")
    print(f"zero recognized words : {stats['zero_word_count']}")
    if stats["zero_word_filenames"]:
        print(f"  zero-word files : {', '.join(stats['zero_word_filenames'])}")

    conf = stats["confidence"]
    print(
        f"\nconfidence: mean={conf['mean']} median={conf['median']} "
        f"min={conf['min']} max={conf['max']}"
    )
    print("confidence distribution:")
    for bucket, count in stats["confidence_buckets"].items():
        pct = (count / stats["successful"] * 100) if stats["successful"] else 0.0
        print(f"  {bucket:<10}: {count:3}  ({pct:.1f}%)")
    if stats["images_without_confidence"]:
        print(f"  (no confidence value: {stats['images_without_confidence']})")

    words = stats["word_count"]
    print(
        f"\nwords/image: mean={words['mean']} median={words['median']} "
        f"min={words['min']} max={words['max']}  total={stats['total_words']}"
    )
    chars = stats["character_count"]
    print(
        f"chars/image: mean={chars['mean']} median={chars['median']} "
        f"min={chars['min']} max={chars['max']}  total={stats['total_characters']}"
    )

    times = stats["processing_time"]
    print(
        f"\nprocessing time (s): mean={times['mean']} median={times['median']} "
        f"min={times['min']} max={times['max']}  total={stats['total_processing_time']}"
    )

    print("\nper source collage:")
    print(f"  {'collage':<16} {'imgs':>4} {'ok':>3} {'0wd':>4} "
          f"{'mean':>7} {'median':>7} {'min':>7} {'max':>7} {'words':>6}")
    for collage, data in stats["per_collage"].items():
        c = data["confidence"]
        print(
            f"  {collage:<16} {data['images']:>4} {data['success']:>3} "
            f"{data['zero_word']:>4} "
            f"{str(c['mean']):>7} {str(c['median']):>7} "
            f"{str(c['min']):>7} {str(c['max']):>7} {data['total_words']:>6}"
        )

    print("\nNOTE: confidence is a triage signal only. No accuracy figure is")
    print("reported because this dataset has no ground-truth transcriptions.")


if __name__ == "__main__":
    main()
