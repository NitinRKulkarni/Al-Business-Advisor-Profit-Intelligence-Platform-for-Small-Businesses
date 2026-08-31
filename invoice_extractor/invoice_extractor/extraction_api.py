"""
AI Extraction Service — the callee for the Spring Boot poller.

Contract (mirrors java/mock_ai_service.py and the Spring RestClient):
    POST /extract/invoice
    Content-Type: application/x-www-form-urlencoded
    body: document_id=<uuid>

Flow:
    1. Receive document_id from the Java InvoiceTriggerService.
    2. Look up the documents row, load the original PDF bytes.
    3. Parse the PDF with the existing parser.
    4. Persist to invoices + invoice_line_items.
    5. Update documents.processed_status to COMPLETED (or FAILED on error).

Run:
    uvicorn invoice_extractor.extraction_api:app --host 0.0.0.0 --port 8000

The Java side defaults to ai.service.python.base-url=http://localhost:8000
and invoice-endpoint=/extract/invoice, so this drops straight in.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, Form, HTTPException

from .db import (
    DocumentNotFoundError,
    PdfNotAvailableError,
    get_store,
)
from .parser import parse_invoice_pdf

logger = logging.getLogger("extraction")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Invoice AI Extraction Service",
    version="1.0.0",
    description="Called by the Spring Boot poller with a document_id; "
                "loads the PDF, extracts fields, and persists the invoice.",
)


@app.get("/health")
def health():
    return {"status": "UP", "service": "Python AI Extraction Service"}


def _confidence(invoice) -> float:
    """
    Cheap confidence heuristic: fraction of the key header/total fields that
    were successfully extracted. Gives the Java side / UI a review signal.
    """
    fields = [
        invoice.invoice_number and invoice.invoice_number != "UNKNOWN",
        invoice.invoice_date is not None,
        invoice.customer_name is not None,
        invoice.total_amount is not None,
        invoice.total_amount_with_tax is not None,
        len(invoice.line_items) > 0,
    ]
    return round(100.0 * sum(bool(f) for f in fields) / len(fields), 2)


@app.post("/extract/invoice")
def extract_invoice(document_id: str = Form(...)):
    """Extract an invoice by document_id and persist the result."""
    logger.info("Extraction trigger received: document_id=%s | DB_BACKEND=%s | DATABASE_URL=%s",
                document_id, os.environ.get("DB_BACKEND"), os.environ.get("DATABASE_URL"))
    store = get_store()
    logger.info("Using DocumentStore class: %s", store.__class__.__name__)
    try:
        try:
            doc = store.get_document(document_id)
        except DocumentNotFoundError:
            raise HTTPException(status_code=404,
                                detail=f"No document found for id={document_id}")
        except PdfNotAvailableError as exc:
            store.set_document_status(document_id, "FAILED")
            raise HTTPException(status_code=422, detail=str(exc))

        if doc.file_type not in ("Invoice", "INVOICE"):
            raise HTTPException(
                status_code=422,
                detail=f"document {document_id} is fileType={doc.file_type}, not an Invoice",
            )

        store.set_document_status(document_id, "PROCESSING")
        try:
            invoice = parse_invoice_pdf(doc.pdf_bytes, file_id=document_id)
            confidence = _confidence(invoice)
            invoice_id = store.save_invoice(
                document_id=document_id,
                organization_id=doc.organization_id,
                invoice=invoice,
                confidence=confidence,
            )
            store.set_document_status(document_id, "COMPLETED")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction failed for %s", document_id)
            store.set_document_status(document_id, "FAILED")
            raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

        data = invoice.model_dump(mode="json")
        data.pop("raw_text", None)
        return {
            "status": "COMPLETED",
            "document_id": document_id,
            "invoice_id": invoice_id,
            "confidence_score": confidence,
            "extracted_data": data,
        }
    finally:
        store.close()
