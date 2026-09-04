"""
Structured data models for a formal PDF invoice.
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
    Fully parsed invoice.
    """

    file_id: str = Field(..., description="ID of the source PDF file")
    invoice_id: str = Field(..., description="Business invoice number extracted from the PDF")

    invoice_number: str
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None

    customer_name: Optional[str] = None
    gst_number: Optional[str] = None

    line_items: List[LineItem] = Field(default_factory=list)

    total_amount: Optional[Decimal] = Field(None, description="Subtotal before tax")
    tax: Optional[Decimal] = Field(None, description="Total tax amount")
    total_amount_with_tax: Optional[Decimal] = Field(None, description="Grand total incl. tax")

    raw_text: Optional[str] = Field(None, description="Raw extracted text")

    @field_validator("total_amount", "tax", "total_amount_with_tax", mode="before")
    @classmethod
    def _coerce_number(cls, v):
        return _to_decimal(v)


def _to_decimal(v) -> Optional[Decimal]:
    """Best-effort conversion of scraped strings like '1,00,000.50' or '₹1,50,000.00' to Decimal."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip()
    cleaned = (
        s.replace(",", "")
        .replace("₹", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
        .strip()
    )
    if cleaned in ("", "-", "None", "null"):
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None
