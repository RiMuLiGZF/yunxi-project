/**
 * 云汐统一前端 SPA — 模块状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { get } from '../api/index.js'

/**
 * 13 个微服务模块定义
 */
const MODULE_DEFINITIONS = [
  { id: 'm0',  name: 'API 网关',    port: 8000, description: '统一入口，路由分发与鉴权' },
  { id: 'm1',  name: '认证中心',    port: 8001, description: '用户认证与权限管理' },
  { id: 'm2',  name: '配置中心',    port: 8002, description: '动态配置与特性开关' },
  { id: 'm3',  name: '数据引擎',    port: 8003, description: '数据采集、清洗与持久化' },
  { id: 'm4',  name: '场景引擎',    port: 8004, description: '智能场景识别与触发' },
  { id: 'm5',  name: '消息队列',    port: 8005, description: '异步消息传递与事件驱动' },
  { id: 'm6',  name: '文件服务',    port: 8006, description: '文件上传、存储与分发' },
  { id: 'm7',  name: '积木平台',    port: 8007, description: '可视化模块搭建与编排' },
  { id: 'm8',  name: '智能代理',    port: 8008, description: 'LLM 集成与智能调度' },
  { id: 'm9',  name: '监控中心',    port: 8009, description: '系统监控与告警聚合' },
  { id: 'm10', name: '审计日志',    port: 8010, description: '操作审计与合规追踪' },
  { id: 'm11', name: '工作流引擎',  port: 8011, description: '流程编排与任务调度' },
  { id: 'm12', name: '用户界面',    port: 8012, description: '前端资源与 SSR 渲染' },
]

export const useModulesStore = defineStore('modules', () => {
  // ---- 状态 ----
  const modules = ref(
    MODULE_DEFINITIONS.map((m) => ({
      ...m,
      status: 'unknown', // 'online' | 'offline' | 'unknown'
      lastCheck: null,
    }))
  )

  let pollTimer = null

  // ---- 计算属性 ----
  const onlineCount = computed(() =>
    modules.value.filter((m) => m.status === 'online').length
  )

  const offlineCount = computed(() =>
    modules.value.filter((m) => m.status === 'offline').length
  )

  const totalCount = computed(() => modules.value.length)

  // ---- 方法 ----

  /**
   * 检测单个模块健康状态
   */
  async function checkModuleHealth(mod) {
    try {
      // 通过模块服务端口进行健康检测
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 3000)

      await fetch(`http://localhost:${mod.port}/health`, {
        method: 'GET',
        mode: 'no-cors',
        signal: controller.signal,
      })

      clearTimeout(timeoutId)
      mod.status = 'online'
    } catch {
      mod.status = 'offline'
    }
    mod.lastCheck = new Date()
  }

  /**
   * 轮询所有模块健康状态
   */
  async function fetchHealth() {
    const checks = modules.value.map((mod) => checkModuleHealth(mod))
    await Promise.allSettled(checks)
  }

  /**
   * 启动自动轮询（每 30 秒）
   */
  function startPolling() {
    stopPolling()
    fetchHealth() // 立即执行一次
    pollTimer = setInterval(fetchHealth, 30000)
  }

  /**
   * 停止自动轮询
   */
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /**
   * 根据 id 获取模块
   */
  function getModuleById(id) {
    return modules.value.find((m) => m.id === id)
  }

  return {
    modules,
    onlineCount,
    offlineCount,
    totalCount,
    fetchHealth,
    startPolling,
    stopPolling,
    getModuleById,
  }
})
