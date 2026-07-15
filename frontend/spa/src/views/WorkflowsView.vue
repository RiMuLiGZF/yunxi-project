<template>
  <MainLayout>
    <div class="workflows-page fade-in">
      <h1 class="page-title">工作流</h1>
      <p class="page-subtitle">流程编排与任务调度管理</p>

      <div class="card workflows-placeholder">
        <h2 class="card-title">工作流列表</h2>
        <p class="card-placeholder">工作流管理页面内容将在后续迭代中填充</p>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import MainLayout from '../layouts/MainLayout.vue'
</script>

<style scoped>
.workflows-placeholder {
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
