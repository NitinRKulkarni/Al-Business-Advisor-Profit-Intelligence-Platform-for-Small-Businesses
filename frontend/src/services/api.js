/**
 * Service to handle document uploads and API integration with the Spring Boot backend.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080'
const DEFAULT_TENANT_ID = 'a0000000-0000-0000-0000-000000000001'

/**
 * Maps frontend UI upload keys to Spring Boot FileType enum display names.
 */
export const CATEGORY_TO_FILE_TYPE = {
  bank: 'BankStmt',
  inventory: 'CsvInventory',
  invoices: 'Invoice',
  images: 'Invoice',
  whatsapp: 'WhatsAppChat',
}

export const CATEGORY_TO_SOURCE_TYPE = {
  bank: 'bank_statement',
  inventory: 'csv_inventory',
  invoices: 'invoice',
  images: 'image_invoice',
  whatsapp: 'whatsapp_chat',
}

/**
 * Uploads a single file to the Spring Boot backend with optional upload progress callback.
 */
export function uploadDocument(file, fileType, tenantId = DEFAULT_TENANT_ID, onProgress = null, sourceType = null) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const formData = new FormData()
    formData.append('file', file)
    
    // Explicit sourceType routing
    const effectiveSourceType = sourceType || CATEGORY_TO_SOURCE_TYPE[fileType?.toLowerCase()] || (fileType === 'Inventory' || fileType === 'CsvInventory' ? 'csv_inventory' : fileType)
    formData.append('sourceType', effectiveSourceType)
    formData.append('fileType', fileType)

    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percentComplete = Math.round((event.loaded / event.total) * 100)
          onProgress(percentComplete, event.loaded, event.total)
        }
      }
    }

    xhr.open('POST', `${API_BASE_URL}/api/v1/files/upload`)
    xhr.setRequestHeader('X-Tenant-ID', tenantId)

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const json = JSON.parse(xhr.responseText)
          resolve(json)
        } catch {
          resolve({ status: 'SUCCESS', message: 'Uploaded successfully' })
        }
      } else {
        let errorDetail = 'Upload failed'
        try {
          const errJson = JSON.parse(xhr.responseText)
          errorDetail = errJson.message || errJson.error || xhr.statusText
        } catch {
          errorDetail = xhr.statusText || `HTTP ${xhr.status}`
        }
        const error = new Error(`Server returned ${xhr.status}: ${errorDetail}`)
        error.status = xhr.status
        reject(error)
      }
    }

    xhr.onerror = () => {
      const error = new Error('Network error during file upload')
      error.status = 0
      reject(error)
    }

    xhr.send(formData)
  })
}

/**
 * Uploads all files grouped by category to the backend with overall progress tracking.
 */
export async function uploadAllDocuments(uploadsState, tenantId = DEFAULT_TENANT_ID, onOverallProgress = null) {
  const results = {
    successful: [],
    successes: [],
    errors: [],
  }

  // Count total files across all categories
  const fileList = []
  for (const [category, files] of Object.entries(uploadsState)) {
    if (!files || files.length === 0) continue
    const fileType = CATEGORY_TO_FILE_TYPE[category] || 'Invoice'
    for (const file of files) {
      fileList.push({ category, file, fileType })
    }
  }

  const total = fileList.length
  if (total === 0) return results

  let completed = 0

  for (let i = 0; i < fileList.length; i++) {
    const { category, file, fileType } = fileList[i]

    if (onOverallProgress) {
      onOverallProgress({
        progressPercent: Math.round((completed / total) * 100),
        currentFile: file.name,
        currentCategory: category,
        completedCount: completed,
        totalCount: total,
      })
    }

    try {
      const response = await uploadDocument(file, fileType, tenantId, (filePercent) => {
        if (onOverallProgress) {
          const baseProgress = (completed / total) * 100
          const fileContribution = (filePercent / 100) * (100 / total)
          onOverallProgress({
            progressPercent: Math.min(99, Math.round(baseProgress + fileContribution)),
            currentFile: file.name,
            currentCategory: category,
            completedCount: completed,
            totalCount: total,
          })
        }
      })

      const successItem = {
        category,
        fileName: file.name,
        response,
      }
      results.successful.push(successItem)
      results.successes.push(successItem)
    } catch (err) {
      results.errors.push({
        category,
        fileName: file.name,
        error: err.message,
        status: err.status,
      })
    }

    completed++
  }

  if (onOverallProgress) {
    onOverallProgress({
      progressPercent: 100,
      currentFile: 'All files completed',
      completedCount: total,
      totalCount: total,
    })
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

/**
 * Fetches the binary Blob for an uploaded document.
 */
export async function fetchDocumentBlob(documentId, tenantId = DEFAULT_TENANT_ID) {
  const url = `${API_BASE_URL}/api/v1/files/${documentId}/view`
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'X-Tenant-ID': tenantId,
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to load document preview: ${response.statusText}`)
  }

  const blob = await response.blob()
  const contentType = response.headers.get('content-type') || blob.type
  return {
    blob,
    contentType,
    blobUrl: URL.createObjectURL(blob),
  }
}

/**
 * Returns direct URL for viewing/streaming document.
 */
export function getDocumentViewUrl(documentId) {
  return `${API_BASE_URL}/api/v1/files/${documentId}/view`
}

/**
 * Fetches Demand Intelligence insights from the Java backend.
 */
export async function getDemandInsights(tenantId = DEFAULT_TENANT_ID) {
  const url = `${API_BASE_URL}/api/v1/insights/demand`
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'X-Tenant-ID': tenantId,
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch demand insights: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Fetches Invoices from the Java backend with live payment & reconciliation statuses.
 */
export async function getInvoices(tenantId = DEFAULT_TENANT_ID, paymentStatus = '') {
  const url = new URL(`${API_BASE_URL}/api/v1/invoices`)
  if (paymentStatus) {
    url.searchParams.append('paymentStatus', paymentStatus)
  }

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: {
      'X-Tenant-ID': tenantId,
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch invoices: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Authenticates user credentials against the Java Spring Boot backend (reading .env properties).
 */
export async function loginUser(username, password) {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ username, password }),
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    const errorMsg = data.message || 'Invalid User ID or Password.'
    const err = new Error(errorMsg)
    err.status = response.status
    throw err
  }

  return data
}

/**
 * Verifies active session token with backend.
 */
export async function verifySession(token) {
  if (!token) return { authenticated: false }

  const response = await fetch(`${API_BASE_URL}/api/v1/auth/verify`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })

  if (!response.ok) {
    return { authenticated: false }
  }

  return response.json()
}

/**
 * Fetches reconciled and recorded Bank Statements from the Java backend.
 */
export async function getBankStatements(tenantId = DEFAULT_TENANT_ID) {
  const url = `${API_BASE_URL}/api/v1/bank-statements`
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'X-Tenant-ID': tenantId,
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch bank statements: ${response.statusText}`)
  }

  return response.json()
}


