"""
verify_heldout
================

Evaluation on HELD-OUT receipts only (`ground_truth/heldout_*.json`).

These images were transcribed after the implementation was complete and
were never inspected while writing or tuning any threshold, regex, weight
or gate. Their scores are therefore an honest estimate of behaviour on an
arbitrary new upload, unlike the development-set benchmark, where the same
images informed the fixes being measured.

Runs the real public entry point (`process_receipt`) with both local
engines, and reuses `benchmark_extraction`'s scorer so numbers are
comparable with the development-set report.

Outputs
---------
    data/output/heldout_verification/heldout_report.csv
    data/output/heldout_verification/heldout_summary.md
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
from benchmark_extraction import (  # noqa: E402
    MONEY_FIELDS, SCALAR_FIELDS, _money_equal, _text_equal, score_result,
)

GROUND_TRUTH_DIR = Path("ground_truth")
OUT_DIR = Path("data/output/heldout_verification")


def main() -> None:
    truth_files = sorted(GROUND_TRUTH_DIR.glob("heldout_*.json"))
    if not truth_files:
        raise SystemExit("no held-out ground truth found (ground_truth/heldout_*.json)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    engines = [TesseractOcrEngine(), EasyOcrEngine()]
    print(f"held-out receipts: {len(truth_files)}\n")

    rows = []
    fin_hits = fin_total = 0
    false_values = 0
    correct_nulls = 0
    missed_values = 0

    for tf in truth_files:
        truth = json.loads(tf.read_text(encoding="utf-8"))
        image_path = Path(truth["image"])
        if not image_path.is_file():
            print(f"  SKIP {tf.name}: image missing at {image_path}")
            continue

        started = time.perf_counter()
        result = process_receipt(image_path, OUT_DIR / "processed", ocr_engines=engines)
        elapsed = time.perf_counter() - started
        produced = result.to_dict()
        scores = score_result(truth, produced)

        f_h = sum(1 for f in MONEY_FIELDS if scores.get(f) is True) + scores["_item_field_hits"]
        f_t = (
            sum(1 for f in MONEY_FIELDS if scores.get(f) is not None)
            + scores["_item_field_total"]
        )
        fin_hits += f_h
        fin_total += f_t

        # Per-field truthfulness accounting, which matters more here than
        # raw accuracy: a wrong number is the failure this project treats
        # as unacceptable, a null is an acceptable "I don't know".
        row_false = row_correct_null = row_missed = 0
        for field in SCALAR_FIELDS + MONEY_FIELDS:
            if field not in truth:
                continue
            expected, actual = truth[field], produced.get(field)
            equal = _money_equal if field in MONEY_FIELDS else _text_equal
            # An empty/whitespace-only string is treated as "no value",
            # NOT as a match. The shared scorer's vendor comparison allows
            # substring matches in either direction, and an empty string
            # is a substring of everything -- so counting it as a hit
            # would silently inflate these numbers.
            if isinstance(actual, str) and not actual.strip():
                actual = None
            if actual is None:
                if expected is None:
                    row_correct_null += 1
                else:
                    row_missed += 1
            elif not equal(expected, actual):
                row_false += 1
        false_values += row_false
        correct_nulls += row_correct_null
        missed_values += row_missed

        rows.append({
            "image": image_path.name,
            "category": truth.get("category", ""),
            "financial_hits": f_h,
            "financial_total": f_t,
            "false_values": row_false,
            "correct_nulls": row_correct_null,
            "missed_values": row_missed,
            "total_expected": truth.get("total"),
            "total_produced": produced.get("total"),
            "vendor_expected": truth.get("vendor_name"),
            "vendor_produced": produced.get("vendor_name"),
            "needs_review": produced["needs_review"],
            "review_reasons": ";".join(produced["review_reasons"]),
            "overall_confidence": produced["overall_confidence"],
            "seconds": round(elapsed, 2),
        })
        print(
            f"  {image_path.name:<30} fin={f_h}/{f_t} false={row_false} "
            f"missed={row_missed} total={produced.get('total')} "
            f"(truth {truth.get('total')}) review={produced['needs_review']}"
        )

    if not rows:
        raise SystemExit("nothing scored")

    lines = ["# Held-Out Receipt Verification\n"]
    lines.append(
        "These receipts were transcribed AFTER the implementation was finished and "
        "were never used to develop or tune any part of it. No threshold, regex, "
        "weight or gate was changed in response to these results.\n"
    )
    lines.append(f"- Held-out receipts: **{len(rows)}**")
    lines.append("- Pipeline: `process_receipt(..., ocr_engines=[Tesseract, EasyOCR])`")
    lines.append(
        f"- Financial-field accuracy: **{fin_hits}/{fin_total} "
        f"({fin_hits / fin_total * 100:.1f}%)**" if fin_total else "- Financial: n/a"
    )
    lines.append(f"- **Wrong non-null values (silent corruption): {false_values}**")
    lines.append(f"- Correct nulls (field genuinely absent, returned null): {correct_nulls}")
    lines.append(f"- Missed values (present on receipt, returned null): {missed_values}")
    lines.append(
        f"- Receipts flagged `needs_review`: "
        f"**{sum(1 for r in rows if r['needs_review'])}/{len(rows)}**\n"
    )

    lines.append("| Image | Category | Financial | Wrong | Missed | total (got/truth) | review |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['image']} | {r['category']} | {r['financial_hits']}/{r['financial_total']} | "
            f"{r['false_values']} | {r['missed_values']} | "
            f"{r['total_produced']} / {r['total_expected']} | {r['needs_review']} |"
        )

    lines.append(
        "\n> `Wrong` is the metric to watch: it counts non-null values that "
        "disagree with the receipt. `Missed` values are nulls where the receipt "
        "does have a value -- undesirable but safe, and flagged for review."
    )

    (OUT_DIR / "heldout_summary.md").write_text("\n".join(lines), encoding="utf-8")
    with (OUT_DIR / "heldout_report.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nwrote -> {OUT_DIR}")


if __name__ == "__main__":
    main()
