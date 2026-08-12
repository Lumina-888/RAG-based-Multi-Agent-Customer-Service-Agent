/**
 * SP-FE-001 SSE 解析器单测（Vitest，纯函数零网络）。
 *
 * - T-FE-101 事件块解析：id/event/data 三行 → 结构化对象；缺 event 默认 message
 * - T-FE-102 跨 chunk 缓冲：事件被拆进多个 chunk 时正确重组（断流不丢事件）
 * - T-FE-103 容错：注释行忽略、空行忽略、data 多行连接、\r\n 兼容
 * - T-FE-104 非 200 响应（4001 统一 JSON）→ 抛错带 code/status
 */
import { describe, it, expect } from 'vitest'
import { parseEventBlock, readSSEEvents, splitEventBlocks } from './sse.js'

const INTENT_BLOCK = 'id: 1\nevent: intent\ndata: {"intent":"refund","conf":0.95}'

describe('parseEventBlock（T-FE-101）', () => {
  it('解析 id/event/data 三行', () => {
    const ev = parseEventBlock(INTENT_BLOCK)
    expect(ev).toEqual({
      id: '1',
      event: 'intent',
      data: '{"intent":"refund","conf":0.95}',
    })
  })

  it('缺 event 字段默认 message（SSE 规范）', () => {
    const ev = parseEventBlock('id: 2\ndata: {"content":"hi"}')
    expect(ev.event).toBe('message')
  })

  it('忽略注释行与未知字段', () => {
    const ev = parseEventBlock(': comment\nid: 3\nevent: done\nretry: 1000\ndata: {}')
    expect(ev.id).toBe('3')
    expect(ev.event).toBe('done')
    expect(ev.data).toBe('{}')
  })

  it('data 多行按 \\n 连接', () => {
    const ev = parseEventBlock('event: x\ndata: line1\ndata: line2')
    expect(ev.data).toBe('line1\nline2')
  })
})

describe('splitEventBlocks（T-FE-102）', () => {
  it('单 chunk 多事件：按空行切分并返回残留', () => {
    const text = `${INTENT_BLOCK}\n\nid: 2\nevent: route\ndata: {}`
    const { blocks, carry } = splitEventBlocks(text)
    expect(blocks).toHaveLength(1)
    expect(blocks[0]).toContain('event: intent')
    expect(carry).toContain('event: route') // 未闭合的事件留到下个 chunk
  })

  it('跨 chunk 缓冲：事件被拆成两半仍能重组', () => {
    const first = `${INTENT_BLOCK.slice(0, 20)}` // 截断在中间
    const { blocks, carry } = splitEventBlocks(first)
    expect(blocks).toHaveLength(0)
    const { blocks: blocks2, carry: carry2 } = splitEventBlocks(
      `${INTENT_BLOCK.slice(20)}\n\nid: 9\nevent: done\ndata: {}\n\n`,
      carry,
    )
    expect(blocks2).toHaveLength(2)
    expect(blocks2[0]).toContain('event: intent')
    expect(blocks2[1]).toContain('event: done')
    expect(carry2).toBe('')
  })

  it('未闭合事件留在 carry（无结尾空行）', () => {
    const { blocks, carry } = splitEventBlocks(`${INTENT_BLOCK}\n\nid: 9\nevent: done\ndata: {}`)
    expect(blocks).toHaveLength(1)
    expect(carry).toContain('event: done')
  })

  it('\\r\\n 兼容', () => {
    const { blocks } = splitEventBlocks(`${INTENT_BLOCK}\r\n\r\n`)
    expect(blocks).toHaveLength(1)
    expect(blocks[0]).not.toContain('\r')
  })
})

describe('readSSEEvents（T-FE-103/104）', () => {
  function fakeResponse(ok, body, chunks) {
    return {
      ok,
      status: ok ? 200 : 400,
      body: ok
        ? {
            getReader() {
              let i = 0
              return {
                releaseLock() {},
                read() {
                  if (i >= chunks.length) return Promise.resolve({ done: true, value: undefined })
                  return Promise.resolve({ done: false, value: chunks[i++] })
                },
              }
            },
          }
        : null,
      async json() {
        return { code: 4001, message: 'message 不能为空' }
      },
    }
  }

  it('逐事件产出（含残留块兜底）', async () => {
    const encoder = new TextEncoder()
    const resp = fakeResponse(true, null, [
      encoder.encode(`${INTENT_BLOCK}\n\nid: 2\nevent: message\ndata: {"content":"你好","delta":true}\n\n`),
      encoder.encode('id: 3\nevent: done\ndata: {}'), // 无结尾空行 → 残留兜底
    ])
    const events = []
    for await (const ev of readSSEEvents(resp)) events.push(ev)
    expect(events.map((e) => e.event)).toEqual(['intent', 'message', 'done'])
    expect(events[0].id).toBe('1')
  })

  it('非 200（4001 统一 JSON）→ 抛出带 code 的错误', async () => {
    const resp = fakeResponse(false, null, [])
    await expect(async () => {
      for await (const _ of readSSEEvents(resp)) { /* noop */ }
    }).rejects.toMatchObject({ code: 4001, status: 400 })
  })
})
