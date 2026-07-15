<template>
  <MainLayout>
    <div class="marketplace fade-in">
      <!-- 顶部标题和统计 -->
      <div class="mp-header">
        <div>
          <h1 class="page-title">内容市场</h1>
          <p class="page-subtitle">发现并安装技能、模板和共享记忆</p>
        </div>
        <div v-if="stats" class="mp-stats">
          <div class="mp-stat-item">
            <span class="mp-stat-value">{{ stats.skills || 0 }}</span>
            <span class="mp-stat-label">技能</span>
          </div>
          <div class="mp-stat-item">
            <span class="mp-stat-value">{{ stats.templates || 0 }}</span>
            <span class="mp-stat-label">模板</span>
          </div>
          <div class="mp-stat-item">
            <span class="mp-stat-value">{{ stats.memories || 0 }}</span>
            <span class="mp-stat-label">记忆</span>
          </div>
        </div>
      </div>

      <!-- Tab 切换 -->
      <div class="mp-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="mp-tab"
          :class="{ active: activeTab === tab.key }"
          @click="switchTab(tab.key)"
        >
          {{ tab.label }}
          <span v-if="tab.count != null" class="mp-tab-count">{{ tab.count }}</span>
        </button>
      </div>

      <!-- 搜索和筛选 -->
      <div class="mp-toolbar">
        <div class="mp-search">
          <span class="mp-search-icon">&#128269;</span>
          <input
            v-model="searchText"
            type="text"
            class="mp-search-input"
            :placeholder="searchPlaceholder"
            @keyup.enter="handleSearch"
          />
        </div>
        <select v-model="selectedCategory" class="mp-select" @change="handleSearch">
          <option value="">全部分类</option>
          <option v-for="cat in currentCategories" :key="cat.id || cat" :value="cat.id || cat">
            {{ cat.name || cat }}
          </option>
        </select>
        <button class="mp-search-btn" @click="handleSearch">搜索</button>
      </div>

      <!-- 内容区域 -->
      <div class="mp-content">
        <!-- 加载状态 -->
        <div v-if="loading" class="mp-loading">
          <div class="mp-spinner"></div>
          <span>加载中...</span>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!currentList.length" class="mp-empty">
          <div class="mp-empty-icon">&#128230;</div>
          <p>{{ emptyText }}</p>
        </div>

        <!-- 卡片网格 -->
        <div v-else class="mp-grid">
          <div v-for="item in currentList" :key="item.id" class="mp-card card">
            <div class="mp-card-header">
              <h3 class="mp-card-title">{{ item.name || item.title }}</h3>
              <span v-if="item.version" class="mp-card-version">v{{ item.version }}</span>
            </div>
            <p class="mp-card-desc">{{ item.description || '暂无描述' }}</p>
            <div class="mp-card-meta">
              <span class="mp-card-author" v-if="item.author">&#128100; {{ item.author }}</span>
              <span class="mp-card-stat" v-if="item.downloads != null">&#11015; {{ formatNumber(item.downloads) }}</span>
              <span class="mp-card-stat" v-if="item.rating != null">&#9733; {{ item.rating }}</span>
            </div>
            <div v-if="item.tags && item.tags.length" class="mp-card-tags">
              <span v-for="tag in item.tags.slice(0, 4)" :key="tag" class="mp-tag">{{ tag }}</span>
            </div>
            <div class="mp-card-footer">
              <span class="mp-card-date" v-if="item.updated_at || item.created_at">
                {{ formatDate(item.updated_at || item.created_at) }}
              </span>
              <button
                class="mp-install-btn"
                :class="{ installed: item.installed, 'btn-loading': item._installing }"
                :disabled="item.installed || item._installing"
                @click="handleInstall(item)"
              >
                {{ item.installed ? '已安装' : (item._installing ? '安装中...' : '安装') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="toast" class="toast" :class="toast.type">
        {{ toast.message }}
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { get, post } from '../api/index.js'
import MainLayout from '../layouts/MainLayout.vue'

// ---- 服务基础地址 ----
const SERVICE_URLS = {
  skill: 'http://localhost:8002',
  template: 'http://localhost:8007',
  memory: 'http://localhost:8005',
}

// ---- Tab 定义 ----
const tabs = reactive([
  { key: 'skill', label: '技能市场', count: null },
  { key: 'template', label: '模板市场', count: null },
  { key: 'memory', label: '记忆共享', count: null },
])

const activeTab = ref('skill')
const loading = ref(false)
const searchText = ref('')
const selectedCategory = ref('')
const toast = ref(null)
let toastTimer = null

// ---- 各 Tab 数据 ----
const skillList = ref([])
const templateList = ref([])
const memoryList = ref([])
const skillCategories = ref([])
const templateCategories = ref([])
const memoryCategories = ref([])

// ---- 统计 ----
const stats = reactive({ skills: 0, templates: 0, memories: 0 })

// ---- 计算属性 ----
const currentList = computed(() => {
  if (activeTab.value === 'skill') return skillList.value
  if (activeTab.value === 'template') return templateList.value
  return memoryList.value
})

const currentCategories = computed(() => {
  if (activeTab.value === 'skill') return skillCategories.value
  if (activeTab.value === 'template') return templateCategories.value
  return memoryCategories.value
})

const searchPlaceholder = computed(() => {
  const map = {
    skill: '搜索技能...',
    template: '搜索模板...',
    memory: '搜索记忆...',
  }
  return map[activeTab.value]
})

const emptyText = computed(() => {
  if (searchText.value) return '没有找到匹配的结果'
  return '暂无内容'
})

// ---- Toast ----
function showToast(message, type = 'info') {
  toast.value = { message, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

// ---- 工具函数 ----
function formatNumber(num) {
  if (num >= 10000) return (num / 10000).toFixed(1) + 'w'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'k'
  return String(num)
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function pad(n) { return String(n).padStart(2, '0') }

// ---- Tab 切换 ----
function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  searchText.value = ''
  selectedCategory.value = ''
  fetchCurrentData()
}

// ---- 搜索 ----
let searchDebounce = null

function handleSearch() {
  if (searchDebounce) clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => {
    fetchCurrentData()
  }, 300)
}

// ---- 安装 ----
async function handleInstall(item) {
  item._installing = true
  try {
    let url = ''
    if (activeTab.value === 'skill') {
      url = `${SERVICE_URLS.skill}/api/v2/market/${item.id}/install`
    } else if (activeTab.value === 'template') {
      url = `${SERVICE_URLS.template}/api/v1/market/templates/${item.id}/install`
    } else {
      url = `${SERVICE_URLS.memory}/api/v1/memory/share/import/${item.id}`
    }
    await post(url)
    item.installed = true
    showToast('安装成功', 'success')
  } catch (e) {
    showToast('安装失败: ' + e.message, 'error')
  } finally {
    item._installing = false
  }
}

// ---- 数据获取 ----
async function fetchCurrentData() {
  loading.value = true
  try {
    if (activeTab.value === 'skill') await fetchSkills()
    else if (activeTab.value === 'template') await fetchTemplates()
    else await fetchMemories()
  } catch (e) {
    showToast('加载失败: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

// ---- 技能市场 ----
async function fetchSkills() {
  const base = SERVICE_URLS.skill
  try {
    if (searchText.value) {
      const data = await get(`${base}/api/v2/market/search`, { q: searchText.value, category: selectedCategory.value })
      skillList.value = normalizeList(data)
    } else {
      const data = await get(`${base}/api/v2/market/list`, { category: selectedCategory.value })
      skillList.value = normalizeList(data)
    }
    tabs[0].count = skillList.value.length
  } catch {
    skillList.value = []
    tabs[0].count = 0
  }
}

async function fetchSkillCategories() {
  try {
    const data = await get(`${SERVICE_URLS.skill}/api/v2/market/categories/list`)
    skillCategories.value = Array.isArray(data) ? data : (data?.items || data?.categories || [])
  } catch {
    skillCategories.value = []
  }
}

async function fetchSkillStats() {
  try {
    const data = await get(`${SERVICE_URLS.skill}/api/v2/market/stats/summary`)
    stats.skills = data?.total || data?.count || 0
  } catch {
    // 服务不可用
  }
}

// ---- 模板市场 ----
async function fetchTemplates() {
  const base = SERVICE_URLS.template
  try {
    if (searchText.value) {
      const data = await get(`${base}/api/v1/market/templates/search`, { q: searchText.value, category: selectedCategory.value })
      templateList.value = normalizeList(data)
    } else {
      const data = await get(`${base}/api/v1/market/templates`, { category: selectedCategory.value })
      templateList.value = normalizeList(data)
    }
    tabs[1].count = templateList.value.length
  } catch {
    templateList.value = []
    tabs[1].count = 0
  }
}

async function fetchTemplateCategories() {
  try {
    const data = await get(`${SERVICE_URLS.template}/api/v1/market/blocks`)
    templateCategories.value = Array.isArray(data) ? data : (data?.items || data?.categories || [])
  } catch {
    templateCategories.value = []
  }
}

async function fetchTemplateStats() {
  try {
    const data = await get(`${SERVICE_URLS.template}/api/v1/market/stats/summary`)
    stats.templates = data?.total || data?.count || 0
  } catch {
    // 服务不可用
  }
}

// ---- 记忆共享 ----
async function fetchMemories() {
  const base = SERVICE_URLS.memory
  try {
    if (searchText.value) {
      const data = await get(`${base}/api/v1/memory/share/search`, { q: searchText.value, category: selectedCategory.value })
      memoryList.value = normalizeList(data)
    } else {
      const data = await get(`${base}/api/v1/memory/share/pool`, { category: selectedCategory.value })
      memoryList.value = normalizeList(data)
    }
    tabs[2].count = memoryList.value.length
  } catch {
    memoryList.value = []
    tabs[2].count = 0
  }
}

async function fetchMemoryStats() {
  try {
    const data = await get(`${SERVICE_URLS.memory}/api/v1/memory/share/stats/summary`)
    stats.memories = data?.total || data?.count || 0
  } catch {
    // 服务不可用
  }
}

// ---- 列表数据标准化 ----
function normalizeList(data) {
  if (!data) return []
  if (Array.isArray(data)) return data
  if (data.items) return data.items
  if (data.list) return data.list
  if (data.data) return Array.isArray(data.data) ? data.data : []
  return []
}

// ---- 生命周期 ----
onMounted(() => {
  fetchCurrentData()
  // 并行加载分类和统计
  fetchSkillCategories()
  fetchSkillStats()
  fetchTemplateCategories()
  fetchTemplateStats()
  fetchMemoryStats()
})

onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer)
  if (searchDebounce) clearTimeout(searchDebounce)
})
</script>

<style scoped>
.marketplace {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ---- 顶部区域 ---- */
.mp-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.mp-stats {
  display: flex;
  gap: 24px;
}

.mp-stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.mp-stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent);
}

.mp-stat-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ---- Tab 切换 ---- */
.mp-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0;
}

.mp-tab {
  padding: 10px 20px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 8px;
}

.mp-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.mp-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}

