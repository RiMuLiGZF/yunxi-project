<template>
  <MainLayout>
    <div class="modules-page fade-in">
      <h1 class="page-title">模块管理</h1>
      <p class="page-subtitle">查看和管理所有微服务模块的运行状态</p>

      <!-- 顶部工具栏 -->
      <div class="toolbar">
        <div class="toolbar-left">
          <div class="search-wrapper">
            <input
              v-model="searchQuery"
              type="text"
              class="input search-input"
              placeholder="搜索模块名称或 ID..."
            />
          </div>
          <div class="filter-group">
            <button
              v-for="f in filters"
              :key="f.value"
              class="filter-btn"
              :class="{ active: activeFilter === f.value }"
              @click="activeFilter = f.value"
            >
              {{ f.label }}
            </button>
          </div>
        </div>
        <div class="toolbar-right">
          <span class="module-count">
            共 {{ filteredModules.length }} 个模块
          </span>
        </div>
      </div>

      <!-- 模块列表 -->
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>端口</th>
              <th>状态</th>
              <th>功能描述</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="mod in filteredModules"
              :key="mod.id"
              class="clickable-row"
              @click="$router.push(`/modules/${mod.id}`)"
            >
              <td><code>{{ mod.id.toUpperCase() }}</code></td>
              <td><strong>{{ mod.name }}</strong></td>
              <td><code>:{{ mod.port }}</code></td>
              <td>
                <span class="status-dot" :class="mod.status"></span>
                <span class="status-text">{{ statusLabel(mod.status) }}</span>
              </td>
              <td class="desc-cell">{{ mod.description }}</td>
              <td>
                <div class="action-btns" @click.stop>
                  <router-link :to="`/modules/${mod.id}`" class="btn btn-sm">详情</router-link>
                  <button class="btn btn-sm" @click="handleRestart(mod)">重启</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 无结果 -->
      <div v-if="filteredModules.length === 0" class="empty-state">
        <span class="empty-icon">&#128269;</span>
        <p>没有找到匹配的模块</p>
      </div>

      <!-- 提示消息 -->
      <div v-if="toast" class="toast" :class="toast.type">
        {{ toast.message }}
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useModulesStore } from '../stores/modules.js'
import { post } from '../api/index.js'
import MainLayout from '../layouts/MainLayout.vue'

const modulesStore = useModulesStore()

const searchQuery = ref('')
const activeFilter = ref('all')
const toast = ref(null)
let toastTimer = null

const filters = [
  { label: '全部', value: 'all' },
  { label: '在线', value: 'online' },
  { label: '离线', value: 'offline' },
]

const filteredModules = computed(() => {
  let list = modulesStore.modules

  // 状态过滤
  if (activeFilter.value !== 'all') {
    list = list.filter((m) => m.status === activeFilter.value)
  }

  // 搜索过滤
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q)
    )
  }

  return list
})

function statusLabel(status) {
  const map = { online: '在线', offline: '离线', unknown: '未知' }
  return map[status] || '未知'
}

async function handleRestart(mod) {
  showToast(`正在重启 ${mod.name}...`, 'info')
  try {
    await post(`/api/v1/modules/${mod.id}/restart`)
    showToast(`${mod.name} 重启指令已发送`, 'success')
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
</script>

<style scoped>
.modules-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.toolbar-right {
  flex-shrink: 0;
}

.search-wrapper {
  flex: 1;
  max-width: 320px;
}

.search-input {
  width: 100%;
}

.filter-group {
  display: flex;
  gap: 4px;
}

.filter-btn {
  padding: 6px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-secondary);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all var(--transition);
}

.filter-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.filter-btn.active {
  background: rgba(56, 189, 248, 0.12);
  border-color: var(--accent);
  color: var(--accent);
}

.module-count {
  font-size: 0.8rem;
  color: var(--text-muted);
}

/* 表格增强 */
.clickable-row {
  cursor: pointer;
}

.status-dot {
  margin-right: 6px;
}

.status-text {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.desc-cell {
  color: var(--text-secondary);
  font-size: 0.85rem;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-btns {
  display: flex;
  gap: 6px;
}

code {
  color: var(--accent);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85rem;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 2.5rem;
  display: block;
  margin-bottom: 8px;
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
@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-left {
    flex-direction: column;
  }

  .search-wrapper {
    max-width: 100%;
  }
}
</style>
