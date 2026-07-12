/**
 * ============================================================
 * M11 MCP Bus - API 调用封装层
 * ============================================================
 *
 * 封装所有与后端的数据交互，统一处理：
 * - API Key 鉴权（从 localStorage 读取，自动加入请求头）
 * - 401 未授权处理（显示登录提示）
 * - 统一错误处理与 Toast 通知
 * - 请求超时控制
 *
 * 所有 API 方法返回 Promise，调用方使用 async/await 处理。
 */

const MCP_API = (function () {
  "use strict";

  // ---------- 常量配置 ----------
  const STORAGE_KEY = "m11_mcp_bus_api_key";
  const API_BASE = "/api/console";
  const ADMIN_API_BASE = "/api/admin";
  const REQUEST_TIMEOUT = 15000; // 15 秒超时

  // ---------- 内部状态 ----------
  let _apiKey = "";
  let _onAuthRequired = null; // 401 回调

  // ============================================================
  // API Key 管理
  // ============================================================

  /**
   * 从 localStorage 加载保存的 API Key
   * @returns {string} 保存的 API Key，没有则返回空字符串
   */
  function loadApiKey() {
    try {
      _apiKey = localStorage.getItem(STORAGE_KEY) || "";
    } catch (e) {
      console.warn("[API] 读取 localStorage 失败:", e);
      _apiKey = "";
    }
    return _apiKey;
  }

  /**
   * 保存 API Key 到 localStorage
   * @param {string} key - API Key 值
   */
  function saveApiKey(key) {
    _apiKey = key || "";
    try {
      if (_apiKey) {
        localStorage.setItem(STORAGE_KEY, _apiKey);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch (e) {
      console.warn("[API] 写入 localStorage 失败:", e);
    }
  }

  /**
   * 清除保存的 API Key
   */
  function clearApiKey() {
    _apiKey = "";
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      console.warn("[API] 清除 localStorage 失败:", e);
    }
  }

  /**
   * 获取当前 API Key
   * @returns {string}
   */
  function getApiKey() {
    return _apiKey;
  }

  /**
   * 检查是否已配置 API Key
   * @returns {boolean}
   */
  function hasApiKey() {
    return _apiKey && _apiKey.length > 0;
  }

  /**
   * 设置 401 回调函数
   * @param {Function} callback - 当收到 401 时调用
   */
  function onAuthRequired(callback) {
    _onAuthRequired = callback;
  }

  // ============================================================
  // 底层请求方法
  // ============================================================

  /**
   * 带超时的 fetch 请求
   * @param {string} url - 请求 URL
   * @param {Object} options - fetch 选项
   * @returns {Promise<Response>}
   */
  function _fetchWithTimeout(url, options) {
    return Promise.race([
      fetch(url, options),
      new Promise((_, reject) =>
        setTimeout(() => {
          reject(new Error("请求超时，请检查网络连接"));
        }, REQUEST_TIMEOUT)
      ),
    ]);
  }

  /**
   * 构建请求头（自动加入 API Key）
   * @param {Object} extraHeaders - 额外请求头
   * @returns {Object} 完整的请求头对象
   */
  function _buildHeaders(extraHeaders = {}) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...extraHeaders,
    };

    if (_apiKey) {
      headers["X-API-Key"] = _apiKey;
    }

    return headers;
  }

  /**
   * 统一请求方法
   * @param {string} url - 请求 URL
   * @param {Object} options - 请求选项
   * @returns {Promise<any>} 解析后的 JSON 数据
   * @throws {Error} 请求失败时抛出错误
   */
  async function _request(url, options = {}) {
    const fullOptions = {
      ...options,
      headers: _buildHeaders(options.headers),
    };

    try {
      const response = await _fetchWithTimeout(url, fullOptions);

      // 401 未授权
      if (response.status === 401) {
        if (_onAuthRequired) {
          _onAuthRequired();
        }
        const err = new Error("未授权：请提供有效的 API Key");
        err.status = 401;
        throw err;
      }

      // 429 速率限制
      if (response.status === 429) {
        const retryAfter = response.headers.get("Retry-After") || "60";
        const err = new Error(`请求过于频繁，请在 ${retryAfter} 秒后重试`);
        err.status = 429;
        throw err;
      }

      // 其他错误状态码
      if (!response.ok) {
        let errorMsg = `请求失败 (${response.status})`;
        try {
          const data = await response.json();
          if (data.detail) {
            errorMsg = data.detail;
          } else if (data.message) {
            errorMsg = data.message;
          }
        } catch (e) {
          // 忽略 JSON 解析错误
        }
        const err = new Error(errorMsg);
        err.status = response.status;
        throw err;
      }

      // 解析响应
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return await response.json();
      }
      return await response.text();
    } catch (error) {
      // 网络错误
      if (error.message === "Failed to fetch" || error.name === "TypeError") {
        const networkErr = new Error("网络连接失败，请检查服务是否正常运行");
        networkErr.status = 0;
        throw networkErr;
      }
      throw error;
    }
  }

  // ============================================================
  // 控制台数据 API
  // ============================================================

  /**
   * 获取控制台统计数据
   * @returns {Promise<Object>} 统计数据对象
   *  - total_servers, online_servers, offline_servers
   *  - total_tools
   *  - total_calls, success_rate, avg_duration_ms
   *  - active_alerts, critical_alerts, warning_alerts, alerts
   *  - popular_tools
   */
  async function getStats() {
    return _request(`${API_BASE}/stats`, {
      method: "GET",
    });
  }

  /**
   * 获取服务器列表
   * @returns {Promise<Object>} { servers: [], total: number }
   */
  async function getServers() {
    return _request(`${API_BASE}/servers`, {
      method: "GET",
    });
  }

  /**
   * 获取最近调用记录
   * @param {number} limit - 返回数量，默认 20
   * @returns {Promise<Object>} { calls: [], total: number }
   */
  async function getRecentCalls(limit = 20) {
    const url = `${API_BASE}/recent-calls?limit=${encodeURIComponent(limit)}`;
    return _request(url, {
      method: "GET",
    });
  }

  // ============================================================
  // 管理操作 API
  // ============================================================

  /**
   * 刷新所有服务器的工具列表
   * @param {boolean} force - 是否强制刷新
   * @returns {Promise<Object>}
   */
  async function refreshTools(force = false) {
    return _request(`${ADMIN_API_BASE}/tools/refresh`, {
      method: "POST",
      body: JSON.stringify({ force }),
    });
  }

  /**
   * 删除服务器
   * @param {number|string} serverId - 服务器 ID
   * @returns {Promise<Object>}
   */
  async function deleteServer(serverId) {
    return _request(`${ADMIN_API_BASE}/servers/${serverId}`, {
      method: "DELETE",
    });
  }

  // ============================================================
  // 工具函数
  // ============================================================

  /**
   * 验证 API Key 是否有效（通过调用一个轻量接口）
   * @param {string} key - 要验证的 API Key
   * @returns {Promise<boolean>} 是否有效
   */
  async function validateApiKey(key) {
    const savedKey = _apiKey;
    _apiKey = key;
    try {
      await getStats();
      return true;
    } catch (e) {
      if (e.status === 401) {
        return false;
      }
      // 其他错误（如网络错误）也视为无效验证
      throw e;
    } finally {
      _apiKey = savedKey;
    }
  }

  // ============================================================
  // 初始化
  // ============================================================
  loadApiKey();

  // ============================================================
  // 公开 API
  // ============================================================
  return {
    // API Key 管理
    loadApiKey,
    saveApiKey,
    clearApiKey,
    getApiKey,
    hasApiKey,
    onAuthRequired,
    validateApiKey,

    // 数据接口
    getStats,
    getServers,
    getRecentCalls,

    // 管理操作
    refreshTools,
    deleteServer,
  };
})();

// 暴露到全局
window.MCP_API = MCP_API;
