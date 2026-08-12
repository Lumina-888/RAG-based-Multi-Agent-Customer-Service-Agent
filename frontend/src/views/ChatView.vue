<template>
  <div class="chat-layout">
    <div class="chat-main">
      <div ref="msgListEl" class="msg-list">
        <ChatMessage v-for="msg in store.messages" :key="msg.id" :message="msg" :docs="lastDocs" />
      </div>
      <div class="chat-footer">
        <QuickActions @send="onSend" />
        <div class="input-row">
          <el-input
            v-model="draft"
            :disabled="store.sending"
            placeholder="请输入问题，Enter 发送（不超过 500 字）"
            maxlength="500"
            @keyup.enter="onSend(draft)"
          />
          <el-button type="primary" :loading="store.sending" @click="onSend(draft)">发送</el-button>
        </div>
        <el-alert
          v-if="store.error"
          :title="`错误 ${store.error.code || ''}`.trim()"
          :description="store.error.message"
          type="error"
          show-icon
          :closable="false"
        />
        <el-alert v-if="store.transfer" title="已转接人工坐席 1001" type="warning" show-icon :closable="false" />
        <el-alert
          v-if="store.ticketId"
          :title="`退款工单已创建：${store.ticketId}，请耐心等待审核`"
          type="success"
          show-icon
          :closable="false"
        />
      </div>
    </div>
    <el-aside width="360px" class="trace-aside">
      <TracePanel :trace="store.trace" />
    </el-aside>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import ChatMessage from '../components/ChatMessage.vue'
import QuickActions from '../components/QuickActions.vue'
import TracePanel from '../components/TracePanel.vue'
import { useChatStore } from '../stores/chat.js'

const store = useChatStore()
const draft = ref('')
const msgListEl = ref(null)

// 最近一次 retrieval 事件的 docs（引用角标溯源数据源）
const lastDocs = computed(() => {
  const items = [...store.trace].reverse()
  const retrieval = items.find((t) => t.event === 'retrieval')
  return retrieval?.data?.docs || []
})

function onSend(text) {
  const content = String(text || '').trim()
  if (!content || store.sending) return
  draft.value = ''
  store.sendMessage(content)
}

// 消息流自动滚动（SP-FE-002）：新消息 / 流式增量 / 时间线更新都滚到底部
watch(
  () => [store.messages.length, store.messages.at(-1)?.content, store.trace.length],
  async () => {
    await nextTick()
    if (msgListEl.value) msgListEl.value.scrollTop = msgListEl.value.scrollHeight
  },
  { deep: true },
)
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}
.chat-footer {
  border-top: 1px solid var(--el-border-color-lighter);
  padding: 12px 24px;
}
.input-row {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}
.trace-aside {
  border-left: 1px solid var(--el-border-color-lighter);
}
</style>
