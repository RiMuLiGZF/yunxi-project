<template>
  <div class="status-bar card">
    <div class="status-summary">
      <span class="status-text">
        <span class="status-count online-count">{{ modulesStore.onlineCount }}</span>
        <span class="status-sep">/</span>
        <span class="status-count total-count">{{ modulesStore.totalCount }}</span>
        <span class="status-label"> 模块在线</span>
      </span>
    </div>
    <div class="status-dots">
      <span
        v-for="mod in modulesStore.modules"
        :key="mod.id"
        class="status-dot-item"
        :class="mod.status"
        :title="`${mod.name}: ${statusText(mod.status)}`"
      ></span>
    </div>
    <div v-if="lastRefresh" class="status-refresh">
      {{ lastRefresh }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useModulesStore } from '../stores/modules.js'

const modulesStore = useModulesStore()
const lastRefresh = ref('')

function statusText(status) {
  const map = { online: '在线', offline: '离线', unknown: '未知' }
  return map[status] || '未知'
}

function updateTime() {
  if (modulesStore.modules[0]?.lastCheck) {
    const d = new Date(modulesStore.modules[0].lastCheck)
    lastRefresh.value = `更新于 ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`
  }
}

let timer = null
onMounted(() => {
  modulesStore.startPolling()
  timer = setInterval(updateTime, 5000)
})

onUnmounted(() => {
  modulesStore.stopPolling()
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
}

.status-summary {
  display: flex;
  align-items: center;
}

.status-count {
  font-weight: 700;
  font-size: 1.1rem;
}

.online-count {
  color: var(--success);
}

.total-count {
  color: var(--text-secondary);
}

.status-sep {
  color: var(--text-muted);
  margin: 0 2px;
}

.status-label {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.status-dots {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot-item {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.status-dot-item.online {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

.status-dot-item.offline {
  background: var(--danger);
  box-shadow: 0 0 6px var(--danger);
}

.status-dot-item.unknown {
  background: var(--text-muted);
}

.status-refresh {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-muted);
}
</style>
