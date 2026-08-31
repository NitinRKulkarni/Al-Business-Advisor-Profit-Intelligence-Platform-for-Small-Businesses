# End-to-End Local Testing: Java (Omni-CFO) + Python (Extraction)

This walks through running **both** services locally and triggering the Java
upload API so the full flow executes:

```
POST /api/v1/files/upload (Java :8080)
   -> stores document (PENDING) + PDF bytes in Postgres
   -> @Scheduled FIFO poller (every 30s) picks up PENDING invoices
   -> POST /extract/invoice (Python :8000) with document_id
        -> Python reads the PDF from documents, parses it,
           writes invoices + invoice_line_items, sets status COMPLETED
```

## Prerequisites (install on your machine)

- **JDK 17** (e.g. Eclipse Temurin) — the Java app targets Java 17.
- **Docker Desktop** — for local Postgres via `java/docker-compose.yml`.
- **Python 3.11+** with this project's deps: `pip install -r requirements.txt`.

> On the current dev machine there is **no JDK and no Docker**, so the Java app
> cannot be built/run here. The Python side is fully verified (see
> `run_e2e_local.py`, which simulates the exact poller trigger). Follow the
> steps below on a machine that has JDK + Docker for the true cross-service run.

## Step 1 — Start Postgres

```bash
cd java
docker compose up -d          # postgres:16 on localhost:5432, db=omnicfo_db
```

Apply the extraction tables (invoices + invoice_line_items) once:

```bash
# from the repo root
psql "postgresql://postgres:postgres@localhost:5432/omnicfo_db" -f invoice_extractor/sql/extraction_schema.sql
```

(The Java app auto-creates `organizations`/`documents` via `ddl-auto: update`
and seeds the two demo tenants on startup.)

## Step 2 — Start the Python extraction service (:8000)

```bash
cd invoice_extractor
set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/omnicfo_db   # Windows
# export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/omnicfo_db  # macOS/Linux
python -m uvicorn invoice_extractor.extraction_api:app --host 0.0.0.0 --port 8000
```

Sanity check: `GET http://localhost:8000/health` -> `{"status":"UP",...}`

## Step 3 — Start the Java backend (:8080)

```bash
cd java
# Windows
.\mvnw.cmd spring-boot:run
# macOS/Linux
./mvnw spring-boot:run
```

The app connects to Postgres, seeds tenants
`a0000000-0000-0000-0000-000000000001` and `b0000000-...-002`, and starts the
30-second FIFO poller.

## Step 4 — Trigger the flow: upload an invoice to the Java API

Using the provided sample PDF (`invoice_extractor/sample_invoice.pdf`) or any
real invoice:

```bash
curl -X POST http://localhost:8080/api/v1/files/upload \
  -H "X-Tenant-ID: a0000000-0000-0000-0000-000000000001" \
  -F "file=@invoice_extractor/sample_invoice.pdf" \
  -F "fileType=Invoice"
```

Response (`201`):
```json
{ "documentId": "<uuid>", "fileName": "sample_invoice.pdf",
  "fileType": "Invoice", "processedStatus": "PENDING", "uploadDate": "..." }
```

Or import `java/OmniCFO_API.postman_collection.json` into Postman and run
**Document Ingestion → Upload Invoice File**.

## Step 5 — Watch it complete

Within ~30s the Java poller dispatches the document to Python. Verify:

**Via the Java list API:**
```bash
curl http://localhost:8080/api/v1/files?fileType=Invoice \
  -H "X-Tenant-ID: a0000000-0000-0000-0000-000000000001"
# processedStatus flips PENDING -> PROCESSING -> COMPLETED
```

**Via the database:**
```sql
SELECT processed_status FROM documents WHERE id = '<uuid>';       -- COMPLETED
SELECT * FROM invoices WHERE document_id = '<uuid>';               -- 1 row
SELECT * FROM invoice_line_items WHERE invoice_id = (
    SELECT id FROM invoices WHERE document_id = '<uuid>');          -- N rows
```

The Python service logs `Extraction trigger received: document_id=...` and
`POST /extract/invoice 200 OK` for each dispatched document.

## Fast path (no Java/Docker needed) — verify the Python side only

```bash
cd invoice_extractor
python -m uvicorn invoice_extractor.extraction_api:app --port 8000   # terminal 1
python run_e2e_local.py                                              # terminal 2 (SQLite)
# => seeds a PENDING doc, fires the poller-equivalent trigger, asserts
#    status COMPLETED + invoice + line items.  Prints: E2E RESULT: PASS
```

## Notes / gotchas

- **PDF storage**: the Java `DocumentService` stores the uploaded bytes in
  `documents.file_data`; the Python service reads them back by `document_id`.
  If you switch to file/S3 storage, populate `documents.file_path` instead and
  (optionally) set `UPLOAD_DIR` for the Python service.
- **Ports**: Java 8080, Python 8000, Postgres 5432. The Java `application.yml`
  points at `ai.service.python.base-url=http://localhost:8000`.
- **fileType** must be one of `Invoice`, `WhatsAppChat`, `BankStmt`,
  `Inventory`. Only `Invoice` is dispatched to extraction.
