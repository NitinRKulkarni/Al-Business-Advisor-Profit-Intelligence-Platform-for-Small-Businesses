package com.omnicfo.service;

import com.omnicfo.model.dto.DocumentResponseDTO;
import com.omnicfo.model.dto.DocumentUploadResponse;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

public interface DocumentService {
    DocumentUploadResponse uploadDocument(UUID organizationId, MultipartFile file, String fileType);

    List<DocumentResponseDTO> getDocuments(UUID organizationId, String fileType);
}
