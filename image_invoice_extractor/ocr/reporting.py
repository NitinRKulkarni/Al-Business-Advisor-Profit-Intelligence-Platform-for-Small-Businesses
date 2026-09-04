"""
reporting
==========

Aggregation and report-writing helpers for the OCR stage.

Why this is a module rather than inline script code
----------------------------------------------------
The batch scripts need to bucket confidences, group by source collage, and
compute distribution statistics. Putting that logic in a script would make
it untestable, and these are exactly the calculations that must not be
quietly wrong -- a mis-bucketed confidence or a mis-parsed collage mapping
would silently distort the evaluation the whole phase depends on. Keeping
it here lets `tests/test_ocr_reporting.py` exercise it directly.

Deliberate non-goal: correctness scoring
------------------------------------------
Nothing here computes or reports an "accuracy" figure. There are no
ground-truth transcriptions for the 156-image dataset, so any percentage
would be fabricated. Confidence is treated strictly as a *triage signal*
(which images to look at first), never as evidence that text is correct.
`summarize()` returns confidence distributions and counts only.
"""

from __future__ import annotations

import csv
import statistics
from collections.abc import Iterable, Sequence
from pathlib import Path

# One row per image. `extracted_text` is included per the reporting
# requirement; newlines inside it are escaped (see `escape_text`) so the
# CSV stays strictly one physical line per image and remains greppable.
BASELINE_CSV_FIELDS = [
    "filename",
    "source_image",
    "source_collage",
    "preprocessing_output",
    "success",
    "mean_confidence",
    "word_count",
    "character_count",
    "processing_time",
    "extracted_text",
    "error",
]

# Confidence bucket edges, as requested: <30, 30-50, 50-70, >70.
# Lower bound inclusive, upper bound exclusive, except the top bucket.
CONFIDENCE_BUCKETS = ("below_30", "30_to_50", "50_to_70", "above_70")


