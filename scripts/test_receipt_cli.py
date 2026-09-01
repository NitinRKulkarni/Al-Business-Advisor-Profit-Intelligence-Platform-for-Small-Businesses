"""
test_receipt_cli
==================

Developer verification tool: run ONE receipt image through the existing,
unmodified pipeline

    image -> preprocessing -> OCR -> structured extraction -> validation

and print the resulting `ExtractionResult` as formatted JSON.

This is not part of the application. It exists so the image-processing /
OCR / extraction work can be checked by hand against a real receipt
without touching the UI, a database, or any other team member's code. The
eventual real flow (UI upload -> this pipeline -> teammate's DB/business
logic) is unaffected by this script.

Reuses `receipt_extraction.process_receipt` exactly as-is -- no
preprocessing, OCR, or extraction logic is duplicated here. The source
image is never modified; processed output is written to an isolated
directory under `data/output/` (created if needed), separate from the
156-image dataset.

Usage
-----
    python scripts/test_receipt_cli.py path/to/receipt.jpg

    # optional: choose where the processed (preprocessed) image is written
    python scripts/test_receipt_cli.py path/to/receipt.jpg --output-dir data/output/my_test_run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from receipt_extraction import process_receipt  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("data/output/cli_test_runs")

_ENGINE_FACTORIES = {
    "tesseract": lambda: __import__("ocr", fromlist=["TesseractOcrEngine"]).TesseractOcrEngine(),
    "easyocr": lambda: __import__("ocr", fromlist=["EasyOcrEngine"]).EasyOcrEngine(),
}

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _print_highlights(data: dict) -> None:
    """Human-readable summary of the fields called out as important."""
    print("\n--- key fields -------------------------------------------")
    print(f"vendor_name           : {data['vendor_name']}")
    print(f"invoice_number        : {data['invoice_number']}")
    print(f"receipt_number        : {data['receipt_number']}")
    print(f"date                  : {data['date']}")
    print(f"subtotal              : {data['subtotal']}")
    print(f"discount              : {data['discount']}")
    print(f"tax                   : {data['tax']}")
    print(f"total                 : {data['total']}")
    print(f"ocr_confidence        : {data['ocr_confidence']}")
    print(f"extraction_confidence : {data['extraction_confidence']}")

    print("\n--- line items --------------------------------------------")
    if data["items"]:
        for i, item in enumerate(data["items"], start=1):
            print(
                f"  {i}. {item['description']!r:<30} "
                f"qty={item['quantity']}  unit_price={item['unit_price']}  "
                f"amount={item['amount']}"
            )
    else:
        print("  (none extracted)")

    print("\n--- validation warnings ------------------------------------")
    if data["warnings"]:
        for w in data["warnings"]:
            print(f"  - {w}")
    else:
        print("  (none)")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Developer tool: run one receipt image through the existing "
            "preprocessing -> OCR -> extraction -> validation pipeline and "
            "print the structured result as JSON."
        )
    )
    parser.add_argument("image_path", help="Path to a single receipt/invoice image (.jpg/.jpeg/.png)")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Where the preprocessed image is written (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--engines",
        default="tesseract",
        help=(
            "Comma-separated OCR engines to use. Default 'tesseract' (single-engine, "
            "original behavior). Use 'tesseract,easyocr' to enable multi-engine "
            "reconciliation. Available: " + ", ".join(_ENGINE_FACTORIES)
        ),
    )
    args = parser.parse_args()

    image_path = Path(args.image_path)

    if not image_path.exists():
        print(f"ERROR: file not found: {image_path}", file=sys.stderr)
        return 1
    if not image_path.is_file():
        print(f"ERROR: not a file: {image_path}", file=sys.stderr)
        return 1
    if image_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(
            f"ERROR: unsupported file type '{image_path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            file=sys.stderr,
        )
        return 1

    engine_names = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in engine_names if e not in _ENGINE_FACTORIES]
    if unknown:
        print(f"ERROR: unknown engine(s) {unknown}. Available: {list(_ENGINE_FACTORIES)}", file=sys.stderr)
        return 1

    if len(engine_names) > 1:
        engines = [_ENGINE_FACTORIES[name]() for name in engine_names]
        result = process_receipt(image_path, args.output_dir, ocr_engines=engines)
    else:
        engine = _ENGINE_FACTORIES[engine_names[0]]()
        result = process_receipt(image_path, args.output_dir, ocr_engine=engine)
    data = result.to_dict()

    if not data["success"]:
        print(f"Pipeline did not succeed: {data['error']}", file=sys.stderr)
        # Still print whatever structure exists (all fields will be
        # null/empty per the "don't guess" contract) so the failure mode
        # is visible, then exit non-zero.
        print(json.dumps(data, indent=2))
        return 2

    print(json.dumps(data, indent=2))
    _print_highlights(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
