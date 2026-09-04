import json
import time
import urllib.request
import urllib.parse
import uuid
import psycopg

JAVA_URL = "http://localhost:8080"
TENANT_ID = "a0000000-0000-0000-0000-000000000001"
DB_URL = "postgresql://postgres:postgres@localhost:5432/omnicfo_db"
PDF_PATH = "sample_invoice.pdf"

def encode_multipart(fields, files):
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())
    for name, (filename, content, mime) in files.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body.extend(f'Content-Type: {mime}\r\n\r\n'.encode())
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return boundary, bytes(body)

def test_e2e():
    print("=" * 65)
    print("STARTING LIVE CROSS-SERVICE END-TO-END VERIFICATION TEST")
    print("=" * 65)

    # 1. Read base PDF bytes and append unique comment to prevent SHA256 duplicate rejection
    with open(PDF_PATH, "rb") as f:
        pdf_bytes = f.read()
    unique_suffix = f"\n% E2E Test Run {uuid.uuid4().hex}\n".encode("utf-8")
    unique_pdf_bytes = pdf_bytes + unique_suffix
    file_name = f"test_invoice_{uuid.uuid4().hex[:8]}.pdf"

    print(f"\n[Step 1] Triggering Java Upload API (POST /api/v1/files/upload)...")
    print(f"  - File Name: {file_name}")

    fields = {"fileType": "Invoice"}
    files = {"file": (file_name, unique_pdf_bytes, "application/pdf")}
    boundary, body = encode_multipart(fields, files)

    req = urllib.request.Request(
        f"{JAVA_URL}/api/v1/files/upload",
        data=body,
        headers={
            "X-Tenant-ID": TENANT_ID,
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            status_code = resp.status
            res_body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"FAILED: Upload returned {e.code}: {e.read().decode()}")
        return False

    print(f"Java Upload Response Status: {status_code}")
    upload_res = json.loads(res_body)
    doc_id = upload_res.get("documentId")
    print(f"Document Uploaded Successfully!")
    print(f"  - Document ID:      {doc_id}")
    print(f"  - File Name:        {upload_res.get('fileName')}")
    print(f"  - Initial Status:   {upload_res.get('processedStatus')}")

    # 2. Poll Java GET API / Wait for Python Extraction via Scheduled Poller
    print("\n[Step 2] Waiting for Java FIFO Poller (every 30s) to dispatch to Python Service...")
    max_wait = 60
    start_time = time.time()
    final_status = "PENDING"
    
    while time.time() - start_time < max_wait:
        get_req = urllib.request.Request(
            f"{JAVA_URL}/api/v1/files?fileType=Invoice",
            headers={"X-Tenant-ID": TENANT_ID}
        )
        try:
            with urllib.request.urlopen(get_req) as g_resp:
                docs = json.loads(g_resp.read().decode())
                target_doc = next((d for d in docs if d["documentId"] == doc_id), None)
                if target_doc:
                    current_status = target_doc.get("processedStatus")
                    elapsed = int(time.time() - start_time)
                    print(f"  [{elapsed}s] Document Status: {current_status}")
                    if current_status == "COMPLETED":
                        final_status = current_status
                        break
                    elif current_status == "FAILED":
                        final_status = current_status
                        break
        except Exception as ex:
            print(f"Error checking status: {ex}")
        time.sleep(3)

    if final_status != "COMPLETED":
        print(f"\nFAILED: Document status reached '{final_status}' instead of COMPLETED.")
        return False

    print("\n[Step 3] Verification: Querying PostgreSQL for extracted Invoice data...")
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, invoice_number, invoice_date, customer_name, total_amount, tax, total_amount_with_tax, confidence_score
                FROM invoices WHERE document_id = %s
                """,
                (doc_id,)
            )
            inv_row = cur.fetchone()
            if not inv_row:
                print("FAILED: No invoice row found in database for document!")
                return False

            inv_id, inv_num, inv_date, cust_name, total, tax, total_with_tax, conf = inv_row
            print(f"  Invoice Row Found in Postgres:")
            print(f"    - Invoice ID:            {inv_id}")
            print(f"    - Invoice Number:        {inv_num}")
            print(f"    - Invoice Date:          {inv_date}")
            print(f"    - Customer Name:         {cust_name}")
            print(f"    - Subtotal / Tax / Total: {total} / {tax} / {total_with_tax}")
            print(f"    - Confidence Score:      {conf}%")

            cur.execute(
                """
                SELECT line_no, item_description, quantity, rate_per_unit, total_rate
                FROM invoice_line_items WHERE invoice_id = %s ORDER BY line_no
                """,
                (inv_id,)
            )
            items = cur.fetchall()
            print(f"  Extracted Line Items ({len(items)} items):")
            for item in items:
                print(f"    Line #{item[0]}: {item[1]} | Qty: {item[2]} | Rate: {item[3]} | Total: {item[4]}")

    print("\n" + "=" * 65)
    print("SUCCESS: CROSS-SERVICE END-TO-END TEST PASSED PERFECTLY!")
    print("=" * 65)
    return True

if __name__ == "__main__":
    test_e2e()
