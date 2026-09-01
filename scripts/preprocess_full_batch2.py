"""
preprocess_full_batch2
========================

Run the EXISTING, UNMODIFIED adaptive preprocessing pipeline
(`image_processing.preprocessing.preprocess_image`) once across every one
of the 156 individual document crops produced by the collage splitter,
and write:

  1. Per-image preprocessing outputs (every stage that was actually
     applied, plus "original" and "final") to a new, dedicated directory
     that does not collide with anything already on disk.
  2. A single CSV report, one row per image, with: filename,
     success/failure, original dimensions, final dimensions, operations
     applied, the quality-analysis warnings that drove those operations,
     and any error/note.
  3. A console summary counting how many images received each
     preprocessing operation.

This script is read-only with respect to source images (only reads from
data/samples/batch2/individual/) and does not touch:
  - image_processing/collage_split.py
  - image_processing/preprocessing.py (or any other pipeline module)
  - data/output/quality_baseline_batch2.csv
  - data/output/quality_improved_batch2.csv
  - data/processed/report.csv (the earlier 9-collage run)

Quality analysis is not re-run as a reporting step here (no new quality
CSV is produced). `preprocess_image()` still needs a
`QualityAnalysisResult` to decide which adaptive stages to run — that is
an internal dependency of the preprocessing pipeline itself (mirrors how
`scripts/preprocess_sample.py` already does it), not a second quality
report.

Usage
-----
    python scripts/preprocess_full_batch2.py

Output
------
    data/processed/full_batch2_preprocessing/<filename_stem>/*.png   per-image stages
    data/output/preprocessing_report_full_batch2.csv                  one row per image
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.config import DEFAULT_CONFIG  # noqa: E402
from image_processing.preprocessing import preprocess_image  # noqa: E402
from image_processing.quality_analysis import analyze_image_quality  # noqa: E402

INDIVIDUAL_DIR = Path("data/samples/batch2/individual")
STAGE_OUT_DIR = Path("data/processed/full_batch2_preprocessing")
REPORT_CSV = Path("data/output/preprocessing_report_full_batch2.csv")

CSV_FIELDS = [
    "filename",
    "success",
    "original_width",
    "original_height",
    "final_width",
    "final_height",
    "operations_applied",
    "warnings_used_for_decisions",
    "errors_notes",
]


def main() -> None:
    paths = sorted(INDIVIDUAL_DIR.glob("*.png"))
    if not paths:
        raise SystemExit(f"No PNGs found in {INDIVIDUAL_DIR.resolve()}")

    STAGE_OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    operation_counts: dict[str, int] = {}
    failures = []

    for path in paths:
        quality_result = analyze_image_quality(path, config=DEFAULT_CONFIG)
        prep_result, stages = preprocess_image(path, config=DEFAULT_CONFIG, quality_result=quality_result)

        if prep_result.success:
            image_dir = STAGE_OUT_DIR / path.stem
            image_dir.mkdir(parents=True, exist_ok=True)
            for stage_name, stage_image in stages.items():
                cv2.imwrite(str(image_dir / f"{stage_name}.png"), stage_image)
            for op in prep_result.operations_applied:
                operation_counts[op] = operation_counts.get(op, 0) + 1
        else:
            failures.append((path.name, prep_result.error))

        rows.append({
            "filename": path.name,
            "success": prep_result.success,
            "original_width": prep_result.original_width,
            "original_height": prep_result.original_height,
            "final_width": prep_result.final_width,
            "final_height": prep_result.final_height,
            "operations_applied": ";".join(prep_result.operations_applied),
            "warnings_used_for_decisions": ";".join(quality_result.warnings),
            "errors_notes": ";".join(
                w for w in prep_result.warnings if w not in quality_result.warnings
            ) or (prep_result.error or ""),
        })

    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows -> {REPORT_CSV}")
    print(f"per-image stage outputs -> {STAGE_OUT_DIR}")

    ok = [r for r in rows if r["success"]]
    print(f"\nprocessed: {len(rows)}   success: {len(ok)}   failed: {len(failures)}")
    if failures:
        for filename, error in failures:
            print(f"  FAILED {filename}: {error}")

    print("\noperation counts (across successfully processed images):")
    for op, count in sorted(operation_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {op}: {count}")


if __name__ == "__main__":
    main()
