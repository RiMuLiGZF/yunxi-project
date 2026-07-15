<template>
  <MainLayout>
    <div class="monitor-page fade-in">
      <div class="monitor-header">
        <div>
          <h1 class="page-title">系统监控</h1>
          <p class="page-subtitle">实时监控各模块运行指标与告警信息</p>
        </div>
        <div class="monitor-actions">
          <span v-if="lastRefresh" class="refresh-time">最后刷新: {{ lastRefresh }}</span>
          <button class="btn btn-sm" :disabled="loading" @click="refreshAll">
            {{ loading ? '刷新中...' : '立即刷新' }}
          </button>
          <span class="auto-label">30s 自动刷新</span>
        </div>
      </div>

      <!-- 系统指标卡片 -->
      <div class="section-title">系统指标</div>
      <div class="grid grid-6 metrics-row">
        <div v-for="m in metricCards" :key="m.key" class="metric-card card">
          <div class="metric-label">{{ m.label }}</div>
          <div class="metric-value" :class="valueColor(m.value)">
            <template v-if="loading"><span class="skeleton-text">--</span></template>
            <template v-else-if="m.value != null">{{ m.display }}</template>
            <template v-else>暂无数据</template>
          </div>
          <div v-if="m.value != null && m.max" class="progress-bar">
            <div
              class="progress-fill"
              :class="barColor(m.value, m.max)"
              :style="{ width: Math.min(m.value / m.max * 100, 100) + '%' }"
            ></div>
          </div>
        </div>
      </div>

      <!-- 模块健康状态表格 -->
      <div class="section-title">模块健康状态</div>
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>状态</th>
              <th>模块</th>
              <th>端口</th>
              <th>描述</th>
              <th>响应时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="mod in modulesStore.modules"
              :key="mod.id"
              class="clickable-row"
              @click="$router.push(`/modules/${mod.id}`)"
            >
              <td>
                <span class="status-dot" :class="mod.status"></span>
              </td>
              <td>
                <strong>{{ mod.name }}</strong>
                <code class="ml-2">{{ mod.id.toUpperCase() }}</code>
              </td>
              <td><code>:{{ mod.port }}</code></td>
              <td>{{ mod.description }}</td>
              <td>
                <span v-if="mod.status === 'online'" class="response-ok">
                  <span class="status-dot online"></span> 正常
                </span>
                <span v-else-if="mod.status === 'offline'" class="response-fail">
                  超时
                </span>
                <span v-else class="text-muted">未知</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 告警历史 -->
      <div class="section-title">告警历史</div>
      <div class="card alerts-card">
        <template v-if="alerts.length">
          <div v-for="alert in alerts" :key="alert.id || alert.timestamp" class="alert-item" :class="alertSeverity(alert)">
            <div class="alert-header">
              <span class="alert-level">{{ alert.level || alert.severity || 'INFO' }}</span>
              <span class="alert-time">{{ formatTime(alert.timestamp || alert.created_at) }}</span>
            </div>
            <div class="alert-message">{{ alert.message || alert.description }}</div>
          </div>
        </template>
        <div v-else class="alerts-empty">
          <span class="alerts-icon">&#128737;</span>
          <p v-if="alertsError">{{ alertsError }}</p>
          <p v-else-if="loading">加载中...</p>
          <p v-else>暂无告警记录</p>
        </div>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useModulesStore } from '../stores/modules.js'
import { get } from '../api/index.js'
import MainLayout from '../layouts/MainLayout.vue'

const modulesStore = useModulesStore()
const loading = ref(false)
const lastRefresh = ref('')
const alerts = ref([])
const alertsError = ref('')

// ---- 系统指标 ----
const metrics = reactive({
  cpu: null,
  memory: null,
  disk: null,
  gpu: null,
  temperature: null,
  processCount: null,
})

const metricCards = computed(() => [
  {
    key: 'cpu',
    label: 'CPU',
    value: metrics.cpu,
    max: 100,
    display: metrics.cpu != null ? metrics.cpu.toFixed(1) + '%' : null,
  },
  {
    key: 'memory',
    label: '内存',
    value: metrics.memory,
    max: 100,
    display: metrics.memory != null ? metrics.memory.toFixed(1) + '%' : null,
  },
  {
    key: 'disk',
    label: '磁盘',
    value: metrics.disk,
    max: 100,
    display: metrics.disk != null ? metrics.disk.toFixed(1) + '%' : null,
  },
  {
    key: 'gpu',
    label: 'GPU',
    value: metrics.gpu,
    max: 100,
    display: metrics.gpu != null ? metrics.gpu.toFixed(1) + '%' : null,
  },
  {
    key: 'temperature',
    label: '温度',
    value: metrics.temperature,
    max: 100,
    display: metrics.temperature != null ? metrics.temperature.toFixed(0) + ' C' : null,
  },
  {
    key: 'processCount',
    label: '进程数',
    value: metrics.processCount,
    max: null,
    display: metrics.processCount != null ? String(metrics.processCount) : null,
  },
])

