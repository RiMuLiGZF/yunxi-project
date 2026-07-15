<template>
  <MainLayout>
    <div class="audit-page fade-in">
      <h1 class="page-title">审计日志</h1>
      <p class="page-subtitle">操作审计与合规追踪记录</p>

      <div class="card audit-placeholder">
        <h2 class="card-title">日志列表</h2>
        <p class="card-placeholder">审计日志页面内容将在后续迭代中填充</p>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import MainLayout from '../layouts/MainLayout.vue'
</script>

<style scoped>
.audit-placeholder {
  padding: 48px 24px;
}

.card-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.card-placeholder {
  color: var(--text-muted);
  font-size: 0.85rem;
}
</style>
