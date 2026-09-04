"""
batch_receipts_cli
====================

Developer verification tool: run MANY receipt images through the existing,
unmodified pipeline in a single call and summarise the results.

    images -> preprocessing -> OCR -> extraction -> validation -> JSON

This is the batch counterpart to `test_receipt_cli.py` (which handles one
image and prints its full JSON). It exists because `process_receipts()`
already supports batches, but nothing exposed that on the command line.

Reuses `receipt_extraction.process_receipts` exactly as-is -- one call for
the whole batch, so preprocessing/OCR/extraction logic is not duplicated
or re-implemented here. Source images are never modified; processed output
goes to an isolated directory under `data/output/`.

Per-image isolation: `process_receipts` returns one result per input and a
failure on one image does not abort the others, so a corrupt file in a
batch of fifty still leaves forty-nine usable results. Each image reports
its own `success`/`error`.

Usage
-----
    # explicit files
    python scripts/batch_receipts_cli.py a.jpg b.png c.jpeg

    # every image in a folder
    python scripts/batch_receipts_cli.py --dir path/to/folder

    # both engines (enables cross-engine reconciliation)
    python scripts/batch_receipts_cli.py --dir imgs --engines tesseract,easyocr

    # write the combined structured output to a file
    python scripts/batch_receipts_cli.py --dir imgs --json-out results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from receipt_extraction import process_receipts  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("data/output/cli_batch_runs")
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

_ENGINE_FACTORIES = {
    "tesseract": lambda: __import__("ocr", fromlist=["TesseractOcrEngine"]).TesseractOcrEngine(),
    "easyocr": lambda: __import__("ocr", fromlist=["EasyOcrEngine"]).EasyOcrEngine(),
}


def collect_images(paths: list[str], directory: str | None) -> tuple[list[Path], list[str]]:
    """
    Resolve CLI arguments to a de-duplicated, ordered list of image paths.

    Returns (images, problems) rather than raising, so one bad argument
    reports a clear message instead of killing an otherwise valid batch.
    """
    images: list[Path] = []
    problems: list[str] = []

    if directory:
        directory_path = Path(directory)
        if not directory_path.is_dir():
            problems.append(f"not a directory: {directory_path}")
        else:
            found = sorted(
                p for p in directory_path.iterdir()
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )
            if not found:
                problems.append(
                    f"no {'/'.join(sorted(SUPPORTED_EXTENSIONS))} images found in {directory_path}"
                )
            images.extend(found)

    for raw in paths:
        path = Path(raw)
        if not path.exists():
            problems.append(f"file not found: {path}")
        elif not path.is_file():
            problems.append(f"not a file: {path}")
        elif path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            problems.append(f"unsupported file type '{path.suffix}': {path}")
        else:
            images.append(path)

    # De-duplicate while preserving order (a file can arrive both
    # explicitly and via --dir).
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in images:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)

    return unique, problems


def _print_summary(results) -> None:
    """One line per receipt, then batch totals."""
    print("\n--- batch summary ------------------------------------------")
    header = (
        f"{'source':<30} {'ok':<4} {'total':>10} {'subtot':>9} "
        f"{'tax':>8} {'disc':>8} {'items':>6} {'review':>7} {'conf':>6}"
    )
    print(header)
    print("-" * len(header))

    def fmt(value) -> str:
        return "-" if value is None else f"{value:g}"

    for result in results:
        data = result.to_dict()
        print(
            f"{data['source'][:30]:<30} "
            f"{('yes' if data['success'] else 'NO'):<4} "
            f"{fmt(data['total']):>10} "
            f"{fmt(data['subtotal']):>9} "
            f"{fmt(data['tax']):>8} "
            f"{fmt(data['discount']):>8} "
            f"{len(data['items']):>6} "
            f"{('YES' if data['needs_review'] else 'no'):>7} "
            f"{fmt(data['overall_confidence']):>6}"
        )

    succeeded = sum(1 for r in results if r.success)
    with_total = sum(1 for r in results if r.receipt.total is not None)
    needs_review = sum(1 for r in results if r.needs_review)
    print("-" * len(header))
    print(f"images processed      : {len(results)}")
    print(f"pipeline succeeded    : {succeeded}/{len(results)}")
    print(f"total extracted       : {with_total}/{len(results)}")
    print(f"flagged needs_review  : {needs_review}/{len(results)}")
    print(
        "\nNote: a null field means the value could not be established "
        "reliably.\nIt is never a guess -- see that image's `warnings` and "
        "`field_decisions`."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Developer tool: run MANY receipt images through the existing "
            "preprocessing -> OCR -> extraction -> validation pipeline and "
            "summarise the structured results."
        )
    )
    parser.add_argument(
        "image_paths", nargs="*",
        help="One or more receipt/invoice image paths (.jpg/.jpeg/.png)",
    )
    parser.add_argument(
        "--dir",
        help="Process every supported image in this directory (non-recursive)",
    )
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR),
        help=f"Where preprocessed images are written (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--engines", default="tesseract",
        help=(
            "Comma-separated OCR engines. Default 'tesseract'. Use "
            "'tesseract,easyocr' to enable cross-engine reconciliation. "
            "Available: " + ", ".join(_ENGINE_FACTORIES)
        ),
    )
    parser.add_argument(
        "--json-out",
        help="Write the combined structured results to this JSON file",
    )
    parser.add_argument(
        "--grouped", action="store_true",
        help="Use the nested to_grouped_dict() contract instead of the flat one",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print only the summary table, not per-image JSON",
    )
    args = parser.parse_args()

    if not args.image_paths and not args.dir:
        print("ERROR: provide image paths, or --dir DIRECTORY", file=sys.stderr)
        return 1

    images, problems = collect_images(args.image_paths, args.dir)
    for problem in problems:
        print(f"WARNING: skipping -- {problem}", file=sys.stderr)
    if not images:
        print("ERROR: no usable images to process", file=sys.stderr)
        return 1

    engine_names = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in engine_names if e not in _ENGINE_FACTORIES]
    if unknown:
        print(
            f"ERROR: unknown engine(s) {unknown}. Available: {list(_ENGINE_FACTORIES)}",
            file=sys.stderr,
        )
        return 1

    print(f"processing {len(images)} image(s) with engines: {', '.join(engine_names)}")

    # Engines are constructed ONCE and reused across the whole batch --
    # EasyOCR loads ~100MB of weights on construction, so building one per
    # image would dominate the runtime.
    if len(engine_names) > 1:
        engines = [_ENGINE_FACTORIES[name]() for name in engine_names]
        results = process_receipts(images, args.output_dir, ocr_engines=engines)
    else:
        engine = _ENGINE_FACTORIES[engine_names[0]]()
        results = process_receipts(images, args.output_dir, ocr_engine=engine)

    payload = [
        (r.to_grouped_dict() if args.grouped else r.to_dict())
        for r in results
    ]

    if not args.quiet:
        print(json.dumps(payload, indent=2))

    _print_summary(results)

    if args.json_out:
        out_path = Path(args.json_out)
        if out_path.parent != Path(""):
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote structured results -> {out_path}")

    # Non-zero exit only if EVERY image failed; a partially successful
    # batch is a success from the caller's point of view because each
    # result carries its own status.
    return 0 if any(r.success for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
