/**
 * 对话状态 store（SP-FE-001/002）：Pinia 包装纯函数状态机 `chatMachine`。
 *
 * - `sendMessage`：POST /api/v1/chat → ReadableStream 解析 SSE → applyEvent
 * - 断线重连：携带 `lastEventId`（Last-Event-ID）
 * - 消息流与追踪时间线自动维护（组件只做渲染）
 */
import { defineStore } from 'pinia'
import { newSessionId, sendChatMessage } from '../api/chat.js'
import { applyEvent, createChatState } from './chatMachine.js'

export const useChatStore = defineStore('chat', {
  state: () => createChatState(newSessionId()),

  actions: {
    async sendMessage(text) {
      const content = String(text || '').trim()
      if (this.sending || !content) return
      this.messages.push({ id: `m-${this.messages.length + 1}`, role: 'user', content })
      this.sending = true
      this.error = null
      this.transfer = false
      this.ticketId = null
      try {
        for await (const ev of sendChatMessage(this.sessionId, content, this.lastEventId)) {
          applyEvent(this, ev)
        }
      } catch (e) {
        this.sending = false
        this.error = { code: e.code || 5000, message: e.message || '网络错误，请稍后重试' }
      }
    },

    reset() {
      Object.assign(this, createChatState(newSessionId()))
    },
  },
})
