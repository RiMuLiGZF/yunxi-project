<template>
  <MainLayout>
    <div class="api-docs-page fade-in">
      <div class="docs-header">
        <div>
          <h1 class="page-title">API 文档</h1>
          <p class="page-subtitle">云汐统一平台 OpenAPI 接口文档</p>
        </div>
        <div class="docs-actions">
          <input
            v-model="searchQuery"
            type="text"
            class="input search-input"
            placeholder="搜索端点..."
          />
          <button class="btn btn-sm" :disabled="loading" @click="fetchAll">
            {{ loading ? '加载中...' : '刷新全部' }}
          </button>
        </div>
      </div>

      <div class="docs-layout">
        <!-- 左侧模块列表 -->
        <aside class="docs-sidebar" :class="{ collapsed: sidebarCollapsed }">
          <div class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed">
            {{ sidebarCollapsed ? '&#9654;' : '&#9664;' }}
          </div>
          <div v-if="!sidebarCollapsed" class="sidebar-content">
            <div class="sidebar-title">模块列表</div>
            <div
              v-for="mod in moduleList"
              :key="mod.id"
              class="sidebar-item"
              :class="{ active: selectedModule === mod.id }"
              @click="selectedModule = mod.id"
            >
              <span class="sidebar-status-dot" :class="mod.status"></span>
              <span class="sidebar-item-name">{{ mod.name }}</span>
              <span class="sidebar-item-id">{{ mod.id.toUpperCase() }}</span>
            </div>
          </div>
          <div v-else class="sidebar-collapsed-icons">
            <div
              v-for="mod in moduleList"
              :key="mod.id"
              class="collapsed-icon-item"
              :class="{ active: selectedModule === mod.id }"
              :title="mod.name"
              @click="selectedModule = mod.id; sidebarCollapsed = false"
            >
              <span class="sidebar-status-dot" :class="mod.status"></span>
            </div>
          </div>
        </aside>

        <!-- 右侧 API 端点列表 -->
        <div class="docs-content">
          <template v-if="loading && !endpoints.length">
            <div class="loading-state">
              <span class="skeleton-text">正在加载 API 文档...</span>
            </div>
          </template>

          <template v-else-if="selectedModule && endpoints.length">
            <div class="content-header">
              <h2 class="content-title">
                {{ currentModuleName }}
                <span class="content-badge">:{{ currentModulePort }}</span>
              </h2>
              <span class="endpoint-count">{{ filteredEndpoints.length }} 个端点</span>
            </div>

            <div class="endpoints-list">
              <div
                v-for="(ep, index) in filteredEndpoints"
                :key="index"
                class="endpoint-item card"
              >
                <div class="endpoint-header">
                  <span class="method-tag" :class="methodClass(ep.method)">
                    {{ ep.method }}
                  </span>
                  <code class="endpoint-path">{{ ep.path }}</code>
                </div>
                <div class="endpoint-summary">{{ ep.summary }}</div>
                <div v-if="ep.tags && ep.tags.length" class="endpoint-tags">
                  <span v-for="tag in ep.tags" :key="tag" class="endpoint-tag">{{ tag }}</span>
                </div>
              </div>
            </div>

            <div v-if="filteredEndpoints.length === 0" class="empty-state">
              <p>没有匹配的端点</p>
            </div>
          </template>

          <template v-else-if="selectedModule && !endpoints.length">
            <div class="empty-state">
              <span class="empty-icon">&#128196;</span>
              <p>该模块暂无 API 文档数据</p>
              <p class="empty-hint">请确保模块已启动并提供了 /openapi.json 接口</p>
            </div>
          </template>

          <template v-else>
            <div class="empty-state">
              <span class="empty-icon">&#128218;</span>
              <p>请从左侧选择一个模块查看 API 文档</p>
            </div>
          </template>
        </div>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useModulesStore } from '../stores/modules.js'
import MainLayout from '../layouts/MainLayout.vue'

const modulesStore = useModulesStore()

const loading = ref(false)
const sidebarCollapsed = ref(false)
const searchQuery = ref('')
const selectedModule = ref(null)

// 模块 OpenAPI 数据缓存：{ moduleId: { endpoints: [...], error: string | null } }
const moduleData = ref({})

const moduleList = computed(() => modulesStore.modules)

const currentModuleName = computed(() => {
  const mod = modulesStore.getModuleById(selectedModule.value)
  return mod?.name || selectedModule.value || ''
})

const currentModulePort = computed(() => {
  const mod = modulesStore.getModuleById(selectedModule.value)
  return mod?.port || ''
})

const endpoints = computed(() => {
  if (!selectedModule.value) return []
  return moduleData.value[selectedModule.value]?.endpoints || []
})

const filteredEndpoints = computed(() => {
  const list = endpoints.value
  if (!searchQuery.value.trim()) return list
  const q = searchQuery.value.trim().toLowerCase()
  return list.filter(
    (ep) =>
      ep.path.toLowerCase().includes(q) ||
      ep.summary.toLowerCase().includes(q) ||
      ep.method.toLowerCase().includes(q) ||
      (ep.tags && ep.tags.some((t) => t.toLowerCase().includes(q)))
  )
})

function methodClass(method) {
  const m = (method || '').toUpperCase()
  if (m === 'GET') return 'method-get'
  if (m === 'POST') return 'method-post'
  if (m === 'PUT') return 'method-put'
  if (m === 'DELETE') return 'method-delete'
  if (m === 'PATCH') return 'method-patch'
  return 'method-other'
}

/**
 * 从 OpenAPI JSON 中提取端点列表
 */
