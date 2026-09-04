"""
benchmark_variants
====================

Measures the effect of multi-variant OCR (`use_variants=True`) against the
single-variant baseline, on the same hand-verified ground truth used by
`benchmark_extraction.py`, and using the identical scoring functions
(imported, not reimplemented, so the two reports are comparable).

Both arms run the FULL public pipeline via `process_receipt`, with both
local engines, so what is measured is the real end-to-end behaviour a
caller gets -- not a hand-assembled approximation of it.

Outputs
---------
    data/output/variant_benchmark/variant_comparison.csv
    data/output/variant_benchmark/variant_summary.md
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import EasyOcrEngine, TesseractOcrEngine  # noqa: E402
from receipt_extraction import process_receipt  # noqa: E402

# Reuse the existing scorer so numbers are directly comparable with the
# main benchmark rather than being computed by a second, subtly different
# implementation.
from benchmark_extraction import MONEY_FIELDS, SCALAR_FIELDS, score_result  # noqa: E402

GROUND_TRUTH_DIR = Path("ground_truth")
OUT_DIR = Path("data/output/variant_benchmark")


def _financial_hits(scores: dict) -> tuple[int, int]:
    hits = sum(1 for f in MONEY_FIELDS if scores.get(f) is True)
    total = sum(1 for f in MONEY_FIELDS if scores.get(f) is not None)
    return hits + scores["_item_field_hits"], total + scores["_item_field_total"]


def _all_field_hits(scores: dict) -> tuple[int, int]:
    checked = [v for k, v in scores.items() if not k.startswith("_") and v is not None]
    return sum(checked), len(checked)


def _false_value_count(truth: dict, produced: dict) -> int:
    """
    Count fields where a NON-NULL value was produced that disagrees with
    ground truth. This is the metric that matters most for this project:
    a wrong number is worse than a null, so it is tracked separately from
    plain accuracy (where a null and a wrong value both just count as
    "not a hit").
    """
    from benchmark_extraction import _money_equal, _text_equal
    false_values = 0
    for field in SCALAR_FIELDS:
        if field not in truth:
            continue
        actual = produced.get(field)
        if actual is not None and not _text_equal(truth[field], actual):
            false_values += 1
    for field in MONEY_FIELDS:
        if field not in truth:
            continue
        actual = produced.get(field)
        if actual is not None and not _money_equal(truth[field], actual):
            false_values += 1
    return false_values


def _null_count(truth: dict, produced: dict) -> int:
    """Fields that ground truth HAS a value for but the pipeline returned null."""
    nulls = 0
    for field in SCALAR_FIELDS + MONEY_FIELDS:
        if field not in truth or truth[field] is None:
            continue
        if produced.get(field) is None:
            nulls += 1
    return nulls


def main() -> None:
    truth_files = sorted(GROUND_TRUTH_DIR.glob("*.json"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tess = TesseractOcrEngine()
    easy = EasyOcrEngine()
    engines = [tess, easy]
    print(f"engines: {tess.name}, {easy.name}")
    print(f"ground truth receipts: {len(truth_files)}\n")

    rows = []
    for tf in truth_files:
        truth = json.loads(tf.read_text(encoding="utf-8"))
        image_path = Path(truth["image"])
        if not image_path.is_file():
            print(f"  SKIP {tf.name}: image missing")
            continue

        record = {"image": image_path.name, "category": truth.get("category", "")}

        for label, use_variants in (("baseline", False), ("variants", True)):
            started = time.perf_counter()
            result = process_receipt(
                image_path,
                OUT_DIR / f"processed_{label}",
                ocr_engines=engines,
                use_variants=use_variants,
            )
            elapsed = time.perf_counter() - started
            produced = result.to_dict()
            scores = score_result(truth, produced)

            fin_hits, fin_total = _financial_hits(scores)
            all_hits, all_total = _all_field_hits(scores)

            record[f"{label}_financial_hits"] = fin_hits
            record[f"{label}_financial_total"] = fin_total
            record[f"{label}_field_hits"] = all_hits
            record[f"{label}_field_total"] = all_total
            record[f"{label}_false_values"] = _false_value_count(truth, produced)
            record[f"{label}_nulls_where_truth_has_value"] = _null_count(truth, produced)
            record[f"{label}_needs_review"] = produced["needs_review"]
            record[f"{label}_seconds"] = round(elapsed, 2)
            record[f"{label}_variant_notes"] = ";".join(
                w for w in produced["warnings"]
                if "variant_selected" in w or "non_default_variant_preferred" in w
            )

        rows.append(record)
        print(
            f"  {image_path.name:<34} "
            f"baseline fin={record['baseline_financial_hits']}/{record['baseline_financial_total']} "
            f"false={record['baseline_false_values']} {record['baseline_seconds']}s | "
            f"variants fin={record['variants_financial_hits']}/{record['variants_financial_total']} "
            f"false={record['variants_false_values']} {record['variants_seconds']}s"
        )

    if not rows:
        raise SystemExit("nothing scored")

    def total(key: str) -> int:
        return sum(r[key] for r in rows)

    lines = ["# Multi-Variant OCR vs Single-Variant Baseline\n"]
    lines.append(f"- Receipts (hand-verified ground truth): **{len(rows)}**")
    lines.append("- Both arms: full `process_receipt` pipeline, both local engines")
    lines.append("- `baseline` = `use_variants=False` (original single preprocessing variant)")
    lines.append("- `variants` = `use_variants=True` (quality-gated variants, evidence-based selection)\n")

    lines.append("| Metric | BASELINE | VARIANTS |")
    lines.append("|---|---|---|")
    for label, key_h, key_t in (
        ("Financial-field accuracy", "financial_hits", "financial_total"),
        ("All-field accuracy", "field_hits", "field_total"),
    ):
        b_h, b_t = total(f"baseline_{key_h}"), total(f"baseline_{key_t}")
        v_h, v_t = total(f"variants_{key_h}"), total(f"variants_{key_t}")
        lines.append(
            f"| {label} | {b_h}/{b_t} ({b_h / b_t * 100:.1f}%) | "
            f"{v_h}/{v_t} ({v_h / v_t * 100:.1f}%) |"
        )

    lines.append(
        f"| **False (wrong non-null) values** | **{total('baseline_false_values')}** | "
        f"**{total('variants_false_values')}** |"
    )
    lines.append(
        f"| Nulls where truth has a value | {total('baseline_nulls_where_truth_has_value')} | "
        f"{total('variants_nulls_where_truth_has_value')} |"
    )
    lines.append(
        f"| Total runtime (s) | {total('baseline_seconds'):.0f} | {total('variants_seconds'):.0f} |"
    )

    lines.append("\n## Per-receipt\n")
    lines.append("| Image | Category | Base fin | Var fin | Base false | Var false | Variant chosen |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        chosen = r["variants_variant_notes"] or "-"
        chosen = chosen.replace("|", "/")[:80]
        lines.append(
            f"| {r['image']} | {r['category']} | "
            f"{r['baseline_financial_hits']}/{r['baseline_financial_total']} | "
            f"{r['variants_financial_hits']}/{r['variants_financial_total']} | "
            f"{r['baseline_false_values']} | {r['variants_false_values']} | {chosen} |"
        )

    lines.append(
        "\n> Most important column pair is `false` (wrong non-null values). "
        "A change that raises accuracy while also raising false values is NOT "
        "an improvement for this project."
    )

    (OUT_DIR / "variant_summary.md").write_text("\n".join(lines), encoding="utf-8")
    with (OUT_DIR / "variant_comparison.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nwrote -> {OUT_DIR}")


if __name__ == "__main__":
    main()