def escape_text(text: str) -> str:
    r"""
    Flatten OCR text to a single CSV cell.

    Newlines become the two-character sequence ``\n`` and carriage returns
    are dropped, so one image is always exactly one CSV row. The unescaped
    text is always also written to its own .txt file, so no information is
    lost by this transformation.
    """
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def load_collage_map(manifest_path: str | Path) -> dict[str, str]:
    """
    Map individual crop filename -> source collage filename.

    Read from the collage splitter's own manifest rather than inferred from
    filename numbering: the crops-per-collage count varies (8, 12, 16, 15,
    30...), so any numeric-range heuristic would silently mis-assign images.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"Collage manifest not found: {path}")

    with path.open(newline="", encoding="utf-8") as fh:
        return {
            row["output_filename"]: row["source_collage"]
            for row in csv.DictReader(fh)
        }


def bucket_confidence(confidence: float | None) -> str | None:
    """
    Return the bucket name for a confidence value, or None if there is no
    confidence to bucket.

    None (rather than a "0" bucket) for missing confidence: an image where
    OCR returned no words at all is a different situation from one that
    returned words it was 0% sure about, and collapsing them would hide
    the zero-word failures that `summarize()` counts separately.
    """
    if confidence is None:
        return None
    if confidence < 30:
        return "below_30"
    if confidence < 50:
        return "30_to_50"
    if confidence < 70:
        return "50_to_70"
    return "above_70"


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    """Mean/median/min/max for a numeric series, tolerant of emptiness."""
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def summarize(records: Iterable[dict]) -> dict:
    """
    Compute the evaluation statistics for a set of per-image OCR records.

    Expects each record to carry at least: success, mean_confidence,
    word_count, character_count, processing_time, source_collage.

    Returns a plain dict (JSON-serializable) so it can be logged, asserted
    against in tests, or rendered to Markdown without further conversion.
    """
    records = list(records)

    successes = [r for r in records if r["success"]]
    failures = [r for r in records if not r["success"]]

    confidences = [
        float(r["mean_confidence"])
        for r in successes
        if r.get("mean_confidence") is not None
    ]
    word_counts = [int(r["word_count"]) for r in successes]
    char_counts = [int(r["character_count"]) for r in successes]
    times = [float(r["processing_time"]) for r in records]

    # A successful OCR call that recognized nothing is a distinct and
    # important failure mode -- the engine ran fine but produced no usable
    # output -- so it is counted separately from `failures`.
    zero_word_images = [r["filename"] for r in successes if int(r["word_count"]) == 0]

    bucket_counts = dict.fromkeys(CONFIDENCE_BUCKETS, 0)
    no_confidence = 0
    for record in successes:
        bucket = bucket_confidence(
            None
            if record.get("mean_confidence") is None
            else float(record["mean_confidence"])
        )
        if bucket is None:
            no_confidence += 1
        else:
            bucket_counts[bucket] += 1

    per_collage: dict[str, dict] = {}
    for collage in sorted({r.get("source_collage", "") for r in records if r.get("source_collage")}):
        subset = [r for r in records if r.get("source_collage") == collage]
        subset_ok = [r for r in subset if r["success"]]
        subset_confs = [
            float(r["mean_confidence"])
            for r in subset_ok
            if r.get("mean_confidence") is not None
        ]
        per_collage[collage] = {
            "images": len(subset),
            "success": len(subset_ok),
            "failed": len(subset) - len(subset_ok),
            "zero_word": sum(1 for r in subset_ok if int(r["word_count"]) == 0),
            "confidence": _stats(subset_confs),
            "total_words": sum(int(r["word_count"]) for r in subset_ok),
            "mean_words": (
                round(statistics.mean([int(r["word_count"]) for r in subset_ok]), 2)
                if subset_ok
                else None
            ),
        }

    return {
        "total_images": len(records),
        "successful": len(successes),
        "failed": len(failures),
        "failed_filenames": [r["filename"] for r in failures],
        "zero_word_count": len(zero_word_images),
        "zero_word_filenames": zero_word_images,
        "images_without_confidence": no_confidence,
        "confidence": _stats(confidences),
        "confidence_buckets": bucket_counts,
        "word_count": _stats([float(w) for w in word_counts]),
        "total_words": sum(word_counts),
        "character_count": _stats([float(c) for c in char_counts]),
        "total_characters": sum(char_counts),
        "processing_time": _stats(times),
        "total_processing_time": round(sum(times), 2),
        "per_collage": per_collage,
    }


def rank_by_confidence(
    records: Iterable[dict],
    count: int,
    worst: bool = True,
) -> list[dict]:
    """
    Return the `count` best or worst records by mean confidence.

    Records with no confidence value are treated as the worst possible so
    that zero-output images surface in the "worst" list rather than being
    silently skipped -- they are the most important ones to inspect.
    """
    scored = [
        (
            -1.0 if r.get("mean_confidence") is None else float(r["mean_confidence"]),
            r,
        )
        for r in records
        if r["success"]
    ]
    scored.sort(key=lambda pair: pair[0], reverse=not worst)
    return [record for _, record in scored[:count]]


def write_records_csv(
    records: Iterable[dict],
    path: str | Path,
    fields: Sequence[str] = BASELINE_CSV_FIELDS,
) -> Path:
    """Write per-image records to CSV, creating parent directories."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    return out_path


def read_records_csv(path: str | Path) -> list[dict]:
    """
    Read a baseline CSV back into records with numeric/bool fields restored.

    Needed because the summary report is generated as a separate step from
    the OCR run, so it must be able to re-read the CSV without re-running
    OCR on 156 images.
    """
    out: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            record = dict(row)
            record["success"] = row["success"] == "True"
            record["mean_confidence"] = (
                float(row["mean_confidence"]) if row["mean_confidence"] else None
            )
            record["word_count"] = int(row["word_count"] or 0)
            record["character_count"] = int(row["character_count"] or 0)
            record["processing_time"] = float(row["processing_time"] or 0.0)
            out.append(record)
    return out
