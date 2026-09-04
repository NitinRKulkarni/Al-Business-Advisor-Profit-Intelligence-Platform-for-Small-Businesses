"""
extractor
==========

Parses structured receipt fields out of raw OCR text, and provides the
public `process_receipt(s)` entry points that wire together the existing
preprocessing pipeline, an existing `OcrEngine`, and this module.

Why regex-based parsing (no LLM, no new heavy dependency)
-------------------------------------------------------------
This layer's job is to turn already-imperfect OCR text into structured
fields WITHOUT inventing values it cannot support. A rule-based parser
that returns `None` when it is not confident is easier to reason about and
audit than a model that can hallucinate a plausible-looking wrong number
-- which is exactly the failure mode this project has already measured
and flagged as dangerous (e.g. a quantity OCR'd as `4` when the source
says `1`). Regexes here are deliberately strict about what counts as a
parseable money/date token; anything outside that shape is left `None`
rather than guessed at.

Decoupling from the OCR engine
--------------------------------
`extract_from_ocr()` depends only on `ocr.engine.OcrResult` (a plain
dataclass: filename/success/text/mean_confidence/engine/error). It does
not import `TesseractOcrEngine` or `EasyOcrEngine`. `process_receipt(s)`
accept any `OcrEngine` instance and default to Tesseract only if none is
given -- so a future Azure-backed `OcrEngine` implementation can be passed
in without touching this module.
"""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from ocr.engine import OcrEngine, OcrResult
from image_processing.receipt_pipeline import process_receipt_images

from .confidence import finalize_confidence
from .layout import (
    description_in_row,
    detect_column_bands,
    find_label_value_on_row,
    group_tokens_into_rows,
    header_row_bottom,
    infer_column_bands_from_alignment,
    value_in_column,
)
from .models import EngineExtraction, ExtractionResult, LineItem, ReceiptData
from .reconciliation import reconcile_extractions
from .validators import validate_receipt
from .variants import (
    VariantCandidate,
    choose_best_per_engine,
    select_variant_stages,
)

# --------------------------------------------------------------- constants

_LOW_OCR_CONFIDENCE_THRESHOLD = 40.0

_HEADER_WORDS = (
    "cash memo", "tax invoice", "invoice", "bill", "receipt", "memo",
    "delivery challan", "challan", "rent receipt", "school fee",
)

_DOCUMENT_TYPE_KEYWORDS: list[tuple[str, str]] = [
    (r"\btax\s*invoice\b", "tax_invoice"),
    (r"\bdelivery\s*challan\b", "delivery_challan"),
    (r"\bchallan\b", "delivery_challan"),
    (r"\binvoice\b", "invoice"),
    (r"\bcash\s*memo\b", "cash_memo"),
    (r"\bbill\b", "bill"),
    (r"\breceipt\b", "receipt"),
]

# Strict money shape: optional currency symbol, digits with optional comma
# grouping, optional 1-2 decimal places, optional trailing "/-" (common in
# handwritten Indian receipts for whole-rupee amounts). Deliberately does
# NOT match a token containing any letter -- a corrupted OCR token like
# "4a50" or "a50/-" will simply fail to match, so it becomes "not found"
# rather than a silently wrong number.
_MONEY_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*/?-?",
    re.IGNORECASE,
)
_MONEY_TOKEN_ONLY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?$|^\d+(?:\.\d{1,2})?$")

_DATE_TOKEN_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_TIME_TOKEN_RE = re.compile(r"\b(\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?)\b")

_INVOICE_NO_RE = re.compile(
    r"\b(?:invoice|inv)\.?\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Za-z]{0,4}-?\d[A-Za-z0-9\-/]{0,19})",
    re.IGNORECASE,
)
_RECEIPT_NO_RE = re.compile(
    r"\b(?:receipt|bill|memo|challan)\.?\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Za-z0-9\-/]{2,20})",
    re.IGNORECASE,
)
_BARE_NO_RE = re.compile(r"\bNo\.?\s*[:\-]?\s*(\d{2,8})\b")

_SUBTOTAL_RE = re.compile(r"\bsub\s*-?\s*total\b", re.IGNORECASE)
_GRAND_TOTAL_RE = re.compile(r"\bgrand\s*total\b", re.IGNORECASE)
_TOTAL_RE = re.compile(r"\btotal\b", re.IGNORECASE)
_DISCOUNT_RE = re.compile(r"\bdisc(?:ount)?\b", re.IGNORECASE)
_TAX_RE = re.compile(r"\b(?:gst|tax|vat)\b", re.IGNORECASE)

# Minimum similarity (0-1, via difflib.SequenceMatcher) for a word to count
# as a fuzzy match against a canonical keyword. Deliberately conservative:
# it recovers common single-letter OCR substitutions (e.g. "Totol",
# "Toial", "Discoumt", "Suntotal") without forcing a match on unrelated
# words or on corruption too severe to safely resolve (e.g. "tert" for
# "Total" scores ~0.44 here and correctly stays unmatched -- the receipt
# that motivated this must still show total=null, not a forced guess).
_FUZZY_KEYWORD_MIN_RATIO = 0.8
# Keywords short enough that fuzzy matching would risk false positives
# against unrelated short words (e.g. "tax" ~ "wax"/"fax") are excluded;
# only matched via the existing strict regexes.
_FUZZY_FINANCIAL_KEYWORDS = ("total", "subtotal", "discount")

# NOTE: a narrower "tot"-prefix fuzzy match for "total" (to recover
# corruption like "Totr") was evaluated and deliberately NOT adopted:
# `_fuzzy_word_matches_keyword` is shared by `_is_summary_row` (decides
# whether a table row is a line item vs. a summary row) and the
# financial-keyword fuzzy fallback in `_extract_financials`. A prefix
# match loose enough to catch "totr" also matches ordinary English words
# ("tote", "tots", "toto") at the same similarity score, which could
# misclassify a genuine line item (e.g. "Toto Snacks 50.00 50.00") as a
# summary row or wrongly assign its amount to `total` -- a financial
# false positive, which this project treats as worse than a missed
# value. Recovering this specific corruption pattern would require
# either hardcoding known corrupted spellings (not allowed) or a
# dictionary lookup (not justified for this single case), so it is left
# as a known limitation: total=null with the raw OCR text preserved is
# the safe outcome here, not a guess.


