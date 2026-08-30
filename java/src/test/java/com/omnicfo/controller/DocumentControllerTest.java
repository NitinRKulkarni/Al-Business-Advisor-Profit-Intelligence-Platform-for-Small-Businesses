package com.omnicfo.controller;

import com.omnicfo.exception.DuplicateDocumentException;
import com.omnicfo.exception.GlobalExceptionHandler;
import com.omnicfo.exception.OrganizationNotFoundException;
import com.omnicfo.model.dto.DocumentUploadResponse;
import com.omnicfo.model.enums.ProcessedStatus;
import com.omnicfo.service.DocumentService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(DocumentController.class)
@Import(GlobalExceptionHandler.class)
class DocumentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private DocumentService documentService;

    @Test
    @DisplayName("POST /api/v1/files/upload returns 201 CREATED on successful upload")
    void uploadDocument_Returns201Created() throws Exception {
        UUID tenantId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();

        MockMultipartFile file = new MockMultipartFile(
            "file",
            "bank_statement_august.pdf",
            MediaType.APPLICATION_PDF_VALUE,
            "dummy bank statement contents".getBytes()
        );

        DocumentUploadResponse response = DocumentUploadResponse.builder()
            .documentId(documentId)
            .fileName("bank_statement_august.pdf")
            .fileType("BankStmt")
            .fileHash("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
            .status(ProcessedStatus.PENDING)
            .uploadDate(Instant.now())
            .message("File uploaded successfully and queued for processing.")
            .build();

        when(documentService.uploadDocument(eq(tenantId), any(), eq("BankStmt")))
            .thenReturn(response);

        mockMvc.perform(multipart("/api/v1/files/upload")
                .file(file)
                .param("fileType", "BankStmt")
                .header("X-Tenant-ID", tenantId.toString()))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.document_id").value(documentId.toString()))
            .andExpect(jsonPath("$.fileType").value("BankStmt"))
            .andExpect(jsonPath("$.status").value("PENDING"))
            .andExpect(jsonPath("$.message").value("File uploaded successfully and queued for processing."));
    }

    @Test
    @DisplayName("POST /api/v1/files/upload returns 409 CONFLICT on duplicate document")
    void uploadDocument_Returns409Conflict() throws Exception {
        UUID tenantId = UUID.randomUUID();
        MockMultipartFile file = new MockMultipartFile(
            "file",
            "invoice.pdf",
            MediaType.APPLICATION_PDF_VALUE,
            "duplicate content".getBytes()
        );

        when(documentService.uploadDocument(eq(tenantId), any(), eq("Invoice")))
            .thenThrow(new DuplicateDocumentException("Duplicate file detected for this organization."));

        mockMvc.perform(multipart("/api/v1/files/upload")
                .file(file)
                .param("fileType", "Invoice")
                .header("X-Tenant-ID", tenantId.toString()))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.status").value(409))
            .andExpect(jsonPath("$.error").value("Conflict"))
            .andExpect(jsonPath("$.message").value("Duplicate file detected for this organization."));
    }

    @Test
    @DisplayName("POST /api/v1/files/upload returns 404 NOT FOUND when tenant does not exist")
    void uploadDocument_Returns404NotFound() throws Exception {
        UUID tenantId = UUID.randomUUID();
        MockMultipartFile file = new MockMultipartFile(
            "file",
            "invoice.pdf",
            MediaType.APPLICATION_PDF_VALUE,
            "test content".getBytes()
        );

        when(documentService.uploadDocument(eq(tenantId), any(), eq("Invoice")))
            .thenThrow(new OrganizationNotFoundException("Organization not found with ID: " + tenantId));

        mockMvc.perform(multipart("/api/v1/files/upload")
                .file(file)
                .param("fileType", "Invoice")
                .header("X-Tenant-ID", tenantId.toString()))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.status").value(404))
            .andExpect(jsonPath("$.error").value("Not Found"))
            .andExpect(jsonPath("$.message").value("Organization not found with ID: " + tenantId));
    }

    @Test
    @DisplayName("POST /api/v1/files/upload returns 400 BAD REQUEST when X-Tenant-ID header is missing")
    void uploadDocument_Returns400OnMissingHeader() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
            "file",
            "invoice.pdf",
            MediaType.APPLICATION_PDF_VALUE,
            "test content".getBytes()
        );

        mockMvc.perform(multipart("/api/v1/files/upload")
                .file(file)
                .param("fileType", "Invoice"))
            .andExpect(status().isBadRequest());
    }
}
