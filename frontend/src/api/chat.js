/**
 * 对话 API（SP-FE-001）：`POST /api/v1/chat`（SSE 流）+ 会话管理。
 *
 * - `sendChatMessage(sessionId, message, lastEventId)`：fetch + ReadableStream，
 *   携带 `Last-Event-ID` 支持断线重连重放（SP-SSE-001）
 * - 非 200（4001 统一 JSON）由 readSSEEvents 抛错（带 code/status）
 */
import { readSSEEvents } from './sse.js'

export async function sendChatMessage(sessionId, message, lastEventId = '') {
  const resp = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Last-Event-ID': lastEventId,
    },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  return readSSEEvents(resp)
}

export function newSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}
