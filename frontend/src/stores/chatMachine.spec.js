/**
 * SP-FE-001/002 聊天事件状态机单测（纯函数，零网络零组件）。
 *
 * - T-FE-201 正常问答链路：intent→route→retrieval→message(delta)→message(end)→done
 *   生成 1 条用户消息 + 1 条 assistant 消息 + 3 条追踪事件
 * - T-FE-202 打字机：delta=true 多次增量追加到同一消息；delta=false 结束
 * - T-FE-203 转人工 / 错误路径：done.transfer 标记；done.error 写入 error 且不发消息
 * - T-FE-204 事件去重与 Last-Event-ID：同 id 重复事件幂等；lastEventId 持续更新
 */
import { describe, it, expect } from 'vitest'
import { applyEvent, createChatState } from './chatMachine.js'

function ev(id, event, data) {
  return { id, event, data: JSON.stringify(data) }
}

describe('chatMachine（T-FE-201）', () => {
  it('正常问答链路：消息与追踪时间线正确', () => {
    const state = createChatState('s1')
    state.messages.push({ id: 'm-0', role: 'user', content: '保温杯容量多大' })
    applyEvent(state, ev('1', 'intent', { intent: 'after_sales', conf: 0.96 }))
    applyEvent(state, ev('2', 'route', { agent: 'qa_agent', reason: 'route' }))
    applyEvent(state, ev('3', 'retrieval', { docs: [{ chunk_id: 'kb-1-0', title: '商品手册', score: 0.8 }], strategy: 'rrf', count: 1 }))
    applyEvent(state, ev('4', 'message', { content: '容量 500ml', delta: true }))
    applyEvent(state, ev('5', 'message', { content: '', delta: false }))
    applyEvent(state, ev('6', 'done', {}))

    expect(state.messages).toHaveLength(2)
    expect(state.messages[1]).toMatchObject({ role: 'assistant', content: '容量 500ml', streaming: false })
    expect(state.trace.map((t) => t.event)).toEqual(['intent', 'route', 'retrieval'])
    expect(state.trace[2].data.docs[0].score).toBe(0.8)
    expect(state.sending).toBe(false)
    expect(state.error).toBeNull()
  })

  it('T-FE-202 打字机：增量追加后结束', () => {
    const state = createChatState('s1')
    applyEvent(state, ev('1', 'message', { content: '退款将', delta: true }))
    applyEvent(state, ev('2', 'message', { content: '在 3~5 个工作日', delta: true }))
    expect(state.messages).toHaveLength(1)
    expect(state.messages[0].content).toBe('退款将在 3~5 个工作日')
    expect(state.messages[0].streaming).toBe(true)
    applyEvent(state, ev('3', 'message', { content: '', delta: false }))
    expect(state.messages[0].streaming).toBe(false)
  })

  it('T-FE-203 转人工与错误路径', () => {
    const transfer = createChatState('s1')
    applyEvent(transfer, ev('1', 'done', { transfer: true }))
    expect(transfer.transfer).toBe(true)

    const failed = createChatState('s1')
    applyEvent(failed, ev('1', 'done', { error: { code: 5001, message: 'LLM 服务不可用' } }))
    expect(failed.error).toEqual({ code: 5001, message: 'LLM 服务不可用' })
    expect(failed.sending).toBe(false)
    expect(failed.messages).toHaveLength(0) // 错误不发消息
  })

  it('T-FE-204 事件去重与 Last-Event-ID 更新', () => {
    const state = createChatState('s1')
    applyEvent(state, ev('1', 'intent', { intent: 'refund', conf: 0.9 }))
    applyEvent(state, ev('1', 'intent', { intent: 'refund', conf: 0.9 })) // 重放
    applyEvent(state, ev('2', 'done', { ticket_id: 'TK-000001' }))
    expect(state.trace).toHaveLength(1) // 同 id 只入一次
    expect(state.lastEventId).toBe('2')
    expect(state.ticketId).toBe('TK-000001')
  })
})
