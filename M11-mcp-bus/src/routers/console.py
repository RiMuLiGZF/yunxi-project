"""M11 MCP Bus - 管理控制台路由.

提供基于 HTML 的管理控制台页面和相关数据 API。
深色主题，现代简洁风格，卡片布局，状态指示灯。
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..db import get_session
from ..models_db import McpCall, McpServer, McpTool
from ..services.alert import alert_service
from ..services.monitor import mcp_monitor

router = APIRouter(tags=["console"])


# ============================================================
# 控制台首页 HTML
# ============================================================

_CONSOLE_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M11 MCP Bus - 管理控制台</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    min-height: 100vh;
  }

  /* ---------- 顶部导航 ---------- */
  .header {
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .header-left { display: flex; align-items: center; gap: 12px; }

  .logo {
    width: 36px;
    height: 36px;
    background: linear-gradient(135deg, #58a6ff, #8b5cf6);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    font-size: 16px;
    color: #fff;
  }

  .title { font-size: 18px; font-weight: 600; color: #f0f6fc; }
  .subtitle { font-size: 12px; color: #8b949e; margin-top: 2px; }

  .header-right { display: flex; align-items: center; gap: 16px; }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3fb950;
    box-shadow: 0 0 8px #3fb950;
    animation: pulse 2s infinite;
    display: inline-block;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  .status-text { font-size: 13px; color: #8b949e; }
  .refresh-btn {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 6px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.2s;
  }
  .refresh-btn:hover {
    background: #30363d;
    border-color: #58a6ff;
  }

  /* ---------- 主内容 ---------- */
  .main { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }

  /* ---------- 统计卡片 ---------- */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }

  .stat-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 20px;
    transition: border-color 0.2s;
  }
  .stat-card:hover { border-color: #58a6ff; }

  .stat-label {
    font-size: 12px;
    color: #8b949e;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .stat-value {
    font-size: 28px;
    font-weight: 700;
    color: #f0f6fc;
    margin-bottom: 4px;
  }

  .stat-sub { font-size: 12px; color: #8b949e; }

  .stat-icon {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    margin-bottom: 12px;
  }
  .icon-server { background: rgba(88,166,255,0.15); color: #58a6ff; }
  .icon-tool { background: rgba(139,92,246,0.15); color: #8b5cf6; }
  .icon-call { background: rgba(63,185,80,0.15); color: #3fb950; }
  .icon-alert { background: rgba(248,81,73,0.15); color: #f85149; }

  /* ---------- 面板布局 ---------- */
  .panels {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 24px;
  }

  @media (max-width: 900px) {
    .panels { grid-template-columns: 1fr; }
  }

  .panel {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    overflow: hidden;
  }

  .panel-header {
    padding: 14px 20px;
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .panel-title { font-size: 14px; font-weight: 600; color: #f0f6fc; }
  .panel-badge {
    background: #21262d;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    color: #8b949e;
  }

  .panel-body { padding: 16px 20px; }

  /* ---------- 服务器列表 ---------- */
  .server-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid #21262d;
  }
  .server-item:last-child { border-bottom: none; }

  .server-info { display: flex; align-items: center; gap: 10px; }

  .server-status {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .status-online { background: #3fb950; box-shadow: 0 0 6px #3fb950; }
  .status-offline { background: #f85149; box-shadow: 0 0 6px #f85149; }

  .server-name { font-size: 13px; color: #f0f6fc; font-weight: 500; }
  .server-transport { font-size: 11px; color: #8b949e; }

  .server-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 12px;
    color: #8b949e;
  }

  .tool-count {
    background: #21262d;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
  }

  /* ---------- 调用记录 ---------- */
  .call-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid #21262d;
    font-size: 12px;
  }
  .call-item:last-child { border-bottom: none; }

  .call-status {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .call-success { background: #3fb950; }
  .call-failed { background: #f85149; }

  .call-tool {
    flex: 1;
    color: #c9d1d9;
    font-family: "SF Mono", Monaco, Consolas, monospace;
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .call-duration { color: #8b949e; white-space: nowrap; }
  .call-time { color: #6e7681; white-space: nowrap; }

  /* ---------- 告警区域 ---------- */
  .alerts-panel { margin-bottom: 24px; }

  .alert-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    background: #161b22;
    border: 1px solid #30363d;
    border-left: 3px solid;
    border-radius: 6px;
    margin-bottom: 8px;
    font-size: 13px;
  }
  .alert-critical { border-left-color: #f85149; }
  .alert-warning { border-left-color: #d29922; }
  .alert-info { border-left-color: #58a6ff; }

  .alert-icon { font-size: 16px; }
  .alert-content { flex: 1; }
  .alert-title { color: #f0f6fc; font-weight: 500; margin-bottom: 2px; }
  .alert-desc { font-size: 12px; color: #8b949e; }
  .alert-time { font-size: 11px; color: #6e7681; white-space: nowrap; }

  .no-data {
    text-align: center;
    padding: 30px 20px;
    color: #6e7681;
    font-size: 13px;
  }

  /* ---------- 操作按钮 ---------- */
  .action-btn {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 4px 10px;
    border-radius: 5px;
    cursor: pointer;
    font-size: 11px;
    transition: all 0.2s;
  }
  .action-btn:hover { background: #30363d; }
  .action-btn.danger:hover {
    border-color: #f85149;
    color: #f85149;
  }

  /* ---------- 页脚 ---------- */
  .footer {
    text-align: center;
    padding: 20px;
    color: #6e7681;
    font-size: 12px;
    border-top: 1px solid #21262d;
    margin-top: 20px;
  }

  /* ---------- 加载状态 ---------- */
  .loading {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid #30363d;
    border-top-color: #58a6ff;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ---------- 成功率条 ---------- */
  .success-bar {
    height: 4px;
    background: #21262d;
    border-radius: 2px;
    overflow: hidden;
    margin-top: 8px;
  }
  .success-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
  }
  .fill-high { background: #3fb950; }
  .fill-mid { background: #d29922; }
  .fill-low { background: #f85149; }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="logo">M11</div>
    <div>
      <div class="title">MCP Bus 管理控制台</div>
      <div class="subtitle">统一管理和路由所有 MCP 工具服务</div>
    </div>
  </div>
  <div class="header-right">
    <span class="status-dot"></span>
    <span class="status-text" id="statusText">服务运行中</span>
    <button class="refresh-btn" onclick="refreshAll()">刷新数据</button>
  </div>
</div>

<div class="main">

  <!-- 统计卡片 -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-icon icon-server">&#9881;</div>
      <div class="stat-label">服务器总数</div>
      <div class="stat-value" id="totalServers">-</div>
      <div class="stat-sub">
        <span style="color:#3fb950;" id="onlineServers">- 在线</span>
        <span style="color:#8b949e;"> / </span>
        <span style="color:#f85149;" id="offlineServers">- 离线</span>
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-icon icon-tool">&#128295;</div>
      <div class="stat-label">工具总数</div>
      <div class="stat-value" id="totalTools">-</div>
      <div class="stat-sub">跨所有在线服务器</div>
    </div>

    <div class="stat-card">
      <div class="stat-icon icon-call">&#128222;</div>
      <div class="stat-label">调用总数</div>
      <div class="stat-value" id="totalCalls">-</div>
      <div class="stat-sub">
        成功率: <span id="successRate">-</span>%
        <div class="success-bar"><div class="success-fill fill-high" id="successFill" style="width:0%"></div></div>
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-icon icon-alert">&#9888;</div>
      <div class="stat-label">活跃告警</div>
      <div class="stat-value" id="activeAlerts">-</div>
      <div class="stat-sub" id="alertSub">无告警</div>
    </div>
  </div>

  <!-- 告警区域 -->
  <div class="alerts-panel" id="alertsPanel" style="display:none;">
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">&#9888; 活跃告警</span>
        <span class="panel-badge" id="alertCount">0</span>
      </div>
      <div class="panel-body" id="alertList"></div>
    </div>
  </div>

  <!-- 服务器 + 调用记录 -->
  <div class="panels">
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">&#128202; 服务器列表</span>
        <button class="action-btn" onclick="refreshTools()">刷新工具</button>
      </div>
      <div class="panel-body" id="serverList">
        <div class="no-data"><span class="loading"></span> 加载中...</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">&#128221; 最近调用记录</span>
        <span class="panel-badge">最近 20 条</span>
      </div>
      <div class="panel-body" id="callList">
        <div class="no-data"><span class="loading"></span> 加载中...</div>
      </div>
    </div>
  </div>

</div>

<div class="footer">
  M11 MCP Bus &middot; 版本 0.1.0 &middot; <span id="updateTime">-</span>
</div>

<script>
// ============================================================
// 工具函数
// ============================================================

function formatTime(isoStr) {
  if (!isoStr) return '从未';
  const d = new Date(isoStr);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return Math.floor(diff) + ' 秒前';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  return Math.floor(diff / 86400) + ' 天前';
}

function formatDuration(ms) {
  if (ms < 1000) return ms + 'ms';
  return (ms / 1000).toFixed(2) + 's';
}

// ============================================================
// 数据加载
// ============================================================

async function loadStats() {
  try {
    const resp = await fetch('/api/console/stats');
    const data = await resp.json();

    document.getElementById('totalServers').textContent = data.total_servers || 0;
    document.getElementById('onlineServers').textContent = (data.online_servers || 0) + ' 在线';
    document.getElementById('offlineServers').textContent = (data.offline_servers || 0) + ' 离线';
    document.getElementById('totalTools').textContent = data.total_tools || 0;
    document.getElementById('totalCalls').textContent = data.total_calls || 0;
    document.getElementById('successRate').textContent = data.success_rate != null ? data.success_rate : '-';

    const fill = document.getElementById('successFill');
    const rate = data.success_rate || 0;
    fill.style.width = rate + '%';
    fill.className = 'success-fill ' + (rate >= 95 ? 'fill-high' : rate >= 80 ? 'fill-mid' : 'fill-low');

    document.getElementById('activeAlerts').textContent = data.active_alerts || 0;
    document.getElementById('alertSub').textContent = 
      data.active_alerts > 0 
        ? (data.critical_alerts > 0 ? data.critical_alerts + ' 个严重' : (data.warning_alerts > 0 ? data.warning_alerts + ' 个警告' : '有告警'))
        : '系统正常';

    document.getElementById('updateTime').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN');
  } catch (e) {
    console.error('加载统计数据失败:', e);
  }
}

async function loadServers() {
  try {
    const resp = await fetch('/api/console/servers');
    const data = await resp.json();
    const servers = data.servers || [];

    const container = document.getElementById('serverList');
    if (servers.length === 0) {
      container.innerHTML = '<div class="no-data">暂无服务器</div>';
      return;
    }

    let html = '';
    for (const s of servers) {
      html += `
        <div class="server-item">
          <div class="server-info">
            <span class="server-status ${s.status === 'online' ? 'status-online' : 'status-offline'}"></span>
            <div>
              <div class="server-name">${s.name}</div>
              <div class="server-transport">${s.transport_type} &middot; ${formatTime(s.last_heartbeat)}</div>
            </div>
          </div>
          <div class="server-meta">
            <span class="tool-count">${s.tool_count || 0} 工具</span>
            <button class="action-btn danger" onclick="removeServer(${s.id}, '${s.name}')">删除</button>
          </div>
        </div>
      `;
    }
    container.innerHTML = html;
  } catch (e) {
    document.getElementById('serverList').innerHTML = '<div class="no-data">加载失败</div>';
    console.error('加载服务器列表失败:', e);
  }
}

async function loadRecentCalls() {
  try {
    const resp = await fetch('/api/console/recent-calls');
    const data = await resp.json();
    const calls = data.calls || [];

    const container = document.getElementById('callList');
    if (calls.length === 0) {
      container.innerHTML = '<div class="no-data">暂无调用记录</div>';
      return;
    }

    let html = '';
    for (const c of calls) {
      html += `
        <div class="call-item">
          <span class="call-status ${c.status === 'success' ? 'call-success' : 'call-failed'}"></span>
          <span class="call-tool" title="${c.tool_name}">${c.tool_name}</span>
          <span class="call-duration">${formatDuration(c.duration_ms || 0)}</span>
          <span class="call-time">${formatTime(c.created_at)}</span>
        </div>
      `;
    }
    container.innerHTML = html;
  } catch (e) {
    document.getElementById('callList').innerHTML = '<div class="no-data">加载失败</div>';
    console.error('加载调用记录失败:', e);
  }
}

async function loadAlerts() {
  try {
    const resp = await fetch('/api/console/stats');
    const data = await resp.json();
    const alerts = data.alerts || [];

    const panel = document.getElementById('alertsPanel');
    const list = document.getElementById('alertList');
    const count = document.getElementById('alertCount');

    if (alerts.length === 0) {
      panel.style.display = 'none';
      return;
    }

    panel.style.display = 'block';
    count.textContent = alerts.length;

    let html = '';
    for (const a of alerts) {
      const sevClass = a.severity === 'critical' ? 'alert-critical' : (a.severity === 'warning' ? 'alert-warning' : 'alert-info');
      const icon = a.severity === 'critical' ? '&#128308;' : (a.severity === 'warning' ? '&#128992;' : '&#128946;');
      html += `
        <div class="alert-item ${sevClass}">
          <span class="alert-icon">${icon}</span>
          <div class="alert-content">
            <div class="alert-title">${a.title}</div>
            <div class="alert-desc">${a.description || ''}</div>
          </div>
          <span class="alert-time">${formatTime(a.created_at)}</span>
        </div>
      `;
    }
    list.innerHTML = html;
  } catch (e) {
    console.error('加载告警失败:', e);
  }
}

// ============================================================
// 操作
// ============================================================

async function refreshAll() {
  await Promise.all([loadStats(), loadServers(), loadRecentCalls(), loadAlerts()]);
}

async function refreshTools() {
  if (!confirm('确定要刷新所有在线服务器的工具列表吗？')) return;
  try {
    const resp = await fetch('/api/admin/tools/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true })
    });
    const data = await resp.json();
    alert(data.message || '刷新完成');
    refreshAll();
  } catch (e) {
    alert('刷新失败: ' + e.message);
  }
}

async function removeServer(id, name) {
  if (!confirm('确定要删除服务器 "' + name + '" 吗？此操作不可恢复。')) return;
  try {
    const resp = await fetch('/api/admin/servers/' + id, { method: 'DELETE' });
    const data = await resp.json();
    if (resp.ok) {
      refreshAll();
    } else {
      alert('删除失败: ' + (data.detail || '未知错误'));
    }
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

// ============================================================
// 初始化
// ============================================================

refreshAll();
setInterval(refreshAll, 30000); // 每 30 秒自动刷新
</script>
</body>
</html>
"""