def _normalize_for_keyword_scan(text: str) -> str:
    """
    Normalize OCR rendering artifacts before scanning for a label keyword.

    Tesseract commonly renders a table's underlined/ruled cell as a
    literal "_" glued directly onto the adjacent word (e.g. "Grand
    Total_|", "Bill No_"). Since "_" counts as a regex word character,
    every `\\b`-anchored keyword pattern in this module would otherwise
    silently fail to match on an otherwise perfectly legible word. This is
    a general OCR-rendering artifact (not specific to any one receipt or
    vendor), so it is applied uniformly everywhere a keyword is searched
    for: financial labels, id labels, and document-type labels alike.
    """
    return text.replace("_", " ")


def _fuzzy_word_matches_keyword(word: str, keyword: str) -> bool:
    """
    True if `word` is close enough to `keyword` to be treated as an
    OCR-corrupted spelling of it (see `_FUZZY_KEYWORD_MIN_RATIO`).
    """
    if not word or abs(len(word) - len(keyword)) > 2:
        return False
    return SequenceMatcher(None, word.lower(), keyword.lower()).ratio() >= _FUZZY_KEYWORD_MIN_RATIO


def _line_matches_financial_keyword_fuzzy(line: str, keyword: str) -> bool:
    """
    Fallback for when the strict keyword regex found nothing on this line:
    check whether any individual word on the line is a close OCR-corrupted
    spelling of `keyword`. Only used for the keywords in
    `_FUZZY_FINANCIAL_KEYWORDS`; short keywords (tax/gst/vat) are
    deliberately excluded to avoid false positives on unrelated 3-letter
    words.
    """
    for token in re.split(r"[\s|:.,]+", line):
        cleaned = token.strip("-/_")
        if cleaned and _fuzzy_word_matches_keyword(cleaned, keyword):
            return True
    return False


_QTY_UNIT_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s?(?:kg|g|gm|gms|ltr|l|pcs|pc|nos|no|mtr|m|sq)?$",
    re.IGNORECASE,
)

_ITEM_ROW_3NUM_RE = re.compile(
    r"^(?P<desc>[A-Za-z][A-Za-z0-9()\-.,'&/ ]*?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?\s?(?:kg|g|gm|gms|ltr|l|pcs|pc|nos|no|mtr|m|sq)?)\s+"
    r"(?P<price>\d[\d,]*(?:\.\d{2})?)\s+"
    r"(?P<amount>\d[\d,]*(?:\.\d{2})?)\s*$",
    re.IGNORECASE,
)
_ITEM_ROW_2NUM_RE = re.compile(
    r"^(?P<desc>[A-Za-z][A-Za-z0-9()\-.,'&/ ]*?)\s+"
    r"(?P<price>\d[\d,]*(?:\.\d{2})?)\s+"
    r"(?P<amount>\d[\d,]*(?:\.\d{2})?)\s*$",
    re.IGNORECASE,
)
_ITEM_ROW_1NUM_RE = re.compile(
    r"^(?P<desc>[A-Za-z][A-Za-z0-9()\-.,'&/ ]{2,})\s+"
    r"(?P<amount>\d[\d,]*(?:\.\d{2})?)\s*$",
    re.IGNORECASE,
)


def _parse_money(token: str) -> float | None:
    """Convert a strictly money-shaped token (see `_MONEY_TOKEN_ONLY_RE`) to float."""
    cleaned = token.strip()
    if not _MONEY_TOKEN_ONLY_RE.match(cleaned):
        return None
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def _clean_row(line: str) -> str:
    """
    Strip table-drawing noise so an item row regex has a fair chance.

    The leading "Sl." (serial number) cell is the noisiest part of a
    scanned table row: OCR renders its border/rule as an unpredictable mix
    of stray symbols (e.g. "@ |", "0 4 |", ". 5 |") glued in front of the
    actual index digit. A pattern that only recognises a single clean
    digit-plus-punctuation prefix misses these and drops the whole row.
    Generalised here to strip up to two leading whitespace-separated
    tokens made ENTIRELY of non-letter characters (digits/symbols, 1-4
    chars each) -- this covers arbitrary combinations of stray symbols and
    the index digit without ever touching a token that contains a letter,
    so real description text is never at risk of being stripped.
    """
    line = line.replace("|", " ")
    line = re.sub(r"\s{2,}", " ", line).strip()
    line = re.sub(r"^(?:[^A-Za-z\s]{1,4}\s+){1,2}", "", line)
    return line.strip(" .")


