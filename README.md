# Al-Business-Advisor-Profit-Intelligence-Platform-for-Small-Businesses
## API & WhatsApp Integration

### Frontend → Backend API Integration

The frontend dashboard is integrated with the Spring Boot backend through REST APIs.

**Frontend API service:**

```text
frontend/src/services/api.js
```

**Backend API controller:**

```text
java/src/main/java/com/omnicfo/controller/DocumentController.java
```

**Base API URL:**

```text
http://localhost:8080
```

**Document Upload Endpoint:**

```text
POST /api/v1/files/upload
```

The frontend sends uploaded files to the Spring Boot backend using `FormData` along with the file type and tenant ID.

### Supported File Types

| Frontend Category | Backend File Type |
| ----------------- | ----------------- |
| Bank Statement    | `BankStmt`        |
| Invoice PDF       | `Invoice`         |
| Invoice Image     | `Invoice`         |
| Inventory CSV     | `Inventory`       |
| WhatsApp Chat     | `WhatsAppChat`    |

### WhatsApp Integration

WhatsApp chat exports uploaded through the frontend are connected to the backend using the same document upload API.

**Flow:**

```text
WhatsApp file selected in frontend
        ↓
App.jsx
        ↓
services/api.js
        ↓
POST /api/v1/files/upload
        ↓
DocumentController
        ↓
DocumentService
        ↓
WhatsAppProcessingService
        ↓
WhatsApp chat processing
```

The frontend maps the WhatsApp upload category to the backend `WhatsAppChat` file type:

```javascript
whatsapp: 'WhatsAppChat'
```

The backend contains the WhatsApp processing service:

```text
java/src/main/java/com/omnicfo/service/WhatsAppProcessingService.java
```

### Document Retrieval API

Previously uploaded documents can be retrieved from the backend using:

```text
GET /api/v1/files
```

The request includes the tenant ID through the `X-Tenant-ID` header.

### Integration Status

* ✅ Frontend REST API integration
* ✅ Spring Boot document upload API
* ✅ File type mapping
* ✅ WhatsApp upload integration
* ✅ WhatsApp processing service
* ✅ Document retrieval API
* ✅ Changes pushed to `feature/integrated-dashboard`
