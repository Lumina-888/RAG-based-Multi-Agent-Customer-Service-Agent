/**
 * 工单 API（SP-FE-003）：对接 M6 `GET /tickets`、`GET /tickets/{id}/audit`、
 * `POST /tickets/{id}/transition`（受限迁移，SP-REF-007/008）。
 */
async function getJSON(url) {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()).data
}

export function fetchTickets(status = '') {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return getJSON(`/api/v1/tickets${query}`)
}

export function fetchTicketAudit(ticketId) {
  return getJSON(`/api/v1/tickets/${ticketId}/audit`)
}

export async function transitionTicket(ticketId, status, operator = 'agent', reason = '') {
  const resp = await fetch(`/api/v1/tickets/${ticketId}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, operator, reason }),
  })
  const body = await resp.json()
  if (!resp.ok) {
    const error = new Error(body?.message || `HTTP ${resp.status}`)
    error.code = body?.code
    throw error
  }
  return body.data
}
