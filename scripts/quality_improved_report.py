"""
quality_improved_report
=========================

Batch-run the IMPROVED quality_analysis pipeline against every individual
document image, and write a one-row-per-image CSV report plus a console
summary. This is the counterpart to `quality_baseline_report.py`, run
after the foreground/background-aware fixes to low_resolution,
high_noise, document_boundary semantics, and low_contrast.

Read-only: does not modify any image file, does not touch config.py or
collage_split.py, and does not run OCR.

Usage
-----
    python scripts/quality_improved_report.py

Output
------
    data/output/quality_improved_batch2.csv   one row per image

Does NOT overwrite data/output/quality_baseline_batch2.csv.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.quality_analysis import analyze_image_quality  # noqa: E402

INDIVIDUAL_DIR = Path("data/samples/batch2/individual")
OUT_CSV = Path("data/output/quality_improved_batch2.csv")

CSV_FIELDS = [
    "filename",
    "success",
    "width",
    "height",
    "brightness",
    "contrast",
    "blur_score",
    "noise_level",
    "ink_paper_contrast",
    "stroke_width_px",
    "skew_angle",
    "document_detected",
    "document_boundary_status",
    "warnings",
    "error",
]


def main() -> None:
    paths = sorted(INDIVIDUAL_DIR.glob("*.png"))
    if not paths:
        raise SystemExit(f"No PNGs found in {INDIVIDUAL_DIR.resolve()}")

    rows = []
    for path in paths:
        result = analyze_image_quality(path)
        d = result.to_dict()
        d["warnings"] = ";".join(d["warnings"])
        rows.append(d)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in CSV_FIELDS})

    print(f"wrote {len(rows)} rows -> {OUT_CSV}")

    ok = [r for r in rows if r["success"]]
    failed = [r for r in rows if not r["success"]]
    print(f"\nprocessed: {len(rows)}   success: {len(ok)}   failed: {len(failed)}")
    if failed:
        for r in failed:
            print(f"  FAILED {r['filename']}: {r['error']}")

    warning_counts: dict[str, list[str]] = {}
    for r in ok:
        for w in r["warnings"].split(";") if r["warnings"] else []:
            warning_counts.setdefault(w, []).append(r["filename"])

    print("\nwarning counts:")
    for w, files in sorted(warning_counts.items(), key=lambda kv: -len(kv[1])):
        print(f"  {w}: {len(files)}")

    boundary_counts: dict[str, int] = {}
    for r in ok:
        boundary_counts[r["document_boundary_status"]] = boundary_counts.get(r["document_boundary_status"], 0) + 1
    print("\ndocument_boundary_status counts:")
    for status, count in sorted(boundary_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {count}")

    numeric_fields = ["width", "height", "brightness", "contrast", "blur_score"]
    print("\nnumeric metric ranges (success=True only, always populated):")
    for field_name in numeric_fields:
        values = [r[field_name] for r in ok]
        print(f"  {field_name}: min={min(values):.2f} max={max(values):.2f} "
              f"avg={statistics.mean(values):.2f} median={statistics.median(values):.2f}")

    print("\nnumeric metric ranges (nullable; n = count with a value):")
    for field_name in ["noise_level", "ink_paper_contrast", "stroke_width_px"]:
        values = [r[field_name] for r in ok if r[field_name] is not None]
        n_none = len(ok) - len(values)
        if values:
            print(f"  {field_name}: n={len(values)} (None={n_none}) "
                  f"min={min(values):.2f} max={max(values):.2f} "
                  f"avg={statistics.mean(values):.2f} median={statistics.median(values):.2f}")
        else:
            print(f"  {field_name}: n=0 (None={n_none})")

    skew_values = [r["skew_angle"] for r in ok if r["skew_angle"] is not None]
    print(f"  skew_angle (n={len(skew_values)} with a value; "
          f"{len(ok) - len(skew_values)} None): "
          + (f"min={min(skew_values):.2f} max={max(skew_values):.2f} "
             f"avg={statistics.mean(skew_values):.2f}" if skew_values else "no values"))

    doc_detected = sum(1 for r in ok if r["document_detected"])
    print(f"  document_detected=True: {doc_detected}/{len(ok)}")


if __name__ == "__main__":
    main()
