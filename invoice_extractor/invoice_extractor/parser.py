"""
PDF -> structured Invoice using pdfplumber.

Strategy
--------
Formal invoices have two extractable regions:
  1. Header / footer key-value fields (Invoice No, Date, GST, Totals)
     -> extracted from the flat text via regex.
  2. A line-item table
     -> extracted with pdfplumber's table extraction, with a text fallback.

Real-world invoices vary wildly in layout, so the regexes below are a
*starting point* tuned to the fields you listed. Treat the patterns as
configuration you refine against your actual invoice templates.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple

import pdfplumber

from .models import Invoice, LineItem, _to_decimal


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def parse_invoice_pdf(pdf_bytes: bytes, file_id: str) -> Invoice:
    """
    Parse raw PDF bytes into a validated Invoice object.

    Args:
        pdf_bytes: the PDF file contents.
        file_id:   identifier of the source file (e.g. S3 key or a UUID).

    Returns:
        A populated Invoice. Fields that can't be found are left as None
        rather than raising, so partial extraction still persists.
    """
    text, tables = _extract_text_and_tables(pdf_bytes)

    invoice_number = _find_invoice_number(text) or "UNKNOWN"
    line_items = _parse_line_items(tables, text)

    invoice = Invoice(
        file_id=file_id,
        invoice_id=invoice_number,
        invoice_number=invoice_number,
        invoice_date=_find_date(text, ["invoice date", "date"]),
        due_date=_find_date(text, ["due date"]),
        customer_name=_find_customer_name(text),
        gst_number=_find_gst(text),
        line_items=line_items,
        total_amount=_find_amount(
            text,
            ["total amount (before tax)", "total amount before tax",
             "sub total", "subtotal", "taxable amount", "total amount", "total rate"],
        ),
        tax=_find_tax(text),
        total_amount_with_tax=_find_amount(
            text,
            ["total amount with tax", "total with tax", "grand total",
             "total payable", "amount payable", "net amount"],
        ),
        raw_text=text,
    )
    return invoice


# --------------------------------------------------------------------------- #
# Extraction primitives
# --------------------------------------------------------------------------- #
def _extract_text_and_tables(pdf_bytes: bytes) -> Tuple[str, List[List[List[str]]]]:
    """Return (full_text, list_of_tables) across all pages."""
    text_parts: List[str] = []
    all_tables: List[List[List[str]]] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            for table in page.extract_tables() or []:
                all_tables.append(table)

    return "\n".join(text_parts), all_tables


# --------------------------------------------------------------------------- #
# Header field parsers
# --------------------------------------------------------------------------- #
def _find_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r"invoice\s*(?:no|number|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)",
        r"inv\s*(?:no|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)",
    ]
    return _first_group(text, patterns)


def _find_gst(text: str) -> Optional[str]:
    # Indian GSTIN: 15 chars -> 2 digit state, 10 char PAN, 1 entity, 'Z', 1 checksum.
    m = re.search(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][A-Z0-9])\b", text)
    if m:
        return m.group(1)
    # Fallback: labelled GST field.
    return _first_group(text, [r"gst\s*(?:in|no|number)?\s*[:\-]?\s*([0-9A-Z]{10,15})"])


def _find_customer_name(text: str) -> Optional[str]:
    patterns = [
        r"customer\s*name\s*[:\-]?\s*(.+)",
        r"(?:bill(?:ed)?\s*to|buyer)\s*[:\-]?\s*(.+)",
        r"(?:to)\s*[:\-]\s*(.+)",
    ]
    val = _first_group(text, patterns)
    if not val:
        return None
    # First line only.
    val = val.splitlines()[0].strip()
    # If the captured text still leads with a label (e.g. "Customer Name:"),
    # strip everything up to and including the first colon.
    m = re.match(r"^\s*(?:customer\s*name|bill(?:ed)?\s*to|buyer|name)\s*[:\-]\s*(.+)$",
                 val, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
    elif ":" in val and val.lower().startswith(("customer", "bill", "buyer", "name")):
        val = val.split(":", 1)[1].strip()
    return val or None


def _find_date(text: str, labels: List[str]) -> Optional[date]:
    # Accept both numeric dates (31-08-2026, 31/08/26) and month-name dates
    # (31-Aug-2026, 15 Sep 2026, Aug 31, 2026).
    date_token = (
        r"("
        r"[0-9]{1,4}[\-/\.][0-9]{1,2}[\-/\.][0-9]{1,4}"          # 31-08-2026
        r"|[0-9]{1,2}[\-/\s][A-Za-z]{3,9}[\-/\s][0-9]{2,4}"       # 31-Aug-2026
        r"|[A-Za-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{2,4}"             # Aug 31, 2026
        r")"
    )
    for label in labels:
        m = re.search(
            rf"{re.escape(label)}\s*[:\-]?\s*{date_token}",
            text,
            re.IGNORECASE,
        )
        if m:
            parsed = _parse_date(m.group(1))
            if parsed:
                return parsed
    return None


def _find_tax(text: str) -> Optional[Decimal]:
    """
    Resolve the tax amount, handling both single-line and split taxes.

    1. Try a single combined tax label (e.g. "GST / Tax (18%)", "Tax Amount").
    2. If absent, sum every component tax line (CGST + SGST, or IGST). Indian
       GST invoices commonly split tax into CGST and SGST halves.
    """
    single = _find_amount(
        text, ["gst / tax", "gst/tax", "tax amount", "total tax", "total gst"]
    )
    if single is not None:
        return single

    currency = r"(?:₹|Rs\.?|\$|■|�)"
    component_re = re.compile(
        rf"^\s*(?:c\s*gst|s\s*gst|i\s*gst|gst)\b"
        rf"(?:[\s@:\-–]*[0-9.]+\s*%?)?"          # optional "@ 9.0%"
        rf"[\s:\-–]*{currency}?\s*([0-9][0-9,]*\.?[0-9]*)",
        re.IGNORECASE | re.MULTILINE,
    )
    total = Decimal("0")
    found = False
    for m in component_re.finditer(text):
        val = _to_decimal(m.group(1))
        if val is not None:
            total += val
            found = True
    if found:
        return total

    # Last resort: a bare "tax" label.
    return _find_amount(text, ["tax"])


def _find_amount(text: str, labels: List[str]) -> Optional[Decimal]:
    """
    Find a currency amount that follows one of the given labels.
    """
    currency = r"(?:₹|Rs\.?|INR|\$|■|)"
    for label in labels:
        m = re.search(
            rf"{re.escape(label)}\b"
            rf"(?:[^\n:]*?)?"
            rf"[\s:\-–=]+"
            rf"{currency}?\s*{currency}?\s*"
            rf"([0-9][0-9,]*\.?[0-9]*)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if m:
            val = _to_decimal(m.group(1))
            if val is not None:
                return val
    return None


# --------------------------------------------------------------------------- #
# Line-item table parser
# --------------------------------------------------------------------------- #
def _parse_line_items(tables: List[List[List[str]]], text: str) -> List[LineItem]:
    """
    Parse line items from extracted tables. Picks the table whose header
    row looks like a line-item header (description/qty/rate/amount).
    """
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [(c or "").strip().lower() for c in table[0]]
        col_map = _map_columns(header)
        if col_map.get("description") is None:
            continue

        items: List[LineItem] = []
        for row in table[1:]:
            if not any(cell and cell.strip() for cell in row):
                continue
            desc = _cell(row, col_map.get("description"))
            if not desc:
                continue
            try:
                items.append(
                    LineItem(
                        description=desc,
                        quantity=_cell(row, col_map.get("quantity")) or 0,
                        rate_per_unit=_cell(row, col_map.get("rate")) or 0,
                        total_rate=_cell(row, col_map.get("total")) or 0,
                    )
                )
            except Exception:
                # Skip malformed rows rather than failing the whole parse.
                continue
        if items:
            return items

    # Fallback: no grid-based table detected (common with borderless invoices).
    # Parse line items from the raw text using a positional heuristic.
    return _parse_line_items_from_text(text)


# A line clearly NOT a line item even if it ends in numbers (contact / bank /
# tax / header rows). Used to reject false positives like a phone number.
_NON_ITEM_RE = re.compile(
    r"phone|e-?mail|gstin|uin|bank|ifsc|a/?c|account|"
    r"invoice|date|subtotal|sub total|\btax\b|gst|cgst|sgst|igst|"
    r"total|qty|rate|description|particular|payment|terms|signator",
    re.IGNORECASE,
)

# The item row: a description followed by qty, rate, and line total.
_ROW_RE = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<rate>\d[\d,]*(?:\.\d+)?)\s+"
    r"(?P<total>\d[\d,]*(?:\.\d+)?)\s*$"
)


def _item_region(lines: List[str]) -> List[str]:
    """
    Narrow the search to the rows between the line-item header
    ("... Qty ... Rate ... Total ...") and the totals block
    ("Subtotal" / "Total" / a tax line). This removes header, address,
    and footer noise that otherwise produces phantom line items.
    """
    start = 0
    for i, ln in enumerate(lines):
        low = ln.lower()
        if ("description" in low or "particular" in low) and (
            "qty" in low or "quantity" in low or "rate" in low or "amount" in low
        ):
            start = i + 1
            break

    end = len(lines)
    for i in range(start, len(lines)):
        low = lines[i].strip().lower()
        if low.startswith(("subtotal", "sub total", "total ", "total:", "cgst",
                            "sgst", "igst", "grand total", "amount payable",
                            "total amount", "total with tax")):
            end = i
            break
    return lines[start:end]


def _parse_line_items_from_text(text: str) -> List[LineItem]:
    """
    Text fallback for borderless line-item tables.

    Handles the common case where an item's description wraps onto the next
    line while the numbers (qty/rate/total) sit on the first line, e.g.:

        Enterprise Cloud ... - Tier 1        2  45,000.00  90,000.00
        Standard Support Package (Monthly Retainer)

    The trailing continuation line is appended to the description.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    region = _item_region(lines)

    items: List[LineItem] = []
    i = 0
    while i < len(region):
        line = region[i]
        if not line:
            i += 1
            continue
        m = _ROW_RE.match(line)
        if not m or _NON_ITEM_RE.search(line):
            i += 1
            continue

        desc = m.group("desc").strip()
        # If the next line is plain text (no trailing numbers, not a total),
        # treat it as a wrapped continuation of this item's description.
        if i + 1 < len(region):
            nxt = region[i + 1]
            if nxt and not _ROW_RE.match(nxt) and not _NON_ITEM_RE.search(nxt):
                desc = f"{desc} {nxt}".strip()
                i += 1  # consume the continuation line

        try:
            items.append(
                LineItem(
                    description=desc,
                    quantity=m.group("qty"),
                    rate_per_unit=m.group("rate"),
                    total_rate=m.group("total"),
                )
            )
        except Exception:
            pass
        i += 1
    return items


