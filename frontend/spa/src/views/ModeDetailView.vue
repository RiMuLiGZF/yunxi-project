<template>
  <MainLayout>
    <div class="mode-detail fade-in">
      <h1 class="page-title">模式详情</h1>
      <p class="page-subtitle">当前模式：{{ $route.params.mode }}</p>

      <div class="card detail-placeholder">
        <h2 class="card-title">模式配置</h2>
        <p class="card-placeholder">模式详情页面内容将在后续迭代中填充</p>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import MainLayout from '../layouts/MainLayout.vue'
</script>

<style scoped>
.detail-placeholder {
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
