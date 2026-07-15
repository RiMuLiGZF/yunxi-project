/**
 * 云汐统一前端 SPA — 路由配置
 */
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { auth: true },
  },
  {
    path: '/modules',
    name: 'Modules',
    component: () => import('../views/ModulesView.vue'),
    meta: { auth: true },
  },
  {
    path: '/modules/:id',
    name: 'ModuleDetail',
    component: () => import('../views/ModuleDetailView.vue'),
    meta: { auth: true },
  },
  {
    path: '/modes',
    name: 'Modes',
    component: () => import('../views/ModesView.vue'),
    meta: { auth: true },
  },
  {
    path: '/modes/:mode',
    name: 'ModeDetail',
    component: () => import('../views/ModeDetailView.vue'),
    meta: { auth: true },
  },
  {
    path: '/workflows',
    name: 'Workflows',
    component: () => import('../views/WorkflowsView.vue'),
    meta: { auth: true },
  },
  {
    path: '/monitor',
    name: 'Monitor',
    component: () => import('../views/MonitorView.vue'),
    meta: { auth: true },
  },
  {
    path: '/audit',
    name: 'Audit',
    component: () => import('../views/AuditView.vue'),
    meta: { auth: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/SettingsView.vue'),
    meta: { auth: true },
  },
  {
    path: '/marketplace',
    name: 'Marketplace',
    component: () => import('../views/MarketplaceView.vue'),
    meta: { auth: true, title: '内容市场' },
  },
  {
    path: '/api-docs',
    name: 'ApiDocs',
    component: () => import('../views/ApiDocsView.vue'),
    meta: { auth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

/**
 * 路由守卫：检查 localStorage.yunxi_token，无则跳转 /login
 */
router.beforeEach((to, from, next) => {
  if (to.meta.auth) {
    const token = localStorage.getItem('yunxi_token')
    if (!token) {
      next({ name: 'Login' })
      return
    }
  }
  next()
})

export default router
