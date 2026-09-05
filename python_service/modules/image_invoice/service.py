import os
import sys
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Ensure image_invoice root is in sys.path for internal subpackage imports (ocr, image_processing)
_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

from python_service.db.document_store import get_document_store

async def process_image_invoice(raw_bytes: bytes, document_id: str, organization_id: str) -> Dict[str, Any]:
    """
    Processes image receipt/invoice bytes through a robust multi-tier pipeline:
      1. Gemini Multimodal Vision API (if GEMINI_API_KEY is configured)
      2. Local OCR Pipeline (Tesseract / EasyOCR with preprocessing)
      3. Fallback Heuristic Record (guarantees DB persistence without crashing)
    Persists structured data into PostgreSQL `invoices` + `invoice_line_items`,
    and updates document status to COMPLETED.
    """
    logger.info(f"Initiating image invoice processing for docId={document_id}, orgId={organization_id}")

    unified_invoice = None
    confidence = 85.0
    raw_ocr_result = {}

    # -------------------------------------------------------------
    # Tier 1: Gemini Vision API (if API key available)
    # -------------------------------------------------------------
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            logger.info("Attempting Tier 1 Gemini Vision multimodal extraction...")
            from google import genai
            client = genai.Client(api_key=gemini_key)
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

            prompt = (
                "You are an expert financial document parser. Analyze this invoice/receipt image and extract all structured data into JSON with this exact schema:\n"
                "{\n"
                '  "invoice_number": "string",\n'
                '  "invoice_date": "YYYY-MM-DD",\n'
                '  "due_date": "YYYY-MM-DD or null",\n'
                '  "customer_name": "string",\n'
                '  "gst_number": "string or null",\n'
                '  "total_amount": 0.00,\n'
                '  "tax": 0.00,\n'
                '  "total_amount_with_tax": 0.00,\n'
                '  "line_items": [\n'
                '    {\n'
                '      "description": "string",\n'
                '      "quantity": 1.0,\n'
                '      "rate_per_unit": 0.00,\n'
                '      "total_rate": 0.00\n'
                '    }\n'
                '  ]\n'
                "}\n"
                "Output ONLY valid JSON. Do not include markdown codeblocks or explanations."
            )

            response = client.models.generate_content(
                model=model_name,
                contents=[
                    genai.types.Part.from_bytes(data=raw_bytes, mime_type="image/png"),
                    prompt,
                ],
            )

            resp_text = response.text.strip()
            if resp_text.startswith("```"):
                resp_text = resp_text.split("```")[1]
                if resp_text.startswith("json"):
                    resp_text = resp_text[4:]
                resp_text = resp_text.strip()

            parsed = json.loads(resp_text)
            if isinstance(parsed, dict) and (parsed.get("invoice_number") or parsed.get("total_amount_with_tax")):
                unified_invoice = parsed
                confidence = 96.0
                raw_ocr_result = {"engine": "GEMINI_VISION", "raw": parsed}
                logger.info(f"Gemini Vision successfully extracted invoice: {unified_invoice.get('invoice_number')}")
        except Exception as e:
            logger.warning(f"Tier 1 Gemini Vision extraction failed or skipped: {e}")

    # -------------------------------------------------------------
    # Tier 2: Local OCR Pipeline (Tesseract / EasyOCR with output_dir)
    # -------------------------------------------------------------
    if not unified_invoice:
        out_dir = tempfile.mkdtemp()
        tmp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                tmp_file.write(raw_bytes)
                tmp_file_path = tmp_file.name

            # Resolve available OCR engine
            selected_engine = None
            try:
                from ocr.tesseract_engine import TesseractOcrEngine
                selected_engine = TesseractOcrEngine()
                logger.info("Using Tesseract OCR Engine")
            except Exception as tess_err:
                logger.info(f"Tesseract not available ({tess_err}), checking EasyOCR...")
                try:
                    from ocr.easyocr_engine import EasyOcrEngine
                    selected_engine = EasyOcrEngine()
                    logger.info("Using EasyOCR Engine")
                except Exception as easy_err:
                    logger.warning(f"EasyOCR not available: {easy_err}")

            if selected_engine:
                from receipt_extraction.extractor import process_receipt
                extraction_result = process_receipt(tmp_file_path, out_dir, ocr_engine=selected_engine)
                data_dict = extraction_result.to_dict() if hasattr(extraction_result, "to_dict") else {}
                receipt_data = data_dict.get("receipt_data", {})

                line_items = [
                    {
                        "description": item.get("description", "Item"),
                        "quantity": float(item.get("quantity") or 1.0),
                        "rate_per_unit": float(item.get("unit_price") or 0.0) if item.get("unit_price") is not None else None,
                        "total_rate": float(item.get("total_price") or 0.0) if item.get("total_price") is not None else None,
                    }
                    for item in receipt_data.get("line_items", [])
                ]

                subtotal = float(receipt_data.get("subtotal") or 0.0) if receipt_data.get("subtotal") is not None else None
                tax_amt = float(receipt_data.get("tax_amount") or 0.0) if receipt_data.get("tax_amount") is not None else None
                total_amt = float(receipt_data.get("total_amount") or 0.0) if receipt_data.get("total_amount") is not None else (subtotal or 0.0)

                unified_invoice = {
                    "invoice_number": receipt_data.get("receipt_number") or receipt_data.get("invoice_number") or f"IMG-{document_id[:8].upper()}",
                    "invoice_date": receipt_data.get("date"),
                    "due_date": None,
                    "customer_name": receipt_data.get("merchant_name") or receipt_data.get("vendor_name") or "Image Receipt Customer",
                    "gst_number": receipt_data.get("tax_id") or receipt_data.get("gstin"),
                    "total_amount": subtotal,
                    "tax": tax_amt,
                    "total_amount_with_tax": total_amt,
                    "line_items": line_items,
                }
                confidence = float(data_dict.get("confidence", 85.0)) if data_dict.get("confidence") is not None else 85.0
                raw_ocr_result = data_dict
                logger.info(f"Local OCR pipeline extracted invoice: {unified_invoice.get('invoice_number')}")
        except Exception as e:
            logger.error(f"Tier 2 Local OCR extraction failed: {e}", exc_info=True)
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                except OSError:
                    pass
            shutil.rmtree(out_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # Tier 3: Deterministic Fallback Record
    # -------------------------------------------------------------
    if not unified_invoice:
        logger.warning("Tier 3: Generating fallback structured invoice for image document.")
        unified_invoice = {
            "invoice_number": f"IMG-{document_id[:8].upper()}",
            "invoice_date": None,
            "due_date": None,
            "customer_name": "Scanned Image Customer",
            "gst_number": None,
            "total_amount": 0.0,
            "tax": 0.0,
            "total_amount_with_tax": 0.0,
            "line_items": [
                {
                    "description": "Scanned Image Invoice (Pending Manual Verification)",
                    "quantity": 1.0,
                    "rate_per_unit": 0.0,
                    "total_rate": 0.0,
                }
            ],
        }
        confidence = 50.0

    # -------------------------------------------------------------
    # Persist into PostgreSQL Database
    # -------------------------------------------------------------
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
        logger.info(f"Successfully saved image invoice id={invoice_id} for docId={document_id}")
    finally:
        store.close()

    return {
        "invoice_id": invoice_id,
        "confidence_score": confidence,
        "data": unified_invoice,
        "raw_ocr_result": raw_ocr_result,
    }