function valueColor(val) {
  if (val == null) return 'metric-na'
  return 'metric-present'
}

function barColor(val, max) {
  if (!max) return 'info'
  const pct = val / max * 100
  if (pct < 60) return 'success'
  if (pct < 85) return 'warn'
  return 'danger'
}

async function fetchMetrics() {
  try {
    const data = await get('/api/v1/status/metrics')
    metrics.cpu = data.cpu_percent ?? data.cpu ?? null
    metrics.memory = data.memory_percent ?? data.memory ?? null
    metrics.disk = data.disk_percent ?? data.disk ?? null
    metrics.gpu = data.gpu_percent ?? data.gpu ?? null
    metrics.temperature = data.temperature ?? data.temp ?? null
    metrics.processCount = data.process_count ?? data.processes ?? null
  } catch {
    // M10 不可用
  }
}

async function fetchAlerts() {
  try {
    const data = await get('/api/v1/alerts')
    alerts.value = Array.isArray(data) ? data : data.items || data.alerts || []
    alertsError.value = ''
  } catch (e) {
    alertsError.value = e.message || '无法获取告警数据'
    alerts.value = []
  }
}

async function refreshAll() {
  loading.value = true
  await Promise.allSettled([
    fetchMetrics(),
    fetchAlerts(),
    modulesStore.fetchHealth(),
  ])
  loading.value = false
  const now = new Date()
  lastRefresh.value = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

function pad(n) { return String(n).padStart(2, '0') }

function alertSeverity(alert) {
  const level = (alert.level || alert.severity || 'info').toLowerCase()
  if (level === 'critical' || level === 'error') return 'severity-critical'
  if (level === 'warning' || level === 'warn') return 'severity-warning'
  return 'severity-info'
}

function formatTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return String(ts)
  }
}

// ---- 30s 自动刷新 ----
let autoTimer = null

onMounted(() => {
  refreshAll()
  autoTimer = setInterval(refreshAll, 30000)
})

onUnmounted(() => {
  if (autoTimer) clearInterval(autoTimer)
})
</script>

<style scoped>
.monitor-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.monitor-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.monitor-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.refresh-time {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.auto-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  padding: 4px 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-top: 8px;
}

/* 指标卡片行 */
.metrics-row {
  grid-template-columns: repeat(6, 1fr);
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.metric-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 1.4rem;
  font-weight: 700;
}

.metric-present { color: var(--text-primary); }
.metric-na { color: var(--text-muted); font-size: 0.9rem; }

.skeleton-text {
  color: var(--text-muted);
  animation: pulse 1.5s infinite;
}

/* 进度条 */
.progress-bar {
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}

.progress-fill.success { background: var(--success); }
.progress-fill.warn { background: var(--warning); }
.progress-fill.danger { background: var(--danger); }
.progress-fill.info { background: var(--accent); }

/* 表格增强 */
.clickable-row {
  cursor: pointer;
}

.ml-2 { margin-left: 8px; }

.response-ok {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
  font-size: 0.85rem;
}

.response-fail {
  color: var(--danger);
  font-size: 0.85rem;
}

.text-muted {
  color: var(--text-muted);
  font-size: 0.85rem;
}

code {
  color: var(--accent);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85rem;
}

/* 告警 */
.alerts-card {
  min-height: 120px;
}

.alert-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.alert-item:last-child {
  border-bottom: none;
}

.alert-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.alert-level {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 4px;
}

.severity-critical .alert-level {
  background: rgba(248, 113, 113, 0.15);
  color: var(--danger);
}

.severity-warning .alert-level {
  background: rgba(251, 191, 36, 0.15);
  color: var(--warning);
}

.severity-info .alert-level {
  background: rgba(56, 189, 248, 0.15);
  color: var(--accent);
}

.alert-time {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.alert-message {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.alerts-empty {
  text-align: center;
  padding: 32px 16px;
  color: var(--text-muted);
}

.alerts-icon {
  font-size: 2rem;
  display: block;
  margin-bottom: 8px;
}

/* 响应式 */
@media (max-width: 1200px) {
  .metrics-row { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 900px) {
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .metrics-row { grid-template-columns: 1fr; }
  .monitor-header { flex-direction: column; gap: 12px; }
}
</style>
