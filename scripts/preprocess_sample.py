"""
preprocess_sample
====================

Run the adaptive preprocessing pipeline against a small, explicitly named
set of individual document crops (not all 156), and write before/after
comparison images plus a CSV summary for manual review.

Read-only with respect to `data/samples/`: only reads from
data/samples/batch2/individual/. Writes stage outputs and comparisons
under data/processed/sample_preprocessing/ — a dedicated directory,
separate from the pre-existing data/processed/report.csv and
per-collage folders, so nothing already on disk is overwritten.

Usage
-----
    python scripts/preprocess_sample.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.config import DEFAULT_CONFIG  # noqa: E402
from image_processing.preprocessing import preprocess_image  # noqa: E402
from image_processing.quality_analysis import analyze_image_quality  # noqa: E402

INDIVIDUAL_DIR = Path("data/samples/batch2/individual")
OUT_DIR = Path("data/processed/sample_preprocessing")

SAMPLE_FILES = {
    "good_1": "batch2_invoice_002.png",
    "good_2": "batch2_invoice_007.png",
    "low_light_1": "batch2_invoice_088.png",
    "low_light_2": "batch2_invoice_089.png",
    "low_contrast": "batch2_invoice_105.png",
    "noisy": "batch2_invoice_060.png",
    "skewed": "batch2_invoice_015.png",
    "low_resolution": "batch2_invoice_006.png",
}


def _comparison_image(original: np.ndarray, final: np.ndarray) -> np.ndarray:
    original_bgr = original if original.ndim == 3 else cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)
    final_bgr = final if final.ndim == 3 else cv2.cvtColor(final, cv2.COLOR_GRAY2BGR)
    target_height = min(original_bgr.shape[0], final_bgr.shape[0], 500)

    def resize_to(img, h):
        scale = h / img.shape[0]
        return cv2.resize(img, (max(1, int(img.shape[1] * scale)), h), interpolation=cv2.INTER_AREA)

    left = resize_to(original_bgr, target_height)
    right = resize_to(final_bgr, target_height)
    left = cv2.copyMakeBorder(left, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    right = cv2.copyMakeBorder(right, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(left, "ORIGINAL", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
    cv2.putText(right, "FINAL", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
    sep = np.zeros((left.shape[0], 4, 3), np.uint8)
    return np.hstack([left, sep, right])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    for label, filename in SAMPLE_FILES.items():
        path = INDIVIDUAL_DIR / filename
        quality_result = analyze_image_quality(path, config=DEFAULT_CONFIG)
        prep_result, stages = preprocess_image(path, config=DEFAULT_CONFIG, quality_result=quality_result)

        image_dir = OUT_DIR / f"{label}__{path.stem}"
        image_dir.mkdir(parents=True, exist_ok=True)
        for stage_name, stage_image in stages.items():
            cv2.imwrite(str(image_dir / f"{stage_name}.png"), stage_image)
        cv2.imwrite(str(image_dir / "comparison.png"), _comparison_image(stages["original"], stages["final"]))

        print(f"{label:<14} {filename}: operations={prep_result.operations_applied} "
              f"warnings={prep_result.warnings}")

        rows.append({
            "label": label,
            "filename": filename,
            "quality_warnings": ";".join(quality_result.warnings),
            "document_boundary_status": quality_result.document_boundary_status,
            "operations_applied": ";".join(prep_result.operations_applied),
            "preprocessing_notes": ";".join(prep_result.warnings),
            "original_size": f"{prep_result.original_width}x{prep_result.original_height}",
            "final_size": f"{prep_result.final_width}x{prep_result.final_height}",
            "processing_time_s": prep_result.processing_time_seconds,
        })

    csv_path = OUT_DIR / "sample_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows -> {csv_path}")
    print(f"per-image stages/comparisons -> {OUT_DIR}")


if __name__ == "__main__":
    main()
