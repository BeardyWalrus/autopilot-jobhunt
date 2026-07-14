// Thin fetch wrapper around the FastAPI backend.
async function req(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  health: () => req('/health'),

  getConfig: () => req('/config'),
  putConfig: (config) => req('/config', { method: 'PUT', body: JSON.stringify(config) }),
  testOllama: (base_url = '') =>
    req('/ollama/test', { method: 'POST', body: JSON.stringify({ base_url }) }),

  getCompanies: () => req('/companies'),
  putCompanies: (companies) => req('/companies', { method: 'PUT', body: JSON.stringify(companies) }),
  addCompany: (company) => req('/companies', { method: 'POST', body: JSON.stringify(company) }),
  suggestStart: (count = 8) =>
    req('/companies/suggest', { method: 'POST', body: JSON.stringify({ count }) }),
  reviewStart: (includeDisabled = true) =>
    req('/companies/review', { method: 'POST', body: JSON.stringify({ include_disabled: includeDisabled }) }),
  reconsiderStart: () => req('/companies/reconsider', { method: 'POST' }),
  jobsResult: () => req('/companies/jobs/result'),

  getResume: () => req('/resume'),
  putResume: (content) => req('/resume', { method: 'PUT', body: JSON.stringify({ content }) }),
  uploadResume: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/resume/upload', { method: 'POST', body: form })
    if (!res.ok) throw new Error((await res.json()).detail || 'upload failed')
    return res.json()
  },

  scanStatus: () => req('/scan/status'),
  scanStart: () => req('/scan/start', { method: 'POST' }),
  scanStop: () => req('/scan/stop', { method: 'POST' }),
  scanLogs: () => req('/scan/logs?limit=2000'),

  results: () => req('/results'),

  getSchedule: () => req('/schedule'),
  putSchedule: (enabled, time) =>
    req('/schedule', { method: 'PUT', body: JSON.stringify({ enabled, time }) }),
}
