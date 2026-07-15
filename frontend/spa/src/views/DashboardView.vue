<template>
  <MainLayout>
    <div class="dashboard fade-in">
      <!-- 顶部欢迎区域 -->
      <div class="dashboard-header">
        <div>
          <h1 class="page-title">{{ greeting }}，{{ authStore.username || '管理员' }}</h1>
          <p class="page-subtitle">云汐统一管理平台 — 全局概览 · {{ currentTime }}</p>
        </div>
      </div>

      <!-- 状态栏 -->
      <StatusBar class="dashboard-status" />

      <!-- 快速操作 -->
      <div class="dashboard-section">
        <h2 class="section-title">快速操作</h2>
        <div class="quick-actions">
          <button class="quick-btn" :disabled="actionLoading" @click="startAll">
            <span class="quick-icon">&#9654;</span>
            <span>启动全部</span>
          </button>
          <button class="quick-btn danger" :disabled="actionLoading" @click="stopAll">
            <span class="quick-icon">&#9632;</span>
            <span>停止全部</span>
          </button>
          <button class="quick-btn" @click="$router.push('/api-docs')">
            <span class="quick-icon">&#9783;</span>
            <span>API 文档</span>
          </button>
          <button class="quick-btn" @click="$router.push('/settings')">
            <span class="quick-icon">&#9881;</span>
            <span>系统设置</span>
          </button>
        </div>
      </div>

      <!-- 系统概览 -->
      <div class="dashboard-section">
        <h2 class="section-title">系统概览</h2>
        <div class="grid grid-4 metrics-grid">
          <div class="metric-card card">
            <div class="metric-label">CPU 使用率</div>
            <div class="metric-value" :class="metricColor(systemMetrics.cpu)">
              {{ systemMetrics.cpu != null ? systemMetrics.cpu.toFixed(1) + '%' : '暂无数据' }}
            </div>
            <div v-if="systemMetrics.cpu != null" class="progress-bar">
              <div class="progress-fill" :style="{ width: systemMetrics.cpu + '%' }" :class="metricBar(systemMetrics.cpu)"></div>
            </div>
          </div>
          <div class="metric-card card">
            <div class="metric-label">内存使用率</div>
            <div class="metric-value" :class="metricColor(systemMetrics.memory)">
              {{ systemMetrics.memory != null ? systemMetrics.memory.toFixed(1) + '%' : '暂无数据' }}
            </div>
            <div v-if="systemMetrics.memory != null" class="progress-bar">
              <div class="progress-fill" :style="{ width: systemMetrics.memory + '%' }" :class="metricBar(systemMetrics.memory)"></div>
            </div>
          </div>
          <div class="metric-card card">
            <div class="metric-label">磁盘使用率</div>
            <div class="metric-value" :class="metricColor(systemMetrics.disk)">
              {{ systemMetrics.disk != null ? systemMetrics.disk.toFixed(1) + '%' : '暂无数据' }}
            </div>
            <div v-if="systemMetrics.disk != null" class="progress-bar">
              <div class="progress-fill" :style="{ width: systemMetrics.disk + '%' }" :class="metricBar(systemMetrics.disk)"></div>
            </div>
          </div>
          <div class="metric-card card">
            <div class="metric-label">在线 / 离线</div>
            <div class="metric-value online-highlight">
              {{ modulesStore.onlineCount }} / {{ modulesStore.offlineCount }}
            </div>
            <div class="progress-bar">
              <div
                class="progress-fill success"
                :style="{ width: (modulesStore.onlineCount / modulesStore.totalCount * 100) + '%' }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 模块卡片网格 -->
      <div class="dashboard-section">
        <h2 class="section-title">服务模块</h2>
        <div class="grid grid-4 dashboard-grid">
          <ModuleCard
            v-for="mod in modulesStore.modules"
            :key="mod.id"
            :module="mod"
          />
        </div>
      </div>

      <!-- 最近记忆 -->
      <div class="dashboard-section">
        <h2 class="section-title">最近记忆</h2>
        <div class="grid grid-4 memory-grid">
          <div class="memory-card card">
            <div class="memory-label">总记忆数</div>
            <div class="memory-value">{{ memoryStats.total }}</div>
          </div>
          <div class="memory-card card">
            <div class="memory-label">沙滩记忆</div>
            <div class="memory-value">{{ memoryStats.beach }}</div>
          </div>
          <div class="memory-card card">
            <div class="memory-label">浅水记忆</div>
            <div class="memory-value">{{ memoryStats.shallow }}</div>
          </div>
          <div class="memory-card card">
            <div class="memory-label">深水记忆</div>
            <div class="memory-value">{{ memoryStats.deep }}</div>
          </div>
        </div>
      </div>

      <!-- 提示消息 -->
      <div v-if="toast" class="toast" :class="toast.type">
        {{ toast.message }}
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth.js'
import { useModulesStore } from '../stores/modules.js'
import { get, post } from '../api/index.js'
import MainLayout from '../layouts/MainLayout.vue'
import StatusBar from '../components/StatusBar.vue'
import ModuleCard from '../components/ModuleCard.vue'

