/**
 * ============================================================
 * M11 MCP Bus - 组件渲染模块
 * ============================================================
 *
 * 提供 UI 组件的渲染函数和通用工具：
 * - 时间格式化工具
 * - 时长格式化工具
 * - Toast 通知系统
 * - 服务器列表项渲染
 * - 调用记录项渲染
 * - 告警项渲染
 * - 空状态 / 加载状态 / 错误状态渲染
 */

const UIComponents = (function () {
  "use strict";

  // ============================================================
  // 工具函数
  // ============================================================

  /**
   * 格式化相对时间
   * @param {string|null} isoStr - ISO 格式时间字符串
   * @returns {string} 相对时间描述（如 "3 分钟前"）
   */
  function formatRelativeTime(isoStr) {
    if (!isoStr) return "从未";

    const date = new Date(isoStr);
    if (isNaN(date.getTime())) return "未知";

    const now = new Date();
    const diffMs = now - date;
    const diffSeconds = Math.floor(diffMs / 1000);

    if (diffSeconds < 0) return "刚刚";
    if (diffSeconds < 60) return `${diffSeconds} 秒前`;

    const diffMinutes = Math.floor(diffSeconds / 60);
    if (diffMinutes < 60) return `${diffMinutes} 分钟前`;

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} 小时前`;

    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 30) return `${diffDays} 天前`;

    const diffMonths = Math.floor(diffDays / 30);
    if (diffMonths < 12) return `${diffMonths} 个月前`;

    const diffYears = Math.floor(diffMonths / 12);
    return `${diffYears} 年前`;
  }

  /**
   * 格式化时长（毫秒）
   * @param {number} ms - 毫秒数
   * @returns {string} 格式化后的时长
   */
  function formatDuration(ms) {
    if (!ms || ms < 0) return "0ms";
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;

    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  }

  /**
   * 格式化数字（添加千分位分隔符）
   * @param {number} num - 数字
   * @returns {string} 格式化后的字符串
   */
  function formatNumber(num) {
    if (num == null || isNaN(num)) return "-";
    return num.toLocaleString("zh-CN");
  }

  /**
   * HTML 转义，防止 XSS
   * @param {string} str - 原始字符串
   * @returns {string} 转义后的字符串
   */
  function escapeHtml(str) {
    if (str == null) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ============================================================
  // Toast 通知系统
  // ============================================================

  const TOAST_DURATION = 4000; // 默认 4 秒自动消失

  /**
   * 显示 Toast 通知
   * @param {string} type - 类型: success / warning / error / info
   * @param {string} title - 标题
   * @param {string} message - 消息内容（可选）
   * @param {number} duration - 持续时间（毫秒），默认 4000
   */
  function showToast(type, title, message = "", duration = TOAST_DURATION) {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const iconMap = {
      success: "✓",
      warning: "⚠",
      error: "✕",
      info: "ℹ",
    };

    toast.innerHTML = `
      <span class="toast-icon">${iconMap[type] || "ℹ"}</span>
      <div class="toast-content">
        <div class="toast-title">${escapeHtml(title)}</div>
        ${message ? `<div class="toast-message">${escapeHtml(message)}</div>` : ""}
      </div>
      <button class="toast-close" title="关闭">×</button>
    `;

    container.appendChild(toast);

    // 关闭按钮
    const closeBtn = toast.querySelector(".toast-close");
    closeBtn.addEventListener("click", () => removeToast(toast));

    // 自动消失
    if (duration > 0) {
      setTimeout(() => removeToast(toast), duration);
    }

    return toast;
  }

  /**
   * 移除 Toast
   * @param {HTMLElement} toast - Toast 元素
   */
  function removeToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.add("toast-out");
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 300);
  }

  // 便捷方法
  const toast = {
    success: (title, msg, dur) => showToast("success", title, msg, dur),
    warning: (title, msg, dur) => showToast("warning", title, msg, dur),
    error: (title, msg, dur) => showToast("error", title, msg, dur),
    info: (title, msg, dur) => showToast("info", title, msg, dur),
  };

  // ============================================================
  // 状态渲染组件
  // ============================================================

  /**
   * 渲染加载状态
   * @param {string} text - 加载提示文字
   * @returns {string} HTML 字符串
   */
  function renderLoading(text = "加载中...") {
    return `
      <div class="loading-state">
        <div class="loading-spinner"></div>
        <span>${escapeHtml(text)}</span>
      </div>
    `;
  }

  /**
   * 渲染空状态
   * @param {string} message - 空状态提示
   * @param {string} icon - 图标（SVG 或 emoji）
   * @returns {string} HTML 字符串
   */
  function renderEmpty(message = "暂无数据", icon = "📭") {
    return `
      <div class="empty-state">
        <span style="font-size: 32px; opacity: 0.3;">${icon}</span>
        <span>${escapeHtml(message)}</span>
      </div>
    `;
  }

  /**
   * 渲染错误状态
   * @param {string} message - 错误信息
   * @returns {string} HTML 字符串
   */
  function renderError(message = "加载失败") {
    return `
      <div class="error-state">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        <span>${escapeHtml(message)}</span>
      </div>
    `;
  }

  // ============================================================
  // 服务器列表组件
  // ============================================================

  /**
   * 渲染单个服务器项
   * @param {Object} server - 服务器数据对象
   * @returns {string} HTML 字符串
   */
  function renderServerItem(server) {
    const isOnline = server.status === "online";
    const statusClass = isOnline ? "status-online" : "status-offline";
    const heartbeatText = formatRelativeTime(server.last_heartbeat);
    const toolCount = server.tool_count || 0;

    return `
      <div class="server-item" data-server-id="${server.id}">
        <div class="server-info">
          <span class="server-status ${statusClass}" title="${
      isOnline ? "在线" : "离线"
    }"></span>
          <div class="server-details">
            <div class="server-name" title="${escapeHtml(server.name)}">${escapeHtml(
      server.name
    )}</div>
            <div class="server-meta-info">${escapeHtml(
              server.transport_type || "unknown"
            )} · ${heartbeatText}</div>
          </div>
        </div>
        <div class="server-meta">
          <span class="tool-count" title="工具数量">${toolCount} 工具</span>
          <button class="action-btn danger" onclick="window.MCP_App.deleteServer(${
            server.id
          }, '${escapeHtml(server.name)}')" title="删除服务器">删除</button>
        </div>
      </div>
    `;
  }

  /**
   * 渲染服务器列表
   * @param {Array} servers - 服务器数组
   * @returns {string} HTML 字符串
   */
  function renderServerList(servers) {
    if (!servers || servers.length === 0) {
      return renderEmpty("暂无服务器", "🖥️");
    }
    return servers.map(renderServerItem).join("");
  }

  // ============================================================
  // 调用记录组件
  // ============================================================

  /**
   * 渲染单条调用记录
   * @param {Object} call - 调用记录对象
   * @returns {string} HTML 字符串
   */
  function renderCallItem(call) {
    const isSuccess = call.status === "success";
    const statusClass = isSuccess ? "call-success" : "call-failed";
    const durationText = formatDuration(call.duration_ms || 0);
    const timeText = formatRelativeTime(call.created_at);

    return `
      <div class="call-item" title="${escapeHtml(call.tool_name || "")}">
        <span class="call-status ${statusClass}" title="${
      isSuccess ? "成功" : "失败"
    }"></span>
        <span class="call-tool">${escapeHtml(call.tool_name || "unknown")}</span>
        <span class="call-duration">${durationText}</span>
        <span class="call-time">${timeText}</span>
      </div>
    `;
  }

  /**
   * 渲染调用记录列表
   * @param {Array} calls - 调用记录数组
   * @returns {string} HTML 字符串
   */
  function renderCallList(calls) {
    if (!calls || calls.length === 0) {
      return renderEmpty("暂无调用记录", "📋");
    }
    return calls.map(renderCallItem).join("");
  }

  // ============================================================
  // 告警组件
  // ============================================================

  /**
   * 渲染单条告警
   * @param {Object} alert - 告警对象
   * @returns {string} HTML 字符串
   */
  function renderAlertItem(alert) {
    const severity = alert.severity || "info";
    const sevClass = `alert-${severity}`;

    const iconMap = {
      critical: "🔴",
      warning: "🟡",
      info: "🔵",
    };

    const icon = iconMap[severity] || "ℹ️";
    const timeText = formatRelativeTime(alert.created_at);

    return `
      <div class="alert-item ${sevClass}">
        <span class="alert-icon">${icon}</span>
        <div class="alert-content">
          <div class="alert-title">${escapeHtml(alert.title || "未知告警")}</div>
          <div class="alert-desc">${escapeHtml(alert.description || "")}</div>
        </div>
        <span class="alert-time">${timeText}</span>
      </div>
    `;
  }

  /**
   * 渲染告警列表
   * @param {Array} alerts - 告警数组
   * @returns {string} HTML 字符串
   */
  function renderAlertList(alerts) {
    if (!alerts || alerts.length === 0) {
      return renderEmpty("暂无告警", "✅");
    }
    return alerts.map(renderAlertItem).join("");
  }

  // ============================================================
  // 统计卡片更新
  // ============================================================

  /**
   * 更新统计数值（带数字动画效果）
   * @param {HTMLElement} element - 目标元素
   * @param {number} newValue - 新数值
   * @param {number} duration - 动画时长（毫秒）
   */
  function animateValue(element, newValue, duration = 500) {
    if (!element) return;

    const startValue = parseInt(element.textContent) || 0;
    const endValue = parseInt(newValue) || 0;

    if (startValue === endValue) {
      element.textContent = formatNumber(endValue);
      return;
    }

    const startTime = performance.now();

    function update(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);

      // easeOutQuart 缓动
      const easeProgress = 1 - Math.pow(1 - progress, 4);
      const currentValue = Math.round(startValue + (endValue - startValue) * easeProgress);

      element.textContent = formatNumber(currentValue);

      if (progress < 1) {
        requestAnimationFrame(update);
      }
    }

    requestAnimationFrame(update);
  }

  // ============================================================
  // 公开 API
  // ============================================================
  return {
    // 工具函数
    formatRelativeTime,
    formatDuration,
    formatNumber,
    escapeHtml,

    // Toast 通知
    toast,
    showToast,

    // 状态渲染
    renderLoading,
    renderEmpty,
    renderError,

    // 服务器
    renderServerItem,
    renderServerList,

    // 调用记录
    renderCallItem,
    renderCallList,

    // 告警
    renderAlertItem,
    renderAlertList,

    // 动画
    animateValue,
  };
})();

// 暴露到全局
window.UIComponents = UIComponents;
