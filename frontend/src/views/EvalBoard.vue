<template>
  <div class="eval-board">
    <div class="page-head">
      <h2>评测看板</h2>
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <!-- 指标卡：各 run_type 最新一次运行 -->
    <div class="cards">
      <el-card v-for="(run, type) in latestByType" :key="type" class="card">
        <template #header>
          <div class="card-head">
            <el-tag size="small" type="info">{{ run.run_type }}</el-tag>
            <span class="run-name">{{ run.name }}</span>
            <span class="run-time">{{ formatTs(run.created_at) }}</span>
          </div>
        </template>
        <div class="metrics">
          <div v-for="(value, key) in run.metrics" :key="key" class="metric" v-show="typeof value === 'number'">
            <div class="metric-value">{{ formatNum(value) }}</div>
            <div class="metric-key">{{ key }}</div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 消融对比表（E1~E5，M7 交付） -->
    <el-card v-if="ablationStrategies.length" class="table-card">
      <template #header>消融实验对比（E1~E5）</template>
      <el-table :data="ablationStrategies" size="small">
        <el-table-column prop="strategy" label="策略" width="140" />
        <el-table-column label="Recall@5" width="120">
          <template #default="{ row }">{{ fmtCell(row['recall@5']) }}</template>
        </el-table-column>
        <el-table-column label="MRR" width="120">
          <template #default="{ row }">{{ fmtCell(row.mrr) }}</template>
        </el-table-column>
        <el-table-column label="NDCG@5" width="120">
          <template #default="{ row }">{{ fmtCell(row['ndcg@5']) }}</template>
        </el-table-column>
        <el-table-column label="用例数" width="90">
          <template #default="{ row }">{{ row.cases }}</template>
        </el-table-column>
        <el-table-column label="状态">
          <template #default="{ row }">
            <el-tag v-if="row.skipped" type="warning" size="small">skipped（无 RERANKER_API_KEY）</el-tag>
            <el-tag v-else type="success" size="small">完成</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 运行历史 -->
    <el-card class="table-card">
      <template #header>运行历史（eval_runs）</template>
      <el-table :data="runs" size="small">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="run_type" label="类型" width="120" />
        <el-table-column prop="name" label="名称" width="200" />
        <el-table-column label="创建时间">
          <template #default="{ row }">{{ formatTs(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchEvalRuns } from '../api/eval.js'

const runs = ref([])
const error = ref('')

onMounted(load)

async function load() {
  error.value = ''
  try {
    runs.value = (await fetchEvalRuns()).runs || []
  } catch (e) {
    error.value = `评测数据加载失败：${e.message}（请确认后端已启动）`
  }
}

// 各 run_type 最新一次运行（runs 新→旧）
const latestByType = computed(() => {
  const map = {}
  for (const run of runs.value) {
    if (!map[run.run_type]) map[run.run_type] = run
  }
  return map
})

const ablationStrategies = computed(() => latestByType.value.ablation?.metrics?.strategies || [])

function fmtNum(value) {
  if (typeof value !== 'number') return value
  return value >= 1 ? value : value.toFixed(3)
}
function fmtCell(value) {
  return value === null || value === undefined ? '—' : Number(value).toFixed(4)
}
function formatTs(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.eval-board {
  padding: 16px 24px;
  overflow-y: auto;
  height: 100%;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.cards {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin: 8px 0 16px;
}
.card {
  width: 320px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.run-name {
  font-weight: 600;
}
.run-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
.metric-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.metric-key {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.table-card {
  margin-bottom: 16px;
}
</style>