function parseOpenAPI(spec) {
  const results = []
  const paths = spec.paths || {}

  for (const [path, methods] of Object.entries(paths)) {
    for (const [method, detail] of Object.entries(methods)) {
      if (['get', 'post', 'put', 'delete', 'patch', 'head', 'options'].includes(method)) {
        results.push({
          method: method.toUpperCase(),
          path,
          summary: detail.summary || detail.description || '',
          tags: detail.tags || [],
        })
      }
    }
  }

  return results
}

/**
 * 并发 fetch 所有模块的 /openapi.json
 */
async function fetchAll() {
  loading.value = true
  const promises = modulesStore.modules.map(async (mod) => {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 5000)
      const resp = await fetch(`http://localhost:${mod.port}/openapi.json`, {
        signal: controller.signal,
      })
      clearTimeout(timeoutId)
      const spec = await resp.json()
      moduleData.value[mod.id] = {
        endpoints: parseOpenAPI(spec),
        error: null,
      }
    } catch (e) {
      moduleData.value[mod.id] = {
        endpoints: [],
        error: e.name === 'AbortError' ? '连接超时' : '不可达',
      }
    }
  })

  await Promise.allSettled(promises)
  loading.value = false

  // 默认选中第一个有数据的模块
  if (!selectedModule.value) {
    const firstWithData = modulesStore.modules.find(
      (m) => moduleData.value[m.id]?.endpoints?.length > 0
    )
    if (firstWithData) {
      selectedModule.value = firstWithData.id
    } else if (modulesStore.modules.length) {
      selectedModule.value = modulesStore.modules[0].id
    }
  }
}

onMounted(() => {
  fetchAll()
})
</script>

<style scoped>
.api-docs-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-height: calc(100vh - var(--topbar-height) - 48px);
}

.docs-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.docs-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input {
  width: 260px;
}

/* 文档布局 */
.docs-layout {
  display: flex;
  gap: 0;
  flex: 1;
  min-height: 0;
}

/* 侧边栏 */
.docs-sidebar {
  width: 240px;
  min-width: 240px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: width var(--transition), min-width var(--transition);
  display: flex;
  flex-direction: column;
}

.docs-sidebar.collapsed {
  width: 56px;
  min-width: 56px;
}

.sidebar-toggle {
  padding: 10px;
  text-align: center;
  cursor: pointer;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  font-size: 0.85rem;
  transition: color var(--transition);
}

.sidebar-toggle:hover {
  color: var(--text-primary);
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.sidebar-title {
  padding: 8px 16px 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sidebar-item:hover {
  background: var(--bg-hover);
}

.sidebar-item.active {
  background: rgba(56, 189, 248, 0.08);
  border-right: 3px solid var(--accent);
}

.sidebar-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sidebar-status-dot.online {
  background: var(--success);
  box-shadow: 0 0 4px var(--success);
}

.sidebar-status-dot.offline {
  background: var(--danger);
}

.sidebar-status-dot.unknown {
  background: var(--text-muted);
}

.sidebar-item-name {
  font-size: 0.85rem;
  color: var(--text-primary);
  flex: 1;
}

.sidebar-item-id {
  font-size: 0.65rem;
  color: var(--text-muted);
  font-family: 'Courier New', monospace;
}

.collapsed-collapsed-icons {
  padding: 8px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.collapsed-icon-item {
  width: 40px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s ease;
}

.collapsed-icon-item:hover {
  background: var(--bg-hover);
}

.collapsed-icon-item.active {
  background: rgba(56, 189, 248, 0.08);
}

/* 右侧内容 */
.docs-content {
  flex: 1;
  margin-left: 16px;
  overflow-y: auto;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.content-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.content-badge {
  font-size: 0.85rem;
  color: var(--accent);
  font-weight: 400;
}

.endpoint-count {
  font-size: 0.8rem;
  color: var(--text-muted);
}

/* 端点列表 */
.endpoints-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.endpoint-item {
  padding: 14px 16px;
}

.endpoint-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.method-tag {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  min-width: 56px;
  text-align: center;
}

.method-get { background: rgba(52, 211, 153, 0.15); color: var(--success); }
.method-post { background: rgba(56, 189, 248, 0.15); color: var(--accent); }
.method-put { background: rgba(251, 191, 36, 0.15); color: var(--warning); }
.method-delete { background: rgba(248, 113, 113, 0.15); color: var(--danger); }
.method-patch { background: rgba(129, 140, 248, 0.15); color: var(--accent2); }
.method-other { background: rgba(100, 116, 139, 0.15); color: var(--text-secondary); }

.endpoint-path {
  font-size: 0.85rem;
  color: var(--text-primary);
  word-break: break-all;
}

.endpoint-summary {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.endpoint-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.endpoint-tag {
  font-size: 0.65rem;
  color: var(--text-muted);
  background: var(--bg-primary);
  padding: 1px 6px;
  border-radius: 3px;
}

/* 加载和空状态 */
.loading-state,
.empty-state {
  text-align: center;
  padding: 64px 24px;
  color: var(--text-muted);
}

.skeleton-text {
  animation: pulse 1.5s infinite;
}

.empty-icon {
  font-size: 2.5rem;
  display: block;
  margin-bottom: 8px;
}

.empty-hint {
  font-size: 0.8rem;
  margin-top: 4px;
}

/* 响应式 */
@media (max-width: 768px) {
  .docs-header {
    flex-direction: column;
    gap: 12px;
  }

  .docs-actions {
    flex-wrap: wrap;
  }

  .search-input {
    width: 100%;
  }

  .docs-layout {
    flex-direction: column;
  }

  .docs-sidebar {
    width: 100% !important;
    min-width: 0 !important;
    border-radius: var(--radius-lg);
    margin-bottom: 12px;
  }

  .docs-sidebar.collapsed {
    max-height: 56px;
  }

  .docs-content {
    margin-left: 0;
  }
}
</style>
