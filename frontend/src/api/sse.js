/**
 * SSE 解析器（SP-FE-001/002）：把 `ReadableStream` 的字节流解析为事件对象。
 *
 * 后端协议（SP-SSE-001）：每条事件固定三行 + 空行分隔
 *   id: {seq}\nevent: {name}\ndata: {json}\n\n
 *
 * - `splitEventBlocks(chunk, carry)`：增量文本 → 完整事件块（跨 chunk 缓冲）
 * - `parseEventBlock(block)`：事件块 → `{id, event, data}`（data 为原始字符串）
 * - 容错：注释行 `:` 忽略、缺 event 默认 `message`、data 多行按 `\n` 连接
 */
// 事件终止符：空行（兼容 \r\n）
const EVENT_TERMINATOR = /\r?\n\r?\n/g

export function splitEventBlocks(text, carry = '') {
  const buffer = carry + text
  const blocks = []
  const re = EVENT_TERMINATOR
  re.lastIndex = 0
  let match
  let start = 0
  while ((match = re.exec(buffer)) !== null) {
    const block = buffer.slice(start, match.index).replace(/\r/g, '')
    if (block.trim()) blocks.push(block)
    start = re.lastIndex
  }
  return { blocks, carry: buffer.slice(start) }
}

export function parseEventBlock(block) {
  const event = { id: '', event: 'message', data: '' }
  const dataLines = []
  for (const raw of block.split('\n')) {
    const line = raw.trimEnd()
    if (!line || line.startsWith(':')) continue // 空行 / 注释行
    if (line.startsWith('id:')) {
      event.id = line.slice(3).trim()
    } else if (line.startsWith('event:')) {
      event.event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
    // 其他字段（retry 等）忽略
  }
  event.data = dataLines.join('\n')
  return event
}

/**
 * 从响应流读取：逐 chunk 解析出完整事件（{id, event, data}），
 * 返回 `{events, onError}` 风格——直接产出一个 async generator。
 * 用法：`for await (const ev of readSSEEvents(response)) { ... }`
 */
export async function* readSSEEvents(response) {
  if (!response.ok) {
    // 非 SSE 响应（如 4001 参数校验统一 JSON）→ 解析错误体后抛出
    const body = await response.json().catch(() => ({}))
    const error = new Error(body?.message || `HTTP ${response.status}`)
    error.code = body?.code
    error.status = response.status
    throw error
  }
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let carry = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      carry += decoder.decode(value, { stream: true })
      const { blocks, carry: rest } = splitEventBlocks(carry)
      carry = rest
      for (const block of blocks) {
        yield parseEventBlock(block)
      }
    }
    // 流结束时若有残留事件块（无结尾空行）也解析
    if (carry.trim()) yield parseEventBlock(carry)
  } finally {
    reader.releaseLock()
  }
}
