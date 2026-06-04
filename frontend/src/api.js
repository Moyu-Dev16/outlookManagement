const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }
  return response.json()
}

export function listAccounts() {
  return request('/api/accounts')
}

export function importAccounts(text) {
  return request('/api/accounts/import', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
}

export function listProxies() {
  return request('/api/proxies')
}

export function importProxies(text, type = 'http') {
  return request('/api/proxies/import', {
    method: 'POST',
    body: JSON.stringify({ text, type }),
  })
}

export function validateActiveProxies() {
  return request('/api/proxies/validate-active', { method: 'POST' })
}

export function getProxyValidationJob(jobId) {
  return request(`/api/proxies/validation-jobs/${jobId}`)
}

export function startOAuth(accountId) {
  return request(`/api/oauth/microsoft/start/${accountId}`)
}

export function startPlaywrightOAuth(accountId) {
  return request(`/api/oauth/microsoft/playwright/${accountId}`, { method: 'POST' })
}

export function syncAccount(accountId) {
  return request(`/api/sync/accounts/${accountId}`, { method: 'POST' })
}

export function syncAccountViaImap(accountId) {
  return request(`/api/imap/accounts/${accountId}/sync`, { method: 'POST' })
}

export function listFolders(accountId) {
  return request(`/api/accounts/${accountId}/folders`)
}

export function listMessages(accountId, folderId) {
  const query = folderId ? `?folder_id=${folderId}` : ''
  return request(`/api/accounts/${accountId}/messages${query}`)
}
