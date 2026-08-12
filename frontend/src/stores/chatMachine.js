/**
 * 聊天事件状态机（SP-FE-001/002 核心逻辑，纯函数可单测）。
 *
 * 输入为 SSE 事件（SP-SSE-001 协议），输出两条状态线：
 * - messages：用户消息 + assistant 流式消息（delta=true 追加 / delta=false 结束）
 * - trace：intent/route/vision/retrieval/tool_call 时间线（含到达时间 t，供耗时标注）
 *
 * 约定：
 * - 事件以 `id:` 序号为 key **去重**（断线重放场景安全）
 * - `lastEventId` 持续更新 → 断线重连携带 `Last-Event-ID`
 * - `done` 事件收尾：错误（data.error）或 transfer/ticket_id
 */
export function createChatState(sessionId) {
  return {
    sessionId,
    messages: [], // {id, role, content, streaming}
    trace: [], // {id, event, data, t}
    lastEventId: '',
    sending: false,
    transfer: false,
    ticketId: null,
    error: null, // {code, message}
    seenIds: new Set(),
  }
}

function parseData(ev) {
  try {
    return ev.data ? JSON.parse(ev.data) : {}
  } catch {
    return { raw: ev.data }
  }
}

export function applyEvent(state, ev) {
  if (ev.id) {
    if (state.seenIds.has(ev.id)) return state // 幂等：重复事件跳过
    state.seenIds.add(ev.id)
    state.lastEventId = ev.id
  }
  const data = parseData(ev)

  if (ev.event === 'message') {
    const content = data.content || ''
    const last = state.messages[state.messages.length - 1]
    if (data.delta) {
      if (last && last.role === 'assistant' && last.streaming) {
        last.content += content // 打字机：增量追加
      } else {
        state.messages.push({ id: `m-${state.messages.length + 1}`, role: 'assistant', content, streaming: true })
      }
    } else if (last && last.role === 'assistant' && last.streaming) {
      last.streaming = false // 该条消息结束
    }
    return state
  }

  if (ev.event === 'done') {
    state.sending = false
    if (data.error) {
      state.error = { code: data.error.code, message: data.error.message }
    } else {
      state.transfer = Boolean(data.transfer)
      state.ticketId = data.ticket_id || null
    }
    return state
  }

  // 追踪类事件：intent / route / vision / retrieval / tool_call
  if (['intent', 'route', 'vision', 'retrieval', 'tool_call'].includes(ev.event)) {
    state.trace.push({ id: ev.id, event: ev.event, data, t: Date.now() })
  }
  return state
}
