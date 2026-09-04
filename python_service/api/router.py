import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from python_service.api.schemas import ExtractionResponse
from python_service.db.document_store import get_document_store, DocumentNotFoundError
from python_service.modules.pdf_invoice.service import process_pdf_invoice
from python_service.modules.image_invoice.service import process_image_invoice
from python_service.modules.whatsapp.service import process_whatsapp_chat

logger = logging.getLogger("ai_router")
router = APIRouter(prefix="/api/v1", tags=["AI Extraction"])

@router.post("/extract", response_model=ExtractionResponse)
async def extract_document(request: Request):
    """
    Dynamic Dispatcher:
    Receives request from Java backend with 'source' parameter (supports both JSON body and Form data),
    fetches document BLOB from PostgreSQL, and executes the appropriate pipeline.
    """
    content_type = request.headers.get("content-type", "").lower()
    document_id = None
    source = None

    if "application/json" in content_type:
        try:
            body = await request.json()
            document_id = body.get("document_id")
            source = body.get("source") or body.get("sourceType") or body.get("source_type")
        except Exception as e:
            logger.error("Failed to parse JSON body: %s", e)
    else:
        try:
            form = await request.form()
            document_id = form.get("document_id")
            source = form.get("source") or form.get("sourceType") or form.get("source_type")
        except Exception as e:
            logger.error("Failed to parse form body: %s", e)

    if not document_id or not source:
        raise HTTPException(
            status_code=400,
            detail=f"Both 'document_id' and 'source' are required. Got document_id={document_id}, source={source}"
        )

    normalized_source = source.strip().lower()
    logger.info("Trigger received: document_id=%s, source=%s", document_id, normalized_source)

    store = get_document_store()
    try:
        doc = store.get_document(document_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Document id={document_id} not found")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed retrieving document BLOB: {exc}")
    finally:
        store.close()

    if normalized_source in ("invoice", "pdf_invoice", "pdf"):
        result = await process_pdf_invoice(doc.raw_bytes, document_id=document_id, organization_id=doc.organization_id)
        return ExtractionResponse(
            status="COMPLETED",
            document_id=document_id,
            source=normalized_source,
            confidence_score=result.get("confidence_score"),
            extracted_data=result.get("data", {}),
            message="PDF invoice processed successfully."
        )

    elif normalized_source in ("image_invoice", "receipt", "image"):
        result = await process_image_invoice(doc.raw_bytes, document_id=document_id, organization_id=doc.organization_id)
        return ExtractionResponse(
            status="COMPLETED",
            document_id=document_id,
            source=normalized_source,
            confidence_score=result.get("confidence_score"),
            extracted_data=result.get("data", {}),
            message="Image receipt OCR processed successfully."
        )

    elif normalized_source in ("whatsapp", "whatsapp_chat", "chat"):
        result = await process_whatsapp_chat(doc.raw_bytes, document_id=document_id, organization_id=doc.organization_id)
        return ExtractionResponse(
            status="COMPLETED",
            document_id=document_id,
            source=normalized_source,
            confidence_score=100.0,
            extracted_data=result.get("data", {}),
            message="WhatsApp chat processed successfully."
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported extraction source '{source}'. Valid options: invoice, image_invoice, whatsapp."
        )

@router.post("/extract/invoice", response_model=ExtractionResponse)
async def extract_invoice_legacy(request: Request):
    content_type = request.headers.get("content-type", "").lower()
    document_id = None
    if "application/json" in content_type:
        body = await request.json()
        document_id = body.get("document_id")
    else:
        form = await request.form()
        document_id = form.get("document_id")

    if not document_id:
        raise HTTPException(status_code=400, detail="Missing document_id")

    store = get_document_store()
    try:
        doc = store.get_document(document_id)
    finally:
        store.close()

    result = await process_pdf_invoice(doc.raw_bytes, document_id=document_id, organization_id=doc.organization_id)
    return ExtractionResponse(
        status="COMPLETED",
        document_id=document_id,
        source="invoice",
        confidence_score=result.get("confidence_score"),
        extracted_data=result.get("data", {}),
        message="PDF invoice processed successfully."
    )
