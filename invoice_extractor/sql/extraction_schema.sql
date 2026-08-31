-- ==============================================================================
-- Invoice Extraction Schema (Python AI service side)
-- Target: PostgreSQL 14+  (same database as the Java Omni-CFO backend: omnicfo_db)
--
-- This adds:
--   1. A file-location column to the existing `documents` table so the Python
--      service can retrieve the original PDF by document_id. The committed
--      java/schema.sql stores NO file bytes/path, so extraction cannot find the
--      file without this. Two options are provided (path OR bytes) — keep the
--      one that matches how the Spring Boot upload actually stores files.
--   2. `invoices` + `invoice_line_items` tables holding the extraction output,
--      shaped to the parser result and the API response.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------------------------
-- 1. Let the documents table point at the stored PDF.
--    Option A (recommended): a storage path / URL (local dir, S3, Azure Blob).
--    Option B: store the raw bytes in-DB (simple for local dev; not for scale).
--    Both are added as NULLable so existing rows and the Java app are unaffected.
-- ------------------------------------------------------------------------------
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_path TEXT;      -- Option A
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_data BYTEA;     -- Option B

-- ------------------------------------------------------------------------------
-- 2. Extracted invoice header. One row per successfully parsed invoice document.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Links back to the source document and its tenant.
    document_id     UUID NOT NULL,
    organization_id UUID NOT NULL,

    -- Extracted header fields (match parser output / API response).
    invoice_number        VARCHAR(100),
    invoice_date          DATE,
    due_date              DATE,
    customer_name         VARCHAR(255),
    gst_number            VARCHAR(50),

    -- Totals.
    total_amount          NUMERIC(15, 2),   -- subtotal before tax
    tax                   NUMERIC(15, 2),   -- total tax (CGST+SGST summed if split)
    total_amount_with_tax NUMERIC(15, 2),   -- grand total

    -- Provenance / QA.
    confidence_score      NUMERIC(5, 2),
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_invoices_document
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    CONSTRAINT fk_invoices_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,

    -- One invoice per document (re-extraction upserts rather than duplicates).
    CONSTRAINT uk_invoices_document UNIQUE (document_id)
);

CREATE INDEX IF NOT EXISTS idx_invoices_org        ON invoices (organization_id);
CREATE INDEX IF NOT EXISTS idx_invoices_number     ON invoices (organization_id, invoice_number);

-- ------------------------------------------------------------------------------
-- 3. Extracted line items. Many rows per invoice.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    invoice_id      UUID NOT NULL,
    organization_id UUID NOT NULL,

    item_description VARCHAR(500),
    quantity         NUMERIC(15, 3),
    rate_per_unit    NUMERIC(15, 2),
    total_rate       NUMERIC(15, 2),

    line_no          INT,   -- 1-based order the item appeared on the invoice

    CONSTRAINT fk_line_items_invoice
        FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    CONSTRAINT fk_line_items_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_line_items_invoice ON invoice_line_items (invoice_id);
