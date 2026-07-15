<template>
  <MainLayout>
    <div class="module-detail fade-in">
      <template v-if="mod">
        <!-- 顶部信息 -->
        <div class="detail-header">
          <div class="header-top">
            <div>
              <h1 class="page-title">{{ mod.name }}</h1>
              <p class="page-subtitle">{{ mod.description }}</p>
            </div>
            <div class="header-actions">
              <span class="badge" :class="statusBadge">{{ statusLabel(mod.status) }}</span>
              <span class="meta-item">
                <strong>ID:</strong> {{ mod.id.toUpperCase() }}
              </span>
              <span class="meta-item">
                <strong>端口:</strong> <code>:{{ mod.port }}</code>
              </span>
            </div>
          </div>
        </div>

        <!-- 功能区：模块简介 -->
        <div class="card detail-card">
          <h2 class="card-title">模块简介</h2>
          <div class="card-body">
            <p>{{ mod.description }}</p>
            <div class="meta-grid">
              <div class="meta-card">
                <div class="meta-card-label">模块 ID</div>
                <div class="meta-card-value">{{ mod.id.toUpperCase() }}</div>
              </div>
              <div class="meta-card">
                <div class="meta-card-label">服务端口</div>
                <div class="meta-card-value">:{{ mod.port }}</div>
              </div>
              <div class="meta-card">
                <div class="meta-card-label">当前状态</div>
                <div class="meta-card-value">
                  <span class="status-dot" :class="mod.status"></span>
                  {{ statusLabel(mod.status) }}
                </div>
              </div>
              <div class="meta-card">
                <div class="meta-card-label">最后检测</div>
                <div class="meta-card-value">{{ lastCheckTime }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 状态区：实时健康检查 -->
        <div class="card detail-card">
          <h2 class="card-title">
            实时健康检查
            <button class="btn btn-sm" @click="runHealthCheck">
              {{ healthLoading ? '检测中...' : '立即检测' }}
            </button>
          </h2>
          <div v-if="healthResult" class="health-result" :class="healthResult.ok ? 'health-ok' : 'health-fail'">
            <div class="health-status-icon">
              {{ healthResult.ok ? '&#10004;' : '&#10008;' }}
            </div>
            <div class="health-info">
              <div class="health-label">
                {{ healthResult.ok ? '服务正常' : '服务不可达' }}
              </div>
              <div class="health-detail" v-if="healthResult.responseTime">
                响应时间: {{ healthResult.responseTime }}ms
              </div>
              <div class="health-detail" v-if="healthResult.error">
                错误: {{ healthResult.error }}
              </div>
            </div>
          </div>
          <div v-else-if="healthLoading" class="health-loading">
            <span class="skeleton-text">正在检测模块健康状态...</span>
          </div>
          <div v-else class="health-placeholder">
            点击"立即检测"按钮进行健康检查
          </div>
        </div>

        <!-- 操作区 -->
        <div class="card detail-card">
          <h2 class="card-title">操作</h2>
          <div class="action-grid">
            <button class="btn" @click="handleRestart">
              &#8634; 重启模块
            </button>
            <a :href="`http://localhost:${mod.port}/docs`" target="_blank" class="btn">
              &#9783; API 文档
            </a>
            <button class="btn" disabled>
              &#128221; 查看日志
            </button>
          </div>
        </div>

        <!-- M4 场景列表 -->
        <div v-if="mod.id === 'm4'" class="card detail-card">
          <h2 class="card-title">
            场景列表
            <button class="btn btn-sm" @click="fetchModes">
              {{ modesLoading ? '加载中...' : '刷新' }}
            </button>
          </h2>
          <div v-if="modes.length" class="modes-list">
            <div v-for="mode in modes" :key="mode.id || mode.name" class="mode-item card">
              <div class="mode-name">{{ mode.name || mode.id }}</div>
              <div class="mode-desc">{{ mode.description || '无描述' }}</div>
              <router-link :to="`/modes/${mode.id || mode.name}`" class="btn btn-sm">
                查看详情
              </router-link>
            </div>
          </div>
          <div v-else-if="modesLoading" class="loading-placeholder">
            <span class="skeleton-text">加载场景列表...</span>
          </div>
          <div v-else class="empty-placeholder">
            暂无场景数据，请确保 M4 服务已启动
          </div>
        </div>
      </template>

      <template v-else>
        <h1 class="page-title">模块未找到</h1>
        <p class="page-subtitle">无法找到 ID 为 {{ $route.params.id }} 的模块</p>
      </template>

      <!-- 提示消息 -->
      <div v-if="toast" class="toast" :class="toast.type">
        {{ toast.message }}
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModulesStore } from '../stores/modules.js'
import { get, post } from '../api/index.js'
import MainLayout from '../layouts/MainLayout.vue'

