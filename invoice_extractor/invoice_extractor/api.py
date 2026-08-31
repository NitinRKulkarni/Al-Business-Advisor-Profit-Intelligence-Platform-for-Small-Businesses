"""
HTTP API layer — connects the invoice parser to a frontend.

This is the bridge a browser/SPA calls. It wraps the existing
`parse_invoice_pdf` + repository behind REST endpoints that mirror the
Omni-CFO branch contract:

    POST /api/v1/files/upload        multipart upload -> parse -> store
    GET  /api/v1/files               list uploaded documents
    GET  /api/v1/files/{document_id} fetch one parsed document

Run locally:
    uvicorn invoice_extractor.api:app --host 0.0.0.0 --port 8080 --reload

Then open http://localhost:8080/docs for interactive Swagger UI, or point
your frontend's fetch() calls at http://localhost:8080.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .parser import parse_invoice_pdf

app = FastAPI(
    title="Invoice Extractor API",
    version="1.0.0",
    description="Upload a PDF invoice; get back structured data. Post-ingestion parser.",
)

# CORS: allow a browser frontend to call this API. In production, replace "*"
# with your actual frontend origin(s), e.g. ["https://app.yourcompany.com"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# In-memory stores (swap for Postgres/DynamoDB in production).
#   _documents:   document_id -> metadata + parsed payload
#   _hash_index:  (tenant_id, sha256) -> document_id   (for dedup)
# --------------------------------------------------------------------------- #
_documents: Dict[str, dict] = {}
_hash_index: Dict[tuple, str] = {}

ALLOWED_FILE_TYPES = {"Invoice", "WhatsAppChat", "BankStmt", "Inventory"}


class UploadResponse(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    status: str
    message: str


class FileListItem(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    upload_date: str
    processed_status: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/files/upload", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    fileType: str = Form("Invoice"),
    # In production the tenant_id comes from the JWT; accepted here for local testing.
    tenant_id: str = Form("demo-tenant"),
):
    """
    Accept a file upload, deduplicate by SHA-256, parse it, and store the result.

    Returns 409 if the same file (per tenant) was already uploaded.
    """
    if fileType not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"fileType must be one of {sorted(ALLOWED_FILE_TYPES)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    file_hash = hashlib.sha256(content).hexdigest()
    dedup_key = (tenant_id, file_hash)
    if dedup_key in _hash_index:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "DUPLICATE_FILE",
                "message": "A file with this SHA256 hash has already been uploaded.",
                "document_id": _hash_index[dedup_key],
            },
        )

    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "file_name": file.filename or "upload.pdf",
        "file_type": fileType,
        "file_hash": file_hash,
        "upload_date": now,
        "processed_status": "PENDING",
        "extracted_data": None,
        "error": None,
    }
    _documents[document_id] = record
    _hash_index[dedup_key] = document_id

    # Parse invoices synchronously (small/fast). Other types are stubbed for now.
    if fileType == "Invoice":
        try:
            invoice = parse_invoice_pdf(content, file_id=document_id)
            data = invoice.model_dump(mode="json")
            data.pop("raw_text", None)  # keep the API response lean
            record["extracted_data"] = data
            record["processed_status"] = "COMPLETED"
        except Exception as exc:  # noqa: BLE001 - surface parse failures to the client
            record["processed_status"] = "FAILED"
            record["error"] = str(exc)

    return UploadResponse(
        document_id=document_id,
        file_name=record["file_name"],
        file_type=fileType,
        status=record["processed_status"],
        message="Upload successful. File processed."
        if record["processed_status"] == "COMPLETED"
        else "Upload received.",
    )


@app.get("/api/v1/files", response_model=dict)
def list_files(fileType: Optional[str] = None):
    """List uploaded documents, optionally filtered by fileType."""
    items: List[FileListItem] = []
    for rec in _documents.values():
        if fileType and rec["file_type"] != fileType:
            continue
        items.append(
            FileListItem(
                document_id=rec["document_id"],
                file_name=rec["file_name"],
                file_type=rec["file_type"],
                upload_date=rec["upload_date"],
                processed_status=rec["processed_status"],
            )
        )
    return {"files": [i.model_dump() for i in items]}


@app.get("/api/v1/files/{document_id}")
def get_file(document_id: str):
    """Fetch a single document's metadata and parsed data."""
    rec = _documents.get(document_id)
    if not rec:
        raise HTTPException(status_code=404, detail="document_id not found")
    return {
        "document_id": rec["document_id"],
        "file_name": rec["file_name"],
        "file_type": rec["file_type"],
        "status": rec["processed_status"],
        "extracted_data": rec["extracted_data"],
        "error": rec["error"],
    }
