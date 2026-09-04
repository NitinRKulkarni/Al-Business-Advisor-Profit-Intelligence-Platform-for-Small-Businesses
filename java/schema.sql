-- ==============================================================================
-- Omni-CFO Multi-Tenant Cloud Platform - Database Schema
-- Target Database: PostgreSQL 14+
-- ==============================================================================

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==============================================================================
-- Table: organizations (Tenants)
-- Represents a distinct business tenant container.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- Table: documents
-- Stores uploaded financial documents and ingestion metadata per tenant.
-- In-database BLOB storage (file_data) for self-contained testing.
-- Deduplication is enforced per tenant using (organization_id, file_hash).
-- ==============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_data BYTEA,
    processed_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    upload_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign Key
    CONSTRAINT fk_documents_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE,
        
    -- Multi-tenant file content deduplication constraint
    CONSTRAINT uk_documents_organization_file_hash 
        UNIQUE (organization_id, file_hash)
);

-- ==============================================================================
-- Table: invoices
-- Stores structured invoice/receipt metadata from both PDF and Image extractors.
-- Tracks payment and reconciliation status against bank statements.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL UNIQUE,
    organization_id UUID NOT NULL,
    invoice_number VARCHAR(100),
    invoice_date DATE,
    due_date DATE,
    customer_name VARCHAR(255),
    gst_number VARCHAR(50),
    total_amount NUMERIC(15, 2),
    tax NUMERIC(15, 2),
    total_amount_with_tax NUMERIC(15, 2),
    payment_status VARCHAR(50) NOT NULL DEFAULT 'UNPAID',
    paid_amount NUMERIC(15, 2) DEFAULT 0.00,
    paid_at DATE,
    matched_bank_statement_id UUID,
    source_type VARCHAR(20) DEFAULT 'PDF',
    confidence_score NUMERIC(5, 2),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_invoices_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_invoices_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE
);

-- ==============================================================================
-- Table: invoice_line_items
-- Stores line-item breakdowns for invoices.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    item_description TEXT NOT NULL,
    quantity NUMERIC(12, 3) DEFAULT 1.000,
    rate_per_unit NUMERIC(15, 2),
    total_rate NUMERIC(15, 2),
    line_no INT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_invoice_line_items_invoice 
        FOREIGN KEY (invoice_id) 
        REFERENCES invoices(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_invoice_line_items_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE
);

-- ==============================================================================
-- Table: bank_statements
-- Stores individual transaction rows parsed from uploaded bank statements.
-- Tracks payment reconciliation status against invoices.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS bank_statements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    document_id UUID NOT NULL,
    txn_date DATE NOT NULL,
    description VARCHAR(500) NOT NULL,
    txn_type VARCHAR(10) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    balance NUMERIC(15, 2) NOT NULL,
    reconciliation_status VARCHAR(50) NOT NULL DEFAULT 'UNMATCHED',
    matched_invoice_id UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_bank_statements_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_bank_statements_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_bank_statements_matched_invoice 
        FOREIGN KEY (matched_invoice_id) 
        REFERENCES invoices(id) 
        ON DELETE SET NULL,

    CONSTRAINT uk_bank_statements_org_txn_dedup 
        UNIQUE (organization_id, txn_date, description, amount, balance)
);

-- Add foreign key from invoices to bank_statements
ALTER TABLE invoices 
    ADD CONSTRAINT fk_invoices_matched_bank_statement 
    FOREIGN KEY (matched_bank_statement_id) 
    REFERENCES bank_statements(id) 
    ON DELETE SET NULL;

-- ==============================================================================
-- Table: whatsapp_messages
-- Stores individual message records parsed from WhatsApp exports.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    customer_name VARCHAR(255),
    sender VARCHAR(255) NOT NULL,
    message_date VARCHAR(50),
    message_time VARCHAR(50),
    message_text TEXT NOT NULL,
    message_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_whatsapp_messages_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_whatsapp_messages_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE
);

-- ==============================================================================
-- Table: inventory_items
-- Stores ground-truth product stock inventory uploaded via direct CSV sheets.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS inventory_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    item_name VARCHAR(255) NOT NULL,
    quantity NUMERIC(12, 3),
    quantity_unit VARCHAR(50),
    unit_price NUMERIC(15, 2) DEFAULT 0.00,
    reorder_level NUMERIC(12, 3) DEFAULT 0.00,
    category VARCHAR(100),
    mention_date VARCHAR(50),
    mention_time VARCHAR(50),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_inventory_items_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_inventory_items_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE
);

-- ==============================================================================
-- Table: whatsapp_queries
-- Stores structured customer inquiries, question intents, and requested items.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS whatsapp_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    customer_name VARCHAR(255),
    sender VARCHAR(255) NOT NULL,
    raw_message TEXT NOT NULL,
    intent VARCHAR(100) NOT NULL DEFAULT 'STOCK_INQUIRY',
    item_demanded VARCHAR(255),
    requested_quantity NUMERIC(12, 3),
    requested_unit VARCHAR(50),
    timeframe VARCHAR(100),
    urgency_level VARCHAR(50) DEFAULT 'NORMAL',
    sentiment VARCHAR(50) DEFAULT 'NEUTRAL',
    structured_payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_whatsapp_queries_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_whatsapp_queries_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE
);

-- ==============================================================================
-- Table: whatsapp_insights
-- Stores high-level AI analysis and demand intelligence extracted from conversation streams.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS whatsapp_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL UNIQUE,
    organization_id UUID NOT NULL,
    demand_intelligence JSONB DEFAULT '{}'::jsonb,
    customer_enquiries JSONB DEFAULT '[]'::jsonb,
    customer_sentiment JSONB DEFAULT '[]'::jsonb,
    unmet_demands JSONB DEFAULT '[]'::jsonb,
    potential_leads JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_whatsapp_insights_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    CONSTRAINT fk_whatsapp_insights_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE
);

-- ==============================================================================
-- Performance Indices
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_documents_tenant_type ON documents(organization_id, file_type);
CREATE INDEX IF NOT EXISTS idx_documents_status_type ON documents(processed_status, file_type, upload_date);
CREATE INDEX IF NOT EXISTS idx_invoices_org_invnum ON invoices(organization_id, invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_payment_status ON invoices(organization_id, payment_status);
CREATE INDEX IF NOT EXISTS idx_bank_statements_org_status ON bank_statements(organization_id, reconciliation_status);
CREATE INDEX IF NOT EXISTS idx_bank_statements_txn_date ON bank_statements(organization_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_inventory_items_org_item ON inventory_items(organization_id, item_name);
CREATE INDEX IF NOT EXISTS idx_inventory_items_doc ON inventory_items(document_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_queries_org_item ON whatsapp_queries(organization_id, item_demanded);
CREATE INDEX IF NOT EXISTS idx_whatsapp_queries_doc ON whatsapp_queries(document_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_doc ON whatsapp_messages(document_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_insights_org ON whatsapp_insights(organization_id);

