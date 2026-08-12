<template>
  <div class="quick-actions">
    <span class="label">快捷指令：</span>
    <el-button v-for="action in actions" :key="action.label" size="small" @click="$emit('send', action.message)">
      {{ action.label }}
    </el-button>
  </div>
</template>

<script setup>
// 快捷指令（SP-FE-001）：一键发送典型问题（查物流/退款/转人工/商品咨询）
defineEmits(['send'])

const actions = [
  { label: '查物流', message: '我的订单到哪了' },
  { label: '申请退款', message: '我要申请退款' },
  { label: '转人工', message: '转人工' },
  { label: '商品咨询', message: '保温杯容量多大' },
]
</script>

<style scoped>
.quick-actions {
  padding: 4px 0;
}
.label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-right: 6px;
}
</style>
