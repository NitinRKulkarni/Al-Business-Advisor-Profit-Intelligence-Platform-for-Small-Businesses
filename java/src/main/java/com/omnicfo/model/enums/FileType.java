package com.omnicfo.model.enums;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

import java.util.Arrays;

public enum FileType {
    INVOICE("Invoice"),
    WHATSAPP_CHAT("WhatsAppChat"),
    BANK_STMT("BankStmt"),
    INVENTORY("Inventory");

    private final String displayName;

    FileType(String displayName) {
        this.displayName = displayName;
    }

    @JsonValue
    public String getDisplayName() {
        return displayName;
    }

    @JsonCreator
    public static FileType fromString(String value) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException("FileType cannot be null or blank");
        }
        String normalized = value.trim().replace("_", "").replace("-", "").toLowerCase();
        for (FileType type : FileType.values()) {
            String enumNormalized = type.name().replace("_", "").toLowerCase();
            String displayNormalized = type.displayName.replace("_", "").toLowerCase();
            if (enumNormalized.equals(normalized) || displayNormalized.equals(normalized)) {
                return type;
            }
        }
        throw new IllegalArgumentException(
            "Unknown FileType: '" + value + "'. Accepted values: " + Arrays.toString(FileType.values())
        );
    }
}
