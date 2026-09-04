"""
ocr_variant_experiment
=======================

TASK 4 -- Controlled comparison of which ALREADY-GENERATED preprocessing
stage image Tesseract reads best, on a small representative subset.

This is deliberately NOT a preprocessing experiment
-----------------------------------------------------
No new preprocessing is performed and no threshold is changed. The
comparison uses only stage images the Phase 1 pipeline already wrote to
disk, so it answers a narrow, safe question: "of the outputs we already
have, which one should be fed to OCR?" Nothing here can alter
preprocessing behaviour.

Variants compared (all three exist for all 156 images, verified):
    A  final.png        -- the pipeline's designated OCR output
    B  grayscale.png    -- grayscale conversion only, before adaptive fixes
    C  thresholded.png  -- the binarization side-branch

`denoised.png` is deliberately NOT included: it exists for only 5 of 156
images, so including it would compare variants on different subsets and
the result would be meaningless.

Honest-comparison safeguards
------------------------------
1. For images whose only operation was `grayscale_conversion`, final.png and
   grayscale.png are byte-identical. The script detects this by hashing and
   reports it, so identical inputs are not presented as a real difference.
2. Confidence alone can be misleading: a variant that returns 3 confident
   words "beats" one returning 60 mixed-quality words on mean confidence
   while being far less useful. Word and character counts are therefore
   reported alongside, and the verdict considers all three.
3. No correctness claim is made -- there is no ground truth for this subset
   beyond the 5 images already manually verified.

Subset selection
-----------------
Ten images chosen by RULE from the existing reports (not hand-picked),
covering the requested quality categories and spread across source
collages. Selection rules and the resulting choices are printed at run
time so the subset is auditable.

Usage
-----
    python scripts/ocr_variant_experiment.py

Output
------
    data/output/ocr_variant_experiment/variant_comparison.csv
    data/output/ocr_variant_experiment/text/<image>__<variant>.txt
"""

from __future__ import annotations

import csv
import hashlib
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import OcrEngine, TesseractOcrEngine  # noqa: E402
from ocr.reporting import load_collage_map, read_records_csv, write_records_csv  # noqa: E402

PREPROCESSED_DIR = Path("data/processed/full_batch2_preprocessing")
MANIFEST = Path("data/samples/batch2/manifest.csv")
QUALITY_CSV = Path("data/output/quality_improved_batch2.csv")
PREP_CSV = Path("data/output/preprocessing_report_full_batch2.csv")
BASELINE_CSV = Path("data/output/ocr_full_batch2_baseline.csv")

OUT_DIR = Path("data/output/ocr_variant_experiment")
TEXT_DIR = OUT_DIR / "text"
OUT_CSV = OUT_DIR / "variant_comparison.csv"

VARIANTS = {
    "A_final": "final.png",
    "B_grayscale": "grayscale.png",
    "C_thresholded": "thresholded.png",
}

CSV_FIELDS = [
    "category",
    "image",
    "source_collage",
    "variant",
    "stage_file",
    "identical_to_final",
    "success",
    "mean_confidence",
    "word_count",
    "character_count",
    "processing_time",
    "error",
]

TARGET_SUBSET_SIZE = 10


def build_engine() -> OcrEngine:
    """Same settings as the baseline run, so numbers stay comparable."""
    return TesseractOcrEngine(language="eng", psm=6, oem=3)


def _load_map(path: Path, key: str = "filename") -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


