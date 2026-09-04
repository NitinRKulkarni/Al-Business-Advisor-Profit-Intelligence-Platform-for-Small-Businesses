"""
layout
=======

Spatial (coordinate-based) reasoning over `OcrToken`s.

Why this module exists
------------------------
The original extractor parsed structure purely from OCR *text lines*. That
fails on real receipts in two specific, measured ways:

1. **Column association.** A table row like
   `Back Cover  1  200.00  200.00` becomes unrecoverable once OCR mangles
   the whitespace/rules between cells: a whitespace split cannot tell
   which number is the quantity and which is the rate. Reading values by
   their **x-position relative to the detected column** is robust to that,
   because a value stays under its own header regardless of how the
   intervening separators were rendered.

2. **Label/value association.** `Grand Total` at (x=500,y=700) and
   `1121.00` at (x=700,y=700) belong together even if OCR emits them in
   different text lines or in the wrong order. Matching by row proximity
   recovers the pair; text-order matching does not.

Everything here is geometry over generic token positions -- there are no
vendor names, no fixed pixel coordinates, and no per-receipt rules, so it
applies unchanged to an unseen receipt of a different layout.

Graceful degradation
----------------------
Every function tolerates an empty token list. When an engine supplies no
geometry, callers fall back to the existing text-based parsing rather than
failing, so adding this module cannot regress an engine that lacks boxes.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from ocr.engine import OcrToken

# A token is treated as being on the same visual row as another when their
# vertical centres differ by less than this fraction of the median token
# height. Expressed relative to token height (not absolute pixels) so it
# scales across the very different resolutions this pipeline handles
# (~200px crops through ~1500px phone photos).
_ROW_TOLERANCE_HEIGHT_FRACTION = 0.6

# Header keywords that identify each logical table column. Matched
# case-insensitively as substrings of a token, and deliberately generic:
# these are standard receipt/invoice column names, not strings taken from
# any particular document in the dataset.
_COLUMN_HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "description": ("particular", "description", "item", "product", "goods", "service"),
    "quantity": ("qty", "quantity", "nos", "no.of", "pcs"),
    "unit_price": ("rate", "price", "unitprice", "mrp", "per"),
    "amount": ("amount", "amt", "value", "total"),
}

_NUMERIC_TOKEN_RE = re.compile(r"^[\d.,]+$")


@dataclass
class TextRow:
    """Tokens sharing a visual row, ordered left-to-right."""

    tokens: list[OcrToken]

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)

    @property
    def center_y(self) -> float:
        return statistics.mean(t.center_y for t in self.tokens)

    @property
    def top(self) -> int:
        return min(t.top for t in self.tokens)

    @property
    def bottom(self) -> int:
        return max(t.bottom for t in self.tokens)

    def numeric_tokens(self) -> list[OcrToken]:
        return [t for t in self.tokens if _NUMERIC_TOKEN_RE.match(t.text.strip())]


@dataclass
class ColumnBand:
    """Horizontal x-range of a detected table column."""

    name: str
    left: float
    right: float

    def contains(self, token: OcrToken) -> bool:
        return self.left <= token.center_x <= self.right


def group_tokens_into_rows(tokens: list[OcrToken]) -> list[TextRow]:
    """
    Cluster tokens into visual rows by vertical position.

    Uses a tolerance proportional to the median token height rather than a
    fixed pixel value, so the same logic works on a small crop and a large
    phone photo without retuning.
    """
    if not tokens:
        return []

    median_height = statistics.median([t.height for t in tokens if t.height > 0] or [10])
    tolerance = max(median_height * _ROW_TOLERANCE_HEIGHT_FRACTION, 2.0)

    ordered = sorted(tokens, key=lambda t: (t.center_y, t.left))
    rows: list[list[OcrToken]] = []
    for token in ordered:
        if rows and abs(token.center_y - statistics.mean(t.center_y for t in rows[-1])) <= tolerance:
            rows[-1].append(token)
        else:
            rows.append([token])

    return [TextRow(sorted(row, key=lambda t: t.left)) for row in rows]


def detect_column_bands(rows: list[TextRow]) -> list[ColumnBand]:
    """
    Find the table's column x-ranges from its header row.

    Looks for the row containing the most distinct column-header keywords
    (a real header row names several columns at once, so this is a strong
    and layout-independent signal). Each header token's x-centre seeds a
    band; band boundaries are placed midway between adjacent headers, so a
    value is assigned to whichever header it sits closest under.

    Returns [] when no plausible header row exists (e.g. a receipt with no
    tabular section) -- callers then skip column-based item extraction
    rather than guessing.
    """
    best_row: TextRow | None = None
    best_hits: dict[str, OcrToken] = {}

    for row in rows:
        hits: dict[str, OcrToken] = {}
        for token in row.tokens:
            normalized = re.sub(r"[^a-z.]", "", token.text.lower())
            if not normalized:
                continue
            for column, keywords in _COLUMN_HEADER_KEYWORDS.items():
                if column in hits:
                    continue
                if any(keyword in normalized for keyword in keywords):
                    hits[column] = token
                    break
        # Require at least two distinct column names: a single stray word
        # like "Total" appears in summary rows too and is not a header.
        if len(hits) >= 2 and len(hits) > len(best_hits):
            best_hits = hits
            best_row = row

    if best_row is None or not best_hits:
        return []

    seeds = sorted(((token.center_x, name) for name, token in best_hits.items()))
    bands: list[ColumnBand] = []
    for index, (center_x, name) in enumerate(seeds):
        left = float("-inf") if index == 0 else (seeds[index - 1][0] + center_x) / 2.0
        right = float("inf") if index == len(seeds) - 1 else (seeds[index + 1][0] + center_x) / 2.0
        bands.append(ColumnBand(name=name, left=left, right=right))

    return bands


def infer_column_bands_from_alignment(rows: list[TextRow]) -> list[ColumnBand]:
    """
    Infer table columns from the x-alignment of numeric tokens, WITHOUT
    needing a recognized header row.

    Why this is necessary
    -----------------------
    Measured on this project's own dataset: Tesseract frequently fails to
    recognize the table header line at all (the `Sl./Particulars/Qty./
    Rate/Amount` row is simply absent from the OCR output on several
    receipts), so header-keyword column detection cannot fire. But the
    *data* rows are still geometrically aligned -- every amount sits in one
    vertical band, every rate in another. Clustering numeric x-centres
    recovers those bands directly from the data.

    Naming is assigned RIGHT-TO-LEFT as amount -> unit_price -> quantity,
    which reflects the near-universal receipt/invoice convention that the
    rightmost money column is the line amount and the leftmost numeric
    column is the count. Any further-left numeric cluster (typically the
    serial-number column) is deliberately left unnamed so it cannot be
    mistaken for a quantity.

    This is a layout convention, not a per-receipt rule: it holds for any
    receipt whose columns run description -> qty -> rate -> amount, and it
    degrades to [] (caller falls back to text parsing) when too few
    aligned numeric rows exist to infer anything.
    """
    summary_re = re.compile(
        r"\b(total|subtotal|discount|gst|tax|vat|cgst|sgst|igst|advance|balance|round)\b",
        re.IGNORECASE,
    )

    candidate_rows = [
        row for row in rows
        if len(row.numeric_tokens()) >= 2 and not summary_re.search(row.text.replace("_", " "))
    ]
    # Need a few consistent rows before trusting inferred geometry; two
    # rows could align by coincidence.
    if len(candidate_rows) < 3:
        return []

    centres: list[float] = []
    widths: list[int] = []
    for row in candidate_rows:
        for token in row.numeric_tokens():
            centres.append(token.center_x)
            widths.append(token.width)
    if not centres:
        return []

    median_width = statistics.median(widths) or 10
    # Two numeric tokens belong to different columns when their centres are
    # further apart than roughly one-and-a-half token widths.
    gap_threshold = max(median_width * 1.5, 8.0)

    centres.sort()
    clusters: list[list[float]] = [[centres[0]]]
    for centre in centres[1:]:
        if centre - clusters[-1][-1] <= gap_threshold:
            clusters[-1].append(centre)
        else:
            clusters.append([centre])

    # Keep only clusters supported by enough rows to be a real column
    # (filters stray one-off numbers inside descriptions).
    min_support = max(2, len(candidate_rows) // 2)
    clusters = [c for c in clusters if len(c) >= min_support]
    if not clusters:
        return []

    cluster_centres = [statistics.mean(c) for c in clusters]
    # Right-to-left naming per the receipt column convention described above.
    names_right_to_left = ["amount", "unit_price", "quantity"]
    named: list[tuple[float, str]] = []
    for offset, name in enumerate(names_right_to_left):
        index = len(cluster_centres) - 1 - offset
        if index < 0:
            break
        named.append((cluster_centres[index], name))
    if not named:
        return []

    named.sort()
    bands: list[ColumnBand] = []
    for index, (centre, name) in enumerate(named):
        left = (named[index - 1][0] + centre) / 2.0 if index > 0 else centre - gap_threshold * 2
        right = (named[index + 1][0] + centre) / 2.0 if index < len(named) - 1 else float("inf")
        bands.append(ColumnBand(name=name, left=left, right=right))

    # Description band = everything left of the leftmost named numeric column.
    bands.insert(0, ColumnBand(name="description", left=float("-inf"), right=bands[0].left))
    return bands


def header_row_bottom(rows: list[TextRow], bands: list[ColumnBand]) -> int | None:
    """
    Bottom y of the header row that produced `bands`, so callers can
    consider only rows *below* the header as candidate item rows.
    """
    if not bands:
        return None
    for row in rows:
        hit_count = 0
        for token in row.tokens:
            normalized = re.sub(r"[^a-z.]", "", token.text.lower())
            for keywords in _COLUMN_HEADER_KEYWORDS.values():
                if normalized and any(k in normalized for k in keywords):
                    hit_count += 1
                    break
        if hit_count >= 2:
            return row.bottom
    return None


def value_in_column(row: TextRow, band: ColumnBand) -> OcrToken | None:
    """
    The numeric token in `row` falling inside `band`.

    When several numeric tokens land in one band (OCR sometimes splits
    `1,250.00` into `1`/`250.00`), the widest is returned as the best
    single representative rather than concatenating them, since
    concatenation risks fabricating a value that was never on the page.
    """
    candidates = [t for t in row.numeric_tokens() if band.contains(t)]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t.width)


def description_in_row(row: TextRow, bands: list[ColumnBand]) -> str | None:
    """
    Text of the description cell: tokens inside the description band, or
    (when no such band was identified) the leading non-numeric tokens.
    """
    description_band = next((b for b in bands if b.name == "description"), None)
    if description_band is not None:
        parts = [
            t.text for t in row.tokens
            if description_band.contains(t) and not _NUMERIC_TOKEN_RE.match(t.text.strip())
        ]
    else:
        parts = []
        for token in row.tokens:
            if _NUMERIC_TOKEN_RE.match(token.text.strip()):
                break
            parts.append(token.text)

    cleaned = " ".join(parts).strip(" |:.-_")
    return cleaned or None


def find_label_value_on_row(
    rows: list[TextRow],
    label_pattern: re.Pattern[str],
) -> tuple[OcrToken, list[OcrToken]] | None:
    """
    Locate a label (e.g. /grand\\s*total/) and the numeric tokens sharing
    its visual row.

    This is the spatial answer to "`Grand Total` at x=500 and `1121.00` at
    x=700 belong together": association is by row membership, so it holds
    even when OCR emits the two in different text lines or out of order.
    Returns the LAST matching row, since summary labels appear at the
    bottom and a later occurrence supersedes an earlier one.
    """
    match_row: tuple[OcrToken, list[OcrToken]] | None = None
    for row in rows:
        # Underscores are a common OCR rendering of table rules and would
        # otherwise defeat \b-anchored label patterns.
        row_text = row.text.replace("_", " ")
        if not label_pattern.search(row_text):
            continue
        label_token = next(
            (t for t in row.tokens if label_pattern.search(t.text.replace("_", " "))),
            row.tokens[0] if row.tokens else None,
        )
        numeric = row.numeric_tokens()
        if label_token is not None:
            # Only numerics to the RIGHT of the label count as its value;
            # a number left of the label belongs to a different cell.
            to_right = [t for t in numeric if t.left >= label_token.left]
            match_row = (label_token, to_right or numeric)
    return match_row
