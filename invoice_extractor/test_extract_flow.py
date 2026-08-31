"""
End-to-end test of the extraction flow against a local SQLite backend.

Simulates the Spring Boot poller:
  1. Seed an organization + a documents row whose file_data holds a real PDF.
  2. Call POST /extract/invoice (via TestClient) with the document_id.
  3. Assert invoices + invoice_line_items rows were written and status COMPLETED.
"""
import os
import uuid

# Force the SQLite backend into a fresh temp DB BEFORE importing the app/db.
DB_PATH = os.path.abspath("test_extraction.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DB_BACKEND"] = "sqlite"
os.environ["SQLITE_PATH"] = DB_PATH

from fastapi.testclient import TestClient  # noqa: E402

from invoice_extractor.extraction_api import app  # noqa: E402
from invoice_extractor.db import SqliteDocumentStore  # noqa: E402
from test_real_invoice import build_pdf  # noqa: E402  (the ABC invoice)

client = TestClient(app)

ORG_ID = "a0000000-0000-0000-0000-000000000001"


def seed():
    store = SqliteDocumentStore(DB_PATH)
    doc_id = str(uuid.uuid4())
    conn = store._conn
    conn.execute("INSERT OR IGNORE INTO organizations (id, business_name) VALUES (?,?)",
                 (ORG_ID, "Acme Retail Enterprises"))
    conn.execute(
        "INSERT INTO documents (id, organization_id, file_name, file_type, "
        "file_hash, processed_status, file_data) VALUES (?,?,?,?,?,?,?)",
        (doc_id, ORG_ID, "ABC_INV.pdf", "Invoice", "hash123", "PENDING", build_pdf()),
    )
    conn.commit()
    store.close()
    return doc_id


def main():
    out = []
    doc_id = seed()
    out.append(f"Seeded document_id={doc_id}")

    # Health
    r = client.get("/health")
    out.append(f"HEALTH {r.status_code}: {r.json()}")

    # The exact form-urlencoded call the Java RestClient makes.
    r = client.post("/extract/invoice", data={"document_id": doc_id})
    out.append(f"\nPOST /extract/invoice -> {r.status_code}")
    body = r.json()
    out.append(f"  status={body.get('status')} invoice_id={body.get('invoice_id')} "
               f"confidence={body.get('confidence_score')}")
    ed = body.get("extracted_data", {})
    out.append(f"  invoice_number={ed.get('invoice_number')} "
               f"total_with_tax={ed.get('total_amount_with_tax')} "
               f"items={len(ed.get('line_items', []))}")

    # Verify persistence directly in the DB.
    store = SqliteDocumentStore(DB_PATH)
    cur = store._conn.cursor()
    cur.execute("SELECT processed_status FROM documents WHERE id=?", (doc_id,))
    status = cur.fetchone()[0]
    cur.execute("SELECT id, invoice_number, tax, total_amount_with_tax FROM invoices "
                "WHERE document_id=?", (doc_id,))
    inv = cur.fetchone()
    cur.execute("SELECT COUNT(*), MIN(item_description) FROM invoice_line_items "
                "WHERE invoice_id=?", (inv[0],))
    n_items, first_item = cur.fetchone()
    store.close()

    out.append("\n--- DB VERIFICATION ---")
    out.append(f"  documents.processed_status = {status}")
    out.append(f"  invoices row: number={inv[1]} tax={inv[2]} total_with_tax={inv[3]}")
    out.append(f"  invoice_line_items count = {n_items} (first: {first_item!r})")

    ok = (status == "COMPLETED" and inv[1] == "INV-2026-0847" and n_items == 3)
    out.append(f"\n=== RESULT: {'PASS' if ok else 'FAIL'} ===")
    print("\n".join(out))


if __name__ == "__main__":
    main()
