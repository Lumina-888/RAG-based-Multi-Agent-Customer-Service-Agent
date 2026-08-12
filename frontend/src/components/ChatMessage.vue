<template>
  <div class="msg-row" :class="message.role">
    <div class="bubble">
      <template v-if="message.role === 'assistant'">
        <!-- 无角标：整段 Markdown 渲染（SP-FE-001） -->
        <div v-if="!hasCitations" class="md" v-html="sanitized" />
        <!-- 有角标：分段渲染，[n] 为可 hover 的溯源角标 -->
        <template v-else>
          <span v-for="(seg, i) in segments" :key="i" class="md-inline" v-html="renderInline(seg.text)" />
          <el-tooltip v-for="(seg, i) in segments.filter((s) => s.ref !== null)" :key="`ref-${i}`" placement="top">
            <template #content>
              <div class="cite-tip">
                <div class="cite-title">{{ docTitle(seg.ref) }}</div>
                <div class="cite-content">{{ docSnippet(seg.ref) }}</div>
              </div>
            </template>
            <sup class="cite-ref">[{{ seg.ref }}]</sup>
          </el-tooltip>
        </template>
        <span v-if="message.streaming" class="cursor">▍</span>
      </template>
      <template v-else>{{ message.content }}</template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { citationDoc, extractCitations, splitByCitations } from '../utils/citations.js'

const props = defineProps({
  message: { type: Object, required: true }, // {role, content, streaming}
  docs: { type: Array, default: () => [] }, // 最近一次 retrieval 事件的 docs（溯源）
})

const hasCitations = computed(() => extractCitations(props.message.content || '').length > 0)
const segments = computed(() => splitByCitations(props.message.content || ''))
const sanitized = computed(() => DOMPurify.sanitize(marked.parse(props.message.content || '')))

function renderInline(text) {
  return DOMPurify.sanitize(marked.parseInline(text))
}
function docTitle(ref) {
  return citationDoc(ref, props.docs)?.title || `来源文档 ${ref}`
}
function docSnippet(ref) {
  const doc = citationDoc(ref, props.docs)
  if (!doc) return '（本次回复无对应检索片段）'
  const content = doc.content || ''
  return content.length > 120 ? `${content.slice(0, 120)}…` : content
}
</script>

<style scoped>
.msg-row {
  display: flex;
  margin: 12px 0;
}
.msg-row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--el-bg-color-page);
  border: 1px solid var(--el-border-color-lighter);
  line-height: 1.6;
  word-break: break-word;
}
.msg-row.user .bubble {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}
.cite-ref {
  color: var(--el-color-primary);
  font-weight: 600;
  cursor: pointer;
  margin: 0 1px;
}
.cursor {
  color: var(--el-color-primary);
  animation: blink 1s step-start infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.cite-tip {
  max-width: 320px;
}
.cite-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.cite-content {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: pre-wrap;
}
.md-inline p {
  display: inline;
}
</style>