.mp-tab-count {
  font-size: 0.7rem;
  background: var(--bg-hover);
  padding: 1px 6px;
  border-radius: 10px;
  color: var(--text-muted);
}

.mp-tab.active .mp-tab-count {
  background: rgba(56, 189, 248, 0.15);
  color: var(--accent);
}

/* ---- 搜索和筛选 ---- */
.mp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mp-search {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}

.mp-search-icon {
  position: absolute;
  left: 12px;
  color: var(--text-muted);
  font-size: 0.85rem;
  pointer-events: none;
}

.mp-search-input {
  width: 100%;
  padding: 10px 12px 10px 36px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: 0.9rem;
  transition: border-color var(--transition);
  box-sizing: border-box;
}

.mp-search-input:focus {
  outline: none;
  border-color: var(--accent);
}

.mp-search-input::placeholder {
  color: var(--text-muted);
}

.mp-select {
  padding: 10px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: 0.9rem;
  cursor: pointer;
  min-width: 140px;
}

.mp-select:focus {
  outline: none;
  border-color: var(--accent);
}

.mp-search-btn {
  padding: 10px 20px;
  background: var(--accent);
  color: #0a1929;
  border: none;
  border-radius: var(--radius);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity var(--transition);
  white-space: nowrap;
}

.mp-search-btn:hover {
  opacity: 0.85;
}