def select_subset() -> list[tuple[str, str]]:
    """
    Pick ~10 (category, image_stem) pairs by rule from existing reports.

    Each category has an explicit predicate. Within a category, candidates
    are ordered to prefer source collages not yet represented, so the
    subset spans capture conditions rather than clustering in one collage.
    Returns fewer than TARGET_SUBSET_SIZE only if a category has no
    qualifying image, which is reported rather than silently padded.
    """
    quality = _load_map(QUALITY_CSV)
    prep = _load_map(PREP_CSV)
    baseline = {r["filename"]: r for r in read_records_csv(BASELINE_CSV)}
    collage_map = load_collage_map(MANIFEST)

    def info(stem: str) -> dict:
        png = f"{stem}.png"
        q = quality.get(png, {})
        p = prep.get(png, {})
        b = baseline.get(stem, {})
        return {
            "stem": stem,
            "collage": collage_map.get(png, ""),
            "warnings": (q.get("warnings") or "").split(";"),
            "brightness": float(q["brightness"]) if q.get("brightness") else None,
            "ops": (p.get("operations_applied") or "").split(";"),
            "conf": b.get("mean_confidence"),
            "words": b.get("word_count", 0),
        }

    all_info = [info(p.name) for p in sorted(PREPROCESSED_DIR.iterdir()) if p.is_dir()]

    def clear_handwritten(i: dict) -> bool:
        return (
            not any(w for w in i["warnings"])
            and (i["conf"] or 0) >= 55
            and (i["brightness"] or 0) >= 150
        )

    def dark_underexposed(i: dict) -> bool:
        return (i["brightness"] or 999) < 120 and "uneven_lighting_or_shadow" in i["warnings"]

    def low_contrast(i: dict) -> bool:
        return "low_contrast" in i["warnings"]

    def noisy(i: dict) -> bool:
        return "high_noise" in i["warnings"]

    def skewed(i: dict) -> bool:
        return "possible_skew" in i["warnings"] or "deskewed" in i["ops"]

    def perspective(i: dict) -> bool:
        return "perspective_corrected" in i["ops"]

    def zero_word(i: dict) -> bool:
        return int(i["words"] or 0) == 0

    # (category label, predicate, how many to take)
    rules = [
        ("clear_handwritten", clear_handwritten, 2),
        ("dark_underexposed", dark_underexposed, 2),
        ("low_contrast", low_contrast, 1),
        ("noisy", noisy, 2),
        ("skewed", skewed, 1),
        ("perspective", perspective, 1),
        ("zero_word_stress", zero_word, 1),
    ]

    chosen: list[tuple[str, str]] = []
    used_stems: set[str] = set()
    used_collages: list[str] = []

    for label, predicate, want in rules:
        candidates = [i for i in all_info if predicate(i) and i["stem"] not in used_stems]
        # Prefer collages not yet represented, then stable filename order.
        candidates.sort(key=lambda i: (used_collages.count(i["collage"]), i["stem"]))
        taken = 0
        for candidate in candidates:
            if taken >= want:
                break
            chosen.append((label, candidate["stem"]))
            used_stems.add(candidate["stem"])
            used_collages.append(candidate["collage"])
            taken += 1
        if taken < want:
            print(f"  NOTE: category '{label}' yielded only {taken}/{want} candidates")

    return chosen[:TARGET_SUBSET_SIZE]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    engine = build_engine()
    print(f"engine: {engine.name}")
    print(f"variants: {', '.join(f'{k}={v}' for k, v in VARIANTS.items())}")
    print("\nselecting subset by rule from existing reports...")

    subset = select_subset()
    collage_map = load_collage_map(MANIFEST)

    print(f"\nsubset ({len(subset)} images):")
    for category, stem in subset:
        print(f"  {category:<18} {stem}  (collage {collage_map.get(f'{stem}.png', '?')})")

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for category, stem in subset:
        image_dir = PREPROCESSED_DIR / stem
        final_hash = _sha256(image_dir / "final.png")

        print(f"\n=== {category}: {stem} ===")
        for variant, stage_file in VARIANTS.items():
            stage_path = image_dir / stage_file
            if not stage_path.is_file():
                print(f"  {variant:<15} MISSING {stage_file}")
                continue

            identical = (
                variant != "A_final" and _sha256(stage_path) == final_hash
            )
            result = engine.recognize(stage_path)

            (TEXT_DIR / f"{stem}__{variant}.txt").write_text(result.text, encoding="utf-8")

            rows.append({
                "category": category,
                "image": stem,
                "source_collage": collage_map.get(f"{stem}.png", ""),
                "variant": variant,
                "stage_file": stage_file,
                "identical_to_final": identical,
                "success": result.success,
                "mean_confidence": result.mean_confidence,
                "word_count": result.word_count,
                "character_count": len(result.text),
                "processing_time": result.processing_time_seconds,
                "error": result.error or "",
            })

            flag = "  [byte-identical to final]" if identical else ""
            print(
                f"  {variant:<15} conf={str(result.mean_confidence):<7} "
                f"words={result.word_count:<4} chars={len(result.text):<5} "
                f"t={result.processing_time_seconds}s{flag}"
            )

    write_records_csv(rows, OUT_CSV, CSV_FIELDS)
    print(f"\n\nwrote {len(rows)} rows -> {OUT_CSV}")
    print(f"per-variant text -> {TEXT_DIR}")

    # ------------------------------------------------------------- verdict
    print("\n================ VARIANT COMPARISON ================")
    print(f"  {'variant':<15} {'n':>3} {'mean_conf':>10} {'median_conf':>12} "
          f"{'mean_words':>11} {'mean_chars':>11} {'zero_word':>10}")
    per_variant: dict[str, dict] = {}
    for variant in VARIANTS:
        subset_rows = [r for r in rows if r["variant"] == variant and r["success"]]
        confs = [r["mean_confidence"] for r in subset_rows if r["mean_confidence"] is not None]
        words = [r["word_count"] for r in subset_rows]
        chars = [r["character_count"] for r in subset_rows]
        zeros = sum(1 for r in subset_rows if r["word_count"] == 0)
        per_variant[variant] = {
            "mean_conf": round(statistics.mean(confs), 2) if confs else None,
            "median_conf": round(statistics.median(confs), 2) if confs else None,
            "mean_words": round(statistics.mean(words), 2) if words else None,
            "mean_chars": round(statistics.mean(chars), 2) if chars else None,
            "zero_word": zeros,
            "n": len(subset_rows),
        }
        v = per_variant[variant]
        print(f"  {variant:<15} {v['n']:>3} {str(v['mean_conf']):>10} "
              f"{str(v['median_conf']):>12} {str(v['mean_words']):>11} "
              f"{str(v['mean_chars']):>11} {v['zero_word']:>10}")

    # Per-image winner counts, which is more robust than comparing group
    # means across a 10-image subset.
    print("\nper-image winner by confidence (ties -> more words wins):")
    wins: dict[str, int] = dict.fromkeys(VARIANTS, 0)
    for _, stem in subset:
        image_rows = [r for r in rows if r["image"] == stem and r["success"]]
        if not image_rows:
            continue
        best = max(
            image_rows,
            key=lambda r: ((r["mean_confidence"] or -1), r["word_count"]),
        )
        wins[best["variant"]] += 1
        print(f"  {stem}: {best['variant']} "
              f"(conf={best['mean_confidence']} words={best['word_count']})")
    print("\nwin counts:", ", ".join(f"{k}={v}" for k, v in wins.items()))

    identical_count = sum(
        1 for r in rows if r["variant"] == "B_grayscale" and r["identical_to_final"]
    )
    print(
        f"\nNOTE: {identical_count}/{len(subset)} images had grayscale.png "
        f"byte-identical to final.png"
    )
    print("      (those images received only grayscale_conversion, so A and B")
    print("      are literally the same input -- no real comparison there).")
    print("\nNOTE: confidence is not correctness. A variant can win on mean")
    print("      confidence while returning less usable text; word/char counts")
    print("      above are included so that trade-off stays visible.")


if __name__ == "__main__":
    main()
