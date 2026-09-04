"""
ocr_compare_5
===============

Run a second OCR engine (EasyOCR) over the EXACT same five representative
images used for the Tesseract baseline, and emit a side-by-side comparison
so the two engines can be judged on identical inputs.

Why it reuses `ocr_experiment_5`
---------------------------------
Image selection, the category labels, and the preprocessing-context lookup
are imported from `scripts/ocr_experiment_5.py` rather than duplicated.
That guarantees the comparison runs on the same five `final.png` files the
baseline used — if the selection logic were copy-pasted it could drift and
silently invalidate the comparison.

Scope guards (deliberate)
--------------------------
- Reads only the five `final.png` files; no preprocessing is re-run.
- Does not modify image_processing/ (preprocessing, config, collage split)
  or `TesseractOcrEngine`.
- Does not overwrite the baseline report; writes alongside it.
- Does NOT do invoice field extraction. Output is raw text + confidence.
- Runs 5 images only, never all 156.

Usage
-----
    python scripts/ocr_compare_5.py

Output
------
    data/output/ocr_experiment/ocr_comparison_report.csv    one row per image/engine pair
    data/output/ocr_experiment/easyocr/<name>.txt           raw EasyOCR text per image
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import EasyOcrEngine, OcrEngine, TesseractOcrEngine  # noqa: E402
from scripts.ocr_experiment_5 import (  # noqa: E402
    OUT_DIR as BASELINE_OUT_DIR,
    _load_preprocessing_context,
    select_images,
)

EASYOCR_TEXT_DIR = BASELINE_OUT_DIR / "easyocr"
COMPARISON_CSV = BASELINE_OUT_DIR / "ocr_comparison_report.csv"

CSV_FIELDS = [
    "category",
    "source_filename",
    "engine",
    "success",
    "mean_confidence",
    "word_count",
    "processing_time_seconds",
    "operations_applied",
    "error",
]


def build_new_engine() -> OcrEngine:
    """
    Construct the challenger engine.

    Single swap point, mirroring `ocr_experiment_5.build_engine()`: any
    future engine that satisfies `OcrEngine` can be dropped in here without
    touching the rest of this script.
    """
    return EasyOcrEngine(languages=("en",), gpu=False, paragraph=False)


def main() -> None:
    selected = select_images()
    context = _load_preprocessing_context()

    # Tesseract is re-run rather than read back from the baseline CSV so
    # both engines are measured in the same process on the same machine
    # state — timings are then comparable rather than being from two
    # different runs.
    baseline_engine: OcrEngine = TesseractOcrEngine(language="eng", psm=6, oem=3)
    print(f"baseline engine : {baseline_engine.name}")

    print("loading challenger engine (downloads models on first run)...")
    new_engine = build_new_engine()
    print(f"challenger engine: {new_engine.name}")

    EASYOCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    for category, source_filename, final_png in selected:
        prep = context.get(source_filename, {})
        stem = Path(source_filename).stem

        baseline_result = baseline_engine.recognize(final_png)
        new_result = new_engine.recognize(final_png)

        (EASYOCR_TEXT_DIR / f"{stem}__{category}.txt").write_text(
            new_result.text, encoding="utf-8"
        )

        for result in (baseline_result, new_result):
            rows.append({
                "category": category,
                "source_filename": source_filename,
                "engine": result.engine,
                "success": result.success,
                "mean_confidence": result.mean_confidence,
                "word_count": result.word_count,
                "processing_time_seconds": result.processing_time_seconds,
                "operations_applied": prep.get("operations_applied", ""),
                "error": result.error or "",
            })

        print(f"\n{'=' * 72}")
        print(f"{category}  ({source_filename})")
        print(f"{'=' * 72}")
        for label, result in (("TESSERACT", baseline_result), ("EASYOCR", new_result)):
            print(
                f"\n-- {label} [{result.engine}] "
                f"conf={result.mean_confidence} words={result.word_count} "
                f"time={result.processing_time_seconds}s"
                + (f" ERROR={result.error}" if result.error else "")
            )
            for line in (result.text or "(no text recognized)").splitlines():
                print(f"   | {line}")

    with COMPARISON_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n\nwrote {len(rows)} rows -> {COMPARISON_CSV}")
    print(f"EasyOCR raw text -> {EASYOCR_TEXT_DIR}")

    # ------------------------------------------------------- summary
    print("\nper-engine summary:")
    for engine_name in sorted({r["engine"] for r in rows}):
        subset = [r for r in rows if r["engine"] == engine_name and r["success"]]
        confs = [r["mean_confidence"] for r in subset if r["mean_confidence"] is not None]
        times = [r["processing_time_seconds"] for r in subset]
        words = sum(r["word_count"] for r in subset)

        mean_conf = f"{sum(confs) / len(confs):.2f}" if confs else "n/a"
        conf_range = f"{min(confs):.2f}-{max(confs):.2f}" if confs else "n/a"
        mean_time = f"{sum(times) / len(times):.3f}s" if times else "n/a"

        print(
            f"  {engine_name}: images={len(subset)} mean_conf={mean_conf} "
            f"range={conf_range} total_words={words} mean_time={mean_time}"
        )


if __name__ == "__main__":
    main()