def _map_columns(header: List[str]) -> dict:
    """Map a header row to canonical column indices."""
    mapping: dict = {"description": None, "quantity": None, "rate": None, "total": None}
    for idx, col in enumerate(header):
        if mapping["description"] is None and any(k in col for k in ("description", "item", "particular")):
            mapping["description"] = idx
        elif mapping["quantity"] is None and any(k in col for k in ("qty", "quantity")):
            mapping["quantity"] = idx
        elif mapping["rate"] is None and any(k in col for k in ("rate", "unit price", "price/unit", "rate/unit")):
            mapping["rate"] = idx
        elif mapping["total"] is None and any(k in col for k in ("amount", "total")):
            mapping["total"] = idx
    return mapping


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _cell(row: List[str], idx: Optional[int]) -> Optional[str]:
    if idx is None or idx >= len(row):
        return None
    val = row[idx]
    return val.strip() if isinstance(val, str) else val


def _first_group(text: str, patterns: List[str]) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip().replace(",", "")
    fmts = [
        # numeric
        "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%m-%y", "%d/%m/%y",
        "%m/%d/%Y", "%m-%d-%Y",
        # month-name (abbreviated + full), e.g. 31-Aug-2026, 15 Sep 2026
        "%d-%b-%Y", "%d %b %Y", "%d/%b/%Y",
        "%d-%B-%Y", "%d %B %Y",
        "%d-%b-%y", "%d %b %y",
        # month-first, e.g. Aug 31 2026
        "%b %d %Y", "%B %d %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
