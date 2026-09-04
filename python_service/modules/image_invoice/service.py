import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

# Ensure image_invoice root is in sys.path for internal subpackage imports (ocr, image_processing)
_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

from receipt_extraction.extractor import process_receipt
from python_service.db.document_store import get_document_store

async def process_image_invoice(raw_bytes: bytes, document_id: str, organization_id: str) -> Dict[str, Any]:
    """
    Processes image receipt bytes through the OCR + receipt extraction pipeline,
    persists structured data into PostgreSQL `invoices` + `invoice_line_items`,
    and updates document status to COMPLETED.
    """
    # Write bytes to a temporary image file for pipeline consumption
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        tmp_file.write(raw_bytes)
        tmp_path = tmp_file.name

    try:
        # Run OCR extraction pipeline
        extraction_result = process_receipt(tmp_path)
        data_dict = extraction_result.to_dict() if hasattr(extraction_result, "to_dict") else {}
        receipt_data = data_dict.get("receipt_data", {})

        # Map to unified invoice schema
        line_items = [
            {
                "description": item.get("description", "Item"),
                "quantity": item.get("quantity", 1.0),
                "rate_per_unit": item.get("unit_price"),
                "total_rate": item.get("total_price"),
            }
            for item in receipt_data.get("line_items", [])
        ]

        unified_invoice = {
            "invoice_number": receipt_data.get("receipt_number") or receipt_data.get("invoice_number") or "REC-" + document_id[:8],
            "invoice_date": receipt_data.get("date"),
            "due_date": None,
            "customer_name": receipt_data.get("merchant_name") or receipt_data.get("vendor_name"),
            "gst_number": receipt_data.get("tax_id") or receipt_data.get("gstin"),
            "total_amount": receipt_data.get("subtotal"),
            "tax": receipt_data.get("tax_amount"),
            "total_amount_with_tax": receipt_data.get("total_amount"),
            "line_items": line_items,
        }

        confidence = float(data_dict.get("confidence", 85.0)) if data_dict.get("confidence") is not None else 85.0

        store = get_document_store()
        try:
            invoice_id = store.save_invoice(
                document_id=document_id,
                organization_id=organization_id,
                invoice_data=unified_invoice,
                source_type="IMAGE",
                confidence=confidence,
            )
            store.set_document_status(document_id, "COMPLETED")
        finally:
            store.close()

        return {
            "invoice_id": invoice_id,
            "confidence_score": confidence,
            "data": unified_invoice,
            "raw_ocr_result": data_dict,
        }

    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
