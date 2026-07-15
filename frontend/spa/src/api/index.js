/**
 * 云汐统一前端 SPA — 统一 HTTP 客户端
 * 基于 fetch 封装，自动附加 Authorization header
 */

const BASE_URL = ''

/**
 * 获取存储的 token
 */
function getToken() {
  return localStorage.getItem('yunxi_token') || ''
}

/**
 * 统一请求封装
 * @param {string} url - 请求路径（相对于 baseURL）
 * @param {RequestInit} options - fetch 选项
 * @returns {Promise<any>}
 */
async function request(url, options = {}) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`

  const response = await fetch(fullUrl, {
    ...options,
    headers,
  })

  // 401 未授权 → 跳转登录
  if (response.status === 401) {
    localStorage.removeItem('yunxi_token')
    localStorage.removeItem('yunxi_user')
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    throw new Error('认证已过期，请重新登录')
  }

  // 非成功状态码抛出错误
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    let message = `请求失败 (${response.status})`
    try {
      const json = JSON.parse(body)
      message = json.detail || json.message || message
    } catch {
      if (body) message = body
    }
    const error = new Error(message)
    error.status = response.status
    throw error
  }

  // 204 No Content
  if (response.status === 204) {
    return null
  }

  return response.json()
}

/* ---- 快捷方法 ---- */

export function get(url, params) {
  let queryString = ''
  if (params) {
    const searchParams = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.append(key, value)
      }
    })
    queryString = searchParams.toString()
  }
  const fullUrl = queryString ? `${url}?${queryString}` : url
  return request(fullUrl)
}

export function post(url, data) {
  return request(url, {
    method: 'POST',
    body: data ? JSON.stringify(data) : undefined,
  })
}

export function put(url, data) {
  return request(url, {
    method: 'PUT',
    body: data ? JSON.stringify(data) : undefined,
  })
}

export function del(url) {
  return request(url, { method: 'DELETE' })
}

export default { get, post, put, del }
