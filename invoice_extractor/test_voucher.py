"""
Test the parser against the Nexus Enterprises TAX INVOICE.

Stressors vs. earlier invoices:
  - Multi-line wrapped item descriptions (numbers on 2nd line)
  - Split tax: CGST + SGST (no single "tax" line)
  - Indian lakh number grouping: 1,62,500.00
  - "BILL TO:" block with name on the next line (no "Customer Name:" label)
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

from invoice_extractor.parser import parse_invoice_pdf


EXPECTED = {
    "invoice_number": "NEX-2026-8941",
    "invoice_date": "2026-08-31",
    "due_date": "2026-09-15",
    "customer_name": "Acme Global Solutions Logistics Inc.",
    "gst_candidates": ["06AAACA4321K2Z0", "29ABCDE1234F1Z5"],
    "total_amount": "162500.00",      # Subtotal
    "tax": "29250.00",                 # CGST 14625 + SGST 14625
    "total_amount_with_tax": "191750.00",
    "n_items": 3,
    "item_totals": ["90000.00", "35000.00", "37500.00"],
}


def build_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm)
    styles = getSampleStyleSheet()
    right = ParagraphStyle("r", parent=styles["Normal"], alignment=TA_RIGHT)
    cell = ParagraphStyle("c", parent=styles["Normal"], fontSize=9, leading=11)
    story = []

    story.append(Paragraph("<b>NEXUS ENTERPRISES PVT LTD</b>", styles["Heading2"]))
    story.append(Paragraph("Building 4B, Phase 3, Outer Ring Road", styles["Normal"]))
    story.append(Paragraph("Bengaluru, Karnataka, 560103", styles["Normal"]))
    story.append(Paragraph("Email: billing@nexusenterprises.com", styles["Normal"]))
    story.append(Paragraph("Phone: +91 80 4912 3456", styles["Normal"]))
    story.append(Paragraph("GSTIN: 29ABCDE1234F1Z5", styles["Normal"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>TAX INVOICE</b>", styles["Title"]))
    story.append(Paragraph("Invoice No: NEX-2026-8941", right))
    story.append(Paragraph("Date: 31-Aug-2026", right))
    story.append(Paragraph("Due Date: 15-Sep-2026", right))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>BILL TO:</b>", styles["Normal"]))
    story.append(Paragraph("<b>Acme Global Solutions Logistics Inc.</b>", styles["Normal"]))
    story.append(Paragraph("Plot No. 12, Sector 44, Gurgaon", styles["Normal"]))
    story.append(Paragraph("Haryana, 122003", styles["Normal"]))
    story.append(Paragraph("Customer GSTIN: 06AAACA4321K2Z0", styles["Normal"]))
    story.append(Spacer(1, 10))

    data = [
        [Paragraph("<b>Item Description</b>", cell), Paragraph("<b>Qty</b>", cell),
         Paragraph("<b>Rate / Unit</b>", cell), Paragraph("<b>Total Rate</b>", cell)],
        [Paragraph("Enterprise Cloud Infrastructure Management Service - Tier 1 "
                   "Standard Support Package (Monthly Retainer)", cell),
         "2", "45,000.00", "90,000.00"],
        [Paragraph("Custom API Integration & Advanced Security Protocol "
                   "Deployments (Professional Services Add-on)", cell),
         "1", "35,000.00", "35,000.00"],
        [Paragraph("Hardware Endpoint Terminals (Secure Firewall Router - "
                   "Rackmount Edition Model v4)", cell),
         "3", "12,500.00", "37,500.00"],
    ]
    items = Table(data, colWidths=[95 * mm, 18 * mm, 30 * mm, 30 * mm])
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2d4a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(items)
    story.append(Spacer(1, 6))

    totals = [
        ["Subtotal:", "1,62,500.00"],
        ["CGST @ 9.0%:", "14,625.00"],
        ["SGST @ 9.0%:", "14,625.00"],
        ["Total with Tax:", "1,91,750.00"],
    ]
    tt = Table(totals, colWidths=[143 * mm, 30 * mm])
    tt.setStyle(TableStyle([("ALIGN", (0, 0), (0, -1), "RIGHT"),
                            ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    story.append(tt)
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Payment Terms &amp; Bank Details</b>", styles["Normal"]))
    story.append(Paragraph("Payment is due within 15 days of invoice date.", styles["Normal"]))
    story.append(Paragraph("Bank Name: HDFC Bank Ltd", styles["Normal"]))
    story.append(Paragraph("A/C Number: 50200012345678", styles["Normal"]))
    story.append(Paragraph("IFSC Code: HDFC0000123", styles["Normal"]))
    story.append(Paragraph("Account Type: Current Account", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def main():
    pdf = build_pdf()
    inv = parse_invoice_pdf(pdf, file_id="NEX-2026-8941.pdf")

    lines = ["=== PARSED RESULT vs GROUND TRUTH ==="]
    passed = total = 0

    def rec(label, got, expected, ok=None):
        nonlocal passed, total
        if ok is None:
            ok = str(got) == str(expected)
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} expected={expected!r}")
        passed += ok
        total += 1

    d_inv = inv.invoice_date.isoformat() if inv.invoice_date else None
    d_due = inv.due_date.isoformat() if inv.due_date else None
    rec("invoice_number", inv.invoice_number, EXPECTED["invoice_number"])
    rec("invoice_date", d_inv, EXPECTED["invoice_date"])
    rec("due_date", d_due, EXPECTED["due_date"])
    rec("customer_name", inv.customer_name, EXPECTED["customer_name"])
    rec("gst_number", inv.gst_number, EXPECTED["gst_candidates"],
        ok=str(inv.gst_number) in EXPECTED["gst_candidates"])
    rec("total_amount(subtotal)", inv.total_amount, EXPECTED["total_amount"])
    rec("tax(CGST+SGST)", inv.tax, EXPECTED["tax"])
    rec("total_amount_with_tax", inv.total_amount_with_tax, EXPECTED["total_amount_with_tax"])

    rec("line_item_count", len(inv.line_items), EXPECTED["n_items"])
    lines.append("  --- line items ---")
    for i, it in enumerate(inv.line_items):
        lines.append(f"    {i+1}. qty={it.quantity} rate={it.rate_per_unit} "
                     f"total={it.total_rate} :: {it.description!r}")

    lines.append(f"\n=== SCORE: {passed}/{total} ===")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
