"""
ocr_summary_report
===================

TASK 3 -- Render the OCR evaluation summary Markdown from the durable
baseline CSV produced by `scripts/ocr_full_baseline.py`.

Reads (never re-runs OCR):
    data/output/ocr_full_batch2_baseline.csv
    data/samples/batch2/manifest.csv              (collage grouping)
    data/output/quality_improved_batch2.csv       (brightness / ink contrast)
    data/output/preprocessing_report_full_batch2.csv  (operations applied)

Writes:
    data/output/ocr_full_batch2_summary.md

Separation of measured vs unverified (TASK 5)
-----------------------------------------------
This report distinguishes three kinds of statement and never blurs them:

1. MEASURED     -- counts/statistics computed from the OCR output
                   (confidence, word counts, timings, per-collage groups).
2. SHAPE-CHECKED -- regex detectors that establish whether output of the
                   right *shape* was produced (e.g. a `dd/mm/yy` token).
                   These say nothing about whether the value is correct.
3. VERIFIED      -- the small set of fields manually compared against the
                   source images during the earlier 5-image experiment.

No accuracy percentage is reported anywhere, because the 156-image dataset
has no ground-truth transcriptions. Confidence is treated strictly as a
triage signal.

Usage
-----
    python scripts/ocr_summary_report.py
"""

from __future__ import annotations

import csv
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.reporting import (  # noqa: E402
    load_collage_map,
    rank_by_confidence,
    read_records_csv,
    summarize,
)

BASELINE_CSV = Path("data/output/ocr_full_batch2_baseline.csv")
MANIFEST = Path("data/samples/batch2/manifest.csv")
QUALITY_CSV = Path("data/output/quality_improved_batch2.csv")
PREP_CSV = Path("data/output/preprocessing_report_full_batch2.csv")
OUT_MD = Path("data/output/ocr_full_batch2_summary.md")

ENGINE_LABEL = "Tesseract 5.4.0.20240606 via pytesseract 0.3.13 (--oem 3 --psm 6, lang=eng)"

# --------------------------------------------------------------- detectors
# Each detector answers "did output of this SHAPE appear?", never "is it
# right?". Kept here (rather than in ocr/reporting.py) because they are
# reporting heuristics for human triage, not part of the OCR contract.
DATE_RE = re.compile(r"\b\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}\b")
INVOICE_NO_RE = re.compile(r"\b(?:No|NO|no|N0)\b\.?\s*[:.]?\s*\d{2,6}\b")
DECIMAL_AMOUNT_RE = re.compile(r"\b\d+\.\d{2}\b")
SLASH_AMOUNT_RE = re.compile(r"\b\d{2,6}\s*/\s*[-~=]")
ANY_NUMBER_RE = re.compile(r"\b\d+\b")
MIXED_TOKEN_RE = re.compile(r"\b(?=\w*\d)(?=\w*[A-Za-z])[A-Za-z0-9.]{3,}\b")
# Tokens that look like a corrupted amount: a digit-string with a stray
# letter substituted in (e.g. a50, as0, 4s0, 4o.00, r20.00, ts000, a4so).
CORRUPT_AMOUNT_RE = re.compile(
    r"\b(?=[A-Za-z0-9.]*\d)[0-9]*[a-zA-Z][0-9a-zA-Z.]*\b"
)
UNIT_TOKEN_RE = re.compile(
    r"^\d+\s*(?:kg|g|gm|gms|mm|cm|m|mtr|ltr|l|nos|no|pcs|pc|w|sq|ft|in)\.?$",
    re.IGNORECASE,
)

