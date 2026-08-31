"""
Structured data models for a formal PDF invoice.

These map 1:1 to the fields the business needs:
- Invoice number, invoice date, due date
- Customer name + GST number
- Line items (description, quantity, rate/unit, total rate)
- Total amount, tax, total amount with tax

Pydantic v2 gives us validation + JSON (de)serialization for free, which
keeps the DB layer and the API contract honest.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class LineItem(BaseModel):
    """A single row in the invoice's line-item table."""

    description: str = Field(..., description="Item description")
    quantity: Decimal = Field(..., description="Quantity")
    rate_per_unit: Decimal = Field(..., description="Rate / unit price")
    total_rate: Decimal = Field(..., description="Line total (quantity * rate_per_unit)")

    @field_validator("quantity", "rate_per_unit", "total_rate", mode="before")
    @classmethod
    def _coerce_number(cls, v):
        return _to_decimal(v)


class Invoice(BaseModel):
    """
    Fully parsed invoice. `file_id` and `invoice_id` are the primary keys
    used for storage/retrieval.
    """

    # --- Identity / storage keys ---
    file_id: str = Field(..., description="ID of the source PDF file (e.g. S3 object key/uuid)")
    invoice_id: str = Field(..., description="Business invoice number extracted from the PDF")

    # --- Header ---
    invoice_number: str
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None

    # --- Customer ---
    customer_name: Optional[str] = None
    gst_number: Optional[str] = None

    # --- Line items ---
    line_items: List[LineItem] = Field(default_factory=list)

    # --- Totals ---
    total_amount: Optional[Decimal] = Field(None, description="Subtotal before tax")
    tax: Optional[Decimal] = Field(None, description="Total tax amount")
    total_amount_with_tax: Optional[Decimal] = Field(None, description="Grand total incl. tax")

    # --- Provenance / debugging ---
    raw_text: Optional[str] = Field(None, description="Raw extracted text, kept for auditing")

    @field_validator("total_amount", "tax", "total_amount_with_tax", mode="before")
    @classmethod
    def _coerce_number(cls, v):
        return _to_decimal(v)

    def to_dynamo_item(self) -> dict:
        """Serialize to a DynamoDB-friendly dict (Decimals preserved, dates as ISO strings)."""
        data = self.model_dump(mode="json")  # dates -> ISO strings, Decimals -> strings via json mode
        # DynamoDB handles Decimal natively; convert numeric strings back to Decimal.
        return _jsonify_for_dynamo(data)


def _to_decimal(v) -> Optional[Decimal]:
    """Best-effort conversion of scraped strings like '1,234.50' or '₹120.00' to Decimal."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v)
    # strip currency symbols, thousands separators, and whitespace
    cleaned = (
        s.replace(",", "")
        .replace("₹", "")
        .replace("$", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .strip()
    )
    if cleaned in ("", "-"):
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _jsonify_for_dynamo(obj):
    """Recursively convert float values to Decimal (DynamoDB rejects float)."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _jsonify_for_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify_for_dynamo(v) for v in obj]
    return obj
