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
-- Deduplication is enforced per tenant using (organization_id, file_hash).
-- ==============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
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
-- Table: bank_statements
-- Stores individual transaction rows parsed from uploaded bank statements.
-- Enforces row-level deduplication across overlapping files using
-- (organization_id, txn_date, description, amount, balance).
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
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign Key to Document
    CONSTRAINT fk_bank_statements_document 
        FOREIGN KEY (document_id) 
        REFERENCES documents(id) 
        ON DELETE CASCADE,

    -- Foreign Key to Organization
    CONSTRAINT fk_bank_statements_organization 
        FOREIGN KEY (organization_id) 
        REFERENCES organizations(id) 
        ON DELETE CASCADE,

    -- Multi-tenant cross-file row deduplication constraint
    CONSTRAINT uk_bank_statements_org_txn_dedup 
        UNIQUE (organization_id, txn_date, description, amount, balance)
);

-- ==============================================================================
-- Indexes for High-Performance Queries
-- ==============================================================================

-- Fast lookup for tenant document listings sorted by newest first
CREATE INDEX IF NOT EXISTS idx_documents_org_upload_date 
    ON documents (organization_id, upload_date DESC);

-- Fast lookup for tenant documents filtered by fileType and sorted by newest first
CREATE INDEX IF NOT EXISTS idx_documents_org_type_upload_date 
    ON documents (organization_id, file_type, upload_date DESC);

-- Fast lookup for document processing status monitoring
CREATE INDEX IF NOT EXISTS idx_documents_org_status 
    ON documents (organization_id, processed_status);

-- Fast lookup for tenant transactions ordered chronologically
CREATE INDEX IF NOT EXISTS idx_bank_statements_org_txn_date 
    ON bank_statements (organization_id, txn_date DESC);

-- Fast lookup for bank statements belonging to a document
CREATE INDEX IF NOT EXISTS idx_bank_statements_document_id 
    ON bank_statements (document_id);

-- ==============================================================================
-- Demo Seed Data (Optional / For Local Testing)
-- ==============================================================================
INSERT INTO organizations (id, business_name, created_at)
VALUES 
    ('a0000000-0000-0000-0000-000000000001', 'Acme Retail Enterprises', CURRENT_TIMESTAMP),
    ('b0000000-0000-0000-0000-000000000002', 'Nova Logistics & Transport', CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

