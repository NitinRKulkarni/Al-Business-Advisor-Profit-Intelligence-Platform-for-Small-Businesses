"""
split_collages
===============

Extract the individual invoices out of the `batch2` collage samples.

This is a CROP-ONLY step. No denoising, contrast enhancement, sharpening,
deskew, perspective correction, binarization or OCR happens here — each
output PNG is an untouched sub-rectangle of the source pixels, so the real
preprocessing pipeline still receives raw input.

Layout on disk
---------------
    data/samples/batch2/*.png             originals, never modified
    data/samples/batch2/raw/              copies of the originals (archive)
    data/samples/batch2/individual/       extracted crops
    data/samples/batch2/manifest.csv      one row per crop
    data/samples/batch2/contact_sheets/   one verification sheet per collage

Crops are read from `raw/` rather than from the originals, so the files in
`batch2/` itself are only ever touched by the initial copy.

Every generated artifact lives in a subdirectory so that the top level of
`batch2/` contains nothing but the original collages. That keeps the archive
step honest: it can treat "every PNG directly in batch2/" as the input set
without risk of re-archiving its own output.

Usage
------
    # test one collage first
    python scripts/split_collages.py --only invoice_01.png

    # then everything
    python scripts/split_collages.py --all
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Allow running as a plain script from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.collage_split import (  # noqa: E402
    CollageSplitConfig,
    Tile,
    split_layout,
)

BATCH_DIR = Path("data/samples/batch2")
RAW_DIR = BATCH_DIR / "raw"
INDIVIDUAL_DIR = BATCH_DIR / "individual"
SHEET_DIR = BATCH_DIR / "contact_sheets"
MANIFEST_PATH = BATCH_DIR / "manifest.csv"

OUTPUT_PREFIX = "batch2_invoice_"
MANIFEST_FIELDS = [
    "source_collage",
    "output_filename",
    "row",
    "column",
    "x",
    "y",
    "width",
    "height",
]

# Contact-sheet appearance.
THUMB_MAX_EDGE = 380      # longest thumbnail edge, px — large enough to read headers
LABEL_HEIGHT = 30
CELL_PADDING = 10
SHEET_BACKGROUND = (32, 32, 36)
LABEL_COLOR = (240, 240, 240)
TITLE_HEIGHT = 44


def load_font(size: int) -> ImageFont.ImageFont:
    """Best-effort truetype font, falling back to Pillow's bitmap default."""
    for candidate in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def mirror_originals_to_raw() -> list[Path]:
    """Copy each original collage into `raw/`, leaving the originals in place.

    Returns the `raw/` paths in sorted order. Copy (not move) so the
    originals in `batch2/` stay exactly where the rest of the project
    expects them; `raw/` is an archive of provably-unmodified input.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INDIVIDUAL_DIR.mkdir(parents=True, exist_ok=True)
    SHEET_DIR.mkdir(parents=True, exist_ok=True)

    # Non-recursive glob, and all generated output lives in subdirectories,
    # so this is exactly the set of original collages.
    originals = sorted(p for p in BATCH_DIR.glob("*.png") if p.is_file())
    for source in originals:
        destination = RAW_DIR / source.name
        if not destination.exists() or destination.stat().st_size != source.stat().st_size:
            shutil.copy2(source, destination)
            print(f"  archived {source.name} -> raw/{source.name}")
    return sorted(RAW_DIR.glob("*.png"))


def read_manifest() -> list[dict[str, str]]:
    if not MANIFEST_PATH.exists():
        return []
    with MANIFEST_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_manifest(rows: list[dict[str, object]]) -> None:
    ordered = sorted(
        rows,
        key=lambda r: (str(r["source_collage"]), int(r["row"]), int(r["column"])),
    )
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def build_contact_sheet(
    crops: list[tuple[Tile, str, np.ndarray]],
    source_name: str,
    method: str,
    destination: Path,
) -> None:
    """Render a labelled grid of every crop taken from one collage.

    The sheet preserves the collage's own row/column layout so a
    mis-detected boundary is immediately obvious next to its neighbours.
    Each thumbnail is captioned with the output filename plus its r/c
    position, which is what makes the sheet usable for verification.
    """
    if not crops:
        return

    rows = max(tile.row for tile, _, _ in crops)
    columns = max(tile.column for tile, _, _ in crops)

    # One cell size for the whole sheet, derived from the widest/tallest crop
    # so nothing is cropped further or stretched.
    max_width = max(tile.width for tile, _, _ in crops)
    max_height = max(tile.height for tile, _, _ in crops)
    scale = THUMB_MAX_EDGE / max(max_width, max_height)
    thumb_width = max(1, int(round(max_width * scale)))
    thumb_height = max(1, int(round(max_height * scale)))

    cell_width = thumb_width + CELL_PADDING * 2
    cell_height = thumb_height + LABEL_HEIGHT + CELL_PADDING * 2

    sheet = Image.new(
        "RGB",
        (columns * cell_width, TITLE_HEIGHT + rows * cell_height),
        SHEET_BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(20)
    label_font = load_font(14)

    draw.text(
        (CELL_PADDING, 12),
        f"{source_name} — {len(crops)} crops — layout {columns}x{rows} — {method}",
        fill=LABEL_COLOR,
        font=title_font,
    )

    for tile, filename, crop in crops:
        thumb = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        thumb.thumbnail((thumb_width, thumb_height), Image.LANCZOS)

        cell_x = (tile.column - 1) * cell_width
        cell_y = TITLE_HEIGHT + (tile.row - 1) * cell_height
        offset_x = cell_x + CELL_PADDING + (thumb_width - thumb.width) // 2
        offset_y = cell_y + CELL_PADDING
        sheet.paste(thumb, (offset_x, offset_y))

        caption = f"{filename}  (r{tile.row} c{tile.column})"
        draw.text(
            (cell_x + CELL_PADDING, offset_y + thumb_height + 6),
            caption,
            fill=LABEL_COLOR,
            font=label_font,
        )

    sheet.save(destination)
    print(f"  contact sheet -> {destination}  ({sheet.width}x{sheet.height})")


def split_one(
    raw_path: Path,
    start_index: int,
    config: CollageSplitConfig,
) -> tuple[list[dict[str, object]], int]:
    """Crop one collage, write its PNGs and contact sheet, return manifest rows."""
    image = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"Could not decode {raw_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    tiles, method = split_layout(gray, raw_path.name, config)

    print(f"{raw_path.name}: {len(tiles)} tiles via {method}")
    per_row: dict[int, int] = {}
    for tile in tiles:
        per_row[tile.row] = per_row.get(tile.row, 0) + 1
    print(f"  rows={len(per_row)} columns_per_row={[per_row[k] for k in sorted(per_row)]}")

    rows: list[dict[str, object]] = []
    crops: list[tuple[Tile, str, np.ndarray]] = []
    index = start_index

    for tile in tiles:
        filename = f"{OUTPUT_PREFIX}{index:03d}.png"
        y_slice, x_slice = tile.slices
        crop = image[y_slice, x_slice]

        # Pure crop: no filtering, no resizing, no colour conversion.
        cv2.imwrite(str(INDIVIDUAL_DIR / filename), crop)

        rows.append(
            {
                "source_collage": raw_path.name,
                "output_filename": filename,
                "row": tile.row,
                "column": tile.column,
                "x": tile.x,
                "y": tile.y,
                "width": tile.width,
                "height": tile.height,
            }
        )
        crops.append((tile, filename, crop))
        index += 1

    build_contact_sheet(
        crops,
        raw_path.name,
        method,
        SHEET_DIR / f"contact_sheet_{raw_path.stem}.png",
    )
    return rows, index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--only",
        action="append",
        metavar="FILENAME",
        help="Process just this collage (repeatable). Use for verification runs.",
    )
    group.add_argument("--all", action="store_true", help="Process every collage.")
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="First number used in the output filenames (default: 1).",
    )
    args = parser.parse_args()

    if not BATCH_DIR.is_dir():
        raise SystemExit(f"Expected sample directory not found: {BATCH_DIR.resolve()}")

    print("Archiving originals:")
    raw_paths = mirror_originals_to_raw()
    if not raw_paths:
        raise SystemExit(f"No PNG collages found in {BATCH_DIR.resolve()}")

    if args.all:
        selected = raw_paths
    else:
        by_name = {path.name: path for path in raw_paths}
        missing = [name for name in args.only if name not in by_name]
        if missing:
            raise SystemExit(f"No such collage(s): {', '.join(missing)}")
        selected = [by_name[name] for name in sorted(args.only)]

    print(f"\nSelected {len(selected)} collage(s): {', '.join(p.name for p in selected)}\n")

    config = CollageSplitConfig()

    # Drop any crops a previous run produced for the selected collages, so a
    # re-run with different thresholds cannot leave stale PNGs behind.
    previous = read_manifest()
    selected_names = {path.name for path in selected}
    kept_rows: list[dict[str, object]] = []
    for row in previous:
        if row["source_collage"] in selected_names:
            stale = INDIVIDUAL_DIR / row["output_filename"]
            if stale.exists():
                stale.unlink()
        else:
            kept_rows.append(dict(row))

    new_rows: list[dict[str, object]] = []
    index = args.start_index
    for raw_path in selected:
        rows, index = split_one(raw_path, index, config)
        new_rows.extend(rows)

    write_manifest(kept_rows + new_rows)

    print(f"\n{len(new_rows)} crops written to {INDIVIDUAL_DIR}")
    print(f"manifest -> {MANIFEST_PATH} ({len(kept_rows) + len(new_rows)} rows total)")


if __name__ == "__main__":
    main()
