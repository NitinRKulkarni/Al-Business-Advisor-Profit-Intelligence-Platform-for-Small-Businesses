"""
Local end-to-end runner for the Python extraction side.

Because a JDK/Docker may not be present, this script proves the full
integration WITHOUT the Java app by doing exactly what the Java stack does:

  1. (Java DocumentService equivalent) seed an org + a documents row and store
     the uploaded PDF bytes.
  2. (Java InvoiceTriggerService equivalent) POST document_id, form-urlencoded,
     to the running Python extraction service at /extract/invoice.
  3. Read back invoices + invoice_line_items and the documents status.

Usage:
  # start the extraction service first (separate terminal):
  #   python -m uvicorn invoice_extractor.extraction_api:app --port 8000
  #
  # SQLite (default, zero setup):
  python run_e2e_local.py
  #
  # Against real Postgres (same DB as Java):
  set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/omnicfo_db
  python run_e2e_local.py --postgres
"""
import argparse
import os
import sys
import uuid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--postgres", action="store_true",
                    help="Use Postgres via DATABASE_URL instead of SQLite.")
    ap.add_argument("--url", default="http://127.0.0.1:8000",
                    help="Base URL of the running extraction service.")
    args = ap.parse_args()

    if args.postgres:
        os.environ["DB_BACKEND"] = "postgres"
        if not os.environ.get("DATABASE_URL"):
            print("ERROR: set DATABASE_URL for --postgres mode.")
            sys.exit(1)
    else:
        os.environ.setdefault("DB_BACKEND", "sqlite")
        os.environ.setdefault("SQLITE_PATH", os.path.abspath("e2e_local.db"))

    # Import after env is set.
    import urllib.request
    import urllib.parse
    import urllib.error
    from invoice_extractor.db import get_store
    from test_real_invoice import build_pdf

    ORG_ID = "a0000000-0000-0000-0000-000000000001"
    doc_id = str(uuid.uuid4())

    # --- Step 1: simulate the Java upload (store org + document + PDF bytes) ---
    store = get_store()
    if os.environ["DB_BACKEND"] == "sqlite":
        conn = store._conn
        conn.execute("INSERT OR IGNORE INTO organizations (id, business_name) VALUES (?,?)",
                     (ORG_ID, "Acme Retail Enterprises"))
        conn.execute(
            "INSERT INTO documents (id, organization_id, file_name, file_type, "
            "file_hash, processed_status, file_data) VALUES (?,?,?,?,?,?,?)",
            (doc_id, ORG_ID, "e2e_invoice.pdf", "Invoice", uuid.uuid4().hex,
             "PENDING", build_pdf()))
        conn.commit()
    else:
        # Postgres: relies on the seed org from schema.sql; insert the doc row.
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            c.execute(
                "INSERT INTO documents (id, organization_id, file_name, file_type, "
                "file_hash, processed_status, file_data) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (doc_id, ORG_ID, "e2e_invoice.pdf", "Invoice", uuid.uuid4().hex,
                 "PENDING", build_pdf()))
            c.commit()
    store.close()
    print(f"[1] Seeded PENDING document_id={doc_id}")

    # --- Step 2: simulate the Java poller trigger (form-urlencoded POST) ---
    data = urllib.parse.urlencode({"document_id": doc_id}).encode()
    req = urllib.request.Request(
        f"{args.url}/extract/invoice", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req) as r:
            print(f"[2] POST /extract/invoice -> {r.status}")
            print(f"    {r.read().decode()[:400]}")
    except urllib.error.URLError as e:
        print(f"[2] ERROR calling extraction service at {args.url}: {e}")
        print("    Is it running?  python -m uvicorn invoice_extractor.extraction_api:app --port 8000")
        sys.exit(1)

    # --- Step 3: verify persistence ---
    store = get_store()
    row = store.get_document(doc_id)  # noqa: F841 (ensures doc still readable)
    print(f"[3] Verifying DB for document_id={doc_id} ...")
    if os.environ["DB_BACKEND"] == "sqlite":
        cur = store._conn.cursor()
        cur.execute("SELECT processed_status FROM documents WHERE id=?", (doc_id,))
        status = cur.fetchone()[0]
        cur.execute("SELECT id, invoice_number, total_amount_with_tax FROM invoices WHERE document_id=?", (doc_id,))
        inv = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id=?", (inv[0],))
        n = cur.fetchone()[0]
    else:
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            status = c.execute("SELECT processed_status FROM documents WHERE id=%s", (doc_id,)).fetchone()[0]
            inv = c.execute("SELECT id, invoice_number, total_amount_with_tax FROM invoices WHERE document_id=%s", (doc_id,)).fetchone()
            n = c.execute("SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id=%s", (inv[0],)).fetchone()[0]
    store.close()

    print(f"    documents.processed_status = {status}")
    print(f"    invoices: number={inv[1]} total_with_tax={inv[2]}")
    print(f"    invoice_line_items = {n}")
    ok = status == "COMPLETED" and n > 0
    print(f"\n=== E2E RESULT: {'PASS' if ok else 'FAIL'} ===")


if __name__ == "__main__":
    main()
