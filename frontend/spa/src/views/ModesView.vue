<template>
  <MainLayout>
    <div class="modes-page fade-in">
      <div class="modes-header">
        <div>
          <h1 class="page-title">场景引擎</h1>
          <p class="page-subtitle">管理和配置智能场景识别与触发规则</p>
        </div>
        <button class="btn btn-sm" :disabled="loading" @click="fetchModes">
          {{ loading ? '加载中...' : '刷新场景' }}
        </button>
      </div>

      <!-- 场景卡片网格 -->
      <div class="grid grid-4 modes-grid">
        <div
          v-for="mode in modesList"
          :key="mode.id"
          class="mode-card card"
          @click="$router.push(`/modes/${mode.id}`)"
        >
          <div class="mode-icon">{{ mode.icon }}</div>
          <div class="mode-info">
            <h3 class="mode-name">{{ mode.name }}</h3>
            <p class="mode-desc">{{ mode.description }}</p>
          </div>
          <div class="mode-footer">
            <span class="mode-tag">{{ mode.id }}</span>
            <span class="mode-arrow">&#8250;</span>
          </div>
        </div>
      </div>

      <!-- 加载中骨架屏 -->
      <div v-if="loading && modesList.length === 0" class="grid grid-4 modes-grid">
        <div v-for="i in 8" :key="'skel-' + i" class="mode-card card skeleton-card">
          <div class="skeleton-block skeleton-icon"></div>
          <div class="skeleton-block skeleton-text-long"></div>
          <div class="skeleton-block skeleton-text-short"></div>
        </div>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { get } from '../api/index.js'
import MainLayout from '../layouts/MainLayout.vue'

const loading = ref(false)
const remoteModes = ref([])
const error = ref(null)

// 8 个默认场景定义
const defaultModes = [
  { id: 'work',       name: '工作开发', description: '专注工作与开发环境，优化生产力',       icon: '&#128187;' },
  { id: 'study',      name: '学习规划', description: '制定学习计划，管理知识体系',           icon: '&#128218;' },
  { id: 'review',     name: '复盘总结', description: '定期回顾与总结，提炼经验教训',           icon: '&#128221;' },
  { id: 'social',     name: '人际关系', description: '维护社交网络，管理人际关系',             icon: '&#129309;' },
  { id: 'emotion',    name: '情感陪伴', description: '情感支持与陪伴，心理健康关怀',           icon: '&#10084;' },
  { id: 'life',       name: '生活管理', description: '日常生活事务管理与规划',                 icon: '&#127968;' },
  { id: 'appearance', name: '形象工坊', description: '个人形象设计与穿搭建议',                 icon: '&#128087;' },
  { id: 'growth',     name: '成长中心', description: '个人成长路径规划与跟踪',               icon: '&#127793;' },
]

const modesList = computed(() => {
  if (remoteModes.value.length === 0) return defaultModes
  // 合并远程数据与默认数据：以远程为准，补充默认数据中没有的
  const remoteIds = new Set(remoteModes.value.map((m) => m.id || m.name))
  const merged = remoteModes.value.map((m) => {
    const id = m.id || m.name
    const def = defaultModes.find((d) => d.id === id)
    return {
      id,
      name: m.name || def?.name || id,
      description: m.description || def?.description || '',
      icon: def?.icon || '&#9670;',
    }
  })
  // 补充远程数据中没有的默认场景
  defaultModes.forEach((d) => {
    if (!remoteIds.has(d.id)) {
      merged.push({ ...d })
    }
  })
  return merged
})

async function fetchModes() {
  loading.value = true
  error.value = null
  try {
    const data = await get('/m4/api/v1/modes')
    remoteModes.value = Array.isArray(data) ? data : data.items || data.modes || []
  } catch {
    // M4 不可用，使用默认数据
    remoteModes.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchModes()
})
</script>

<style scoped>
.modes-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.modes-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

/* 场景卡片 */
.modes-grid {
  grid-template-columns: repeat(4, 1fr);
}

.mode-card {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px 20px;
  transition: all var(--transition);
}

.mode-card:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: 0 8px 28px rgba(56, 189, 248, 0.12);
}

.mode-icon {
  font-size: 2.2rem;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(56, 189, 248, 0.08);
  border-radius: var(--radius-lg);
  flex-shrink: 0;
}

.mode-info {
  flex: 1;
}

.mode-name {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.mode-desc {
  font-size: 0.8rem;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mode-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mode-tag {
  font-size: 0.7rem;
  color: var(--text-muted);
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
}

.mode-arrow {
  font-size: 1.2rem;
  color: var(--text-muted);
  transition: color var(--transition), transform var(--transition);
}

.mode-card:hover .mode-arrow {
  color: var(--accent);
  transform: translateX(4px);
}

/* 骨架屏 */
.skeleton-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px 20px;
}

.skeleton-block {
  border-radius: 4px;
  background: var(--bg-hover);
  animation: pulse 1.5s infinite;
}

.skeleton-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
}

.skeleton-text-long {
  height: 16px;
  width: 80%;
}

.skeleton-text-short {
  height: 12px;
  width: 60%;
}

/* 响应式 */
@media (max-width: 1200px) {
  .modes-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 900px) {
  .modes-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .modes-grid { grid-template-columns: 1fr; }
}
</style>
