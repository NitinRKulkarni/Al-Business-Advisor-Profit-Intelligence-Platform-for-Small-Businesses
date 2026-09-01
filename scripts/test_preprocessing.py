"""
test_preprocessing
====================

Batch test driver for Step 4 (image preprocessing).

What this does
---------------
For every image in `data/samples/`:

1. Run quality analysis (`analyze_image_quality`).
2. Run the adaptive preprocessing pipeline (`preprocess_image`), using the
   quality result to decide which corrections apply.
3. Save every stage that was actually produced to
   `data/processed/<image_name>/<stage>.jpg` (no fake/placeholder stages
   for corrections that were skipped).
4. Save a side-by-side ORIGINAL -> FINAL comparison image to
   `data/processed/<image_name>/comparison.jpg`, so the effect of
   preprocessing (or lack of it) can be checked visually.
5. Record one row in a CSV report at `data/processed/report.csv`.

A failure on any single image (corrupted file, unexpected error) is
caught and recorded as a failed row in the report; it does not stop the
rest of the batch.

This script does not perform OCR, does not claim OCR accuracy, and does
not implement any stage beyond image preprocessing.

Usage
-----
    python scripts/test_preprocessing.py
    python scripts/test_preprocessing.py path/to/other/samples_dir
"""

from __future__ import annotations

import csv
import logging
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.config import DEFAULT_CONFIG  # noqa: E402
from image_processing.preprocessing import preprocess_image  # noqa: E402
from image_processing.quality_analysis import analyze_image_quality  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

CSV_FIELDNAMES = [
    "filename",
    "original_width",
    "original_height",
    "operations_applied",
    "final_width",
    "final_height",
    "processing_time",
    "status",
    "warnings",
]


def _build_comparison_image(original: np.ndarray, final: np.ndarray) -> np.ndarray:
    """
    Build a side-by-side ORIGINAL | FINAL comparison image for visual
    review, with each half labeled.

    Both images are resized to a common height (the smaller of the two
    heights, to avoid upscaling) before being placed side by side, since
    preprocessing may have changed the final image's dimensions (resize,
    perspective crop, etc.) relative to the original.
    """
    original_bgr = original if original.ndim == 3 else cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)
    final_bgr = final if final.ndim == 3 else cv2.cvtColor(final, cv2.COLOR_GRAY2BGR)

    target_height = min(original_bgr.shape[0], final_bgr.shape[0], 1000)

    def _resize_to_height(img: np.ndarray, height: int) -> np.ndarray:
        scale = height / img.shape[0]
        width = max(1, int(img.shape[1] * scale))
        return cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)

    left = _resize_to_height(original_bgr, target_height)
    right = _resize_to_height(final_bgr, target_height)

    label_height = 30
    left = cv2.copyMakeBorder(left, label_height, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    right = cv2.copyMakeBorder(right, label_height, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(left, "ORIGINAL", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    cv2.putText(right, "FINAL", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

    separator = np.full((left.shape[0], 4, 3), (0, 0, 0), dtype=np.uint8)
    return np.hstack([left, separator, right])


def process_one_image(image_path: Path, output_dir: Path) -> dict:
    """
    Run quality analysis + preprocessing on one image, save its stages
    and comparison image, and return a CSV-row dict describing the
    outcome. Never raises: any exception is caught and reported as a
    failed row so the batch can continue.
    """
    row = {field_name: "" for field_name in CSV_FIELDNAMES}
    row["filename"] = image_path.name

    try:
        quality_result = analyze_image_quality(image_path, config=DEFAULT_CONFIG)
        prep_result, stages = preprocess_image(
            image_path, config=DEFAULT_CONFIG, quality_result=quality_result
        )

        if not prep_result.success:
            row["status"] = "failed"
            row["warnings"] = prep_result.error or "unknown error"
            return row

        image_output_dir = output_dir / image_path.stem
        image_output_dir.mkdir(parents=True, exist_ok=True)

        for stage_name, stage_image in stages.items():
            stage_path = image_output_dir / f"{stage_name}.jpg"
            cv2.imwrite(str(stage_path), stage_image)

        comparison = _build_comparison_image(stages["original"], stages["final"])
        cv2.imwrite(str(image_output_dir / "comparison.jpg"), comparison)

        row["original_width"] = prep_result.original_width
        row["original_height"] = prep_result.original_height
        row["operations_applied"] = ";".join(prep_result.operations_applied)
        row["final_width"] = prep_result.final_width
        row["final_height"] = prep_result.final_height
        row["processing_time"] = f"{prep_result.processing_time_seconds:.4f}"
        row["status"] = "success"
        row["warnings"] = ";".join(prep_result.warnings)
        return row

    except Exception as exc:  # noqa: BLE001 - intentionally broad: one bad image must not stop the batch
        logger.error("Unexpected error processing %s: %s", image_path.name, exc)
        logger.debug(traceback.format_exc())
        row["status"] = "error"
        row["warnings"] = f"unexpected error: {exc}"
        return row


def run_batch(samples_dir: Path, output_dir: Path) -> list[dict]:
    """Process every supported image file in `samples_dir`; return CSV rows."""
    supported_extensions = DEFAULT_CONFIG.io.supported_extensions
    image_paths = sorted(
        p for p in samples_dir.iterdir()
        if p.is_file() and p.suffix.lower().lstrip(".") in supported_extensions
    )

    if not image_paths:
        print(f"No supported images found in {samples_dir}")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for image_path in image_paths:
        print(f"Processing {image_path.name} ...")
        row = process_one_image(image_path, output_dir)
        rows.append(row)
        print(f"  status={row['status']} operations={row['operations_applied']!r}")

    return rows


def write_csv_report(rows: list[dict], output_dir: Path) -> Path:
    """Write the batch results to `output_dir/report.csv`."""
    report_path = output_dir / "report.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return report_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    samples_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLES_DIR
    output_dir = DEFAULT_OUTPUT_DIR

    if not samples_dir.is_dir():
        print(f"Samples directory not found: {samples_dir}")
        return 2

    rows = run_batch(samples_dir, output_dir)
    if not rows:
        return 1

    report_path = write_csv_report(rows, output_dir)

    success_count = sum(1 for r in rows if r["status"] == "success")
    print(f"\nProcessed {len(rows)} image(s): {success_count} succeeded, {len(rows) - success_count} failed.")
    print(f"Report written to: {report_path}")
    print(f"Stage outputs written under: {output_dir}")

    return 0 if success_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
