<template>
  <div class="trace-panel">
    <div class="trace-title">Agent 追踪面板</div>
    <div v-if="steps.length === 0" class="empty">发送消息后，此处展示意图 → 路由 → 检索 → 工具 全链路时间线。</div>
    <div ref="timelineEl" class="timeline">
      <div v-for="(step, i) in steps" :key="step.id || i" class="step">
        <div class="step-head">
          <el-tag size="small" :type="tagType(step.event)" class="step-tag">{{ label(step.event) }}</el-tag>
          <span class="step-time">{{ i === 0 ? '0ms' : `${step.elapsed}ms` }}</span>
        </div>
        <div class="step-body">
          <template v-if="step.event === 'intent'">
            <span class="kv">intent: <b>{{ step.data.intent }}</b></span>
            <span class="kv">conf: {{ (step.data.conf * 100).toFixed(0) }}%</span>
          </template>
          <template v-else-if="step.event === 'route'">
            <span class="kv">agent: <b>{{ step.data.agent }}</b></span>
            <span class="kv">reason: {{ step.data.reason }}</span>
          </template>
          <template v-else-if="step.event === 'vision'">
            <span class="kv">图片理解: {{ step.data.description }}</span>
          </template>
          <template v-else-if="step.event === 'retrieval'">
            <span class="kv">strategy: {{ step.data.strategy }}（{{ step.data.count }} 条）</span>
            <div v-for="(doc, di) in (step.data.docs || []).slice(0, 5)" :key="di" class="doc-row">
              <span class="doc-rank">{{ di + 1 }}</span>
              <span class="doc-title">{{ doc.title }}</span>
              <span class="doc-score">{{ (doc.score || 0).toFixed(3) }}</span>
            </div>
          </template>
          <template v-else-if="step.event === 'tool_call'">
            <span class="kv">tool: <b>{{ step.data.tool }}</b></span>
            <div class="json-block">参数: {{ json(step.data.args) }}</div>
            <div v-if="step.data.result" class="json-block">结果: {{ json(step.data.result) }}</div>
            <el-tag v-if="step.data.pending" size="small" type="warning">待二次确认</el-tag>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  trace: { type: Array, default: () => [] }, // {id, event, data, t}
})

const timelineEl = ref(null)

// 每步耗时：与上一步到达时间差（客户端观测口径）
const steps = computed(() =>
  props.trace.map((item, i) => ({
    ...item,
    elapsed: i === 0 ? 0 : item.t - props.trace[i - 1].t,
  })),
)

function label(event) {
  return { intent: '意图识别', route: '路由', vision: '图片理解', retrieval: '检索', tool_call: '工具调用' }[event] || event
}
function tagType(event) {
  return { intent: 'primary', route: 'success', vision: 'info', retrieval: 'warning', tool_call: 'danger' }[event] || 'info'
}
function json(value) {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

watch(
  () => props.trace.length,
  async () => {
    await nextTick()
    if (timelineEl.value) timelineEl.value.scrollTop = timelineEl.value.scrollHeight
  },
)
</script>

<style scoped>
.trace-panel {
  height: 100%;
  padding: 12px;
  border-left: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
}
.trace-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.timeline {
  flex: 1;
  overflow-y: auto;
}
.step {
  border-left: 2px solid var(--el-border-color);
  padding: 6px 0 10px 12px;
  position: relative;
}
.step::before {
  content: '';
  position: absolute;
  left: -5px;
  top: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-primary);
}
.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.step-body {
  font-size: 13px;
  margin-top: 4px;
  color: var(--el-text-color-regular);
}
.kv {
  margin-right: 12px;
}
.doc-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 2px;
  font-size: 12px;
}
.doc-rank {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--el-color-primary-light-8);
  text-align: center;
  line-height: 16px;
}
.doc-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-score {
  color: var(--el-text-color-secondary);
}
.json-block {
  font-family: monospace;
  font-size: 12px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 2px 6px;
  margin-top: 2px;
  word-break: break-all;
}
</style>
