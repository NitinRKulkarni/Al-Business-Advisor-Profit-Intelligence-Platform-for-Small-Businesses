"""
PDF -> structured Invoice using pdfplumber.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple

import pdfplumber

from .models import Invoice, LineItem, _to_decimal


def parse_invoice_pdf(pdf_bytes: bytes, file_id: str) -> Invoice:
    """
    Parse raw PDF bytes into a validated Invoice object.
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


def _extract_text_and_tables(pdf_bytes: bytes) -> Tuple[str, List[List[List[str]]]]:
    text_parts: List[str] = []
    all_tables: List[List[List[str]]] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            for table in page.extract_tables() or []:
                all_tables.append(table)

    return "\n".join(text_parts), all_tables


def _find_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r"invoice\s*(?:no|number|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)",
        r"inv\s*(?:no|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)",
    ]
    return _first_group(text, patterns)


def _find_gst(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][A-Z0-9])\b", text)
    if m:
        return m.group(1)
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
    val = val.splitlines()[0].strip()
    m = re.match(r"^\s*(?:customer\s*name|bill(?:ed)?\s*to|buyer|name)\s*[:\-]\s*(.+)$",
                 val, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
    elif ":" in val and val.lower().startswith(("customer", "bill", "buyer", "name")):
        val = val.split(":", 1)[1].strip()
    return val or None


def _find_date(text: str, labels: List[str]) -> Optional[date]:
    date_token = (
        r"("
        r"[0-9]{1,4}[\-/\.][0-9]{1,2}[\-/\.][0-9]{1,4}"
        r"|[0-9]{1,2}[\-/\s][A-Za-z]{3,9}[\-/\s][0-9]{2,4}"
        r"|[A-Za-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{2,4}"
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
    single = _find_amount(
        text, ["gst / tax", "gst/tax", "tax amount", "total tax", "total gst"]
    )
    if single is not None:
        return single

    currency = r"(?:₹|Rs\.?|\$|■|)"
    component_re = re.compile(
        rf"^\s*(?:c\s*gst|s\s*gst|i\s*gst|gst)\b"
        rf"(?:[\s@:\-–]*[0-9.]+\s*%?)?"
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

    return _find_amount(text, ["tax"])


def _find_amount(text: str, labels: List[str]) -> Optional[Decimal]:
    currency = r"(?:₹|Rs\.?|\$|■|)"
    for label in labels:
        m = re.search(
            rf"^\s*{re.escape(label)}\b"
            rf"(?:[\s:\-–]*\([^)]*\))?"
            rf"[\s:\-–]*{currency}?\s*{currency}?\s*"
            rf"([0-9][0-9,]*\.?[0-9]*)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if m:
            return _to_decimal(m.group(1))
    return None


def _parse_line_items(tables: List[List[List[str]]], text: str) -> List[LineItem]:
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
                continue
        if items:
            return items

    return _parse_line_items_from_text(text)


_NON_ITEM_RE = re.compile(
    r"phone|e-?mail|gstin|uin|bank|ifsc|a/?c|account|"
    r"invoice|date|subtotal|sub total|\btax\b|gst|cgst|sgst|igst|"
    r"total|qty|rate|description|particular|payment|terms|signator",
    re.IGNORECASE,
)

_ROW_RE = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<rate>\d[\d,]*(?:\.\d+)?)\s+"
    r"(?P<total>\d[\d,]*(?:\.\d+)?)\s*$"
)


def _item_region(lines: List[str]) -> List[str]:
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
        if i + 1 < len(region):
            nxt = region[i + 1]
            if nxt and not _ROW_RE.match(nxt) and not _NON_ITEM_RE.search(nxt):
                desc = f"{desc} {nxt}".strip()
                i += 1

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
        "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%m-%y", "%d/%m/%y",
        "%m/%d/%Y", "%m-%d-%Y",
        "%d-%b-%Y", "%d %b %Y", "%d/%b/%Y",
        "%d-%B-%Y", "%d %B %Y",
        "%d-%b-%y", "%d %b %y",
        "%b %d %Y", "%B %d %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
