<template>
  <div class="main-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <!-- Logo 区域 -->
      <div class="sidebar-logo">
        <span class="logo-icon">Y</span>
        <span v-if="!sidebarCollapsed" class="logo-text">云汐</span>
      </div>

      <!-- 导航菜单 -->
      <nav class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <div v-if="!sidebarCollapsed" class="nav-group-label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: isActive(item.path) }"
            :title="item.label"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span v-if="!sidebarCollapsed" class="nav-label">{{ item.label }}</span>
          </router-link>
        </div>
      </nav>

      <!-- 折叠按钮 -->
      <div class="sidebar-toggle" @click="toggleSidebar">
        <span v-if="sidebarCollapsed">&#9654;</span>
        <span v-else>&#9664;</span>
      </div>

      <!-- 底部用户信息 -->
      <div class="sidebar-footer">
        <div class="user-info">
          <span class="user-avatar">{{ userInitial }}</span>
          <span v-if="!sidebarCollapsed" class="user-name">{{ authStore.username || '用户' }}</span>
        </div>
        <button v-if="!sidebarCollapsed" class="btn btn-sm logout-btn" @click="handleLogout">
          退出
        </button>
      </div>
    </aside>

    <!-- 主内容区域 -->
    <div class="main-content" :class="{ expanded: sidebarCollapsed }">
      <!-- 顶部栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <!-- 面包屑 -->
          <div class="breadcrumb">
            <router-link to="/dashboard" class="breadcrumb-item">首页</router-link>
            <template v-if="currentRoute.name && currentRoute.name !== 'Dashboard'">
              <span class="breadcrumb-sep">/</span>
              <span class="breadcrumb-item current">{{ currentRoute.meta?.title || currentRoute.name }}</span>
            </template>
          </div>
        </div>

        <div class="topbar-right">
          <!-- 搜索框 -->
          <div class="search-box">
            <input type="text" class="input search-input" placeholder="搜索..." />
          </div>

          <!-- 通知 -->
          <button class="topbar-icon-btn" title="通知">
            <span class="bell-icon">&#128276;</span>
          </button>

          <!-- 用户（移动端） -->
          <span class="topbar-user">{{ authStore.username || '用户' }}</span>
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="content-area">
        <slot />
        <router-view v-if="!$slots.default" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 侧边栏折叠状态，从 localStorage 恢复
const sidebarCollapsed = ref(localStorage.getItem('yunxi_sidebar_collapsed') === 'true')

// 当前路由
const currentRoute = computed(() => route)

// 用户名首字母
const userInitial = computed(() => {
  const name = authStore.username || 'U'
  return name.charAt(0).toUpperCase()
})

// 导航分组
const navGroups = [
  {
    label: '概览',
    items: [
      { path: '/dashboard', label: 'Dashboard', icon: '&#9632;' },
    ],
  },
  {
    label: '业务',
    items: [
      { path: '/modes', label: '场景引擎', icon: '&#9670;' },
      { path: '/modules', label: '积木平台', icon: '&#9881;' },
      { path: '/workflows', label: '工作流', icon: '&#8634;' },
    ],
  },
  {
    label: '管理',
    items: [
      { path: '/modules', label: '模块管理', icon: '&#9776;' },
      { path: '/monitor', label: '系统监控', icon: '&#9673;' },
      { path: '/audit', label: '审计日志', icon: '&#9998;' },
      { path: '/settings', label: '设置', icon: '&#9881;' },
    ],
  },
  {
    label: '文档',
    items: [
      { path: '/api-docs', label: 'API 文档', icon: '&#9783;' },
    ],
  },
]

/**
 * 判断导航项是否激活
 */
function isActive(path) {
  return route.path === path || route.path.startsWith(path + '/')
}

/**
 * 切换侧边栏折叠
 */
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('yunxi_sidebar_collapsed', String(sidebarCollapsed.value))
}

/**
 * 退出登录
 */
function handleLogout() {
  authStore.logout()
  router.push('/login')
}

