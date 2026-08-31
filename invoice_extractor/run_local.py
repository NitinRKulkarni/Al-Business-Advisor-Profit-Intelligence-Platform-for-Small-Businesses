"""
Local runner: parse a PDF from disk and print the structured invoice.
Lets you validate extraction before deploying to AWS.

Usage:
    python run_local.py path/to/invoice.pdf
"""
import json
import sys
from pathlib import Path

from invoice_extractor.parser import parse_invoice_pdf
from invoice_extractor.repository import InMemoryInvoiceRepository


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_local.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    pdf_bytes = pdf_path.read_bytes()
    file_id = pdf_path.name

    invoice = parse_invoice_pdf(pdf_bytes, file_id=file_id)

    repo = InMemoryInvoiceRepository()
    repo.save(invoice)

    # Drop raw_text from the console view for readability.
    view = invoice.model_dump(mode="json")
    view.pop("raw_text", None)
    print(json.dumps(view, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
