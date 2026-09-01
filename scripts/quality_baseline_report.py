"""
quality_baseline_report
=========================

Batch-run the EXISTING, UNMODIFIED quality_analysis pipeline against every
individual document image produced by the collage splitter, and write a
one-row-per-image CSV report plus a console summary.

This is a read-only reporting tool for the baseline step: it does not
change any image file, does not touch config.py or collage_split.py, and
does not run OCR. It only calls `analyze_image_quality()` (imported as-is
from image_processing.quality_analysis) and records what comes back.

Usage
-----
    python scripts/quality_baseline_report.py

Output
------
    data/output/quality_baseline_batch2.csv   one row per image
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.quality_analysis import analyze_image_quality  # noqa: E402

INDIVIDUAL_DIR = Path("data/samples/batch2/individual")
OUT_CSV = Path("data/output/quality_baseline_batch2.csv")

CSV_FIELDS = [
    "filename",
    "success",
    "width",
    "height",
    "brightness",
    "contrast",
    "blur_score",
    "noise_level",
    "skew_angle",
    "document_detected",
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

    # ---------------------------------------------------------- summary
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

    print("\nwarning -> filenames:")
    for w, files in sorted(warning_counts.items(), key=lambda kv: -len(kv[1])):
        print(f"  {w} ({len(files)}): {', '.join(files)}")

    numeric_fields = ["width", "height", "brightness", "contrast", "blur_score",
                       "noise_level"]
    print("\nnumeric metric ranges (success=True only):")
    for field_name in numeric_fields:
        values = [r[field_name] for r in ok]
        print(f"  {field_name}: min={min(values):.2f} max={max(values):.2f} "
              f"avg={statistics.mean(values):.2f} median={statistics.median(values):.2f}")

    skew_values = [r["skew_angle"] for r in ok if r["skew_angle"] is not None]
    print(f"  skew_angle (n={len(skew_values)} with a value; "
          f"{len(ok) - len(skew_values)} None): "
          + (f"min={min(skew_values):.2f} max={max(skew_values):.2f} "
             f"avg={statistics.mean(skew_values):.2f}" if skew_values else "no values"))

    doc_detected = sum(1 for r in ok if r["document_detected"])
    print(f"  document_detected=True: {doc_detected}/{len(ok)}")

    # Distribution by source collage (prefix before the numeric range),
    # useful context for the "new problems vs collage-level" question.
    print("\nwarning counts by source collage (invoice_01..09, by filename number range):")


if __name__ == "__main__":
    main()
