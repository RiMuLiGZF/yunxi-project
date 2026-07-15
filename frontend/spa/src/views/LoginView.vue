<template>
  <div class="login-page">
    <div class="login-card card fade-in">
      <div class="login-header">
        <div class="login-logo">Y</div>
        <h1 class="login-title">云汐</h1>
        <p class="login-subtitle">统一管理平台</p>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label">用户名</label>
          <input
            v-model="username"
            type="text"
            class="input"
            placeholder="请输入用户名"
            autocomplete="username"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">密码</label>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="请输入密码"
            autocomplete="current-password"
            required
          />
        </div>
        <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>
        <button type="submit" class="btn btn-primary btn-block login-btn" :disabled="loading">
          <span v-if="loading" class="pulse">登录中...</span>
          <span v-else>登 录</span>
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  errorMsg.value = ''
  loading.value = true

  const result = await authStore.login(username.value, password.value)

  loading.value = false

  if (result.success) {
    router.push('/dashboard')
  } else {
    errorMsg.value = result.message || '登录失败，请检查用户名和密码'
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  background-image:
    radial-gradient(ellipse at 20% 50%, rgba(56, 189, 248, 0.05) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 50%, rgba(129, 140, 248, 0.05) 0%, transparent 50%);
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 40px 32px;
  background: var(--bg-card);
  border: 1px solid var(--border);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-logo {
  width: 56px;
  height: 56px;
  margin: 0 auto 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  color: #0a1929;
  font-weight: 800;
  font-size: 1.5rem;
  border-radius: 14px;
}

.login-title {
  font-size: 1.6rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.login-subtitle {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 0.85rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.form-error {
  color: var(--danger);
  font-size: 0.8rem;
  text-align: center;
}

.login-btn {
  margin-top: 8px;
  padding: 12px;
  font-size: 1rem;
}
</style>