const authStore = useAuthStore()
const modulesStore = useModulesStore()

// ---- 时钟 ----
const currentTime = ref('')
let clockTimer = null
function updateClock() {
  const now = new Date()
  currentTime.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}
function pad(n) { return String(n).padStart(2, '0') }

// ---- 问候语 ----
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

// ---- 系统指标 (M10) ----
const systemMetrics = reactive({ cpu: null, memory: null, disk: null })
const metricsLoading = ref(false)

async function fetchMetrics() {
  metricsLoading.value = true
  try {
    const data = await get('/api/v1/status/metrics')
    systemMetrics.cpu = data.cpu_percent ?? data.cpu ?? null
    systemMetrics.memory = data.memory_percent ?? data.memory ?? null
    systemMetrics.disk = data.disk_percent ?? data.disk ?? null
  } catch {
    // M10 不可用，保持 null
  } finally {
    metricsLoading.value = false
  }
}

// ---- 记忆统计 (M5) ----
const memoryStats = reactive({ total: 0, beach: 0, shallow: 0, deep: 0, abyss: 0 })

async function fetchMemoryStats() {
  try {
    const data = await get('/api/v1/memory/stats')
    memoryStats.total = data.total ?? data.count ?? 0
    memoryStats.beach = data.beach ?? data.beach_count ?? 0
    memoryStats.shallow = data.shallow ?? data.shallow_count ?? 0
    memoryStats.deep = data.deep ?? data.deep_count ?? 0
    memoryStats.abyss = data.abyss ?? data.abyss_count ?? 0
  } catch {
    // M5 不可用
  }
}

// ---- 快速操作 ----
const actionLoading = ref(false)

async function startAll() {
  actionLoading.value = true
  showToast('正在启动全部模块...', 'info')
  try {
    await post('/api/v1/modules/start-all')
    showToast('全部模块启动指令已发送', 'success')
    await modulesStore.fetchHealth()
  } catch (e) {
    showToast('启动失败: ' + e.message, 'error')
  } finally {
    actionLoading.value = false
  }
}

async function stopAll() {
  actionLoading.value = true
  showToast('正在停止全部模块...', 'info')
  try {
    await post('/api/v1/modules/stop-all')
    showToast('全部模块停止指令已发送', 'success')
    await modulesStore.fetchHealth()
  } catch (e) {
    showToast('停止失败: ' + e.message, 'error')
  } finally {
    actionLoading.value = false
  }
}

// ---- Toast ----
const toast = ref(null)
let toastTimer = null
function showToast(message, type = 'info') {
  toast.value = { message, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

// ---- 指标颜色辅助 ----
function metricColor(val) {
  if (val == null) return 'metric-na'
  if (val < 60) return 'metric-good'
  if (val < 85) return 'metric-warn'
  return 'metric-danger'
}
function metricBar(val) {
  if (val < 60) return 'success'
  if (val < 85) return 'warn'
  return 'danger'
}

// ---- 生命周期 ----
onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  fetchMetrics()
  fetchMemoryStats()
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

/* 快速操作 */
.quick-actions {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.quick-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: 0.9rem;
  cursor: pointer;
  transition: all var(--transition);
}

.quick-btn:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
}

.quick-btn.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}

.quick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.quick-icon {
  font-size: 1.1rem;
}

/* 指标卡片 */
.metrics-grid {
  grid-template-columns: repeat(4, 1fr);
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-label {
  font-size: 0.8rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 1.6rem;
  font-weight: 700;
}

.metric-good { color: var(--success); }
.metric-warn { color: var(--warning); }
.metric-danger { color: var(--danger); }
.metric-na { color: var(--text-muted); font-size: 1rem; }
.online-highlight { color: var(--accent); }

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

/* 记忆统计 */
.memory-grid {
  grid-template-columns: repeat(4, 1fr);
}

.memory-card {
  text-align: center;
}

.memory-label {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.memory-value {
  font-size: 1.8rem;
  font-weight: 700;
  color: var(--accent2);
}

/* 模块网格 */
.dashboard-grid {
  grid-template-columns: repeat(4, 1fr);
}

/* Toast */
.toast {
  position: fixed;
  top: 80px;
  right: 24px;
  padding: 12px 20px;
  border-radius: var(--radius);
  font-size: 0.85rem;
  z-index: 1000;
  animation: fadeIn 0.2s ease;
}

.toast.info { background: var(--accent); color: #0a1929; }
.toast.success { background: var(--success); color: #0a1929; }
.toast.error { background: var(--danger); color: #fff; }

/* 响应式 */
@media (max-width: 1200px) {
  .dashboard-grid,
  .metrics-grid,
  .memory-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .quick-actions { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 900px) {
  .dashboard-grid,
  .metrics-grid,
  .memory-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .dashboard-grid,
  .metrics-grid,
  .memory-grid {
    grid-template-columns: 1fr;
  }
  .quick-actions { grid-template-columns: 1fr; }
}
</style>
