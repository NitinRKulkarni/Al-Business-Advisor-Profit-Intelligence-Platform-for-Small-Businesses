package com.omnicfo.service;

import com.omnicfo.model.entity.Document;
import org.springframework.web.multipart.MultipartFile;

import java.util.UUID;

public interface InventoryCsvService {
    int ingestInventoryCsv(UUID organizationId, Document document, MultipartFile file);
}
