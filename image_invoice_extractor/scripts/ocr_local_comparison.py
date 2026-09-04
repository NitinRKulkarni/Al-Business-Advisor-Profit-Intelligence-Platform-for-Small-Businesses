"""
ocr_local_comparison
======================

Phase 3 -- compare Tesseract vs EasyOCR on a small, reproducibly-selected
10-image subset. Does not touch preprocessing, does not call any cloud
OCR API, does not reinstall/upgrade any package.

Selection is driven by the existing baseline CSV + quality CSV (not
random), covering: clear handwritten, dark/underexposed, skewed/
perspective, noisy, low contrast, spread across collages, plus a couple
of numeric-heavy invoices.

Outputs:
    data/output/ocr_local_comparison/selected_images.csv
    data/output/ocr_local_comparison/comparison.csv
    data/output/ocr_local_comparison/text/<filename>_<engine>.txt
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import EasyOcrEngine, TesseractOcrEngine  # noqa: E402
from ocr.reporting import load_collage_map, read_records_csv, write_records_csv  # noqa: E402

PREPROCESSED_DIR = Path("data/processed/full_batch2_preprocessing")
MANIFEST = Path("data/samples/batch2/manifest.csv")
QUALITY_CSV = Path("data/output/quality_improved_batch2.csv")
BASELINE_CSV = Path("data/output/ocr_full_batch2_baseline.csv")

OUT_DIR = Path("data/output/ocr_local_comparison")
TEXT_DIR = OUT_DIR / "text"
SELECTED_CSV = OUT_DIR / "selected_images.csv"
COMPARISON_CSV = OUT_DIR / "comparison.csv"

CSV_FIELDS = [
    "filename", "engine", "success", "mean_confidence", "word_count",
    "character_count", "processing_time", "extracted_text", "error",
]


def _load_map(path: Path, key: str = "filename") -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


def select_subset() -> list[tuple[str, str]]:
    """Rule-based selection of ~10 images from existing reports."""
    quality = _load_map(QUALITY_CSV)
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
            "conf": b.get("mean_confidence"), "words": b.get("word_count", 0),
            "chars": b.get("character_count", 0),
        }

    all_info = [info(p.name) for p in sorted(PREPROCESSED_DIR.iterdir()) if p.is_dir()]

    def clear_handwritten(i):
        return not any(i["warnings"]) and (i["conf"] or 0) >= 55 and (i["brightness"] or 0) >= 150

    def dark_underexposed(i):
        return (i["brightness"] or 999) < 120 and "uneven_lighting_or_shadow" in i["warnings"]

    def skewed_perspective(i):
        return "possible_skew" in i["warnings"]

    def noisy(i):
        return "high_noise" in i["warnings"]

    def low_contrast(i):
        return "low_contrast" in i["warnings"]

    def numeric_heavy(i):
        return int(i["chars"] or 0) >= 250 and int(i["words"] or 0) >= 40

    rules = [
        ("clear_handwritten", clear_handwritten, 2),
        ("dark_underexposed", dark_underexposed, 2),
        ("skewed_perspective", skewed_perspective, 1),
        ("noisy", noisy, 2),
        ("low_contrast", low_contrast, 1),
        ("numeric_heavy", numeric_heavy, 2),
    ]

    chosen: list[tuple[str, str]] = []
    used: set[str] = set()
    used_collages: list[str] = []
    for label, predicate, want in rules:
        candidates = [i for i in all_info if predicate(i) and i["stem"] not in used]
        candidates.sort(key=lambda i: (used_collages.count(i["collage"]), i["stem"]))
        taken = 0
        for c in candidates:
            if taken >= want:
                break
            chosen.append((label, c["stem"]))
            used.add(c["stem"])
            used_collages.append(c["collage"])
            taken += 1
    return chosen[:10]


def main() -> None:
    subset = select_subset()
    collage_map = load_collage_map(MANIFEST)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    with SELECTED_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["category", "filename", "source_collage"])
        for category, stem in subset:
            writer.writerow([category, stem, collage_map.get(f"{stem}.png", "")])
    print(f"wrote {len(subset)} selections -> {SELECTED_CSV}")
    for category, stem in subset:
        print(f"  {category:<18} {stem}")

    tess = TesseractOcrEngine(language="eng", psm=6, oem=3)
    print(f"\nengine A: {tess.name}")
    print("loading EasyOCR reader (may take a moment)...")
    easy = EasyOcrEngine(languages=("en",), gpu=False, paragraph=False)
    print(f"engine B: {easy.name}")

    rows: list[dict] = []
    for category, stem in subset:
        final_png = PREPROCESSED_DIR / stem / "final.png"
        print(f"\n=== {category}: {stem} ===")
        for engine in (tess, easy):
            result = engine.recognize(final_png)
            tag = "tesseract" if engine is tess else "easyocr"
            (TEXT_DIR / f"{stem}_{tag}.txt").write_text(result.text, encoding="utf-8")
            rows.append({
                "filename": stem, "engine": result.engine, "success": result.success,
                "mean_confidence": result.mean_confidence, "word_count": result.word_count,
                "character_count": len(result.text),
                "processing_time": result.processing_time_seconds,
                "extracted_text": (result.text or "").replace("\r\n", "\n").replace("\n", "\\n"),
                "error": result.error or "",
            })
            print(f"  {tag:<10} conf={result.mean_confidence} words={result.word_count} "
                  f"chars={len(result.text)} t={result.processing_time_seconds}s")

    write_records_csv(rows, COMPARISON_CSV, CSV_FIELDS)
    print(f"\nwrote {len(rows)} rows -> {COMPARISON_CSV}")

    print("\n================ AGGREGATE (NOT accuracy -- confidence/volume only) ================")
    for tag in ("tesseract", "easyocr"):
        subset_rows = [r for r in rows if r["engine"].startswith(tag) and r["success"]]
        confs = [r["mean_confidence"] for r in subset_rows if r["mean_confidence"] is not None]
        words = [r["word_count"] for r in subset_rows]
        times = [r["processing_time"] for r in subset_rows]
        zero = sum(1 for r in subset_rows if r["word_count"] == 0)
        print(f"{tag}: n={len(subset_rows)} "
              f"mean_conf={round(statistics.mean(confs), 2) if confs else None} "
              f"median_conf={round(statistics.median(confs), 2) if confs else None} "
              f"mean_words={round(statistics.mean(words), 2) if words else None} "
              f"mean_time={round(statistics.mean(times), 3) if times else None}s "
              f"zero_word={zero}")

    print("\nper-image winner by confidence (tie -> more words):")
    for category, stem in subset:
        image_rows = [r for r in rows if r["filename"] == stem and r["success"]]
        if not image_rows:
            continue
        best = max(image_rows, key=lambda r: ((r["mean_confidence"] or -1), r["word_count"]))
        print(f"  {stem}: {best['engine']} (conf={best['mean_confidence']} words={best['word_count']})")


if __name__ == "__main__":
    main()
