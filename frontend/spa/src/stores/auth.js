/**
 * 云汐统一前端 SPA — 认证状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { post } from '../api/index.js'

export const useAuthStore = defineStore('auth', () => {
  // ---- 状态 ----
  const token = ref(localStorage.getItem('yunxi_token') || '')
  const username = ref(localStorage.getItem('yunxi_user') || '')
  const role = ref(localStorage.getItem('yunxi_role') || '')

  // ---- 计算属性 ----
  const isAuthenticated = computed(() => !!token.value)

  // ---- 方法 ----

  /**
   * 登录
   * @param {string} user - 用户名
   * @param {string} password - 密码
   */
  async function login(user, password) {
    try {
      const data = await post('/api/auth/login', { username: user, password })
      token.value = data.token || data.access_token || ''
      username.value = data.username || user
      role.value = data.role || 'user'

      // 持久化
      localStorage.setItem('yunxi_token', token.value)
      localStorage.setItem('yunxi_user', username.value)
      localStorage.setItem('yunxi_role', role.value)

      return { success: true }
    } catch (error) {
      return { success: false, message: error.message }
    }
  }

  /**
   * 退出登录
   */
  function logout() {
    token.value = ''
    username.value = ''
    role.value = ''
    localStorage.removeItem('yunxi_token')
    localStorage.removeItem('yunxi_user')
    localStorage.removeItem('yunxi_role')
  }

  return {
    token,
    username,
    role,
    isAuthenticated,
    login,
    logout,
  }
})