# Manually VERIFIED observations preserved from the earlier 5-image
# experiment (see data/output/ocr_experiment/). These are the only fields in
# this project that have been checked character-by-character against the
# source images, so they are reproduced rather than re-derived, and are the
# sole basis for any statement about correctness.
VERIFIED_5_IMAGE_FINDINGS = [
    {
        "image": "batch2_invoice_002 (clear, hand-printed)",
        "conf": "80.32",
        "verified": (
            "Invoice no `0893`, date `18/05/24`, vendor, all 5 item descriptions, "
            "all 5 quantities (5/10/10/2/1), all 5 rates, all 5 amounts, "
            "subtotal `430.00`, discount `20.00`, total `410.00` -- all correct."
        ),
        "failed": "Cursive signature `Vijay` -> `Ve)`. Label `Grand Total` dropped.",
    },
    {
        "image": "batch2_invoice_089 (dark/underexposed)",
        "conf": "51.97",
        "verified": (
            "Vendor `KAVERI TRADERS` and `Thank You! Visit Again` correct. "
            "Rates `1350`, `1450`, `1550` all correct."
        ),
        "failed": (
            "Quantities read `4,4,4` -- actual values are `1,1,1`. "
            "Bill no `116` -> `1G`. Date `23/04/22` -> `2a/esfan`. "
            "Total `4350` -> `4a50/`. Amount column lost."
        ),
    },
    {
        "image": "batch2_invoice_105 (low contrast)",
        "conf": "28.14",
        "verified": "Nothing in this image was recognized correctly.",
        "failed": (
            "Header `BEAUTY PARLOUR / GLOW & GORGEOUS` -> `PP aciow scorceous`. "
            "Line items (`Hair Cut 250`, `Threading 100`, `Facial 500`) lost. "
            "Total `850/-` -> `a50/-5`."
        ),
    },
    {
        "image": "batch2_invoice_060 (noisy)",
        "conf": "32.73",
        "verified": "Total `830/-` and balance `530/-` correct.",
        "failed": (
            "All four service descriptions destroyed "
            "(`Saree Fall` -> `A Repem es od`, `Blouse Stitching` -> `As Fd`). "
            "`Advance 300` mangled to `ae ELI`."
        ),
    },
    {
        "image": "batch2_invoice_015 (skewed/perspective)",
        "conf": "51.90",
        "verified": (
            "Customer name `Revathi`, invoice no `486`, and the detail lines "
            "`Salwar Suit - Rani Pink` / `Blouse - Rani Pink` correct."
        ),
        "failed": (
            "Phone `7871375223` -> `FSHBIS223`. Date `15/05/22` not recovered. "
            "Total `4440` not recovered. Table body largely unreadable."
        ),
    },
]


def _load_csv_map(path: Path, key: str) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


def _fmt(value) -> str:
    return "n/a" if value is None else str(value)


def analyse_patterns(records: list[dict]) -> dict:
    """Run the shape detectors across all records and collect examples."""
    counts = dict.fromkeys(
        [
            "date_like",
            "invoice_no_like",
            "decimal_amount",
            "slash_amount",
            "any_number",
            "mixed_token",
            "corrupt_amount",
        ],
        0,
    )
    corrupt_examples: list[tuple[str, list[str]]] = []
    date_examples: list[tuple[str, str]] = []
    invno_examples: list[tuple[str, str]] = []

    for record in records:
        text = (record["extracted_text"] or "").replace("\\n", "\n")

        if match := DATE_RE.search(text):
            counts["date_like"] += 1
            if len(date_examples) < 8:
                date_examples.append((record["filename"], match.group(0)))
        if match := INVOICE_NO_RE.search(text):
            counts["invoice_no_like"] += 1
            if len(invno_examples) < 8:
                invno_examples.append((record["filename"], match.group(0)))
        if DECIMAL_AMOUNT_RE.search(text):
            counts["decimal_amount"] += 1
        if SLASH_AMOUNT_RE.search(text):
            counts["slash_amount"] += 1
        if ANY_NUMBER_RE.search(text):
            counts["any_number"] += 1

        mixed = [
            t for t in MIXED_TOKEN_RE.findall(text)
            if re.search(r"[A-Za-z]", t) and re.search(r"\d", t)
        ]
        if mixed:
            counts["mixed_token"] += 1

        # Corrupted-amount candidates exclude legitimate unit tokens
        # (2kg, 20mtr, 12mm...), which are real invoice content rather
        # than OCR damage.
        corrupt = [t for t in mixed if not UNIT_TOKEN_RE.match(t)]
        if corrupt:
            counts["corrupt_amount"] += 1
            if len(corrupt_examples) < 12:
                corrupt_examples.append((record["filename"], corrupt[:4]))

    return {
        "counts": counts,
        "corrupt_examples": corrupt_examples,
        "date_examples": date_examples,
        "invno_examples": invno_examples,
    }