def _extract_date(text: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    text = _normalize_for_keyword_scan(text)
    for d_str, m_str, y_str in _DATE_TOKEN_RE.findall(text):
        d, m, y = int(d_str), int(m_str), int(y_str)
        year = y if y > 99 else (2000 + y if y < 70 else 1900 + y)
        # This dataset is India-sourced, so DD/MM is tried before MM/DD.
        for day, month in ((d, m), (m, d)):
            try:
                return date(year, month, day).isoformat(), warnings
            except ValueError:
                continue
        warnings.append(f"date_token_unparseable:{d_str}/{m_str}/{y_str}")
    return None, warnings


def _extract_time(text: str) -> str | None:
    match = _TIME_TOKEN_RE.search(text)
    return match.group(1) if match else None


def _is_header_word_line(candidate: str) -> bool:
    """
    True when `candidate` is (or is an OCR-corrupted spelling of) a
    generic document-header phrase like "Cash Memo", rather than an actual
    vendor name.

    Exact substring matching alone misses common single-letter OCR
    corruption (observed: "Cash Memo" read as "Cash Meme"), which then
    gets kept as if it were the vendor name. The fuzzy check reuses the
    same conservative similarity threshold as the financial-keyword
    fallback, so it recovers ordinary OCR noise without loosening enough
    to risk misclassifying a real vendor name that happens to contain a
    short common word.
    """
    lowered = candidate.lower()
    if any(header in lowered for header in _HEADER_WORDS):
        return True
    # Strip a leading stray token made entirely of non-letters (the same
    # OCR table-border noise `_clean_row` strips from item rows, e.g. the
    # "5" in "5 Cash Meme"), then compare the remaining words against each
    # header phrase word-for-word so single-letter corruption within a
    # word (Memo -> Meme) is still caught.
    words = re.split(r"\s+", re.sub(r"^[^A-Za-z\s]{1,4}\s+", "", lowered))
    for header in _HEADER_WORDS:
        header_words = header.split()
        if len(header_words) != len(words):
            continue
        if all(_fuzzy_word_matches_keyword(w, h) for w, h in zip(words, header_words)):
            return True
    return False


def _extract_vendor_name(lines: list[str]) -> str | None:
    for raw_line in lines[:6]:
        candidate = raw_line.strip()
        if len(candidate) < 3:
            continue
        if _is_header_word_line(candidate):
            continue
        if _DATE_TOKEN_RE.search(candidate) or _BARE_NO_RE.search(candidate):
            continue
        letters = sum(1 for c in candidate if c.isalpha())
        if letters < 3:
            continue
        # Strip a leading stray token OCR sometimes glues on ahead of the
        # real vendor name (a lone digit, symbol, or misread accented
        # character from a table border/rule) -- same noise class already
        # handled for item rows in `_clean_row`. Only ever strips a SHORT
        # leading token, so a genuine short vendor name is not truncated.
        cleaned = re.sub(r"^[^A-Za-z\s]{1,4}\s+", "", candidate).strip(" :.-")
        return cleaned or candidate.strip(" :.-")
    return None


def _plausible_identifier(value: str | None) -> str | None:
    """
    Keep an extracted invoice/receipt number only if it could actually BE
    one, otherwise return None.

    A document identifier always contains at least one digit. Requiring
    that discards OCR garbage that the label regexes can otherwise capture
    when the label itself was misread -- measured on a held-out receipt,
    a corrupted "No." was captured as the receipt number "Ne", i.e. a
    two-letter word was published as a financial-document identifier.
    Returning None there is both correct and safer: downstream treats a
    null as "unknown" and the receipt is already flagged for review, while
    a bogus identifier could be used to deduplicate or match records.

    This is a shape check over any string, not a list of known-good
    identifiers, so it generalizes to arbitrary numbering schemes
    (`190`, `0456`, `INV-500`, `2024/A/17`).
    """
    if value is None:
        return None
    cleaned = value.strip(" .:-")
    if not cleaned or not any(c.isdigit() for c in cleaned):
        return None
    return cleaned


def _extract_ids(text: str) -> tuple[str | None, str | None]:
    invoice_number = None
    receipt_number = None
    text = _normalize_for_keyword_scan(text)

    match = _INVOICE_NO_RE.search(text)
    if match:
        invoice_number = _plausible_identifier(match.group(1))

    match = _RECEIPT_NO_RE.search(text)
    if match:
        receipt_number = _plausible_identifier(match.group(1))

    if invoice_number is None and receipt_number is None:
        match = _BARE_NO_RE.search(text)
        if match:
            receipt_number = _plausible_identifier(match.group(1))

    return invoice_number, receipt_number


def _extract_document_type(text: str) -> str | None:
    text = _normalize_for_keyword_scan(text)
    for pattern, label in _DOCUMENT_TYPE_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None


def _extract_financials(lines: list[str]) -> tuple[dict[str, float | None], list[str]]:
    """
    Scan lines for subtotal/discount/tax/total keywords and pull the
    right-most money-shaped token on that line as the value.

    Grand total takes priority over a plain "Total" line for the `total`
    field (both may appear; grand total is the authoritative one). A
    keyword line with no parseable money token on it is recorded as a
    warning rather than silently skipped, since it usually means the
    amount itself was OCR-corrupted (e.g. `a50/-5`) and the caller should
    know the field is genuinely unknown, not merely absent from the
    receipt.
    """
    values: dict[str, float | None] = {
        "subtotal": None, "discount": None, "tax": None, "total": None,
    }
    warnings: list[str] = []
    grand_total_seen = False
    # Index (within `lines`) of the plain "Total" line that most recently
    # set `values["total"]`, so it can be invalidated below if a
    # discount/tax adjustment turns out to come AFTER it -- see the
    # reclassification pass following this loop.
    plain_total_line_index: int | None = None
    discount_line_index: int | None = None
    tax_line_index: int | None = None

    for index, line in enumerate(lines):
        # Whole-token check, not a digit-substring search: a corrupted
        # token like "4a50/-5" must NOT contribute the digits "4", "50" or
        # "5" it happens to contain. Only a token that is ENTIRELY a valid
        # money shape (after stripping surrounding punctuation) counts.
        # Split on whitespace AND on "_"/"|" (not just whitespace): a
        # table's underlined, ruled cell often comes back with NO space at
        # all between the label and the value (e.g. "Discount__|_15.00" is
        # a single whitespace-free run), so splitting on whitespace only
        # would leave the amount glued to its label and unparseable. "_"
        # and "|" are structural table-rendering artifacts, never part of
        # a genuine money token, so splitting on them is safe and does not
        # affect the "4a50/-5" corrupted-token case (no "_"/"|" inside it,
        # so it is untouched and still correctly rejected below).
        money_matches = []
        for raw_tok in re.split(r"[\s_|]+", line):
            stripped = raw_tok.strip(":-/").rstrip("/-")
            parsed = _parse_money(stripped)
            if parsed is not None:
                money_matches.append(parsed)
        value = money_matches[-1] if money_matches else None

        # See `_normalize_for_keyword_scan`: undoes underscore-glued
        # rendering artifacts before any keyword regex runs.
        keyword_line = _normalize_for_keyword_scan(line)

        if _SUBTOTAL_RE.search(keyword_line):
            if value is not None:
                values["subtotal"] = value
            else:
                warnings.append("subtotal_line_found_but_amount_unparseable")
        elif _GRAND_TOTAL_RE.search(keyword_line):
            if value is not None:
                # A plain "Total" line seen earlier is a pre-adjustment
                # figure once a Grand Total follows (the structure this
                # whole reclassification exists for: Total -> Discount/Tax
                # -> Grand Total). Recover it as subtotal here rather than
                # letting it be silently overwritten and lost -- this is
                # the SAME structural fact the post-loop reclassification
                # below handles for the no-grand-total case; this branch
                # covers the grand-total-present case that block does not
                # reach (it only runs `if not grand_total_seen`).
                if (
                    plain_total_line_index is not None
                    and values["subtotal"] is None
                    and values["total"] is not None
                ):
                    values["subtotal"] = values["total"]
                    warnings.append(
                        f"total_line_reclassified_as_subtotal_before_grand_total:{values['total']}"
                    )
                values["total"] = value
                grand_total_seen = True
            else:
                warnings.append("total_line_found_but_amount_unparseable")
        elif _DISCOUNT_RE.search(keyword_line):
            if value is not None:
                values["discount"] = value
                discount_line_index = index
            else:
                warnings.append("discount_line_found_but_amount_unparseable")
        elif _TAX_RE.search(keyword_line):
            if value is not None:
                values["tax"] = value
                tax_line_index = index
            else:
                warnings.append("tax_line_found_but_amount_unparseable")
        elif not grand_total_seen and _TOTAL_RE.search(keyword_line):
            if value is not None:
                values["total"] = value
                plain_total_line_index = index
            else:
                warnings.append("total_line_found_but_amount_unparseable")
        # Fuzzy fallback: only tried when NONE of the strict keyword
        # regexes matched this line at all (not merely "amount
        # unparseable" -- that case already means the keyword itself WAS
        # found and is handled above). This keeps the fuzzy path narrow:
        # it only fires on lines that would otherwise contribute nothing,
        # and only for the three longer, less ambiguous keywords.
        elif value is not None:
            for keyword, target in (
                ("subtotal", "subtotal"), ("discount", "discount"), ("total", "total"),
            ):
                if target == "total" and grand_total_seen:
                    continue
                if _line_matches_financial_keyword_fuzzy(keyword_line, keyword):
                    values[target] = value
                    if target == "total":
                        plain_total_line_index = index
                    elif target == "discount":
                        discount_line_index = index
                    warnings.append(f"{target}_matched_via_fuzzy_keyword")
                    break

    # Structural invalidation: a plain "Total" line is NOT the payable
    # total if a discount/tax adjustment appears AFTER it. That ordering
    # ("Total 430.00" / "Discount 20.00" / "410.00") means the labeled
    # "Total" was actually a pre-adjustment figure -- treating it as the
    # final total would silently return the wrong number. This generalizes
    # to any receipt with that line ordering, not one specific example.
    if not grand_total_seen and plain_total_line_index is not None:
        later_adjustment = max(
            (i for i in (discount_line_index, tax_line_index) if i is not None),
            default=None,
        )
        if later_adjustment is not None and later_adjustment > plain_total_line_index:
            pre_adjustment_value = values["total"]
            values["total"] = None
            if values["subtotal"] is None:
                # The invalidated figure was explicitly labeled as a total
                # before the adjustment, which is exactly what a subtotal
                # is -- reclassify it rather than discarding it outright.
                values["subtotal"] = pre_adjustment_value
            warnings.append(
                "total_line_precedes_discount_or_tax_adjustment:"
                f"reclassified_{pre_adjustment_value}_and_marked_total_unknown"
            )

    return values, warnings


def _is_summary_row(cleaned: str) -> bool:
    """
    True when a row is a summary/total row rather than a line item.

    Checks exact keywords AND a fuzzy match, because an OCR-corrupted
    summary label that slips through becomes a PHANTOM LINE ITEM carrying a
    real money value (measured on this dataset: "Discount 10.00" was read
    as "Diseamtt 10.00" and became a fabricated item row). Fabricating a
    financial row is the single worst failure mode for this project, so the
    filter errs toward classifying a doubtful row as summary.
    """
    lowered = cleaned.lower()
    exact_keywords = (
        "total", "discount", "tax", "gst", "vat", "cgst", "sgst", "igst",
        "advance", "balance", "grand", "round", "payable", "net",
    )
    if any(k in lowered for k in exact_keywords):
        return True

    fuzzy_targets = ("total", "subtotal", "discount", "balance", "advance")
    for token in re.split(r"[\s|:.,]+", cleaned):
        candidate = token.strip("-/_")
        if len(candidate) < 4:
            continue
        if any(_fuzzy_word_matches_keyword(candidate, target) for target in fuzzy_targets):
            return True
    return False


def _extract_line_items(lines: list[str]) -> tuple[list[LineItem], list[str]]:
    items: list[LineItem] = []
    warnings: list[str] = []
    # Rows carrying at least a price+amount pair (strong table evidence)
    # are kept separate from rows carrying only a single amount, so the
    # structural guard below can decide whether the latter are trustworthy.
    structured_items: list[LineItem] = []
    single_amount_items: list[LineItem] = []

    for raw_line in lines:
        cleaned = _clean_row(raw_line)
        if not cleaned or _is_summary_row(cleaned):
            continue

        match = _ITEM_ROW_3NUM_RE.match(cleaned)
        if match:
            qty_match = _QTY_UNIT_RE.match(match.group("qty").strip())
            quantity = float(qty_match.group(1)) if qty_match else None
            structured_items.append(LineItem(
                description=match.group("desc").strip(" .-"),
                quantity=quantity,
                unit_price=_parse_money(match.group("price")),
                amount=_parse_money(match.group("amount")),
            ))
            continue

        match = _ITEM_ROW_2NUM_RE.match(cleaned)
        if match and len(match.group("desc").strip()) >= 3:
            structured_items.append(LineItem(
                description=match.group("desc").strip(" .-"),
                quantity=None,
                unit_price=_parse_money(match.group("price")),
                amount=_parse_money(match.group("amount")),
            ))
            continue

        match = _ITEM_ROW_1NUM_RE.match(cleaned)
        if match and len(match.group("desc").strip()) >= 3:
            single_amount_items.append(LineItem(
                description=match.group("desc").strip(" .-"),
                quantity=None,
                unit_price=None,
                amount=_parse_money(match.group("amount")),
            ))

    # Structural guard against fabricated financial rows.
    #
    # A "description + one amount" row is inherently ambiguous: it matches
    # both a genuine single-price item AND a summary line whose label OCR
    # corrupted beyond keyword/fuzzy recognition (measured on this dataset:
    # "Discount 10.00" read as "Diseamtt 10.00", too damaged to match
    # "discount" at any safe similarity threshold). When the receipt
    # clearly HAS a structured table -- i.e. some row yielded a full
    # quantity/unit_price/amount triple -- a lone single-amount row is far
    # more likely a summary line, so it is dropped rather than emitted as
    # an item. Fabricating a financial row is worse than omitting one.
    if structured_items:
        if single_amount_items:
            warnings.append("single_amount_rows_dropped_table_structure_present")
        items = structured_items
    else:
        # No structured table found: single-amount rows are the best (and
        # only) item evidence available, so they are kept.
        items = single_amount_items

    if items and any(item.quantity is None for item in items):
        warnings.append("some_line_items_missing_quantity")
    if items and any(item.unit_price is None for item in items):
        warnings.append("some_line_items_missing_unit_price")

    return items, warnings


def _item_set_consistency(items: list[LineItem]) -> float:
    """
    Fraction of fully-populated rows whose own arithmetic holds
    (quantity x unit_price ~= amount).

    Used to arbitrate between competing extraction methods on evidence
    rather than on a hard-coded preference: a row set where the numbers
    multiply out correctly is far more likely to have assigned values to
    the right fields. Returns -1.0 for an empty set so any real candidate
    beats "found nothing", and 0.0 when rows exist but none are
    checkable (no better than a coin flip, so completeness decides).
    """
    if not items:
        return -1.0
    checkable = [
        i for i in items
        if i.quantity is not None and i.unit_price is not None and i.amount is not None
    ]
    if not checkable:
        return 0.0
    consistent = sum(
        1 for i in checkable
        if abs(i.quantity * i.unit_price - i.amount) <= max(1.0, abs(i.amount) * 0.02)
    )
    return consistent / len(checkable)


def _item_set_completeness(items: list[LineItem]) -> float:
    """Mean fraction of (quantity, unit_price, amount) populated per row."""
    if not items:
        return 0.0
    filled = sum(
        sum(1 for v in (i.quantity, i.unit_price, i.amount) if v is not None)
        for i in items
    )
    return filled / (len(items) * 3)


def _extract_line_items_spatial(tokens: list) -> tuple[list[LineItem], list[str]]:
    """
    Extract line items using token GEOMETRY (column bands) rather than
    whitespace splitting.

    This is the primary fix for wrong quantity/rate/amount association: a
    value is assigned to the column whose header it sits under, so a
    mangled separator between cells no longer shifts a number into the
    wrong field. Returns ([], [reason]) when no table structure is
    detectable, so the caller can fall back to text parsing.
    """
    rows = group_tokens_into_rows(tokens)
    if not rows:
        return [], ["spatial_no_rows"]

    # Prefer a recognized header row (most reliable). Fall back to
    # inferring columns from numeric x-alignment, which is necessary
    # because Tesseract often fails to recognize the header line at all
    # on these receipts even when the data rows are cleanly aligned.
    bands = detect_column_bands(rows)
    inferred = False
    if not bands:
        bands = infer_column_bands_from_alignment(rows)
        inferred = True
    if not bands:
        return [], ["spatial_no_table_structure_detected"]

    header_bottom = None if inferred else header_row_bottom(rows, bands)
    band_by_name = {b.name: b for b in bands}
    qty_band = band_by_name.get("quantity")
    price_band = band_by_name.get("unit_price")
    amount_band = band_by_name.get("amount")

    items: list[LineItem] = []
    warnings: list[str] = []

    for row in rows:
        if header_bottom is not None and row.top <= header_bottom:
            continue
        # Same phantom-row guard as the text path (`_is_summary_row`),
        # including its fuzzy check, so an OCR-corrupted summary label
        # cannot become a fabricated line item on either path.
        if _is_summary_row(row.text.replace("_", " ")):
            continue

        description = description_in_row(row, bands)
        qty_token = value_in_column(row, qty_band) if qty_band else None
        price_token = value_in_column(row, price_band) if price_band else None
        amount_token = value_in_column(row, amount_band) if amount_band else None

        # Require a description plus at least one numeric cell before
        # treating a row as an item -- otherwise stray text rows (address
        # lines, footers) would become phantom items.
        if not description or not any((qty_token, price_token, amount_token)):
            continue

        items.append(LineItem(
            description=description,
            quantity=_parse_money(qty_token.text) if qty_token else None,
            unit_price=_parse_money(price_token.text) if price_token else None,
            amount=_parse_money(amount_token.text) if amount_token else None,
        ))

    if items:
        warnings.append(
            "line_items_extracted_spatially_inferred_columns" if inferred
            else "line_items_extracted_spatially_header_columns"
        )
        if any(i.quantity is None for i in items):
            warnings.append("some_line_items_missing_quantity")
        if any(i.unit_price is None for i in items):
            warnings.append("some_line_items_missing_unit_price")

    return items, warnings


def _extract_financials_spatial(tokens: list) -> tuple[dict[str, float | None], list[str]]:
    """
    Locate summary financial fields by finding each label and reading the
    numeric token(s) on the SAME VISUAL ROW.

    Row-based association is what makes `Grand Total` (x=500) pair with
    `1121.00` (x=700) even when OCR emits them out of text order. Returns
    only fields it could locate; the caller merges these over the
    text-based results rather than replacing them, so a field found by
    only one method is still kept.
    """
    rows = group_tokens_into_rows(tokens)
    values: dict[str, float | None] = {
        "subtotal": None, "discount": None, "tax": None, "total": None,
    }
    warnings: list[str] = []
    if not rows:
        return values, warnings

    # Order matters: the more specific labels are searched first so a
    # "Grand Total" row is not also consumed as a plain "Total".
    targets = [
        ("total", _GRAND_TOTAL_RE),
        ("subtotal", _SUBTOTAL_RE),
        ("discount", _DISCOUNT_RE),
        ("tax", _TAX_RE),
    ]
    for field_name, pattern in targets:
        found = find_label_value_on_row(rows, pattern)
        if not found:
            continue
        _, numeric_tokens = found
        for token in reversed(numeric_tokens):
            parsed = _parse_money(token.text.strip("|:-/_"))
            if parsed is not None:
                values[field_name] = parsed
                warnings.append(f"{field_name}_located_spatially")
                break

    # Plain "Total" only if no grand total was found spatially.
    if values["total"] is None:
        found = find_label_value_on_row(rows, _TOTAL_RE)
        if found:
            _, numeric_tokens = found
            for token in reversed(numeric_tokens):
                parsed = _parse_money(token.text.strip("|:-/_"))
                if parsed is not None:
                    values["total"] = parsed
                    warnings.append("total_located_spatially")
                    break

    return values, warnings


def _extraction_confidence(
    receipt: ReceiptData,
    text: str,
    ocr_confidence: float | None,
    warnings: list[str],
) -> float:
    """
    Deterministic 0-100 score combining (a) how much structure was
    successfully pulled out of the text, (b) OCR quality, and (c) how many
    validation-relevant warnings exist -- NOT a correctness measure. A
    receipt can score moderately here and still contain a wrong digit;
    this score only says the pipeline found and cross-checked *some*
    structure, not that it is guaranteed right.

    This directly implements the project requirement that OCR confidence
    alone must never stand in for extraction confidence: a receipt with
    only 2-3 fields found gets a low score even when `ocr_confidence` is
    high (e.g. the earlier `batch2_invoice_087` case: 87.5% OCR confidence
    but only "Thank You !" recognized -- completeness must dominate).
    """
    if len(text.strip()) < 5:
        return 0.0

    # Completeness: how much structure was found (0-100, same weights as
    # before -- this is the dominant term).
    completeness = 0.0
    if receipt.vendor_name:
        completeness += 15
    if receipt.date:
        completeness += 15
    if receipt.invoice_number or receipt.receipt_number:
        completeness += 10
    if receipt.total is not None:
        completeness += 20
    if receipt.items:
        completeness += 20
    if receipt.subtotal is not None:
        completeness += 10
    if receipt.tax is not None:
        completeness += 5
    if receipt.discount is not None:
        completeness += 5
    completeness = min(completeness, 100.0)

    # OCR-quality factor (0-1): scales completeness down when the
    # underlying text itself was unreliable, even if a few fields happened
    # to parse. Missing OCR confidence (engine reported none) is treated
    # neutrally (1.0) rather than penalized, since that is a property of
    # the engine, not evidence of bad text.
    ocr_factor = 1.0 if ocr_confidence is None else max(0.0, min(ocr_confidence / 100.0, 1.0))

    # Warning penalty: each mathematical-inconsistency or ambiguity
    # warning is evidence the extracted structure may not be trustworthy,
    # so it reduces the score directly rather than being invisible to it.
    # Structural informational warnings (e.g. which stage produced a
    # value) are excluded -- only warnings indicating a genuine numeric or
    # data problem count.
    penalizing_warnings = [
        w for w in warnings
        if any(
            marker in w
            for marker in (
                "mismatch", "inconsistent", "unparseable", "malformed",
                "negative", "suspicious", "low_ocr_confidence",
                "insufficient_text",
            )
        )
    ]
    warning_penalty = min(len(penalizing_warnings) * 8.0, 40.0)

    score = completeness * (0.5 + 0.5 * ocr_factor) - warning_penalty
    return round(max(0.0, min(score, 100.0)), 2)


def recompute_extraction_confidence(result: ExtractionResult) -> None:
    """
    Recompute `result.extraction_confidence` in place from its CURRENT
    receipt/warnings state.

    Called once by `extract_from_ocr` (initial score) and again by
    `validators.validate_receipt` after it appends its own warnings, so
    the final score reflects validation findings too (e.g. an
    `item_amount_mismatch` or `total_inconsistent_with_subtotal_discount_tax`
    lowers confidence even though those warnings only exist after
    validation runs). Imported lazily by `validators` to avoid a circular
    import at module load time; safe because both modules are fully loaded
    by the time either calls this.
    """
    if not result.success:
        return
    result.extraction_confidence = _extraction_confidence(
        result.receipt, result.raw_text, result.ocr_confidence, result.warnings
    )


def extract_from_ocr(
    ocr_result: OcrResult,
    operations_applied: list[str] | None = None,
) -> ExtractionResult:
    """
    Parse a `ReceiptData` out of an already-produced `OcrResult`.

    Decoupled from any specific engine: only `OcrResult`'s public fields
    are read. A future engine (including an Azure-backed one) only needs
    to produce an `OcrResult` to be usable here.
    """
    if not ocr_result.success:
        return ExtractionResult(
            source=ocr_result.filename,
            success=False,
            ocr_engine=ocr_result.engine,
            operations_applied=list(operations_applied or []),
            error=ocr_result.error or "OCR did not succeed",
            warnings=["ocr_failed"],
        )

    text = ocr_result.text or ""
    lines = [line for line in text.splitlines()]
    warnings: list[str] = []

    if ocr_result.mean_confidence is not None and ocr_result.mean_confidence < _LOW_OCR_CONFIDENCE_THRESHOLD:
        warnings.append("low_ocr_confidence")

    if len(text.strip()) < 5:
        warnings.append("insufficient_text_for_extraction")
        receipt = ReceiptData()
        return ExtractionResult(
            source=ocr_result.filename,
            success=True,
            receipt=receipt,
            raw_text=text,
            ocr_engine=ocr_result.engine,
            ocr_confidence=ocr_result.mean_confidence,
            extraction_confidence=0.0,
            operations_applied=list(operations_applied or []),
            warnings=warnings,
        )


    date_str, date_warnings = _extract_date(text)
    warnings.extend(date_warnings)
    invoice_number, receipt_number = _extract_ids(text)

    financials, fin_warnings = _extract_financials(lines)
    warnings.extend(fin_warnings)
    items, item_warnings = _extract_line_items(lines)

    # Spatial pass (only possible when the engine supplied token geometry).
    # Results are MERGED over the text-based results, never blindly
    # replacing them: a field that only one method could find is still
    # kept, and where both found a value the spatial one wins because
    # column/row geometry survives OCR separator damage that whitespace
    # splitting does not.
    tokens = list(ocr_result.tokens or [])
    if tokens:
        spatial_financials, spatial_fin_warnings = _extract_financials_spatial(tokens)
        for key, spatial_value in spatial_financials.items():
            if spatial_value is not None:
                if financials.get(key) is not None and financials[key] != spatial_value:
                    warnings.append(
                        f"{key}_disagreement_text_vs_spatial:"
                        f"text_{financials[key]}_spatial_{spatial_value}"
                    )
                financials[key] = spatial_value
        warnings.extend(spatial_fin_warnings)

        spatial_items, spatial_item_warnings = _extract_line_items_spatial(tokens)
        if spatial_items:
            # Cross-method reconciliation (never "highest confidence wins"):
            # score both candidate item sets on how internally consistent
            # their own arithmetic is (quantity x unit_price == amount) and
            # keep the better-supported one. Measured on this project's
            # ground-truth subset, neither method dominates the other, so
            # picking per-receipt on evidence beats hard-coding a
            # preference for either.
            text_score = _item_set_consistency(items)
            spatial_score = _item_set_consistency(spatial_items)
            if spatial_score > text_score:
                items = spatial_items
                item_warnings = spatial_item_warnings
            elif spatial_score < text_score:
                item_warnings = item_warnings + ["spatial_items_discarded_less_consistent"]
            else:
                # Equally consistent: prefer whichever recovered more
                # complete rows, since a row missing qty/price is less
                # useful downstream even when not contradictory.
                if _item_set_completeness(spatial_items) > _item_set_completeness(items):
                    items = spatial_items
                    item_warnings = spatial_item_warnings
    else:
        warnings.append("no_token_geometry_available_text_only_extraction")

    warnings.extend(item_warnings)

    receipt = ReceiptData(
        document_type=_extract_document_type(text),
        vendor_name=_extract_vendor_name(lines),
        customer_name=None,  # not reliably distinguishable from vendor via regex alone
        invoice_number=invoice_number,
        receipt_number=receipt_number,
        date=date_str,
        time=_extract_time(text),
        currency="INR" if re.search(r"₹|\bRs\.?\b|\bINR\b", text, re.IGNORECASE) else None,
        subtotal=financials["subtotal"],
        tax=financials["tax"],
        discount=financials["discount"],
        total=financials["total"],
        payment_method=None,  # no reliable signal in this dataset's receipts
        items=items,
    )

    return ExtractionResult(
        source=ocr_result.filename,
        success=True,
        receipt=receipt,
        raw_text=text,
        ocr_engine=ocr_result.engine,
        ocr_confidence=ocr_result.mean_confidence,
        extraction_confidence=_extraction_confidence(
            receipt, text, ocr_result.mean_confidence, warnings
        ),
        operations_applied=list(operations_applied or []),
        warnings=warnings,
    )


def _extraction_from_single_engine(
    ocr_result: OcrResult,
    operations_applied: list[str],
) -> ExtractionResult:
    """The original (pre-reconciliation) single-engine path, unchanged."""
    extraction = extract_from_ocr(ocr_result, operations_applied=operations_applied)
    validate_receipt(extraction)
    finalize_confidence(extraction)
    extraction.engines_used = [ocr_result.engine] if ocr_result.success else []
    extraction.raw_ocr_by_engine = {ocr_result.engine: ocr_result.text} if ocr_result.success else {}
    return extraction


def _best_ocr_result_across_variants(
    engine: OcrEngine,
    variant_paths: dict[str, str],
    source_name: str,
    operations_applied: list[str],
) -> tuple[OcrResult, list[str]]:
    """
    Run `engine` over each available preprocessing variant and return the
    OCR result whose EXTRACTION carries the strongest evidence.

    Selection is delegated to `variants.score_candidate` /
    `choose_best_per_engine`, which weight arithmetic self-consistency and
    structural recovery far above text volume and treat OCR confidence as
    a tiebreak only. See `variants` for why confidence cannot drive this
    decision (measured: the highest-confidence variant on a real image
    recovered three words while a discarded variant recovered thirty-nine).

    `variant_paths` maps variant name -> image path and MUST contain
    "final"; that entry reproduces the original single-variant behaviour,
    so this can only change the outcome when some other variant scores
    strictly better.

    A variant whose OCR call raises is skipped (recorded in notes) rather
    than aborting the whole image -- one bad variant must not lose the
    others.
    """
    candidates: list[VariantCandidate] = []
    notes: list[str] = []
    ocr_by_variant: dict[str, OcrResult] = {}

    for variant_name, image_path in variant_paths.items():
        try:
            ocr_result = engine.recognize(image_path)
        except Exception as exc:  # noqa: BLE001 - one variant must not kill the rest
            notes.append(f"variant_ocr_failed:{engine.name}:{variant_name}:{exc}")
            continue
        ocr_result.filename = source_name
        ocr_by_variant[variant_name] = ocr_result
        if not ocr_result.success:
            notes.append(f"variant_ocr_unsuccessful:{engine.name}:{variant_name}")
            continue
        extraction = extract_from_ocr(ocr_result, operations_applied=operations_applied)
        validate_receipt(extraction)
        finalize_confidence(extraction)
        candidates.append(VariantCandidate(
            engine=engine.name,
            variant=variant_name,
            extraction=extraction,
            ocr_confidence=ocr_result.mean_confidence,
            word_count=ocr_result.word_count,
        ))

    if not candidates:
        # Nothing scored: fall back to whatever OCR result exists for
        # `final` so the caller still gets a real (possibly failed)
        # OcrResult to report, rather than a synthetic one.
        fallback = ocr_by_variant.get("final")
        if fallback is not None:
            return fallback, notes
        failed = OcrResult(
            filename=source_name, success=False, engine=engine.name,
            error="all preprocessing variants failed OCR",
        )
        return failed, notes

    winners, selection_notes = choose_best_per_engine(candidates)
    notes.extend(selection_notes)
    best = winners[0]
    return ocr_by_variant[best.variant], notes


def _extraction_from_multi_engine(
    ocr_results: list[OcrResult],
    operations_applied: list[str],
) -> ExtractionResult:
    """
    Reconciled path: run independent extraction per successful engine
    result, then merge via `reconcile_extractions`.

    Any engine that failed OCR outright is excluded from reconciliation
    (nothing to reconcile against) but its failure is still recorded in
    warnings, since "one engine crashed" is useful provenance even when
    another engine covered for it.
    """
    filename = next((r.filename for r in ocr_results), "unknown")
    warnings: list[str] = []
    per_engine_extractions: list[EngineExtraction] = []
    raw_ocr_by_engine: dict[str, str] = {}
    engines_used: list[str] = []

    for ocr_result in ocr_results:
        if not ocr_result.success:
            warnings.append(f"engine_failed:{ocr_result.engine}:{ocr_result.error}")
            continue
        single = extract_from_ocr(ocr_result, operations_applied=operations_applied)
        per_engine_extractions.append(EngineExtraction(
            engine=ocr_result.engine,
            ocr_confidence=ocr_result.mean_confidence,
            receipt=single.receipt,
            raw_text=ocr_result.text,
            warnings=single.warnings,
        ))
        raw_ocr_by_engine[ocr_result.engine] = ocr_result.text
        engines_used.append(ocr_result.engine)
        warnings.extend(f"{ocr_result.engine}:{w}" for w in single.warnings)

    if not per_engine_extractions:
        result = ExtractionResult(
            source=filename, success=False,
            error="all OCR engines failed",
            warnings=warnings or ["ocr_failed"],
            engines_used=[], reconciliation_performed=False,
            operations_applied=list(operations_applied),
        )
        finalize_confidence(result)
        return result

    receipt, field_decisions, reconciliation_warnings = reconcile_extractions(per_engine_extractions)
    warnings.extend(reconciliation_warnings)

    # Representative OCR confidence/text for the flat/legacy fields: the
    # highest-confidence successful engine, so single-engine consumers of
    # the old flat contract still see a sensible value.
    best = max(per_engine_extractions, key=lambda e: e.ocr_confidence or 0.0)

    if len(per_engine_extractions) < 5:
        combined_text = "\n---\n".join(e.raw_text for e in per_engine_extractions)
    else:
        combined_text = best.raw_text
    if best.ocr_confidence is not None and best.ocr_confidence < _LOW_OCR_CONFIDENCE_THRESHOLD:
        warnings.append("low_ocr_confidence")

    result = ExtractionResult(
        source=filename,
        success=True,
        receipt=receipt,
        raw_text=combined_text,
        ocr_engine="+".join(engines_used),
        ocr_confidence=best.ocr_confidence,
        operations_applied=list(operations_applied),
        warnings=warnings,
        engines_used=engines_used,
        reconciliation_performed=len(per_engine_extractions) > 1,
        raw_ocr_by_engine=raw_ocr_by_engine,
        field_decisions=field_decisions,
    )
    result.extraction_confidence = _extraction_confidence(
        receipt, combined_text, best.ocr_confidence, warnings
    )
    validate_receipt(result)
    finalize_confidence(result)
    return result


def process_receipts(
    image_paths: list[str | Path],
    output_dir: str | Path,
    ocr_engine: OcrEngine | None = None,
    ocr_engines: list[OcrEngine] | None = None,
    use_variants: bool = False,
) -> list[ExtractionResult]:
    """
    Full pipeline for one or more receipt images: existing preprocessing
    -> one or more OCR engines -> extraction -> reconciliation (if more
    than one engine) -> validation -> confidence/review.

    Parameters
    ----------
    image_paths:
        Source image paths. Never modified (enforced by
        `receipt_pipeline.process_receipt_images`).
    output_dir:
        Where processed images are written; must be isolated from the
        source dataset (caller's responsibility, same as
        `process_receipt_images`).
    ocr_engine:
        Single-engine mode (backward compatible with the original API).
        Any `OcrEngine` implementation. Ignored if `ocr_engines` is given.
        Defaults to `TesseractOcrEngine` if neither parameter is given, so
        every pre-existing caller keeps behaving identically.
    ocr_engines:
        Multi-engine reconciliation mode. A list of `OcrEngine`
        implementations (e.g. `[TesseractOcrEngine(), EasyOcrEngine()]`,
        or a future `AzureOcrEngine` added to the list -- no other code
        here needs to change for that). Each engine runs independently on
        the same preprocessed image; results are merged by
        `reconcile_extractions`. One engine crashing does not stop the
        others -- see `_extraction_from_multi_engine`.
    use_variants:
        Enable multi-variant OCR. When True, image-quality analysis
        decides whether any ADDITIONAL preprocessing variant of the image
        is worth OCR-ing (see `variants.select_variant_stages`), each
        engine reads every selected variant, and each engine keeps the
        variant whose extraction carries the strongest evidence
        (arithmetic self-consistency, field/structure coverage, text
        coverage -- explicitly NOT OCR confidence; see `variants`).

        Defaults to False so existing callers keep byte-identical
        behaviour. On a clean image the gate selects only `final`, so
        enabling it costs nothing extra there; the cost is paid only on
        images whose quality signals suggest the single adaptive choice
        may be poor.

        Variants are collapsed to one winner PER ENGINE before
        reconciliation, so cross-engine agreement is never inflated by
        two renderings of the same image read by the same model.
    """
    if ocr_engines:
        engines = list(ocr_engines)
        multi_engine_mode = True
    else:
        engines = [ocr_engine] if ocr_engine is not None else None
        multi_engine_mode = False
        if engines is None:
            from ocr import TesseractOcrEngine
            engines = [TesseractOcrEngine()]

    if use_variants:
        # Ask for every stage the gate could possibly select; the gate
        # itself (applied per image below, using that image's own quality
        # signals) decides which of them are actually OCR'd. Stages an
        # image does not have, or that are pixel-identical to `final`, are
        # skipped by `process_receipt_images`.
        prep_records = process_receipt_images(
            image_paths, output_dir, variant_stages=["grayscale", "thresholded"],
        )
    else:
        prep_records = process_receipt_images(image_paths, output_dir)

    results: list[ExtractionResult] = []
    for record in prep_records:
        if not record["processing_success"] or not record["processed_image_path"]:
            failed = ExtractionResult(
                source=Path(record["input_path"]).name,
                success=False,
                error=record["error"] or "preprocessing failed",
                warnings=["preprocessing_failed"],
            )
            finalize_confidence(failed)
            results.append(failed)
            continue

        source_name = Path(record["input_path"]).name
        variant_notes: list[str] = []

        # Resolve which variants this specific image should be read on.
        # `final` is always first so it wins any scoring tie -- a variant
        # only displaces the pipeline's own adaptive choice on strictly
        # better evidence.
        if use_variants:
            selected = select_variant_stages(
                record["operations_applied"], record["warnings"],
            )
            available = record.get("variant_image_paths") or {}
            variant_paths = {"final": record["processed_image_path"]}
            for stage_name in selected:
                if stage_name != "final" and stage_name in available:
                    variant_paths[stage_name] = available[stage_name]
        else:
            variant_paths = {"final": record["processed_image_path"]}

        multi_variant = len(variant_paths) > 1

        if multi_engine_mode and len(engines) > 1:
            ocr_results = []
            for engine in engines:
                if multi_variant:
                    ocr_result, notes = _best_ocr_result_across_variants(
                        engine, variant_paths, source_name, record["operations_applied"],
                    )
                    variant_notes.extend(notes)
                else:
                    ocr_result = engine.recognize(record["processed_image_path"])
                    ocr_result.filename = source_name
                ocr_results.append(ocr_result)
            extraction = _extraction_from_multi_engine(ocr_results, record["operations_applied"])
        else:
            if multi_variant:
                ocr_result, notes = _best_ocr_result_across_variants(
                    engines[0], variant_paths, source_name, record["operations_applied"],
                )
                variant_notes.extend(notes)
            else:
                ocr_result = engines[0].recognize(record["processed_image_path"])
                ocr_result.filename = source_name
            extraction = _extraction_from_single_engine(ocr_result, record["operations_applied"])

        extraction.warnings = list(record["warnings"]) + variant_notes + extraction.warnings
        results.append(extraction)

    return results


def process_receipt(
    image_path: str | Path,
    output_dir: str | Path,
    ocr_engine: OcrEngine | None = None,
    ocr_engines: list[OcrEngine] | None = None,
    use_variants: bool = False,
) -> ExtractionResult:
    """Single-image convenience wrapper around `process_receipts`."""
    return process_receipts(
        [image_path], output_dir, ocr_engine=ocr_engine, ocr_engines=ocr_engines,
        use_variants=use_variants,
    )[0]
