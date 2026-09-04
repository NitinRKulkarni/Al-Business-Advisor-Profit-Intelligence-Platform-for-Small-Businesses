import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
import psycopg
from python_service.config import settings

logger = logging.getLogger("document_store")

def _clean_numeric(val: Any) -> Optional[Decimal]:
    """
    Sanitizes strings, Indian currency formats (e.g. '1,00,000.00', '₹ 12,50,000.50'),
    or existing numeric types into a clean Decimal safe for PostgreSQL NUMERIC columns.
    """
    if val is None or val == "":
        return None
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    
    s = str(val).strip()
    cleaned = (
        s.replace(",", "")
        .replace("₹", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
        .strip()
    )
    if cleaned in ("", "-", "None", "null"):
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None

class DocumentNotFoundError(Exception):
    pass

class DocumentDataEmptyError(Exception):
    pass

@dataclass
class StoredDocument:
    id: str
    organization_id: str
    file_name: str
    file_type: str
    raw_bytes: bytes
    processed_status: str

DocumentRecord = StoredDocument

class PostgresDocumentStore:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.DATABASE_URL
        self._conn = psycopg.connect(self.db_url, autocommit=True)

    def get_document(self, document_id: str) -> StoredDocument:
        return self.fetch_document(document_id)

    def fetch_document(self, document_id: str) -> StoredDocument:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, organization_id, file_name, file_type, file_data, processed_status
                FROM documents
                WHERE id = %s
                """,
                (document_id,)
            )
            row = cur.fetchone()
            if not row:
                raise DocumentNotFoundError(f"Document id '{document_id}' not found in database.")

            doc_id, org_id, file_name, file_type, file_data, status = row
            if file_data is None:
                raise ValueError(f"Document id '{document_id}' has no file_data BLOB.")

            raw_bytes = bytes(file_data) if isinstance(file_data, (memoryview, bytearray, bytes)) else str(file_data).encode("utf-8")
            return StoredDocument(
                id=str(doc_id),
                organization_id=str(org_id),
                file_name=file_name,
                file_type=file_type,
                raw_bytes=raw_bytes,
                processed_status=status
            )

    def save_invoice(
        self,
        document_id: str,
        organization_id: str,
        invoice_data: Dict[str, Any],
        source_type: str = "PDF",
        confidence: float = 100.0
    ) -> str:
        with self._conn.cursor() as cur:
            total_amt = _clean_numeric(invoice_data.get("total_amount") or invoice_data.get("subtotal"))
            tax_amt = _clean_numeric(invoice_data.get("tax"))
            total_amt_tax = _clean_numeric(invoice_data.get("total_amount_with_tax") or invoice_data.get("total"))

            cur.execute(
                """
                INSERT INTO invoices (
                    document_id, organization_id, invoice_number, invoice_date,
                    due_date, customer_name, gst_number, total_amount, tax,
                    total_amount_with_tax, source_type, confidence_score
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET
                    invoice_number        = EXCLUDED.invoice_number,
                    invoice_date          = EXCLUDED.invoice_date,
                    due_date              = EXCLUDED.due_date,
                    customer_name         = EXCLUDED.customer_name,
                    gst_number            = EXCLUDED.gst_number,
                    total_amount          = EXCLUDED.total_amount,
                    tax                   = EXCLUDED.tax,
                    total_amount_with_tax = EXCLUDED.total_amount_with_tax,
                    source_type           = EXCLUDED.source_type,
                    confidence_score      = EXCLUDED.confidence_score
                RETURNING id
                """,
                (
                    document_id,
                    organization_id,
                    invoice_data.get("invoice_number") or invoice_data.get("receipt_number"),
                    invoice_data.get("invoice_date") or invoice_data.get("date"),
                    invoice_data.get("due_date"),
                    invoice_data.get("customer_name") or invoice_data.get("merchant_name"),
                    invoice_data.get("gst_number") or invoice_data.get("gstin"),
                    total_amt,
                    tax_amt,
                    total_amt_tax,
                    source_type,
                    confidence,
                ),
            )
            invoice_id = cur.fetchone()[0]

            # Re-insert line items
            cur.execute("DELETE FROM invoice_line_items WHERE invoice_id = %s", (invoice_id,))
            line_items = invoice_data.get("line_items", [])
            for idx, item in enumerate(line_items, start=1):
                qty = _clean_numeric(item.get("quantity")) or Decimal("1.0")
                rate = _clean_numeric(item.get("rate_per_unit") or item.get("unit_price"))
                tot_rate = _clean_numeric(item.get("total_rate") or item.get("total_price") or item.get("amount"))

                cur.execute(
                    """
                    INSERT INTO invoice_line_items (
                        invoice_id, organization_id, item_description,
                        quantity, rate_per_unit, total_rate, line_no
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        invoice_id,
                        organization_id,
                        item.get("description") or item.get("name") or item.get("raw_text") or "Item",
                        qty,
                        rate,
                        tot_rate,
                        idx,
                    ),
                )
            logger.info("Saved invoice %s with %d line items for document %s", invoice_id, len(line_items), document_id)
            return str(invoice_id)

    def save_whatsapp_data(
        self,
        document_id: str,
        organization_id: str,
        parsed_messages: List[Dict[str, Any]],
        insights: Dict[str, Any],
        extracted_queries: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Persists parsed WhatsApp messages, extracted customer queries,
        and demand intelligence insights. Ground-truth inventory_items is NOT modified.
        """
        extracted_queries = extracted_queries or []
        with self._conn.cursor() as cur:
            # 1. Insert chat messages
            cur.execute("DELETE FROM whatsapp_messages WHERE document_id = %s", (document_id,))
            for msg in parsed_messages:
                cur.execute(
                    """
                    INSERT INTO whatsapp_messages (
                        document_id, organization_id, customer_name,
                        sender, message_date, message_time, message_text
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        document_id,
                        organization_id,
                        msg.get("customer_name"),
                        msg.get("sender", "Unknown"),
                        msg.get("date"),
                        msg.get("time"),
                        msg.get("message", "")
                    )
                )

            # 2. Insert extracted customer queries and inquiries
            cur.execute("DELETE FROM whatsapp_queries WHERE document_id = %s", (document_id,))
            for q in extracted_queries:
                cur.execute(
                    """
                    INSERT INTO whatsapp_queries (
                        document_id, organization_id, customer_name, sender,
                        raw_message, intent, item_demanded, requested_quantity,
                        requested_unit, timeframe, urgency_level, sentiment, structured_payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        document_id,
                        organization_id,
                        q.get("customer_name"),
                        q.get("sender", "Unknown"),
                        q.get("raw_message", ""),
                        q.get("intent", "STOCK_INQUIRY"),
                        q.get("item_demanded"),
                        _clean_numeric(q.get("requested_quantity")),
                        q.get("requested_unit", "units"),
                        q.get("timeframe", "upcoming"),
                        q.get("urgency_level", "NORMAL"),
                        q.get("sentiment", "NEUTRAL"),
                        json.dumps(q.get("structured_payload", {}))
                    )
                )

            # 3. Upsert high-level insights & demand intelligence
            demand_intel = insights.get("demand_intelligence", {})
            cur.execute(
                """
                INSERT INTO whatsapp_insights (
                    document_id, organization_id, demand_intelligence,
                    customer_enquiries, customer_sentiment, unmet_demands, potential_leads
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET
                    demand_intelligence = EXCLUDED.demand_intelligence,
                    customer_enquiries  = EXCLUDED.customer_enquiries,
                    customer_sentiment  = EXCLUDED.customer_sentiment,
                    unmet_demands       = EXCLUDED.unmet_demands,
                    potential_leads     = EXCLUDED.potential_leads
                """,
                (
                    document_id,
                    organization_id,
                    json.dumps(demand_intel),
                    json.dumps(extracted_queries),
                    json.dumps([]),
                    json.dumps(insights.get("unmet_demands", [])),
                    json.dumps([])
                )
            )
            logger.info("Saved %d messages, %d customer queries, and demand intelligence for doc %s",
                len(parsed_messages), len(extracted_queries), document_id)

    def set_document_status(self, document_id: str, status: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET processed_status = %s WHERE id = %s",
                (status, document_id)
            )

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

def get_document_store() -> PostgresDocumentStore:
    return PostgresDocumentStore()