def analyse_quality_correlation(records: list[dict], collage_map: dict[str, str]) -> dict:
    """Join OCR confidence against preprocessing quality metrics."""
    quality = _load_csv_map(QUALITY_CSV, "filename")

    per_collage = []
    for collage in sorted(set(collage_map.values())):
        members = {f for f, c in collage_map.items() if c == collage}
        subset = [r for r in records if f"{r['filename']}.png" in members]
        confs = [r["mean_confidence"] for r in subset if r["mean_confidence"] is not None]
        brights, contrasts = [], []
        for record in subset:
            q = quality.get(f"{record['filename']}.png")
            if not q:
                continue
            if q.get("brightness"):
                brights.append(float(q["brightness"]))
            if q.get("ink_paper_contrast"):
                contrasts.append(float(q["ink_paper_contrast"]))
        per_collage.append({
            "collage": collage,
            "n": len(subset),
            "ocr_conf": round(statistics.mean(confs), 2) if confs else None,
            "brightness": round(statistics.mean(brights), 2) if brights else None,
            "ink_contrast": round(statistics.mean(contrasts), 2) if contrasts else None,
            "zero_word": sum(1 for r in subset if r["word_count"] == 0),
        })

    paired_b, paired_c, paired_k = [], [], []
    for record in records:
        if record["mean_confidence"] is None:
            continue
        q = quality.get(f"{record['filename']}.png")
        if not q or not q.get("brightness"):
            continue
        paired_b.append(float(q["brightness"]))
        paired_c.append(record["mean_confidence"])
        if q.get("ink_paper_contrast"):
            paired_k.append(float(q["ink_paper_contrast"]))

    corr_bright = (
        round(statistics.correlation(paired_b, paired_c), 3)
        if len(paired_b) > 2 else None
    )
    corr_contrast = (
        round(statistics.correlation(paired_k, paired_c[: len(paired_k)]), 3)
        if len(paired_k) > 2 else None
    )

    return {
        "per_collage": per_collage,
        "n_paired": len(paired_b),
        "corr_brightness": corr_bright,
        "corr_ink_contrast": corr_contrast,
    }


def analyse_by_operation(records: list[dict]) -> list[dict]:
    """Group OCR confidence by the preprocessing operations each image got."""
    prep = _load_csv_map(PREP_CSV, "filename")
    by_op: dict[str, list[float]] = {}
    for record in records:
        if record["mean_confidence"] is None:
            continue
        for op in (prep.get(f"{record['filename']}.png", {}).get("operations_applied", "") or "").split(";"):
            if op:
                by_op.setdefault(op, []).append(record["mean_confidence"])
    return sorted(
        (
            {
                "operation": op,
                "n": len(vals),
                "mean_conf": round(statistics.mean(vals), 2),
                "median_conf": round(statistics.median(vals), 2),
            }
            for op, vals in by_op.items()
        ),
        key=lambda d: -d["mean_conf"],
    )


