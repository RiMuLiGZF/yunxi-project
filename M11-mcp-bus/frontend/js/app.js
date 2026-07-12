/**
 * ============================================================
 * M11 MCP Bus - 管理控制台主逻辑
 * ============================================================
 *
 * 整合 API 层和组件层，实现完整的控制台交互：
 * - 仪表盘统计数据加载与渲染
 * - 服务器列表加载与操作
 * - 最近调用记录加载
 * - 告警列表加载
 * - API Key 管理与鉴权
 * - 自动刷新功能
 * - 事件绑定
 */

(function () {
  "use strict";

  const API = window.MCP_API;
  const UI = window.UIComponents;

  // ============================================================
  // 应用状态
  // ============================================================

  const state = {
    isLoading: false,
    autoRefresh: true,
    refreshInterval: 30, // 秒
    refreshTimer: null,
    isAuthenticated: false,
  };

  // ============================================================
  // DOM 元素缓存
  // ============================================================

  const dom = {};

  function cacheDom() {
    // 顶部导航
    dom.apiKeyInput = document.getElementById("apiKeyInput");
    dom.apiKeyBtn = document.getElementById("apiKeyBtn");
    dom.statusDot = document.getElementById("statusDot");
    dom.statusText = document.getElementById("statusText");
    dom.refreshBtn = document.getElementById("refreshBtn");
    dom.autoRefreshToggle = document.getElementById("autoRefreshToggle");
    dom.refreshInterval = document.getElementById("refreshInterval");

    // 鉴权提示
    dom.authPrompt = document.getElementById("authPrompt");
    dom.authKeyInput = document.getElementById("authKeyInput");
    dom.authSubmitBtn = document.getElementById("authSubmitBtn");
    dom.dashboardContent = document.getElementById("dashboardContent");

    // 统计卡片
    dom.totalServers = document.getElementById("totalServers");
    dom.onlineServers = document.getElementById("onlineServers");
    dom.offlineServers = document.getElementById("offlineServers");
    dom.totalTools = document.getElementById("totalTools");
    dom.totalCalls = document.getElementById("totalCalls");
    dom.successRate = document.getElementById("successRate");
    dom.successFill = document.getElementById("successFill");
    dom.activeAlerts = document.getElementById("activeAlerts");
    dom.alertSub = document.getElementById("alertSub");

    // 告警面板
    dom.alertsPanel = document.getElementById("alertsPanel");
    dom.alertList = document.getElementById("alertList");
    dom.alertCount = document.getElementById("alertCount");

    // 服务器列表
    dom.serverList = document.getElementById("serverList");
    dom.refreshToolsBtn = document.getElementById("refreshToolsBtn");

    // 调用记录
    dom.callList = document.getElementById("callList");

    // 页脚
    dom.updateTime = document.getElementById("updateTime");
  }

  // ============================================================
  // 状态更新
  // ============================================================

  function setConnectionStatus(status, text) {
    if (!dom.statusDot || !dom.statusText) return;

    dom.statusDot.className = "status-dot";
    if (status === "online") {
      dom.statusDot.classList.add("");
    } else if (status === "offline") {
      dom.statusDot.classList.add("offline");
    } else if (status === "connecting") {
      dom.statusDot.classList.add("connecting");
    }

    dom.statusText.textContent = text;
  }

  function setRefreshing(isRefreshing) {
    if (!dom.refreshBtn) return;
    state.isLoading = isRefreshing;

    if (isRefreshing) {
      dom.refreshBtn.classList.add("loading");
      dom.refreshBtn.disabled = true;
    } else {
      dom.refreshBtn.classList.remove("loading");
      dom.refreshBtn.disabled = false;
    }
  }

  function showAuthPrompt() {
    state.isAuthenticated = false;
    if (dom.authPrompt) dom.authPrompt.style.display = "flex";
    if (dom.dashboardContent) dom.dashboardContent.style.display = "none";
    setConnectionStatus("offline", "未授权");
  }

  function hideAuthPrompt() {
    state.isAuthenticated = true;
    if (dom.authPrompt) dom.authPrompt.style.display = "none";
    if (dom.dashboardContent) dom.dashboardContent.style.display = "block";
    setConnectionStatus("online", "服务运行中");
  }

  // ============================================================
  // 数据加载与渲染
  // ============================================================

  /**
   * 加载统计数据
   */
  async function loadStats() {
    try {
      const data = await API.getStats();

      // 服务器统计
      UI.animateValue(dom.totalServers, data.total_servers || 0);
      dom.onlineServers.textContent = `${data.online_servers || 0} 在线`;
      dom.offlineServers.textContent = `${data.offline_servers || 0} 离线`;

      // 工具统计
      UI.animateValue(dom.totalTools, data.total_tools || 0);

      // 调用统计
      UI.animateValue(dom.totalCalls, data.total_calls || 0);
      const rate = data.success_rate != null ? Math.round(data.success_rate) : 0;
      dom.successRate.textContent = rate;

      // 成功率进度条
      const fill = dom.successFill;
      fill.style.width = rate + "%";
      fill.className = "success-fill";
      if (rate >= 95) {
        fill.classList.add("fill-high");
      } else if (rate >= 80) {
        fill.classList.add("fill-mid");
      } else {
        fill.classList.add("fill-low");
      }

      // 告警统计
      UI.animateValue(dom.activeAlerts, data.active_alerts || 0);
      const critical = data.critical_alerts || 0;
      const warning = data.warning_alerts || 0;
      if (data.active_alerts > 0) {
        if (critical > 0) {
          dom.alertSub.textContent = `${critical} 个严重告警`;
          dom.alertSub.className = "stat-sub text-danger";
        } else if (warning > 0) {
          dom.alertSub.textContent = `${warning} 个警告`;
          dom.alertSub.className = "stat-sub text-warning";
        } else {
          dom.alertSub.textContent = "有告警";
          dom.alertSub.className = "stat-sub text-info";
        }
      } else {
        dom.alertSub.textContent = "系统正常";
        dom.alertSub.className = "stat-sub";
      }

      // 渲染告警列表
      renderAlerts(data.alerts || []);

      return data;
    } catch (e) {
      console.error("[App] 加载统计数据失败:", e);
      throw e;
    }
  }

  /**
   * 渲染告警列表
   */
  function renderAlerts(alerts) {
    if (!dom.alertsPanel || !dom.alertList || !dom.alertCount) return;

    if (alerts.length === 0) {
      dom.alertsPanel.style.display = "none";
      return;
    }

    dom.alertsPanel.style.display = "block";
    dom.alertCount.textContent = alerts.length;
    dom.alertList.innerHTML = UI.renderAlertList(alerts.slice(0, 10));
  }

  /**
   * 加载服务器列表
   */
  async function loadServers() {
    if (!dom.serverList) return;

    try {
      const data = await API.getServers();
      const servers = data.servers || [];
      dom.serverList.innerHTML = UI.renderServerList(servers);
      return servers;
    } catch (e) {
      console.error("[App] 加载服务器列表失败:", e);
      dom.serverList.innerHTML = UI.renderError("加载失败：" + e.message);
      throw e;
    }
  }

  /**
   * 加载最近调用记录
   */
  async function loadRecentCalls() {
    if (!dom.callList) return;

    try {
      const data = await API.getRecentCalls(20);
      const calls = data.calls || [];
      dom.callList.innerHTML = UI.renderCallList(calls);
      return calls;
    } catch (e) {
      console.error("[App] 加载调用记录失败:", e);
      dom.callList.innerHTML = UI.renderError("加载失败：" + e.message);
      throw e;
    }
  }

  /**
   * 刷新所有数据
   */
  async function refreshAll() {
    if (state.isLoading) return;
    setRefreshing(true);

    try {
      await Promise.all([loadStats(), loadServers(), loadRecentCalls()]);

      // 更新最后更新时间
      if (dom.updateTime) {
        dom.updateTime.textContent =
          "更新于 " + new Date().toLocaleTimeString("zh-CN");
      }

      setConnectionStatus("online", "服务运行中");
    } catch (e) {
      if (e.status === 401) {
        showAuthPrompt();
      } else if (e.status === 0) {
        setConnectionStatus("offline", "连接失败");
      }
    } finally {
      setRefreshing(false);
    }
  }

  // ============================================================
  // 操作处理
  // ============================================================

  /**
   * 保存 API Key
   */
  function handleSaveApiKey() {
    const key = dom.apiKeyInput.value.trim();
    if (!key) {
      API.clearApiKey();
      UI.toast.info("已清除 API Key");
      showAuthPrompt();
      stopAutoRefresh();
      return;
    }

    API.saveApiKey(key);
    UI.toast.success("API Key 已保存");

    // 验证 Key 有效性
    validateAndRefresh(key);
  }

  /**
   * 验证 API Key 并刷新数据
   */
  async function validateAndRefresh(key) {
    try {
      setConnectionStatus("connecting", "验证中...");
      const isValid = await API.validateApiKey(key);
      if (isValid) {
        API.saveApiKey(key);
        hideAuthPrompt();
        startAutoRefresh();
        refreshAll();
      } else {
        showAuthPrompt();
        UI.toast.error("API Key 无效", "请检查您的 API Key 是否正确");
      }
    } catch (e) {
      console.error("[App] 验证 API Key 失败:", e);
      UI.toast.error("验证失败", e.message);
      // 网络错误时也尝试刷新（可能是开发环境无鉴权）
      if (e.status === 0) {
        setConnectionStatus("offline", "连接失败");
      }
    }
  }

  /**
   * 鉴权页面提交
   */
  function handleAuthSubmit() {
    const key = dom.authKeyInput.value.trim();
    if (!key) {
      UI.toast.warning("请输入 API Key");
      return;
    }

    // 同步到顶部输入框
    dom.apiKeyInput.value = key;
    validateAndRefresh(key);
  }

  /**
   * 刷新工具列表
   */
  async function handleRefreshTools() {
    if (!confirm("确定要刷新所有在线服务器的工具列表吗？")) return;

    try {
      dom.refreshToolsBtn.disabled = true;
      dom.refreshToolsBtn.textContent = "刷新中...";

      const result = await API.refreshTools(true);
      UI.toast.success("刷新完成", result.message || "工具列表已更新");
      refreshAll();
    } catch (e) {
      UI.toast.error("刷新失败", e.message);
    } finally {
      dom.refreshToolsBtn.disabled = false;
      dom.refreshToolsBtn.textContent = "刷新工具";
    }
  }

  /**
   * 删除服务器
   */
  async function deleteServer(id, name) {
    if (!confirm(`确定要删除服务器 "${name}" 吗？此操作不可恢复。`)) return;

    try {
      await API.deleteServer(id);
      UI.toast.success("删除成功", `服务器 "${name}" 已删除`);
      refreshAll();
    } catch (e) {
      UI.toast.error("删除失败", e.message);
    }
  }

  // ============================================================
  // 自动刷新
  // ============================================================

  function startAutoRefresh() {
    stopAutoRefresh();
    if (!state.autoRefresh || !state.isAuthenticated) return;

    const intervalMs = state.refreshInterval * 1000;
    state.refreshTimer = setInterval(() => {
      if (!state.isLoading) {
        refreshAll();
      }
    }, intervalMs);
  }

  function stopAutoRefresh() {
    if (state.refreshTimer) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
  }

  function toggleAutoRefresh(enabled) {
    state.autoRefresh = enabled;
    if (enabled) {
      startAutoRefresh();
      UI.toast.info("自动刷新已开启", `每 ${state.refreshInterval} 秒刷新一次`);
    } else {
      stopAutoRefresh();
      UI.toast.info("自动刷新已关闭");
    }
  }

  function setRefreshInterval(seconds) {
    state.refreshInterval = parseInt(seconds) || 30;
    if (state.autoRefresh && state.isAuthenticated) {
      startAutoRefresh();
    }
  }

  // ============================================================
  // 事件绑定
  // ============================================================

  function bindEvents() {
    // API Key 输入
    dom.apiKeyBtn.addEventListener("click", handleSaveApiKey);
    dom.apiKeyInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        handleSaveApiKey();
      }
    });

    // 鉴权页面
    dom.authSubmitBtn.addEventListener("click", handleAuthSubmit);
    dom.authKeyInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        handleAuthSubmit();
      }
    });

    // 刷新按钮
    dom.refreshBtn.addEventListener("click", refreshAll);

    // 刷新工具按钮
    dom.refreshToolsBtn.addEventListener("click", handleRefreshTools);

    // 自动刷新开关
    dom.autoRefreshToggle.addEventListener("change", (e) => {
      toggleAutoRefresh(e.target.checked);
    });

    // 刷新间隔选择
    dom.refreshInterval.addEventListener("change", (e) => {
      setRefreshInterval(e.target.value);
    });

    // 键盘快捷键
    document.addEventListener("keydown", (e) => {
      // R 键刷新（无输入框聚焦时）
      if (
        e.key === "r" &&
        !e.ctrlKey &&
        !e.metaKey &&
        document.activeElement.tagName !== "INPUT" &&
        document.activeElement.tagName !== "SELECT"
      ) {
        e.preventDefault();
        refreshAll();
      }
    });

    // 页面可见性变化（页面隐藏时暂停自动刷新，节省资源）
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopAutoRefresh();
      } else if (state.autoRefresh && state.isAuthenticated) {
        // 回到前台时立即刷新一次，然后恢复自动刷新
        refreshAll();
        startAutoRefresh();
      }
    });
  }

  // ============================================================
  // 初始化
  // ============================================================

  function init() {
    // 缓存 DOM
    cacheDom();

    // 绑定事件
    bindEvents();

    // 注册 401 回调
    API.onAuthRequired(() => {
      showAuthPrompt();
      stopAutoRefresh();
    });

    // 加载保存的 API Key 到输入框
    const savedKey = API.getApiKey();
    if (savedKey) {
      dom.apiKeyInput.value = savedKey;
    }

    // 恢复自动刷新设置
    const savedAutoRefresh = localStorage.getItem("m11_auto_refresh");
    if (savedAutoRefresh !== null) {
      state.autoRefresh = savedAutoRefresh === "true";
      dom.autoRefreshToggle.checked = state.autoRefresh;
    }

    const savedInterval = localStorage.getItem("m11_refresh_interval");
    if (savedInterval) {
      state.refreshInterval = parseInt(savedInterval) || 30;
      dom.refreshInterval.value = state.refreshInterval;
    }

    // 保存设置到 localStorage（当改变时）
    const originalToggle = dom.autoRefreshToggle.addEventListener.bind(
      dom.autoRefreshToggle
    );
    dom.autoRefreshToggle.addEventListener("change", () => {
      localStorage.setItem("m11_auto_refresh", state.autoRefresh);
    });
    dom.refreshInterval.addEventListener("change", () => {
      localStorage.setItem("m11_refresh_interval", state.refreshInterval);
    });

    // 初始状态
    setConnectionStatus("connecting", "连接中...");

    // 尝试加载数据（如果有 API Key 或开发环境）
    refreshAll();
  }

  // ============================================================
  // 暴露到全局（供 HTML 中的 onclick 等调用）
  // ============================================================

  window.MCP_App = {
    refreshAll,
    deleteServer,
    state,
  };

  // ============================================================
  // 启动
  // ============================================================

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
