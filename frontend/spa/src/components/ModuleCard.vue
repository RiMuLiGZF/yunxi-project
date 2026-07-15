<template>
  <div class="module-card card" @click="goDetail">
    <div class="module-header">
      <span class="module-name">{{ module.name }}</span>
      <span class="status-dot" :class="module.status"></span>
    </div>
    <div class="module-body">
      <div class="module-port">
        <span class="port-label">端口</span>
        <span class="port-value">:{{ module.port }}</span>
      </div>
      <div class="module-desc">{{ module.description }}</div>
    </div>
    <div class="module-footer">
      <span class="badge" :class="statusBadgeClass">{{ statusLabel }}</span>
      <span class="module-id">{{ module.id.toUpperCase() }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  module: {
    type: Object,
    required: true,
  },
})

const router = useRouter()

const statusLabel = computed(() => {
  const map = { online: '在线', offline: '离线', unknown: '未知' }
  return map[props.module.status] || '未知'
})

const statusBadgeClass = computed(() => {
  const map = { online: 'badge-success', offline: 'badge-danger', unknown: 'badge-warning' }
  return map[props.module.status] || 'badge-warning'
})

function goDetail() {
  router.push(`/modules/${props.module.id}`)
}
</script>

<style scoped>
.module-card {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.module-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 6px 24px rgba(56, 189, 248, 0.1);
}

.module-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.module-name {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
}

.module-body {
  flex: 1;
}

.module-port {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.port-label {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.port-value {
  font-size: 0.9rem;
  color: var(--accent);
  font-family: 'Courier New', monospace;
}

.module-desc {
  font-size: 0.8rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

.module-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.module-id {
  font-size: 0.7rem;
  color: var(--text-muted);
  font-family: 'Courier New', monospace;
}
</style>
