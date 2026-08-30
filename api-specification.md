# Omni-CFO Platform: Database & API Design Specification

This document outlines the foundation for the Omni-CFO intelligence engine, specifically designed for multi-tenant data isolation and asynchronous processing.

---

## 1. Database Architecture (PostgreSQL)

The database enforces multi-tenancy at the kernel level using PostgreSQL Row-Level Security (RLS). All incoming data is staged in the `documents` or `chat_logs` tables before being mathematically validated and committed to the `transactions` ledger.

### DDL & Schema Setup

```sql
-- 1. Tenant & Organization Container
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    auto_commit_transactions BOOLEAN DEFAULT FALSE,
    currency VARCHAR(10) DEFAULT 'INR',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Raw Ingestion & Staging Layer
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL CHECK (source_type IN ('BANK_CSV', 'INVOICE_PDF', 'INVOICE_IMAGE', 'INVENTORY_CSV')),
    s3_file_url TEXT NOT NULL,
    processing_status VARCHAR(50) DEFAULT 'PENDING' CHECK (processing_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'PENDING_REVIEW')),
    raw_extracted_data JSONB,
    confidence_score NUMERIC(5,2),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Unified Financial Ledger
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    transaction_date DATE NOT NULL,
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('SALE', 'EXPENSE')),
    category VARCHAR(100) NOT NULL,
    counterparty_name VARCHAR(255),
    total_amount NUMERIC(15, 2) NOT NULL,
    payment_status VARCHAR(50) DEFAULT 'PAID',
    payment_mode VARCHAR(50) DEFAULT 'CASH',
    notes TEXT,
    is_verified BOOLEAN DEFAULT TRUE,
    is_edited BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Line Items (Optional Breakdown)
CREATE TABLE transaction_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    line_item_name VARCHAR(255) NOT NULL,
    quantity NUMERIC(12, 3) DEFAULT 1.000,
    unit_price NUMERIC(15, 2) NOT NULL,
    total_price NUMERIC(15, 2) NOT NULL
);

-- 5. WhatsApp & Conversational Logs
CREATE TABLE chat_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    sender_phone VARCHAR(20),
    raw_message TEXT NOT NULL,
    extracted_intent JSONB,
    processing_status VARCHAR(50) DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Performance Indexes
CREATE INDEX idx_transactions_tenant_active ON transactions(tenant_id, is_deleted, transaction_date DESC);
CREATE INDEX idx_docs_tenant_status ON documents(tenant_id, processing_status);

-- 7. Row-Level Security (RLS) Configuration
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY isolate_documents ON documents USING (tenant_id = current_setting('app.current_tenant')::UUID);
CREATE POLICY isolate_transactions ON transactions USING (tenant_id = current_setting('app.current_tenant')::UUID);
CREATE POLICY isolate_transaction_items ON transaction_items USING (tenant_id = current_setting('app.current_tenant')::UUID);
CREATE POLICY isolate_chats ON chat_logs USING (tenant_id = current_setting('app.current_tenant')::UUID);

```

---

## 2. REST API Specification

All endpoints require a valid JWT passed in the `Authorization: Bearer <token>` header. The API Gateway extracts the `tenant_id` from this token to inject into the PostgreSQL context.

### Module A: Universal Ingestion

**Upload File (PDF, Image, CSV)**

* **Method:** `POST`
* **Endpoint:** `/api/v1/ingest/file`
* **Content-Type:** `multipart/form-data`
* **Payload:**
* `file`: Binary file data
* `source_type`: String (`BANK_CSV`, `INVOICE_PDF`, `INVOICE_IMAGE`, `INVENTORY_CSV`)


* **Response (202 Accepted):**
```json
{
  "document_id": "c8a9f2e3-4b5c-6d7e-8f9a-0b1c2d3e4f5a",
  "status": "PENDING",
  "message": "File routed to processing queue."
}

```



**Upload Freeflow Text (WhatsApp)**

* **Method:** `POST`
* **Endpoint:** `/api/v1/ingest/text`
* **Content-Type:** `application/json`
* **Payload:**
```json
{
  "sender_phone": "+919876543210",
  "message": "Paid 4500 to Raju Transport for diesel"
}

```


* **Response (202 Accepted):**
```json
{
  "chat_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "status": "PENDING"
}

```



**Poll Extraction Status**

* **Method:** `GET`
* **Endpoint:** `/api/v1/ingest/status/{document_id}`
* **Response (200 OK):**
```json
{
  "document_id": "c8a9f2e3-4b5c-6d7e-8f9a-0b1c2d3e4f5a",
  "status": "COMPLETED",
  "confidence_score": 96.5,
  "extracted_data": {
    "transaction_type": "EXPENSE",
    "total_amount": 4500.00,
    "counterparty_name": "Raju Transport",
    "date": "2026-08-30"
  }
}

```



### Module B: Ledger & Transaction Management

**List Transactions (Paginated)**

* **Method:** `GET`
* **Endpoint:** `/api/v1/transactions`
* **Query Parameters:** `page`, `limit`, `start_date`, `end_date`, `type`
* **Response (200 OK):**
```json
{
  "total_records": 128,
  "page": 1,
  "limit": 20,
  "transactions": [
    {
      "id": "a94c1d2e-5678-4321-bcde-f0123456789a",
      "transaction_date": "2026-08-30",
      "transaction_type": "EXPENSE",
      "total_amount": 4500.00,
      "counterparty_name": "Raju Transport",
      "is_edited": false
    }
  ]
}

```



**Update/Correct Transaction**

* **Method:** `PUT`
* **Endpoint:** `/api/v1/transactions/{transaction_id}`
* **Payload:**
```json
{
  "total_amount": 4000.00,
  "counterparty_name": "Raju Transport Services",
  "notes": "Corrected misread amount from receipt."
}

```


* **Response (200 OK):**
```json
{
  "status": "SUCCESS",
  "message": "Transaction updated. CDC event triggered for KPI recalculation."
}

```



**Void Transaction (Soft Delete)**

* **Method:** `DELETE`
* **Endpoint:** `/api/v1/transactions/{transaction_id}`
* **Response (200 OK):**
```json
{
  "status": "SUCCESS",
  "message": "Transaction marked as deleted."
}

```



### Module C: Intelligence & BI

**Fetch Dashboard KPIs**

* **Method:** `GET`
* **Endpoint:** `/api/v1/analytics/kpis`
* **Query Parameters:** `start_date`, `end_date`
* **Response (200 OK):**
```json
{
  "total_revenue": 450000.00,
  "total_expenses": 310000.00,
  "net_profit": 140000.00,
  "outstanding_payables": 15000.00
}

```



**Conversational Text-to-SQL Query**

* **Method:** `POST`
* **Endpoint:** `/api/v1/chat/query`
* **Payload:**
```json
{
  "question": "What was my highest expense category this month?"
}

```


* **Response (200 OK):**
```json
{
  "question": "What was my highest expense category this month?",
  "generated_sql": "SELECT category, SUM(total_amount) FROM transactions WHERE is_deleted = false AND transaction_date >= '2026-08-01' GROUP BY category ORDER BY SUM(total_amount) DESC LIMIT 1;",
  "answer": "Your highest expense this month was **Logistics**, totaling **₹45,000**.",
  "data_preview": [{"category": "Logistics", "sum": 45000.00}]
}

```