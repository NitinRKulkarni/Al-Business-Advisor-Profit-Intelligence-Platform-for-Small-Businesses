# 🚀 Omni-CFO Platform — `feature/upload_api` Branch Documentation

> **Active Feature Branch:** `feature/upload_api`  
> **Platform:** Omni-CFO Multi-Tenant Cloud Platform (Small Business AI Financial Advisor)  
> **Backend Tech Stack:** Java 17 | Spring Boot 3.3.3 | Spring Data JPA | PostgreSQL 16 | Docker  

---

## 📅 Activity Log & Development History

### **[2026-08-31] — Milestone 2: Asynchronous FIFO Poller, AI Trigger & Bank Statement Engine**

#### **1. Bank Statement Scheduled Processor & Cross-File Deduplication Engine**
- Created `BankStatement` entity representing individual transaction rows.
- Enforced multi-tenant cross-file row deduplication with database unique constraint: `uk_bank_statements_org_txn_dedup (organization_id, txn_date, description, amount, balance)`.
- Created `BankStatementRepository` with `existsByOrganizationIdAndTxnDateAndDescriptionAndAmountAndBalance(...)`.
- Implemented `BankStatementProcessingService` annotated with `@Scheduled(fixedDelay = 45000)` (runs every 45s) to parse CSV rows in strict FIFO order, detect and skip duplicate rows across overlapping statement files, and update document status to `COMPLETED`.
- Updated PostgreSQL `schema.sql` with table DDL, foreign keys, and performance indexes.

#### **2. Invoice Scheduled FIFO Poller (`InvoiceTriggerService`)**
- Added `@Scheduled(fixedDelay = 30000)` poller executing every 30 seconds to fetch up to 10 oldest `PENDING` invoices (FIFO).
- Added query method in `DocumentRepository`: `findTop10ByProcessedStatusAndFileTypeOrderByUploadDateAsc(...)`.
- Immediately transitions status to `PROCESSING` prior to dispatch to prevent duplicate polling in distributed environments.

#### **3. External Python AI Service Integration**
- Configured dynamic `ai.service.python.base-url` and `ai.service.python.invoice-endpoint` in `application.yml`.
- Created `AiClientConfig` providing a Spring Boot 3 `RestClient` bean.
- Implemented fire-and-forget `POST /extract/invoice` with `application/x-www-form-urlencoded` payload containing `document_id`.
- Added automated fallback error handling: if the Python service fails or is unreachable, the document status is safely updated to `FAILED`.

#### **4. Local Testing Mock (`mock_ai_service.py`)**
- Created a standalone Python HTTP server (`mock_ai_service.py`) on port 8000 simulating the AI service with zero dependencies.

---

### **[2026-08-30] — Milestone 1: Multi-Tenant Ingestion, Listing API & Cloud Provisioning**

#### **1. Multi-Tenant Document Upload & Ingestion API**
- Implemented `POST /api/v1/files/upload` supporting `multipart/form-data`.
- Enforced tenant isolation via mandatory `X-Tenant-ID` HTTP header.
- Implemented SHA-256 file hashing to prevent duplicate uploads per tenant. Returns `409 Conflict` if duplicate hash exists for the tenant.
- Supported file business classifications (`Invoice`, `WhatsAppChat`, `BankStmt`, `Inventory`).

#### **2. Document Listing & Filtering API**
- Implemented `GET /api/v1/files` returning uploaded documents and processing statuses for a tenant.
- Implemented query filter `GET /api/v1/files?fileType={type}` sorted chronologically (`uploadDate DESC`).
- Added DTO `DocumentResponseDTO` (containing `documentId`, `fileName`, `fileType`, `processedStatus`, `uploadDate`).

#### **3. Database Schema & Query Optimization**
- Created `schema.sql` (PostgreSQL 14+ compatible DDL):
  - `organizations` table: tenant management.
  - `documents` table: metadata storage with foreign key cascade.
  - Multi-tenant unique constraint: `uk_documents_organization_file_hash (organization_id, file_hash)`.
  - Composite performance indexes:
    - `idx_documents_org_upload_date (organization_id, upload_date DESC)`
    - `idx_documents_org_type_upload_date (organization_id, file_type, upload_date DESC)`
    - `idx_documents_org_status (organization_id, processed_status)`

#### **4. Cloud Native & Azure Ubuntu Deployment Preparation**
- Created `application-prod.yml` with HikariCP connection pooling and dynamic environment variables (`SPRING_DATASOURCE_URL`, `SPRING_DATASOURCE_USERNAME`, `SPRING_DATASOURCE_PASSWORD`).
- Added multi-stage `Dockerfile` (Alpine JRE runtime, non-root user).
- Added `.env.example` and configured `.gitignore` to prevent any local machine credential leaks.

#### **5. Testing & Postman Collection**
- Unit & Controller mock tests (`DocumentControllerTest`, `DocumentServiceTest`).
- Updated `OmniCFO_API.postman_collection.json` with all upload and listing requests and pre-seeded test tenant IDs.

---

## 📡 API Reference

### **Base URL:** `http://localhost:8080` (or your Azure Host)

| Method | Endpoint | Headers | Query Params / Body | Description |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/organizations` | `Content-Type: application/json` | `{"businessName": "Acme Retail"}` | Creates a new tenant organization |
| `GET` | `/api/v1/organizations` | — | — | Lists all initialized tenants |
| `POST` | `/api/v1/files/upload` | `X-Tenant-ID: <UUID>` | Multipart (`file`, `fileType`) | Ingests document with SHA-256 deduplication |
| `GET` | `/api/v1/files` | `X-Tenant-ID: <UUID>` | — | Lists all documents for tenant (newest first) |
| `GET` | `/api/v1/files` | `X-Tenant-ID: <UUID>` | `fileType=Invoice` | Lists documents filtered by type (newest first) |

---

## 🛠️ Local Development Setup

### 1. Start PostgreSQL with Docker Compose
```bash
docker compose up -d
```

### 2. Run the Application Locally
```bash
# Windows
.\mvnw.cmd spring-boot:run

# Linux / macOS
./mvnw spring-boot:run
```

### 3. Pre-Seeded Test Tenants
When the app starts, the following test tenants are automatically initialized:
* **Tenant 1:** `a0000000-0000-0000-0000-000000000001` (*Acme Retail Enterprises*)
* **Tenant 2:** `b0000000-0000-0000-0000-000000000002` (*Nova Logistics & Transport*)

---

## ☁️ Azure / Ubuntu Deployment Guide

### Running with Docker Container:
```bash
# 1. Build Docker image
docker build -t omni-cfo-api .

# 2. Run container with Azure PostgreSQL credentials
docker run -d \
  -p 8080:8080 \
  -e SPRING_PROFILES_ACTIVE=prod \
  -e SPRING_DATASOURCE_URL="jdbc:postgresql://<azure-pg-host>:5432/omnicfo_db?sslmode=require" \
  -e SPRING_DATASOURCE_USERNAME="<azure-db-user>" \
  -e SPRING_DATASOURCE_PASSWORD="<azure-db-password>" \
  --name omnicfo-api omni-cfo-api
```

---

## 📝 Commit & Changelog Maintenance Instructions

Whenever you add new changes to this branch:
1. Append a new dated sub-heading under **Activity Log & Development History** (e.g. `### [YYYY-MM-DD] — Feature Name`).
2. List the new features, bug fixes, or architectural changes made.
3. Commit both the code and the updated `README.md`.
