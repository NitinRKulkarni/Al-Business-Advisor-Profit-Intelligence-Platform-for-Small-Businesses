"""
collage_split
==============

Split composite/collage sample images into their individual invoices.

Why this module exists
-----------------------
The handwritten-invoice samples in `data/samples/batch2/` are not individual
documents: every file is a 1536x1024 collage holding between 8 and 30
separate invoices, receipts and challans laid out in a grid. Running the
preprocessing pipeline on a collage is not merely useless, it is actively
harmful — `data/processed/report.csv` shows perspective correction being
applied to whole collages, which warps 20 unrelated documents to fit one
imagined page quadrilateral (invoice_07 lost ~29% of its height that way).
Everything downstream (quality analysis, deskew, boundary detection, OCR)
assumes exactly one document per image, so the collages must be split
before any of it can produce meaningful numbers.

This module does ONE thing: it works out where the tile boundaries are and
returns those rectangles. It deliberately performs no denoising, contrast
enhancement, sharpening, deskew, perspective correction, binarization or
OCR — the extracted crops are byte-faithful sub-rectangles of the source
pixels, so the real preprocessing pipeline still sees untouched input.

How detection works
--------------------
Collage tiles are separated by thin, near-white gutter lines. The naive
approach — find every column and every row that is bright across the whole
image, and treat that as one global grid — fails on this sample set. In
`invoice_06`, `invoice_07` and `invoice_09` the tiles in row 1 do not have
the same widths as the tiles in row 2, so no vertical line spans the full
image height and global detection finds zero columns.

So detection is two-pass and row-local:

1.  Find *horizontal* gutters by scanning full-width rows.
2.  For each row band independently, rescan using only that band's pixels
    to find the vertical gutters inside it.

That gives each row its own column layout, which is what the sample set
actually contains. A row that yields no vertical gutters is kept as a
single wide tile rather than being silently dropped, so a detection miss
shows up as an obviously-wrong crop in the contact sheet instead of a
missing invoice.

What counts as a gutter
------------------------
The obvious test — "what fraction of this scanline is brighter than X?" —
does not survive contact with these samples. A tile that is itself a
brightly-lit white page (the hole-punched Patel Medicals sheet in
`invoice_01`, for instance) has interior columns that are just as bright as
a real gutter, so a fraction-based test slices that invoice in half. No
single brightness/fraction pair works across all nine collages: the value
needed to keep `invoice_05` intact misses a genuine row break in
`invoice_09`.

What actually distinguishes a gutter is not brightness alone but
*flatness*. A gutter is canvas: a uniform line of near-constant value
along its whole length. A bright page interior always carries ink, ruling,
shadow gradients and paper texture, so its variance along the line is far
higher even when its median is similar. Testing median AND standard
deviation along each scanline separates the two cleanly, and does so over a
broad plateau of threshold values (median 215-240 combined with std 20-55
all give identical, correct results on this sample set) rather than at one
knife-edge setting. That plateau is the reason to prefer this test: it
means the numbers below are not overfitted to these nine files.

Note there is deliberately no special allowance for a wide bright margin at
the image edge. An earlier version granted edge-touching runs a looser
thickness cap on the theory that the collage's outer margin is legitimately
wider than an interior gutter. On `invoice_01` that loophole swallowed the
right-hand 218px of a real invoice. Edge runs are now held to the same thin
cap as interior ones; if a future batch really does have a wide margin, the
cost is only that the margin stays attached to the edge tiles.

Manual layout overrides
------------------------
Brightness-based detection cannot work when the tiles themselves are
edge-to-edge white paper, because the paper is as bright as the gutter.
`invoice_03.png` is exactly that case: 16 documents whose sheets butt
almost edge to edge, so no brightness threshold separates them.

There are two override mechanisms, in precedence order:

`TILE_OVERRIDES` gives explicit per-tile rectangles. This is the strongest
and preferred form, because it can describe a layout that is not a grid at
all. `invoice_03.png` uses it.

`LAYOUT_OVERRIDES` gives a uniform (columns, rows) grid, applied via
`uniform_tiles`. It is retained for a collage whose tiles genuinely are
evenly spaced, but it was *wrong* for `invoice_03.png` and that is worth
recording. The 16 sheets there are hand-placed and slightly rotated: crop
widths actually run 339-453px and heights 226-309px, against 384x256 for a
uniform grid, and the column boundaries shift between rows (the first
vertical separator sits at x=346 in row 1 but x=341 in row 3). Forcing a
uniform grid onto that sliced headers off the row-4 bills and cut the
`Grand Total` / signature lines off several others. A uniform grid is only
safe once the tiles have been confirmed evenly spaced, not merely counted.

Overrides are the documented exception, not a fallback — one is only added
after a human has inspected the boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CollageSplitConfig:
    """Thresholds controlling collage gutter detection.

    STARTING VALUES, calibrated against the nine `batch2` collages only.
    Re-check them if a new batch is added with different gutter styling.
    """

    # Minimum median pixel value along a scanline for it to be gutter-bright.
    # Median rather than mean so that a few dark pixels where a tile
    # overhangs its cell cannot veto an otherwise obvious separator.
    # Verified plateau: 215-240 all behave identically on this sample set,
    # so 235 sits comfortably inside rather than on an edge. Raise it if
    # pale page interiors start being read as gutters (symptom: one invoice
    # split into vertical strips); lower it if dimly-lit collages stop
    # splitting at all (symptom: whole rows emitted as single wide tiles).
    gutter_median_min: float = 235.0

    # Maximum standard deviation along a scanline for it to count as flat.
    # This is the criterion that separates canvas from bright paper: gutter
    # lines are near-constant, page interiors carry ink, ruling and texture.
    # Verified plateau: 20-55 all behave identically here; 30 is mid-range.
    gutter_std_max: float = 30.0

    # Maximum thickness, in pixels, of a gutter run. Real gutters in this
    # sample set are 2-4px, so this is a generous cap whose purpose is to
    # reject any wide flat-bright expanse (a genuinely blank region of page)
    # that passes the median/std test. Applies to edge-touching runs too —
    # see the module docstring on why edges get no special allowance.
    max_gutter_px: int = 40

    # Smallest plausible tile edge in pixels. Bands narrower than this are
    # discarded as detection artifacts (double-drawn gutter lines, stray
    # bright borders) rather than emitted as unusable slivers. Starting
    # value: the tightest real tile in this set is ~195px wide
    # (invoice_09, 6 columns across 1536px), so 110 leaves margin without
    # admitting noise.
    min_tile_px: int = 110


# Collages whose tiles cannot be separated by brightness but ARE evenly
# spaced, mapped to their visually confirmed (columns, rows) uniform grid.
# See the module docstring: confirm even spacing, not just the tile count,
# before adding an entry here. `invoice_03.png` was listed here as (4, 4)
# and that was incorrect; it now has explicit rectangles in TILE_OVERRIDES.
LAYOUT_OVERRIDES: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class Tile:
    """One detected sub-image within a collage.

    `row` and `column` are 1-based positions in the collage layout, where
    `column` is counted within that row (rows may have differing column
    counts). `x`/`y` are the top-left corner in source pixel coordinates.
    """

    row: int
    column: int
    x: int
    y: int
    width: int
    height: int

    @property
    def slices(self) -> tuple[slice, slice]:
        """(y, x) slice pair for cropping a NumPy image array."""
        return (
            slice(self.y, self.y + self.height),
            slice(self.x, self.x + self.width),
        )


# Explicit per-tile rectangles for collages whose layout is neither
# detectable by brightness nor a uniform grid. Takes precedence over
# LAYOUT_OVERRIDES. See the module docstring.
#
# invoice_03.png (1536x1024), 16 documents
# ----------------------------------------
# Boundaries were read off the full-resolution image with a labelled
# coordinate overlay, then refined per cell. The separators here are only
# 1-6px wide and — this is the part that defeats every automatic approach —
# they are not all dark. Where a cream sheet meets the brown backing card
# you get a shadow line, but where two white sheets butt together you get a
# *bright* highlight ridge along the upper sheet's edge. A dark-seam
# detector misses those and lands the boundary ~20px into the next
# document, which is what decapitated the row-4 headers.
#
# Each rectangle was checked three ways before being written down:
#   * every one of the 16 crops rendered whole in a review montage,
#     including its header, table and Grand Total / signature line;
#   * adjacent rectangles leave a positive gap everywhere (3-13px), so no
#     crop can contain part of a neighbouring document;
#   * every dark pixel run touching a crop border was identified as a sheet
#     edge, seam shadow or backing-card wedge — none is pen ink.
#
# The sheets are slightly rotated, so an axis-aligned rectangle that holds a
# whole document unavoidably takes in a small wedge of backing card at some
# corners. That is left in deliberately: deskew and perspective correction
# belong to the preprocessing stage, which must receive uncropped content.
#
# Right edges in column 4 stop where the sheet falls into deep shadow
# (x2 = 1527 / 1530 / 1526 / 1513 by row) rather than following the paper to
# its physical edge; that shadowed strip carries no content.
TILE_OVERRIDES: dict[str, tuple[Tile, ...]] = {
    "invoice_03.png": (
        # row, column,    x,    y,  width, height        vendor / date
        Tile(1, 1,        7,    7,    339,    295),  # Shree Ganesh Stores 12/05
        Tile(1, 2,      358,    0,    348,    306),  # Kaveri Electricals  15/05
        Tile(1, 3,      712,    0,    355,    309),  # Shri Sai Hardware   20/05
        Tile(1, 4,     1079,    0,    448,    302),  # Patel Medicals      22/05

        Tile(2, 1,        0,  310,    347,    248),  # Vijay Book Center   18/05
        Tile(2, 2,      356,  310,    361,    248),  # New Krishna Bakery  25/05
        Tile(2, 3,      720,  313,    352,    242),  # Om Electronics      28/05
        Tile(2, 4,     1077,  307,    453,    248),  # Sagar Mobile Point  30/05

        Tile(3, 1,        1,  562,    340,    228),  # Hotel Annapurna     01/06
        Tile(3, 2,      348,  563,    360,    226),  # Shree Balaji Stny   03/06
        Tile(3, 3,      719,  561,    355,    229),  # Shree Ganesh Stores 04/06
        Tile(3, 4,     1082,  560,    444,    230),  # Pragati Traders     05/06

        Tile(4, 1,        0,  793,    343,    231),  # Shivam Auto Parts   06/06
        Tile(4, 2,      348,  793,    362,    230),  # Fresh Fruits Mart   07/06
        Tile(4, 3,      723,  793,    349,    229),  # Computer Point      08/06
        Tile(4, 4,     1084,  794,    429,    230),  # Meera Tailors       10/06
    ),
}


def _true_runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Return [start, end) index ranges of consecutive True values."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(flags):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _flat_bright_mask(
    region: np.ndarray,
    axis: int,
    config: CollageSplitConfig,
) -> np.ndarray:
    """Mark scanlines that are both bright and flat along their length.

    `axis` is the axis collapsed over, so axis=1 tests rows of `region` and
    axis=0 tests columns. See the module docstring for why flatness, not
    brightness alone, is the discriminator.
    """
    median = np.median(region, axis=axis)
    deviation = region.std(axis=axis)
    return (median >= config.gutter_median_min) & (deviation <= config.gutter_std_max)


def _gutter_runs(
    mask: np.ndarray,
    config: CollageSplitConfig,
) -> list[tuple[int, int]]:
    """Reduce a flat-bright scanline mask to plausible separator runs.

    Runs thicker than `max_gutter_px` are rejected: a separator is a thin
    line, so anything wide is a blank stretch of page and must stay part of
    the tile. Edge-touching runs get no exemption.
    """
    return [
        (start, end)
        for start, end in _true_runs(mask)
        if end - start <= config.max_gutter_px
    ]


def _bands(
    span: int,
    gutters: list[tuple[int, int]],
    config: CollageSplitConfig,
) -> list[tuple[int, int]]:
    """Return the [start, end) content bands lying between gutter runs."""
    bands: list[tuple[int, int]] = []
    cursor = 0
    for start, end in gutters:
        if start - cursor >= config.min_tile_px:
            bands.append((cursor, start))
        cursor = end
    if span - cursor >= config.min_tile_px:
        bands.append((cursor, span))
    return bands


def detect_tiles(
    gray: np.ndarray,
    config: CollageSplitConfig = CollageSplitConfig(),
) -> list[Tile]:
    """Detect collage tiles by row-local gutter analysis.

    Parameters
    ----------
    gray:
        Single-channel (grayscale) collage image, shape (height, width).
    config:
        Detection thresholds.

    Returns
    -------
    list[Tile]
        Tiles in reading order (top-to-bottom, then left-to-right within
        each row). A collage that yields no usable gutters returns a single
        full-frame tile, which is a signal that detection failed rather
        than a claim that the image holds one invoice.
    """
    if gray.ndim != 2:
        raise ValueError(f"detect_tiles expects a 2-D grayscale array, got shape {gray.shape}")

    height, width = gray.shape
    source = gray.astype(np.float64, copy=False)

    # Pass 1: horizontal gutters across the full width give the row bands.
    row_mask = _flat_bright_mask(source, axis=1, config=config)
    row_bands = _bands(height, _gutter_runs(row_mask, config), config)
    if not row_bands:
        row_bands = [(0, height)]

    tiles: list[Tile] = []
    for row_index, (y0, y1) in enumerate(row_bands, start=1):
        # Pass 2: rescan using ONLY this row band's pixels, so each row gets
        # its own column layout. This is the step that makes invoice_06/07/09
        # work, where column widths differ between rows.
        band = source[y0:y1, :]
        column_mask = _flat_bright_mask(band, axis=0, config=config)
        column_bands = _bands(width, _gutter_runs(column_mask, config), config)
        if not column_bands:
            column_bands = [(0, width)]

        for column_index, (x0, x1) in enumerate(column_bands, start=1):
            tiles.append(
                Tile(
                    row=row_index,
                    column=column_index,
                    x=x0,
                    y=y0,
                    width=x1 - x0,
                    height=y1 - y0,
                )
            )
    return tiles


def uniform_tiles(width: int, height: int, columns: int, rows: int) -> list[Tile]:
    """Split a frame into an evenly spaced `columns` x `rows` grid.

    Used for collages listed in `LAYOUT_OVERRIDES`, where the tiles are too
    bright for gutter detection but the layout is known from a manual count.
    Boundaries are rounded so the tiles tile the frame exactly with no
    dropped or double-counted pixel columns.
    """
    if columns < 1 or rows < 1:
        raise ValueError(f"columns and rows must be >= 1, got {columns}x{rows}")

    x_edges = [round(index * width / columns) for index in range(columns + 1)]
    y_edges = [round(index * height / rows) for index in range(rows + 1)]

    tiles: list[Tile] = []
    for row_index in range(rows):
        for column_index in range(columns):
            x0, x1 = x_edges[column_index], x_edges[column_index + 1]
            y0, y1 = y_edges[row_index], y_edges[row_index + 1]
            tiles.append(
                Tile(
                    row=row_index + 1,
                    column=column_index + 1,
                    x=x0,
                    y=y0,
                    width=x1 - x0,
                    height=y1 - y0,
                )
            )
    return tiles


def split_layout(
    gray: np.ndarray,
    source_name: str,
    config: CollageSplitConfig = CollageSplitConfig(),
) -> tuple[list[Tile], str]:
    """Return the tiles for one collage plus the method used.

    Precedence: explicit per-tile rectangles (`TILE_OVERRIDES`), then a
    uniform grid (`LAYOUT_OVERRIDES`), then row-local gutter detection.
    """
    tile_override = TILE_OVERRIDES.get(source_name)
    if tile_override is not None:
        height, width = gray.shape
        for tile in tile_override:
            if (
                tile.x < 0
                or tile.y < 0
                or tile.x + tile.width > width
                or tile.y + tile.height > height
            ):
                raise ValueError(
                    f"{source_name}: override tile r{tile.row}c{tile.column} "
                    f"({tile.x},{tile.y} {tile.width}x{tile.height}) falls "
                    f"outside the {width}x{height} frame"
                )
        return list(tile_override), f"override:explicit-{len(tile_override)}-tiles"

    override = LAYOUT_OVERRIDES.get(source_name)
    if override is not None:
        columns, rows = override
        height, width = gray.shape
        return uniform_tiles(width, height, columns, rows), f"override:{columns}x{rows}"
    return detect_tiles(gray, config), "gutter-detection"
