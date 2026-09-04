package com.omnicfo.service;

import com.omnicfo.exception.DuplicateDocumentException;
import com.omnicfo.exception.OrganizationNotFoundException;
import com.omnicfo.model.dto.DocumentUploadResponse;
import com.omnicfo.model.entity.Document;
import com.omnicfo.model.entity.Organization;
import com.omnicfo.model.enums.FileType;
import com.omnicfo.model.enums.ProcessedStatus;
import com.omnicfo.repository.DocumentRepository;
import com.omnicfo.repository.OrganizationRepository;
import com.omnicfo.service.impl.DocumentServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DocumentServiceTest {

    @Mock
    private OrganizationRepository organizationRepository;

    @Mock
    private DocumentRepository documentRepository;

    @InjectMocks
    private DocumentServiceImpl documentService;

    private UUID tenantId;
    private Organization testOrg;
    private MockMultipartFile testFile;
    private String expectedHash;

    @BeforeEach
    void setUp() throws Exception {
        tenantId = UUID.randomUUID();
        testOrg = Organization.builder()
                .id(tenantId)
                .businessName("Acme Corp")
                .createdAt(Instant.now())
                .build();

        byte[] content = "Invoice-Line-Item-Data-12345".getBytes(StandardCharsets.UTF_8);
        testFile = new MockMultipartFile(
                "file",
                "invoice_aug_2026.pdf",
                "application/pdf",
                content);

        MessageDigest md = MessageDigest.getInstance("SHA-256");
        expectedHash = HexFormat.of().formatHex(md.digest(content));
    }

    @Test
    @DisplayName("Successfully uploads document when tenant exists and file is unique")
    void uploadDocument_Success() {
        // Arrange
        when(organizationRepository.findById(tenantId)).thenReturn(Optional.of(testOrg));
        when(documentRepository.findByOrganizationIdAndFileHash(tenantId, expectedHash)).thenReturn(Optional.empty());

        UUID generatedDocId = UUID.randomUUID();
        when(documentRepository.save(any(Document.class))).thenAnswer(invocation -> {
            Document doc = invocation.getArgument(0);
            doc.setId(generatedDocId);
            doc.setUploadDate(Instant.now());
            return doc;
        });

        // Act
        DocumentUploadResponse response = documentService.uploadDocument(tenantId, testFile, "Invoice");

        // Assert
        assertThat(response).isNotNull();
        assertThat(response.getDocumentId()).isEqualTo(generatedDocId);
        assertThat(response.getFileName()).isEqualTo("invoice_aug_2026.pdf");
        assertThat(response.getFileType()).isEqualTo("Invoice");
        assertThat(response.getFileHash()).isEqualTo(expectedHash);
        assertThat(response.getStatus()).isEqualTo(ProcessedStatus.PENDING);

        ArgumentCaptor<Document> captor = ArgumentCaptor.forClass(Document.class);
        verify(documentRepository).save(captor.capture());
        Document captured = captor.getValue();
        assertThat(captured.getOrganization()).isEqualTo(testOrg);
        assertThat(captured.getFileHash()).isEqualTo(expectedHash);
        assertThat(captured.getFileType()).isEqualTo(FileType.INVOICE);
    }

    @Test
    @DisplayName("Successfully allows re-submission when previous document is in FAILED status")
    void uploadDocument_AllowsResubmissionOnFailedStatus() {
        // Arrange
        UUID failedDocId = UUID.randomUUID();
        Document existingFailedDoc = Document.builder()
                .id(failedDocId)
                .organization(testOrg)
                .fileName("old_invoice.pdf")
                .fileType(FileType.INVOICE)
                .fileHash(expectedHash)
                .processedStatus(ProcessedStatus.FAILED)
                .build();

        when(organizationRepository.findById(tenantId)).thenReturn(Optional.of(testOrg));
        when(documentRepository.findByOrganizationIdAndFileHash(tenantId, expectedHash))
                .thenReturn(Optional.of(existingFailedDoc));
        when(documentRepository.save(any(Document.class))).thenAnswer(invocation -> invocation.getArgument(0));

        // Act
        DocumentUploadResponse response = documentService.uploadDocument(tenantId, testFile, "Invoice");

        // Assert
        assertThat(response).isNotNull();
        assertThat(response.getDocumentId()).isEqualTo(failedDocId);
        assertThat(response.getStatus()).isEqualTo(ProcessedStatus.PENDING);
        assertThat(existingFailedDoc.getProcessedStatus()).isEqualTo(ProcessedStatus.PENDING);
        verify(documentRepository).save(existingFailedDoc);
    }

    @Test
    @DisplayName("Throws DuplicateDocumentException when file with same hash exists and is COMPLETED")
    void uploadDocument_ThrowsDuplicateDocumentExceptionWhenCompleted() {
        // Arrange
        Document existingCompletedDoc = Document.builder()
                .id(UUID.randomUUID())
                .organization(testOrg)
                .fileName("completed_invoice.pdf")
                .fileType(FileType.INVOICE)
                .fileHash(expectedHash)
                .processedStatus(ProcessedStatus.COMPLETED)
                .build();

        when(organizationRepository.findById(tenantId)).thenReturn(Optional.of(testOrg));
        when(documentRepository.findByOrganizationIdAndFileHash(tenantId, expectedHash))
                .thenReturn(Optional.of(existingCompletedDoc));

        // Act & Assert
        assertThatThrownBy(() -> documentService.uploadDocument(tenantId, testFile, "Invoice"))
                .isInstanceOf(DuplicateDocumentException.class)
                .hasMessageContaining(expectedHash);

        verify(documentRepository, never()).save(any(Document.class));
    }

    @Test
    @DisplayName("Throws OrganizationNotFoundException when tenant ID does not exist")
    void uploadDocument_ThrowsOrganizationNotFoundException() {
        // Arrange
        when(organizationRepository.findById(tenantId)).thenReturn(Optional.empty());

        // Act & Assert
        assertThatThrownBy(() -> documentService.uploadDocument(tenantId, testFile, "Invoice"))
                .isInstanceOf(OrganizationNotFoundException.class)
                .hasMessageContaining(tenantId.toString());

        verify(documentRepository, never()).existsByOrganizationIdAndFileHash(any(), any());
        verify(documentRepository, never()).save(any());
    }

    @Test
    @DisplayName("Throws IllegalArgumentException when uploaded file is empty")
    void uploadDocument_ThrowsIllegalArgumentOnEmptyFile() {
        MockMultipartFile emptyFile = new MockMultipartFile("file", "empty.pdf", "application/pdf", new byte[0]);

        assertThatThrownBy(() -> documentService.uploadDocument(tenantId, emptyFile, "Invoice"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("empty");
    }
}