# ============================================================
# 路由：控制台页面
# ============================================================

@router.get("/console", response_class=HTMLResponse, summary="管理控制台页面")
async def console_page() -> HTMLResponse:
    """管理控制台首页.

    返回 HTML 页面，展示服务器状态、工具统计、调用记录等信息。
    深色主题，现代简洁风格。
    """
    return HTMLResponse(content=_CONSOLE_HTML)


# ============================================================
# 路由：控制台数据 API
# ============================================================

@router.get("/api/console/stats", summary="控制台统计数据")
async def console_stats() -> Dict[str, Any]:
    """获取控制台统计数据.

    返回服务器数、工具数、调用数、成功率、告警数等概览数据。
    """
    db = get_session()
    try:
        # 服务器统计
        total_servers = db.query(McpServer).count()
        online_servers = db.query(McpServer).filter(McpServer.status == "online").count()
        offline_servers = total_servers - online_servers

        # 工具统计
        total_tools = db.query(McpTool).count()

        # 调用统计（从内存 + 数据库）
        monitor_stats = mcp_monitor.get_stats()

        # 告警统计
        alert_stats = alert_service.get_alert_stats()
        active_alerts = alert_service.get_active_alerts()
        alert_list = [a.to_dict() for a in active_alerts[:10]]

        critical_alerts = sum(1 for a in active_alerts if a.severity == "critical")
        warning_alerts = sum(1 for a in active_alerts if a.severity == "warning")

        return {
            "total_servers": total_servers,
            "online_servers": online_servers,
            "offline_servers": offline_servers,
            "total_tools": total_tools,
            "total_calls": monitor_stats.get("total_calls", 0),
            "success_calls": monitor_stats.get("success_calls", 0),
            "failed_calls": monitor_stats.get("failed_calls", 0),
            "success_rate": monitor_stats.get("success_rate", 0.0),
            "avg_duration_ms": monitor_stats.get("avg_duration_ms", 0.0),
            "active_alerts": alert_stats.get("total_active", 0),
            "critical_alerts": critical_alerts,
            "warning_alerts": warning_alerts,
            "alerts": alert_list,
            "popular_tools": monitor_stats.get("popular_tools", []),
        }
    finally:
        db.close()


@router.get("/api/console/servers", summary="控制台服务器列表")
async def console_servers() -> Dict[str, Any]:
    """获取服务器列表（带状态和工具数量）.

    用于控制台服务器列表展示。
    """
    db = get_session()
    try:
        servers = db.query(McpServer).order_by(McpServer.name.asc()).all()

        server_list = []
        for s in servers:
            tool_count = db.query(McpTool).filter(McpTool.server_id == s.id).count()
            server_list.append({
                "id": s.id,
                "name": s.name,
                "status": s.status,
                "transport_type": s.transport_type,
                "endpoint": s.endpoint or "",
                "tool_count": tool_count,
                "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            })

        return {
            "servers": server_list,
            "total": len(server_list),
        }
    finally:
        db.close()


@router.get("/api/console/recent-calls", summary="控制台最近调用记录")
async def console_recent_calls(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
) -> Dict[str, Any]:
    """获取最近的调用记录.

    优先从内存环形缓冲区读取，速度快。

    Args:
        limit: 返回数量限制

    Returns:
        调用记录列表
    """
    calls = mcp_monitor.get_recent_calls(limit=limit)
    return {
        "calls": calls,
        "total": len(calls),
    }
