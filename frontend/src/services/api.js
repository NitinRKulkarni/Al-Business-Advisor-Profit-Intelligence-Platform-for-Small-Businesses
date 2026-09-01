const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080'
export const DEFAULT_TENANT_ID = 'a0000000-0000-0000-0000-000000000001'

/**
 * File category to backend FileType enum mapping:
 * - Bank statement CSV → BankStmt
 * - PDF invoices → Invoice
 * - Invoice images → Invoice
 * - Inventory CSV → Inventory
 */
export const CATEGORY_FILE_TYPE_MAP = {
  bank: 'BankStmt',
  invoices: 'Invoice',
  images: 'Invoice',
  inventory: 'Inventory',
}

/**
 * Uploads a single file to the Spring Boot backend service.
 * 
 * @param {File} file - File object to upload
 * @param {string} fileType - Backend FileType enum ("BankStmt", "Invoice", "Inventory", "WhatsAppChat")
 * @param {string} tenantId - Organization UUID
 * @returns {Promise<Object>} JSON response from server
 */
export async function uploadDocument(file, fileType, tenantId = DEFAULT_TENANT_ID) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('fileType', fileType)

  const response = await fetch(`${API_BASE_URL}/api/v1/files/upload`, {
    method: 'POST',
    headers: {
      'X-Tenant-ID': tenantId,
    },
    body: formData,
  })

  const data = await response.json()

  if (!response.ok) {
    const errorMsg = data.message || `Upload failed with status ${response.status}`
    const error = new Error(errorMsg)
    error.status = response.status
    error.data = data
    throw error
  }

  return data
}

/**
 * Uploads all staged files across all upload categories to the backend.
 * Skips empty categories and frontend-only categories.
 * 
 * @param {Object} uploadsState - { bank: File[], invoices: File[], images: File[], inventory: File[] }
 * @param {string} tenantId - Organization UUID
 * @returns {Promise<{ successes: Array, errors: Array }>} Summary of upload results
 */
export async function uploadAllDocuments(uploadsState, tenantId = DEFAULT_TENANT_ID) {
  const results = {
    successes: [],
    errors: [],
  }

  for (const [category, files] of Object.entries(uploadsState)) {
    const backendFileType = CATEGORY_FILE_TYPE_MAP[category]
    if (!backendFileType || !files || files.length === 0) {
      continue
    }

    for (const file of files) {
      try {
        const response = await uploadDocument(file, backendFileType, tenantId)
        results.successes.push({
          category,
          fileName: file.name,
          response,
        })
      } catch (err) {
        results.errors.push({
          category,
          fileName: file.name,
          error: err.message,
          status: err.status,
        })
      }
    }
  }

  return results
}

/**
 * Fetches list of uploaded documents from the backend for the tenant.
 */
export async function getDocuments(tenantId = DEFAULT_TENANT_ID, fileType = '') {
  const url = new URL(`${API_BASE_URL}/api/v1/files`)
  if (fileType) {
    url.searchParams.append('fileType', fileType)
  }

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: {
      'X-Tenant-ID': tenantId,
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch documents: ${response.statusText}`)
  }

  return response.json()
}
