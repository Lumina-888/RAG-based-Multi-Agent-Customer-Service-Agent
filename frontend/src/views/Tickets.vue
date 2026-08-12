<template>
  <div class="tickets-page">
    <div class="page-head">
      <h2>工单管理</h2>
      <div>
        <el-select v-model="statusFilter" placeholder="按状态筛选" clearable size="small" style="width: 160px" @change="load">
          <el-option v-for="s in STATUSES" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button size="small" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-alert
      v-if="transitionError"
      :title="transitionError"
      type="error"
      show-icon
      :closable="true"
      @close="transitionError = ''"
    />

    <el-table :data="tickets" size="small" v-loading="loading" @expand-change="onExpand">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="audit-block">
            <div class="audit-title">审计回溯（{{ (auditMap[row.ticket_id] || []).length }} 条）</div>
            <el-timeline v-if="auditMap[row.ticket_id]?.length">
              <el-timeline-item
                v-for="log in auditMap[row.ticket_id]"
                :key="log.id"
                :timestamp="formatTs(log.ts)"
              >
                <b>{{ log.from_status || '—' }}</b> → <b>{{ log.to_status || '—' }}</b>
                <span class="audit-op">操作人：{{ log.operator }}</span>
                <div v-if="log.reason" class="audit-reason">{{ log.reason }}</div>
              </el-timeline-item>
            </el-timeline>
            <div v-else class="audit-empty">加载中…</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="ticket_id" label="工单号" width="130" />
      <el-table-column prop="order_id" label="订单号" width="180" />
      <el-table-column prop="refund_type" label="类型" width="120" />
      <el-table-column prop="amount" label="金额" width="90">
        <template #default="{ row }">¥{{ row.amount }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态流转（模拟坐席）" min-width="240">
        <template #default="{ row }">
          <template v-if="transitionOptions(row.status).length">
            <el-select
              v-model="transitionTarget[row.ticket_id]"
              size="small"
              placeholder="目标状态"
              style="width: 130px"
            >
              <el-option v-for="target in transitionOptions(row.status)" :key="target" :label="target" :value="target" />
            </el-select>
            <el-button size="small" type="primary" :loading="transitioning[row.ticket_id]" @click="doTransition(row)">
              提交
            </el-button>
          </template>
          <span v-else class="no-op">—（终态/无受限迁移）</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { fetchTicketAudit, fetchTickets, transitionTicket } from '../api/tickets.js'
import { allowedTransitions } from '../utils/ticketTransitions.js'

const STATUSES = ['CREATED', 'APPROVING', 'APPROVED', 'REFUNDING', 'REFUNDED', 'REJECTED', 'FAILED']

const tickets = ref([])
const loading = ref(false)
const error = ref('')
const transitionError = ref('')
const statusFilter = ref('')
const auditMap = reactive({})
const transitionTarget = reactive({})
const transitioning = reactive({})

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchTickets(statusFilter.value || '')
    tickets.value = data.tickets || []
  } catch (e) {
    error.value = `工单加载失败：${e.message}（请确认后端已启动）`
  } finally {
    loading.value = false
  }
}

async function onExpand(row, expandedRows) {
  if (!expandedRows.length) return
  if (auditMap[row.ticket_id]) return
  try {
    auditMap[row.ticket_id] = (await fetchTicketAudit(row.ticket_id)).audit_logs || []
  } catch (e) {
    auditMap[row.ticket_id] = [{ id: 0, ts: '', operator: '—', from_status: '', to_status: '', reason: e.message }]
  }
}

async function doTransition(row) {
  const target = transitionTarget[row.ticket_id]
  if (!target) return
  transitioning[row.ticket_id] = true
  transitionError.value = ''
  try {
    await transitionTicket(row.ticket_id, target, 'agent', '前端工单页流转')
    await load()
    delete transitionTarget[row.ticket_id]
  } catch (e) {
    transitionError.value = `流转失败：${e.message}（${e.code || ''}）`
  } finally {
    transitioning[row.ticket_id] = false
  }
}

// 受限迁移（SP-FE-003）：仅 APPROVING → APPROVED/REJECTED，永不出现 REFUNDING
function transitionOptions(status) {
  return allowedTransitions(status)
}

function statusTag(status) {
  return {
    CREATED: 'info',
    APPROVING: 'warning',
    APPROVED: 'success',
    REFUNDING: 'primary',
    REFUNDED: 'success',
    REJECTED: 'danger',
    FAILED: 'danger',
  }[status] || 'info'
}

function formatTs(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.tickets-page {
  padding: 16px 24px;
  overflow-y: auto;
  height: 100%;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.audit-block {
  padding: 8px 24px;
}
.audit-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.audit-op {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.audit-reason {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.audit-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.no-op {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