onMounted(() => {
  // 为路由设置中文标题
  const titleMap = {
    Dashboard: '仪表盘',
    Modules: '模块管理',
    ModuleDetail: '模块详情',
    Modes: '场景引擎',
    ModeDetail: '模式详情',
    Workflows: '工作流',
    Monitor: '系统监控',
    Audit: '审计日志',
    Settings: '设置',
    ApiDocs: 'API 文档',
  }
  // 通过路由 meta 传递标题
  route.meta = route.meta || {}
  if (!route.meta.title && titleMap[route.name]) {
    route.meta.title = titleMap[route.name]
  }
})
</script>

<style scoped>
.main-layout {
  display: flex;
  min-height: 100vh;
}

/* ---- 侧边栏 ---- */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 240px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 100;
  overflow: hidden;
}

.sidebar.collapsed {
  width: 64px;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border);
  min-height: 56px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  color: #0a1929;
  font-weight: 700;
  font-size: 1.1rem;
  border-radius: 8px;
  flex-shrink: 0;
}

.logo-text {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
}

/* ---- 导航菜单 ---- */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.nav-group {
  margin-bottom: 4px;
}

.nav-group-label {
  padding: 8px 16px 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.nav-item:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.nav-item.active {
  color: var(--accent);
  background: rgba(56, 189, 248, 0.08);
  border-right: 3px solid var(--accent);
}

.collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
}

.nav-icon {
  font-size: 1rem;
  width: 20px;
  text-align: center;
  flex-shrink: 0;
}

.nav-label {
  font-size: 0.9rem;
}

/* ---- 折叠按钮 ---- */
.sidebar-toggle {
  padding: 10px;
  border-top: 1px solid var(--border);
  text-align: center;
  cursor: pointer;
  color: var(--text-secondary);
  transition: color 0.15s ease;
}

.sidebar-toggle:hover {
  color: var(--text-primary);
}

/* ---- 侧边栏底部 ---- */
.sidebar-footer {
  border-top: 1px solid var(--border);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent2);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 600;
  flex-shrink: 0;
}

.user-name {
  font-size: 0.85rem;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  padding: 4px 10px;
  font-size: 0.75rem;
  border-color: var(--danger);
  color: var(--danger);
  background: transparent;
}

.logout-btn:hover {
  background: rgba(248, 113, 113, 0.1);
}

/* ---- 主内容区域 ---- */
.main-content {
  margin-left: 240px;
  flex: 1;
  transition: margin-left 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.main-content.expanded {
  margin-left: 64px;
}

/* ---- 顶部栏 ---- */
.topbar {
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 50;
}

.topbar-left {
  display: flex;
  align-items: center;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* ---- 面包屑 ---- */
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
}

.breadcrumb-item {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.breadcrumb-item.current {
  color: var(--text-primary);
}

.breadcrumb-sep {
  color: var(--text-muted);
  font-size: 0.8rem;
}

/* ---- 搜索框 ---- */
.search-box {
  display: flex;
  align-items: center;
}

.search-input {
  width: 200px;
  padding: 6px 12px;
  font-size: 0.85rem;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  transition: width 0.2s ease, border-color var(--transition);
}

.search-input:focus {
  width: 260px;
  border-color: var(--accent);
}

/* ---- 顶部栏图标按钮 ---- */
.topbar-icon-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  font-size: 1.1rem;
  transition: color 0.15s ease;
}

.topbar-icon-btn:hover {
  color: var(--accent);
}

.topbar-user {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

/* ---- 内容区域 ---- */
.content-area {
  flex: 1;
  padding: 24px;
  background: var(--bg-primary);
}

/* ---- 响应式 ---- */
@media (max-width: 768px) {
  .sidebar {
    width: 0;
    border-right: none;
  }

  .sidebar.collapsed {
    width: 0;
  }

  .main-content {
    margin-left: 0;
  }

  .main-content.expanded {
    margin-left: 0;
  }

  .search-input {
    width: 120px;
  }

  .search-input:focus {
    width: 160px;
  }

  .topbar-user {
    display: none;
  }
}
</style>