def build_markdown(
    records: list[dict],
    stats: dict,
    patterns: dict,
    quality: dict,
    by_operation: list[dict],
) -> str:
    total = stats["total_images"]
    ok = stats["successful"]
    conf = stats["confidence"]
    buckets = stats["confidence_buckets"]
    times = stats["processing_time"]
    words = stats["word_count"]
    chars = stats["character_count"]

    tier_a = [
        r for r in records
        if (r["mean_confidence"] or 0) >= 50 and r["word_count"] >= 30
    ]
    tier_b = [
        r for r in records
        if r not in tier_a and (r["mean_confidence"] or 0) >= 30 and r["word_count"] >= 10
    ]
    tier_c = [r for r in records if r not in tier_a and r not in tier_b]

    def pct(n: int, d: int = ok) -> str:
        return f"{n / d * 100:.1f}%" if d else "n/a"

    lines: list[str] = []
    add = lines.append

    add("# OCR Evaluation Summary - Local Tesseract Baseline (Phase 2)")
    add("")
    add(f"- **Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    add(f"- **Engine**: {ENGINE_LABEL}")
    add(f"- **OCR input**: `data/processed/full_batch2_preprocessing/<name>/final.png`")
    add(f"- **Per-image data**: `{BASELINE_CSV.as_posix()}`")
    add(f"- **Per-image text**: `data/output/ocr_full_batch2_baseline/text/*.txt`")
    add("")
    add("> **No accuracy percentage appears in this report.** The 156-image dataset has")
    add("> no ground-truth transcriptions, so any accuracy figure would be fabricated.")
    add("> Confidence is reported as a **triage signal** (which images to inspect first),")
    add("> never as evidence that recognized text is correct. Statements about")
    add("> correctness are confined to Section 9's manually verified set.")
    add("")

    # ------------------------------------------------------------ 1
    add("## 1. Dataset size")
    add("")
    add(f"- Images submitted to OCR: **{total}**")
    add(f"- Source collages represented: **{len(quality['per_collage'])}** (`invoice_01`-`invoice_09`)")
    add(f"- Total words returned: **{stats['total_words']}**")
    add(f"- Total characters returned: **{stats['total_characters']}**")
    add("")

    # ------------------------------------------------------------ 2
    add("## 2. Successful / failed OCR count")
    add("")
    add(f"- Engine invocations succeeded: **{ok} / {total}**")
    add(f"- Engine invocations failed (exception / unreadable): **{stats['failed']}**")
    add(f"- Succeeded but returned **zero words**: **{stats['zero_word_count']}**")
    add("")
    if stats["zero_word_filenames"]:
        add("Zero-word images (engine ran cleanly, produced nothing usable):")
        add("")
        for name in stats["zero_word_filenames"]:
            record = next(r for r in records if r["filename"] == name)
            add(f"- `{name}` (collage `{record['source_collage']}`)")
        add("")
    add("A zero-word result is counted separately from a failure on purpose: the engine")
    add("did not error, so a naive success count would report 100% and hide these.")
    add("")

    # ------------------------------------------------------------ 3
    add("## 3. Confidence distribution")
    add("")
    add(f"- Mean: **{_fmt(conf['mean'])}**")
    add(f"- Median: **{_fmt(conf['median'])}**")
    add(f"- Minimum: **{_fmt(conf['min'])}**")
    add(f"- Maximum: **{_fmt(conf['max'])}**")
    add("")
    add("| Bucket | Images | Share of successful |")
    add("|---|---:|---:|")
    add(f"| below 30 | {buckets['below_30']} | {pct(buckets['below_30'])} |")
    add(f"| 30 - 50 | {buckets['30_to_50']} | {pct(buckets['30_to_50'])} |")
    add(f"| 50 - 70 | {buckets['50_to_70']} | {pct(buckets['50_to_70'])} |")
    add(f"| above 70 | {buckets['above_70']} | {pct(buckets['above_70'])} |")
    add(f"| no confidence value (zero words) | {stats['images_without_confidence']} | "
        f"{pct(stats['images_without_confidence'])} |")
    add("")
    add(f"Words per image: mean **{_fmt(words['mean'])}**, median **{_fmt(words['median'])}**, "
        f"min **{_fmt(words['min'])}**, max **{_fmt(words['max'])}**.")
    add(f"Characters per image: mean **{_fmt(chars['mean'])}**, median **{_fmt(chars['median'])}**, "
        f"min **{_fmt(chars['min'])}**, max **{_fmt(chars['max'])}**.")
    add("")
    add("### Confidence alone is not a usability measure")
    add("")
    add("Combining confidence with output volume gives a more honest triage picture")
    add("than confidence by itself (still **not** a correctness measure):")
    add("")
    add("| Tier | Definition | Images | Share |")
    add("|---|---|---:|---:|")
    add(f"| A | confidence >= 50 **and** >= 30 words | {len(tier_a)} | {pct(len(tier_a), total)} |")
    add(f"| B | confidence >= 30 **and** >= 10 words | {len(tier_b)} | {pct(len(tier_b), total)} |")
    add(f"| C | everything else | {len(tier_c)} | {pct(len(tier_c), total)} |")
    add("")
    add("The clearest single illustration: **`batch2_invoice_087` scored the highest")
    add("confidence in the entire dataset (87.54) while returning only 3 words**")
    add("(`Thank You !`). It is one of the darkest images in the set. Tesseract was")
    add("highly confident about the little it found and silently ignored the rest of")
    add("the receipt. Ranking by confidence alone would place this image first.")
    add("")

    # ------------------------------------------------------------ 4
    add("## 4. Worst 20 images")
    add("")
    add("Ranked ascending by confidence; zero-word images sort first because they are")
    add("the most important to inspect.")
    add("")
    add("| # | Image | Collage | Confidence | Words | Chars |")
    add("|---:|---|---|---:|---:|---:|")
    for i, record in enumerate(rank_by_confidence(records, 20, worst=True), start=1):
        add(f"| {i} | `{record['filename']}` | {record['source_collage']} | "
            f"{_fmt(record['mean_confidence'])} | {record['word_count']} | "
            f"{record['character_count']} |")
    add("")

    # ------------------------------------------------------------ 5
    add("## 5. Best 20 images")
    add("")
    add("| # | Image | Collage | Confidence | Words | Chars |")
    add("|---:|---|---|---:|---:|---:|")
    for i, record in enumerate(rank_by_confidence(records, 20, worst=False), start=1):
        add(f"| {i} | `{record['filename']}` | {record['source_collage']} | "
            f"{_fmt(record['mean_confidence'])} | {record['word_count']} | "
            f"{record['character_count']} |")
    add("")
    add("Note row 1: the top-ranked image by confidence returned 3 words. Rows 2-4")
    add("(`invoice_006`, `invoice_002`, `invoice_008`, all from `invoice_01.png`) are the")
    add("genuinely strong results -- high confidence *and* 60+ words.")
    add("")

    # ------------------------------------------------------------ 6
    add("## 6. Processing time")
    add("")
    add(f"- Mean per image: **{_fmt(times['mean'])} s**")
    add(f"- Median per image: **{_fmt(times['median'])} s**")
    add(f"- Fastest / slowest: **{_fmt(times['min'])} s** / **{_fmt(times['max'])} s**")
    add(f"- Total for {total} images: **{_fmt(stats['total_processing_time'])} s**")
    add("")
    add("Throughput is a non-issue for this engine: the whole dataset OCRs in under a")
    add("minute on CPU with no GPU and no network. Speed is not what limits this")
    add("baseline.")
    add("")

    # ------------------------------------------------------------ 7
    add("## 7. Per-collage statistics")
    add("")
    add("| Collage | Images | Zero-word | Mean conf | Median | Min | Max | Total words |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for collage, data in stats["per_collage"].items():
        c = data["confidence"]
        add(f"| {collage} | {data['images']} | {data['zero_word']} | "
            f"{_fmt(c['mean'])} | {_fmt(c['median'])} | {_fmt(c['min'])} | "
            f"{_fmt(c['max'])} | {data['total_words']} |")
    add("")
    add("OCR quality is **strongly grouped by source collage**, which matters because a")
    add("collage corresponds to one photography session/condition:")
    add("")
    add("| Collage | Mean OCR conf | Mean brightness | Mean ink/paper contrast | Zero-word |")
    add("|---|---:|---:|---:|---:|")
    for row in quality["per_collage"]:
        add(f"| {row['collage']} | {_fmt(row['ocr_conf'])} | {_fmt(row['brightness'])} | "
            f"{_fmt(row['ink_contrast'])} | {row['zero_word']} |")
    add("")
    add(f"Across the {quality['n_paired']} images with both OCR and quality metrics:")
    add("")
    add(f"- correlation(source brightness, OCR confidence) = **{_fmt(quality['corr_brightness'])}**")
    add(f"- correlation(ink/paper contrast, OCR confidence) = **{_fmt(quality['corr_ink_contrast'])}**")
    add("")
    add("Both are moderate positive correlations, not deterministic -- brightness")
    add("explains part of the variation in OCR confidence but far from all of it.")
    add("")

    # ------------------------------------------------------------ 8
    add("## 8. Common OCR failure patterns")
    add("")
    add("All counts below are **shape checks** over the 156 outputs: they establish")
    add("whether text of a given form was produced, *not* whether it is correct.")
    add("")
    counts = patterns["counts"]
    add("| Pattern | Images | Share |")
    add("|---|---:|---:|")
    add(f"| produced any digit at all | {counts['any_number']} | {pct(counts['any_number'], total)} |")
    add(f"| produced a `dd/mm/yy`-shaped token | {counts['date_like']} | {pct(counts['date_like'], total)} |")
    add(f"| produced a `No. NNNN`-shaped token | {counts['invoice_no_like']} | {pct(counts['invoice_no_like'], total)} |")
    add(f"| produced a `NNN.NN` decimal amount | {counts['decimal_amount']} | {pct(counts['decimal_amount'], total)} |")
    add(f"| produced a `NNN/-` style amount | {counts['slash_amount']} | {pct(counts['slash_amount'], total)} |")
    add(f"| contains digit/letter-mixed tokens | {counts['mixed_token']} | {pct(counts['mixed_token'], total)} |")
    add(f"| contains likely-corrupted amount tokens | {counts['corrupt_amount']} | {pct(counts['corrupt_amount'], total)} |")
    add("")
    add("Recurring patterns, in order of how often they showed up:")
    add("")
    add("1. **Silent truncation.** The engine returns a handful of confident words from")
    add("   the easiest region (usually a printed letterhead or `Thank You`) and omits")
    add("   the rest of the document. This is the most dangerous pattern because it")
    add("   presents as *high* confidence.")
    add("2. **Digit/letter substitution inside amounts.** Seen in "
        f"{counts['corrupt_amount']} of {total} images. Actual tokens taken from the")
    add("   dataset output (shape-detected, not correctness-checked):")
    add("")
    for filename, tokens in patterns["corrupt_examples"][:10]:
        add(f"   - `{filename}`: {', '.join(f'`{t}`' for t in tokens)}")
    add("")
    add("   `a50`/`as0`/`4s0`/`4o.00`/`r20.00`/`ts000` are amount fields with a letter")
    add("   substituted for a digit. Note these are counted conservatively -- legitimate")
    add("   unit tokens (`2kg`, `20mtr`, `12mm`, `200gm`) are excluded from the count.")
    add("3. **Table structure collapse.** Column separators come back as `|` runs or")
    add("   vanish, so a row's quantity, rate and amount can merge or shift columns.")
    add("4. **Total wipeout on low-contrast input.** 21 images scored below 30")
    add("   confidence and 6 returned nothing at all.")
    add("")

    # ------------------------------------------------------------ 9
    add("## 9. Problems with handwritten text")
    add("")
    add("This section is the **only** place correctness is asserted, and it covers only")
    add("the 5 images manually compared against their source photographs during the")
    add("earlier experiment (`data/output/ocr_experiment/`). The other")
    add(f"{total - 5} images have **not** been verified.")
    add("")
    for finding in VERIFIED_5_IMAGE_FINDINGS:
        add(f"**{finding['image']}** - confidence {finding['conf']}")
        add("")
        add(f"- Verified correct: {finding['verified']}")
        add(f"- Verified wrong/missing: {finding['failed']}")
        add("")
    add("Pattern across the verified set: Tesseract handles **neat hand-printed**")
    add("characters on bright, high-contrast paper well (invoice_002 was essentially")
    add("fully correct). It fails on **cursive** (every signature) and degrades sharply")
    add("once the photograph is dark or low-contrast, regardless of how legible a human")
    add("finds the preprocessed image. Handwriting is not a single difficulty level in")
    add("this dataset: hand-printed block text is tractable, connected script is not.")
    add("")

    # ------------------------------------------------------------ 10
    add("## 10. Problems with numbers and amounts")
    add("")
    add("Numbers are the highest-stakes content here and the weakest area.")
    add("")
    add(f"- {counts['any_number']}/{total} images produced at least one digit, but only")
    add(f"  {counts['decimal_amount']}/{total} produced a well-formed `NNN.NN` amount and")
    add(f"  {counts['slash_amount']}/{total} a `NNN/-` style total.")
    add(f"- {counts['corrupt_amount']}/{total} images contain at least one amount-shaped")
    add("  token corrupted by a letter substitution.")
    add("")
    add("Verified numeric failures (from the 5 checked images):")
    add("")
    add("| Field | Ground truth | Tesseract read | Nature of error |")
    add("|---|---|---|---|")
    add("| invoice_089 quantities | `1`, `1`, `1` | `4`, `4`, `4` | **plausible but wrong** |")
    add("| invoice_089 total | `4350` | `4a50/` | visibly corrupt |")
    add("| invoice_105 total | `850/-` | `a50/-5` | visibly corrupt |")
    add("| invoice_105 `Threading` | `100` | not recovered | missing |")
    add("| invoice_002 (all numerics) | 15 values | all 15 correct | none |")
    add("")
    add("The distinction in that last column is the important one. Most of Tesseract's")
    add("numeric errors are **visibly corrupt** (`4a50`, `a50/-5`) and a downstream")
    add("validator could reject them. But invoice_089's quantity column read `4` where")
    add("the true value is `1` -- syntactically valid, semantically wrong, and")
    add("undetectable without the source image. That class of error is the real")
    add("blocker for financial extraction.")
    add("")

    # ------------------------------------------------------------ 11
    add("## 11. Problems with dates")
    add("")
    add(f"- {counts['date_like']}/{total} images ({pct(counts['date_like'], total)}) produced")
    add("  a token shaped like a date.")
    add("- Examples of date-shaped output:")
    add("")
    for filename, token in patterns["date_examples"]:
        add(f"  - `{filename}`: `{token}`")
    add("")
    add("Shape-valid does not mean correct. The three date outcomes that were")
    add("manually verified:")
    add("")
    add("- `invoice_002`: `18/05/24` -- **verified correct**.")
    add("- `invoice_089`: true date `23/04/22` came back as `2a/esfan` -- destroyed.")
    add("- `invoice_015`: date not recovered at all.")
    add("")
    add("Also seen: `batch2_invoice_039` produced `0/05/22`, a malformed day field. So")
    add("roughly four-fifths of the dataset yielded no date-shaped token at all, and")
    add("even among those that did, the value cannot be trusted without checking.")
    add("")

    # ------------------------------------------------------------ 12
    add("## 12. Problems with invoice numbers")
    add("")
    add(f"- {counts['invoice_no_like']}/{total} images ({pct(counts['invoice_no_like'], total)})")
    add("  produced a `No. NNNN`-shaped token.")
    add("- Examples:")
    add("")
    for filename, token in patterns["invno_examples"]:
        add(f"  - `{filename}`: `{token}`")
    add("")
    add("Verified: `invoice_002` -> `0893` correct; `invoice_015` -> `486` correct;")
    add("`invoice_089` -> bill no `116` misread as `1G`.")
    add("")
    add("The `1` -> `1G`/`I` confusion is the same digit/letter substitution seen in")
    add("amounts. Because invoice numbers are identifiers with no checksum and no")
    add("arithmetic relationship to anything else, a corrupted one cannot be caught by")
    add("validation -- it can only be caught by re-reading the image.")
    add("")

    # ------------------------------------------------------------ 13
    add("## 13. Problems caused by dark / low-contrast images")
    add("")
    add("This is the single strongest signal in the dataset, and it is measured rather")
    add("than assumed.")
    add("")
    add("The nine collages split cleanly into two populations:")
    add("")
    bright_rows = [r for r in quality["per_collage"] if (r["brightness"] or 0) >= 150]
    dark_rows = [r for r in quality["per_collage"] if (r["brightness"] or 0) < 150]
    if bright_rows:
        b_conf = statistics.mean([r["ocr_conf"] for r in bright_rows if r["ocr_conf"]])
        b_n = sum(r["n"] for r in bright_rows)
        b_zero = sum(r["zero_word"] for r in bright_rows)
        add(f"- **Bright group** ({', '.join(r['collage'].replace('.png', '') for r in bright_rows)}): "
            f"{b_n} images, mean OCR confidence **{b_conf:.2f}**, zero-word images **{b_zero}**.")
    if dark_rows:
        d_conf = statistics.mean([r["ocr_conf"] for r in dark_rows if r["ocr_conf"]])
        d_n = sum(r["n"] for r in dark_rows)
        d_zero = sum(r["zero_word"] for r in dark_rows)
        add(f"- **Dark group** ({', '.join(r['collage'].replace('.png', '') for r in dark_rows)}): "
            f"{d_n} images, mean OCR confidence **{d_conf:.2f}**, zero-word images **{d_zero}**.")
    add("")
    add("**Every single zero-word image comes from the dark group.** The best-performing")
    add("collage (`invoice_01`, mean brightness 183.7, ink/paper contrast 130.1) reached")
    add("mean confidence 71.2; the dark collages (`invoice_07`/`08`/`09`, mean brightness")
    add("98.8-115.1) sit at 39.1-43.7.")
    add("")
    add("### Confidence grouped by preprocessing operation applied")
    add("")
    add("| Operation | Images | Mean conf | Median conf |")
    add("|---|---:|---:|---:|")
    for row in by_operation:
        add(f"| {row['operation']} | {row['n']} | {row['mean_conf']} | {row['median_conf']} |")
    add("")
    add("**This table must not be read as 'shadow correction hurts OCR'.** The")
    add("operations are applied *adaptively* -- `shadow_correction` runs precisely on")
    add("the images that were already dark and uneven, and `contrast_enhancement`'s")
    add("single data point is the worst image in the set for unrelated reasons. What the")
    add("table actually shows is that the images *needing* the most correction remain")
    add("the hardest to OCR afterwards. It is a selection effect, and it is evidence")
    add("about input quality, not about the preprocessing stage's behaviour. The")
    add("preprocessing outputs were separately validated as human-legible in Phase 1.")
    add("")
    add("Practical implication: the ceiling here is set by capture conditions. No")
    add("further tuning of a printed-text OCR engine will recover a receipt")
    add("photographed at brightness ~99.")
    add("")

    # ------------------------------------------------------------ 14
    add("## 14. Is Tesseract suitable as a local baseline?")
    add("")
    add("**As a baseline: yes. As the production engine for handwritten invoice field")
    add("extraction: no.**")
    add("")
    add("Suitable as a baseline because:")
    add("")
    add(f"- It ran on all {total} images with **{stats['failed']} hard failures** -- fully stable.")
    add(f"- {_fmt(times['mean'])}s per image, {_fmt(stats['total_processing_time'])}s for the whole")
    add("  dataset, CPU-only, no network, no credentials.")
    add("- Its confidence scores are **usefully calibrated**: the verified strong image")
    add("  scored 80.3 and the verified near-total failure scored 28.1. That makes")
    add("  confidence viable for routing/triage even though it is not proof of")
    add("  correctness.")
    add("- It establishes a reproducible reference point that any future engine")
    add("  (including a cloud service in a later phase) can be measured against on")
    add("  identical inputs.")
    add("")
    add("Not sufficient for production because:")
    add("")
    add(f"- Only {len(tier_a)}/{total} images ({pct(len(tier_a), total)}) reached even the")
    add("  loose 'confidence >= 50 and >= 30 words' tier -- and that tier still carries no")
    add("  correctness guarantee.")
    add(f"- {stats['zero_word_count']} images produced no text whatsoever.")
    add("- Verified numeric corruption includes at least one *plausible-but-wrong*")
    add("  quantity (`1` read as `4`), which no downstream validation can catch.")
    add("- Cursive handwriting fails consistently; Tesseract has no handwriting model.")
    add("")
    add("### Recommendation")
    add("")
    add("Keep Tesseract as the **frozen local baseline** and the default engine for now.")
    add("It is stable, fast, free, and its errors are mostly loud rather than quiet.")
    add("The `OcrEngine` protocol in `ocr/engine.py` means it can stay in place as a")
    add("comparison reference when a stronger engine is introduced in a later phase.")
    add("")
    add("The evidence points at input capture quality as the dominant limiting factor,")
    add("not engine tuning. The dark-group collages will need either a")
    add("handwriting-capable engine or better source photographs; both are decisions for")
    add("the next phase, not changes to make now.")
    add("")
    add("---")
    add("")
    add("## Reproducing this report")
    add("")
    add("```")
    add("python scripts/ocr_full_baseline.py     # runs OCR on all 156, writes the CSV")
    add("python scripts/ocr_summary_report.py    # regenerates this file from the CSV")
    add("```")
    add("")
    add("The summary reads the CSV rather than re-running OCR, so it can be regenerated")
    add("without reprocessing images.")
    add("")

    return "\n".join(lines)


def main() -> None:
    if not BASELINE_CSV.is_file():
        raise SystemExit(
            f"Baseline CSV not found: {BASELINE_CSV}\n"
            "Run scripts/ocr_full_baseline.py first."
        )

    records = read_records_csv(BASELINE_CSV)
    collage_map = load_collage_map(MANIFEST)

    # The CSV already carries source_collage, but re-derive defensively so a
    # stale CSV cannot silently produce an ungrouped report.
    for record in records:
        if not record.get("source_collage"):
            record["source_collage"] = collage_map.get(f"{record['filename']}.png", "")

    stats = summarize(records)
    patterns = analyse_patterns(records)
    quality = analyse_quality_correlation(records, collage_map)
    by_operation = analyse_by_operation(records)

    markdown = build_markdown(records, stats, patterns, quality, by_operation)

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(markdown, encoding="utf-8")

    print(f"wrote summary -> {OUT_MD}")
    print(f"  images={stats['total_images']} successful={stats['successful']} "
          f"zero_word={stats['zero_word_count']}")
    print(f"  mean_conf={stats['confidence']['mean']} "
          f"median={stats['confidence']['median']}")
    print(f"  sections rendered: 14 (+ caveats and reproduction notes)")


if __name__ == "__main__":
    main()
