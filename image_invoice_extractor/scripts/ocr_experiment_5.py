"""
ocr_experiment_5
==================

Baseline OCR experiment: run exactly FIVE representative preprocessed
images through the OCR stage and record raw text, confidence, word count,
timing and any errors, so the baseline engine's real-world quality on this
dataset can be judged before committing to it for all 156 images.

Scope guards (deliberate)
--------------------------
- Reads ONLY `final.png` from data/processed/full_batch2_preprocessing/.
- Does not touch image_processing/ (preprocessing, config, collage split)
  or any source image.
- Does not overwrite the existing preprocessing/quality reports; all
  output goes to data/output/ocr_experiment/.
- Does NOT do invoice field extraction. The goal is only:
  preprocessed image -> OCR -> raw text + confidence -> report.

Which five images, and why these
----------------------------------
The five categories are taken from the already-established sample set in
`data/processed/sample_preprocessing/sample_report.csv` rather than picked
fresh, so this experiment is measured on the same images the preprocessing
stage was visually validated against. That file maps a category label
(e.g. "noisy", "low_contrast") to a specific filename; this script reads
those labels rather than hardcoding filenames, so if the sample set is
ever re-generated the experiment follows it automatically.

Engine independence
--------------------
This runner talks only to the `OcrEngine` protocol. Swapping Tesseract for
EasyOCR/TrOCR/a cloud API later means changing the single line in
`build_engine()`; nothing else here needs to move.

Usage
-----
    python scripts/ocr_experiment_5.py

Output
------
    data/output/ocr_experiment/ocr_experiment_report.csv   one row per image
    data/output/ocr_experiment/<name>.txt                  raw OCR text per image
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import OcrEngine, TesseractOcrEngine  # noqa: E402

PREPROCESSED_DIR = Path("data/processed/full_batch2_preprocessing")
SAMPLE_REPORT = Path("data/processed/sample_preprocessing/sample_report.csv")
FULL_REPORT = Path("data/output/preprocessing_report_full_batch2.csv")
OUT_DIR = Path("data/output/ocr_experiment")

# Requested experiment category -> label used in sample_report.csv.
# Keeping this indirection (rather than filenames) means the experiment
# stays pinned to the already-validated sample set by *role*, not by a
# filename that could drift.
CATEGORY_TO_SAMPLE_LABEL = {
    "clear_handwritten": "good_1",
    "dark_underexposed": "low_light_2",
    "low_contrast": "low_contrast",
    "noisy": "noisy",
    "skewed_perspective": "skewed",
}

CSV_FIELDS = [
    "category",
    "source_filename",
    "ocr_input_path",
    "engine",
    "success",
    "mean_confidence",
    "word_count",
    "processing_time_seconds",
    "operations_applied",
    "preprocessing_warnings",
    "error",
]


def build_engine() -> OcrEngine:
    """
    Construct the OCR engine for this experiment.

    Single swap point: returning a different `OcrEngine` implementation
    here is all that is needed to re-run the same experiment on another
    engine.
    """
    return TesseractOcrEngine(language="eng", psm=6, oem=3)


def _load_label_to_filename() -> dict[str, str]:
    """Map sample_report.csv's category label -> source image filename."""
    if not SAMPLE_REPORT.is_file():
        raise SystemExit(f"Expected sample report not found: {SAMPLE_REPORT}")
    with SAMPLE_REPORT.open(newline="", encoding="utf-8") as fh:
        return {row["label"]: row["filename"] for row in csv.DictReader(fh)}


def _load_preprocessing_context() -> dict[str, dict[str, str]]:
    """Map source filename -> its row in the full preprocessing report."""
    if not FULL_REPORT.is_file():
        raise SystemExit(f"Expected preprocessing report not found: {FULL_REPORT}")
    with FULL_REPORT.open(newline="", encoding="utf-8") as fh:
        return {row["filename"]: row for row in csv.DictReader(fh)}


def select_images() -> list[tuple[str, str, Path]]:
    """
    Resolve the five (category, source_filename, final_png_path) triples.

    Fails loudly if any expected label or `final.png` is missing rather
    than silently running on four images.
    """
    label_to_filename = _load_label_to_filename()
    selected: list[tuple[str, str, Path]] = []

    for category, label in CATEGORY_TO_SAMPLE_LABEL.items():
        if label not in label_to_filename:
            raise SystemExit(
                f"Label '{label}' (for category '{category}') not found in {SAMPLE_REPORT}"
            )
        source_filename = label_to_filename[label]
        final_png = PREPROCESSED_DIR / Path(source_filename).stem / "final.png"
        if not final_png.is_file():
            raise SystemExit(f"Preprocessed output missing: {final_png}")
        selected.append((category, source_filename, final_png))

    return selected


def main() -> None:
    engine = build_engine()
    print(f"engine: {engine.name}")

    selected = select_images()
    context = _load_preprocessing_context()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    for category, source_filename, final_png in selected:
        result = engine.recognize(final_png)
        prep = context.get(source_filename, {})

        text_path = OUT_DIR / f"{Path(source_filename).stem}__{category}.txt"
        text_path.write_text(result.text, encoding="utf-8")

        rows.append({
            "category": category,
            "source_filename": source_filename,
            "ocr_input_path": str(final_png).replace("\\", "/"),
            "engine": result.engine,
            "success": result.success,
            "mean_confidence": result.mean_confidence,
            "word_count": result.word_count,
            "processing_time_seconds": result.processing_time_seconds,
            "operations_applied": prep.get("operations_applied", ""),
            "preprocessing_warnings": prep.get("warnings_used_for_decisions", ""),
            "error": result.error or "",
        })

        print(
            f"\n=== {category}  ({source_filename}) ===\n"
            f"  success={result.success} conf={result.mean_confidence} "
            f"words={result.word_count} time={result.processing_time_seconds}s"
            + (f" error={result.error}" if result.error else "")
        )
        print("  --- raw text ---")
        for line in (result.text or "(no text recognized)").splitlines():
            print(f"  | {line}")

    csv_path = OUT_DIR / "ocr_experiment_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nwrote {len(rows)} rows -> {csv_path}")
    print(f"raw text files -> {OUT_DIR}")

    ok = [r for r in rows if r["success"]]
    confs = [r["mean_confidence"] for r in ok if r["mean_confidence"] is not None]
    print(f"\nsucceeded: {len(ok)}/{len(rows)}")
    if confs:
        print(f"mean confidence across images: {sum(confs) / len(confs):.2f}")
        print(f"confidence range: {min(confs):.2f} - {max(confs):.2f}")
    print(f"total words recognized: {sum(r['word_count'] for r in ok)}")


if __name__ == "__main__":
    main()
