package com.omnicfo.exception;

/** Container for the domain exceptions used by the ingestion API. */
public final class ApiExceptions {

    private ApiExceptions() {
    }

    /** Tenant referenced by X-Tenant-ID does not exist -> 404. */
    public static class TenantNotFoundException extends RuntimeException {
        public TenantNotFoundException(String message) {
            super(message);
        }
    }

    /** Same file hash already uploaded for this tenant -> 409. */
    public static class DuplicateFileException extends RuntimeException {
        public DuplicateFileException(String message) {
            super(message);
        }
    }
}
