"""
Test the parser against the user-provided ABC Business Solutions invoice.

Rebuilds the invoice PDF as faithfully as possible (same text, layout, and
table structure), runs the REAL parser, and reports field-by-field accuracy
against the known-correct values.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

from invoice_extractor.parser import parse_invoice_pdf


# Ground truth taken directly from the provided invoice.
EXPECTED = {
    "invoice_number": "INV-2026-0847",
    "invoice_date": "2026-08-31",
    "due_date": "2026-09-15",
    "customer_name": "Rahul Enterprises",
    # Two GSTINs appear: seller 29ABCDE1234F1Z5 and customer 29AABCR5678K1Z2.
    "gst_number_candidates": ["29AABCR5678K1Z2", "29ABCDE1234F1Z5"],
    "line_items": [
        ("Business Consultation Service", "2", "5000.00", "10000.00"),
        ("Software Support & Maintenance", "3", "2500.00", "7500.00"),
        ("Data Analytics Report", "1", "4000.00", "4000.00"),
    ],
    "total_amount": "21500.00",
    "tax": "3870.00",
    "total_amount_with_tax": "25370.00",
}


def build_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm)
    styles = getSampleStyleSheet()
    right = ParagraphStyle("r", parent=styles["Normal"], alignment=TA_RIGHT)
    story = []

    story.append(Paragraph("<b>ABC BUSINESS SOLUTIONS</b>", styles["Normal"]))
    story.append(Paragraph("Bengaluru, Karnataka, India", styles["Normal"]))
    story.append(Paragraph("GSTIN: 29ABCDE1234F1Z5", styles["Normal"]))
    story.append(Paragraph("Email: accounts@abcbusiness.in", styles["Normal"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>INVOICE</b>", styles["Title"]))
    story.append(Paragraph("Invoice No: INV-2026-0847", right))
    story.append(Paragraph("Invoice Date: 31-Aug-2026", right))
    story.append(Paragraph("Due Date: 15-Sep-2026", right))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Bill To</b>", styles["Normal"]))
    bill_to = [
        ["Customer Name: Rahul Enterprises"],
        ["Customer GSTIN: 29AABCR5678K1Z2"],
        ["Address: MG Road, Bengaluru, Karnataka - 560001"],
    ]
    t = Table(bill_to, colWidths=[170 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    story.append(t)
    story.append(Spacer(1, 10))

    data = [
        ["Sl. No.", "Item Description", "Quantity", "Rate / Unit", "Total"],
        ["1", "Business Consultation Service", "2", "5,000.00", "10,000.00"],
        ["2", "Software Support & Maintenance", "3", "2,500.00", "7,500.00"],
        ["3", "Data Analytics Report", "1", "4,000.00", "4,000.00"],
    ]
    items = Table(data, colWidths=[15 * mm, 75 * mm, 22 * mm, 28 * mm, 30 * mm])
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#cccccc")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(items)
    story.append(Spacer(1, 8))

    totals = [
        ["Total Amount (Before Tax)", "21,500.00"],
        ["GST / Tax (18%)", "3,870.00"],
        ["Total Amount With Tax", "25,370.00"],
    ]
    tt = Table(totals, colWidths=[140 * mm, 30 * mm])
    tt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(tt)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Amount Payable: 25,370.00 (Rupees Twenty-Five Thousand Three Hundred Seventy Only)",
        styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def check(label, got, expected):
    ok = str(got) == str(expected)
    return f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} expected={expected!r}", ok


def main():
    pdf = build_pdf()
    inv = parse_invoice_pdf(pdf, file_id="ABC_INV-2026-0847.pdf")

    lines = ["=== PARSED RESULT vs GROUND TRUTH ==="]
    passed = total = 0

    for field in ["invoice_number", "invoice_date", "due_date",
                  "customer_name", "total_amount", "tax", "total_amount_with_tax"]:
        got = getattr(inv, field)
        got = got.isoformat() if hasattr(got, "isoformat") else got
        msg, ok = check(field, got, EXPECTED[field])
        lines.append(msg)
        passed += ok
        total += 1

    # GST: accept either the customer or seller GSTIN.
    gst_ok = str(inv.gst_number) in EXPECTED["gst_number_candidates"]
    lines.append(f"  [{'PASS' if gst_ok else 'FAIL'}] gst_number: got={inv.gst_number!r} "
                 f"(any of {EXPECTED['gst_number_candidates']})")
    passed += gst_ok
    total += 1

    # Line items
    lines.append(f"\n  Line items parsed: {len(inv.line_items)} (expected 3)")
    li_ok = len(inv.line_items) == 3
    passed += li_ok
    total += 1
    for i, item in enumerate(inv.line_items):
        lines.append(f"    {i+1}. {item.description!r} qty={item.quantity} "
                     f"rate={item.rate_per_unit} total={item.total_rate}")

    lines.append(f"\n=== SCORE: {passed}/{total} fields correct ===")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
