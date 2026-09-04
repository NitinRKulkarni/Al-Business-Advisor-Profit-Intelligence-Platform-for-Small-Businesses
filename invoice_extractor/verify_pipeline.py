"""
End-to-end verification for the invoice-extractor module.

1. Generate a formal sample invoice PDF in-memory (reportlab).
2. Parse it with the real pdfplumber-based parser.
3. Persist it to the in-memory repository keyed by file_id.
4. Read it back and print the structured result.

Run:  python verify_pipeline.py
"""
import io
import json

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from invoice_extractor.parser import parse_invoice_pdf
from invoice_extractor.repository import InMemoryInvoiceRepository


def build_sample_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("TAX INVOICE", styles["Title"]))
    story.append(Spacer(1, 8))

    header = (
        "Invoice Number: INV-2026-00042<br/>"
        "Invoice Date: 12/08/2026<br/>"
        "Due Date: 11/09/2026<br/>"
        "Bill To: Acme Retail Pvt Ltd<br/>"
        "GSTIN: 29ABCDE1234F1Z5"
    )
    story.append(Paragraph(header, styles["Normal"]))
    story.append(Spacer(1, 12))

    data = [
        ["Description", "Qty", "Rate/Unit", "Total Rate"],
        ["Widget A - stainless", "10", "150.00", "1500.00"],
        ["Widget B - brass fitting", "5", "220.00", "1100.00"],
        ["Service - installation", "2", "500.00", "1000.00"],
    ]
    table = Table(data, colWidths=[80 * mm, 20 * mm, 30 * mm, 30 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))

    totals = (
        "Total Amount: 3600.00<br/>"
        "Tax (GST 18%): 648.00<br/>"
        "Total Amount With Tax: 4248.00"
    )
    story.append(Paragraph(totals, styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def main():
    lines = []
    try:
        pdf_bytes = build_sample_pdf()
        file_id = "sample_invoice.pdf"

        invoice = parse_invoice_pdf(pdf_bytes, file_id=file_id)

        repo = InMemoryInvoiceRepository()
        repo.save(invoice)

        stored = repo.get_by_file_id(file_id)
        stored.pop("raw_text", None)

        lines.append("=== STORED INVOICE (keyed by file_id / invoice_id) ===")
        lines.append(json.dumps(stored, indent=2, ensure_ascii=False))

        assert invoice.file_id == file_id
        assert invoice.invoice_number == "INV-2026-00042", invoice.invoice_number
        assert invoice.gst_number == "29ABCDE1234F1Z5", invoice.gst_number
        assert len(invoice.line_items) == 3, f"expected 3 line items, got {len(invoice.line_items)}"
        lines.append("\nRESULT: PASS")
    except Exception as e:
        import traceback
        lines.append("RESULT: FAIL")
        lines.append(traceback.format_exc())

    print("\n".join(lines))


if __name__ == "__main__":
    main()
