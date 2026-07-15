<template>
  <MainLayout>
    <div class="settings-page fade-in">
      <h1 class="page-title">设置</h1>
      <p class="page-subtitle">系统配置与个性化设置</p>

      <div class="card settings-placeholder">
        <h2 class="card-title">全局设置</h2>
        <p class="card-placeholder">设置页面内容将在后续迭代中填充</p>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import MainLayout from '../layouts/MainLayout.vue'
</script>

<style scoped>
.settings-placeholder {
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
