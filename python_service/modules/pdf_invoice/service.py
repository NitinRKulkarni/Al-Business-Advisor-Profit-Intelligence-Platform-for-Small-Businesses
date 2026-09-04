from typing import Any, Dict
from python_service.db.document_store import get_document_store
from .parser import parse_invoice_pdf

def _calculate_confidence(invoice) -> float:
    fields = [
        invoice.invoice_number and invoice.invoice_number != "UNKNOWN",
        invoice.invoice_date is not None,
        invoice.customer_name is not None,
        invoice.total_amount is not None,
        invoice.total_amount_with_tax is not None,
        len(invoice.line_items) > 0,
    ]
    return round(100.0 * sum(bool(f) for f in fields) / len(fields), 2)

async def process_pdf_invoice(raw_bytes: bytes, document_id: str, organization_id: str) -> Dict[str, Any]:
    """
    Parses PDF invoice bytes, persists to PostgreSQL `invoices` + `invoice_line_items`,
    and updates document status to COMPLETED.
    """
    invoice = parse_invoice_pdf(raw_bytes, file_id=document_id)
    confidence = _calculate_confidence(invoice)

    data = invoice.model_dump(mode="json")
    data.pop("raw_text", None)

    store = get_document_store()
    try:
        invoice_id = store.save_invoice(
            document_id=document_id,
            organization_id=organization_id,
            invoice_data=data,
            source_type="PDF",
            confidence=confidence,
        )
        store.set_document_status(document_id, "COMPLETED")
    finally:
        store.close()

    return {
        "invoice_id": invoice_id,
        "confidence_score": confidence,
        "data": data,
    }