/* ---- 内容区域 ---- */
.mp-content {
  min-height: 300px;
}

/* ---- 加载状态 ---- */
.mp-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.mp-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: mp-spin 0.8s linear infinite;
}

@keyframes mp-spin {
  to { transform: rotate(360deg); }
}

/* ---- 空状态 ---- */
.mp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: var(--text-muted);
  gap: 12px;
}

.mp-empty-icon {
  font-size: 3rem;
  opacity: 0.5;
}

.mp-empty p {
  font-size: 0.95rem;
}

/* ---- 卡片网格 ---- */
.mp-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

/* ---- 卡片 ---- */
.mp-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
}

.mp-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mp-card-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mp-card-version {
  font-size: 0.7rem;
  color: var(--text-muted);
  background: var(--bg-hover);
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.mp-card-desc {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.5em;
}

.mp-card-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.78rem;
  color: var(--text-muted);
}

.mp-card-author {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mp-card-stat {
  white-space: nowrap;
}

/* ---- 标签 ---- */
.mp-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mp-tag {
  font-size: 0.7rem;
  padding: 2px 8px;
  background: rgba(56, 189, 248, 0.1);
  color: var(--accent);
  border-radius: 4px;
  white-space: nowrap;
}

/* ---- 卡片底部 ---- */
.mp-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.mp-card-date {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.mp-install-btn {
  padding: 6px 16px;
  background: var(--accent);
  color: #0a1929;
  border: none;
  border-radius: var(--radius);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.mp-install-btn:hover {
  opacity: 0.85;
}

.mp-install-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.mp-install-btn.installed {
  background: var(--bg-hover);
  color: var(--success);
  border: 1px solid var(--success);
}

.mp-install-btn.btn-loading {
  opacity: 0.7;
}

/* ---- Toast ---- */
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

/* ---- 响应式 ---- */
@media (max-width: 1200px) {
  .mp-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .mp-header {
    flex-direction: column;
    gap: 12px;
  }

  .mp-toolbar {
    flex-wrap: wrap;
  }

  .mp-search {
    flex-basis: 100%;
  }

  .mp-select {
    flex: 1;
  }

  .mp-grid {
    grid-template-columns: 1fr;
  }

  .mp-tabs {
    overflow-x: auto;
  }

  .mp-tab {
    padding: 8px 14px;
    font-size: 0.85rem;
    white-space: nowrap;
  }
}
</style>