const route = useRoute()
const router = useRouter()
const modulesStore = useModulesStore()

const mod = computed(() => modulesStore.getModuleById(route.params.id))

const statusLabel = (s) => ({ online: '在线', offline: '离线', unknown: '未知' }[s] || '未知')
const statusBadge = computed(() => {
  const map = { online: 'badge-success', offline: 'badge-danger', unknown: 'badge-warning' }
  return map[mod.value?.status] || 'badge-warning'
})

const lastCheckTime = computed(() => {
  if (!mod.value?.lastCheck) return '尚未检测'
  const d = new Date(mod.value.lastCheck)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})

function pad(n) { return String(n).padStart(2, '0') }

// ---- 健康检查 ----
const healthLoading = ref(false)
const healthResult = ref(null)

async function runHealthCheck() {
  if (!mod.value) return
  healthLoading.value = true
  healthResult.value = null

  const start = Date.now()
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000)
    await fetch(`http://localhost:${mod.value.port}/health`, {
      method: 'GET',
      signal: controller.signal,
    })
    clearTimeout(timeoutId)
    healthResult.value = { ok: true, responseTime: Date.now() - start }
  } catch (e) {
    healthResult.value = {
      ok: false,
      responseTime: Date.now() - start,
      error: e.name === 'AbortError' ? '连接超时 (5s)' : e.message,
    }
  } finally {
    healthLoading.value = false
  }
}

// ---- M4 场景列表 ----
const modes = ref([])
const modesLoading = ref(false)

async function fetchModes() {
  modesLoading.value = true
  try {
    const data = await get('/m4/api/v1/modes')
    modes.value = Array.isArray(data) ? data : data.items || data.modes || []
  } catch {
    modes.value = []
  } finally {
    modesLoading.value = false
  }
}

// ---- 操作 ----
const toast = ref(null)
let toastTimer = null

async function handleRestart() {
  if (!mod.value) return
  showToast(`正在重启 ${mod.value.name}...`, 'info')
  try {
    await post(`/api/v1/modules/${mod.value.id}/restart`)
    showToast(`${mod.value.name} 重启指令已发送`, 'success')
    await modulesStore.fetchHealth()
  } catch (e) {
    showToast(`重启失败: ${e.message}`, 'error')
  }
}

function showToast(message, type = 'info') {
  toast.value = { message, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

onMounted(() => {
  if (mod.value?.id === 'm4') {
    fetchModes()
  }
})
</script>

<style scoped>
.module-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-header {
  margin-bottom: 8px;
}

.header-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.meta-item {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.meta-item strong {
  color: var(--text-primary);
}

.detail-card {
  margin-bottom: 0;
}

.card-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-body p {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin-bottom: 16px;
}

/* 模块简介元数据 */
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.meta-card {
  padding: 12px;
  background: var(--bg-primary);
  border-radius: var(--radius);
}

.meta-card-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.meta-card-value {
  font-size: 0.9rem;
  color: var(--text-primary);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 健康检查 */
.health-result {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: var(--radius);
}

.health-ok {
  background: rgba(52, 211, 153, 0.08);
  border: 1px solid rgba(52, 211, 153, 0.2);
}

.health-fail {
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.2);
}

.health-status-icon {
  font-size: 1.5rem;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  flex-shrink: 0;
}

.health-ok .health-status-icon {
  color: var(--success);
  background: rgba(52, 211, 153, 0.15);
}

.health-fail .health-status-icon {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.15);
}

.health-label {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.health-detail {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-top: 2px;
}

.health-loading,
.health-placeholder,
.empty-placeholder,
.loading-placeholder {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.skeleton-text {
  animation: pulse 1.5s infinite;
}

/* 操作区 */
.action-grid {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

/* M4 场景列表 */
.modes-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.mode-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mode-name {
  font-weight: 600;
  color: var(--text-primary);
}

.mode-desc {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

code {
  color: var(--accent);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85rem;
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
@media (max-width: 900px) {
  .header-top { flex-direction: column; }
  .header-actions { flex-wrap: wrap; }
  .meta-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .meta-grid { grid-template-columns: 1fr; }
}
</style>
