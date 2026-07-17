"""
云汐 Grafana 仪表盘数据模型（OB-004, P2级）
==========================================

提供 Grafana 仪表盘的 JSON 定义，可直接导入 Grafana 使用。

仪表盘类型：
1. system_overview: 系统总览仪表盘
2. business_monitor: 业务监控仪表盘
3. security_monitor: 安全监控仪表盘
4. module_detail: 模块详情仪表盘
5. logs_dashboard: 日志分析仪表盘

每个仪表盘包含：
- 基本信息（标题、描述、标签）
- 变量定义
- 面板列表（图表、指标、表格等）
- 时间范围
- 刷新间隔

使用方式：
    from shared.core.observability.dashboards import (
        generate_system_overview_dashboard,
        generate_business_dashboard,
        generate_security_dashboard,
        generate_module_detail_dashboard,
        generate_logs_dashboard,
        DASHBOARD_REGISTRY,
    )

    # 生成系统总览仪表盘 JSON
    dashboard = generate_system_overview_dashboard()

    # 保存为 JSON 文件（可导入 Grafana）
    import json
    with open("system_overview.json", "w") as f:
        json.dump(dashboard, f, indent=2)
"""

import json
from typing import Dict, Any, List, Optional


# ============================================================================
# 仪表盘面板类型
# ============================================================================

class PanelType:
    """Grafana 面板类型"""
    GRAPH = "graph"
    STAT = "stat"
    GAUGE = "gauge"
    BAR_GAUGE = "bargauge"
    TABLE = "table"
    HEATMAP = "heatmap"
    PIECHART = "piechart"
    TIMESERIES = "timeseries"
    STATUS_HISTORY = "status-history"
    TEXT = "text"
    LOGS = "logs"


# ============================================================================
# 辅助函数
# ============================================================================

def _make_panel(
    panel_id: int,
    title: str,
    panel_type: str,
    datasource: str = "Prometheus",
    grid_pos: Optional[Dict[str, int]] = None,
    targets: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
    field_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """创建 Grafana 面板配置"""
    return {
        "id": panel_id,
        "title": title,
        "type": panel_type,
        "datasource": {"type": "prometheus", "uid": datasource},
        "gridPos": grid_pos or {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": targets or [],
        "options": options or {},
        "fieldConfig": field_config or {"defaults": {}, "overrides": []},
        "editable": True,
    }


def _make_prometheus_target(
    expr: str,
    legend_format: str = "{{label}}",
    ref_id: str = "A",
) -> Dict[str, Any]:
    """创建 Prometheus 查询目标"""
    return {
        "refId": ref_id,
        "expr": expr,
        "legendFormat": legend_format,
        "interval": "",
        "intervalFactor": 1,
    }


def _make_dashboard(
    title: str,
    description: str,
    tags: List[str],
    panels: List[Dict[str, Any]],
    variables: Optional[List[Dict[str, Any]]] = None,
    time_from: str = "now-6h",
    refresh: str = "30s",
) -> Dict[str, Any]:
    """创建 Grafana 仪表盘配置"""
    return {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                }
            ]
        },
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "liveNow": False,
        "panels": panels,
        "refresh": refresh,
        "schemaVersion": 38,
        "style": "dark",
        "tags": tags,
        "templating": {
            "list": variables or [
                {
                    "current": {"selected": False, "text": "All", "value": "$__all"},
                    "hide": 0,
                    "includeAll": True,
                    "multi": True,
                    "name": "module",
                    "query": "label_values(yunxi_up, module)",
                    "refresh": 1,
                    "type": "query",
                }
            ],
        },
        "time": {"from": time_from, "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "description": description,
        "uid": f"yunxi-{title.lower().replace(' ', '-')}",
        "version": 1,
        "weekStart": "",
    }


# ============================================================================
# 系统总览仪表盘
# ============================================================================

def generate_system_overview_dashboard() -> Dict[str, Any]:
    """生成系统总览仪表盘

    包含：
    - 系统状态总览（健康/降级/不健康模块数）
    - CPU/内存/磁盘使用率
    - 网络流量
    - 各模块状态列表
    - 系统告警状态
    """
    panels = []
    panel_id = 1

    # ---- 行：系统状态 ----
    panels.append({
        "id": panel_id,
        "title": "System Status",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 健康模块数
    panels.append(_make_panel(
        panel_id, "Healthy Modules", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 0, "y": 1},
        targets=[_make_prometheus_target(
            'sum(yunxi_module_up{module=~"$module"})',
            legend_format="Healthy",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
        field_config={"defaults": {"color": {"mode": "palette-classic"}, "mappings": []}},
    ))
    panel_id += 1

    # 降级模块数
    panels.append(_make_panel(
        panel_id, "Degraded Modules", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 6, "y": 1},
        targets=[_make_prometheus_target(
            'sum(yunxi_module_health_status{module=~"$module"} == 0.5)',
            legend_format="Degraded",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 不健康模块数
    panels.append(_make_panel(
        panel_id, "Unhealthy Modules", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 12, "y": 1},
        targets=[_make_prometheus_target(
            'count(yunxi_module_health_status{module=~"$module"} == 0)',
            legend_format="Unhealthy",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 活跃告警数
    panels.append(_make_panel(
        panel_id, "Active Alerts", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 18, "y": 1},
        targets=[_make_prometheus_target(
            'sum(ALERTS{alertstate="firing"})',
            legend_format="Active Alerts",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # ---- 行：资源使用 ----
    panels.append({
        "id": panel_id,
        "title": "Resource Usage",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 5},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # CPU 使用率
    panels.append(_make_panel(
        panel_id, "CPU Usage", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 8, "x": 0, "y": 6},
        targets=[_make_prometheus_target(
            '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
            legend_format="{{instance}}",
        )],
    ))
    panel_id += 1

    # 内存使用率
    panels.append(_make_panel(
        panel_id, "Memory Usage", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 8, "x": 8, "y": 6},
        targets=[_make_prometheus_target(
            '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
            legend_format="{{instance}}",
        )],
    ))
    panel_id += 1

    # 磁盘使用率
    panels.append(_make_panel(
        panel_id, "Disk Usage", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 8, "x": 16, "y": 6},
        targets=[_make_prometheus_target(
            '100 - ((node_filesystem_avail_bytes{mountpoint="/",fstype!~"rootfs|tmpfs"} / node_filesystem_size_bytes) * 100)',
            legend_format="{{mountpoint}}",
        )],
    ))
    panel_id += 1

    # ---- 行：网络流量 ----
    panels.append({
        "id": panel_id,
        "title": "Network Traffic",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 14},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 网络接收
    panels.append(_make_panel(
        panel_id, "Network Receive", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 15},
        targets=[_make_prometheus_target(
            'rate(node_network_receive_bytes_total{device!~"lo"}[5m])',
            legend_format="{{device}} in",
        )],
    ))
    panel_id += 1

    # 网络发送
    panels.append(_make_panel(
        panel_id, "Network Transmit", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 15},
        targets=[_make_prometheus_target(
            'rate(node_network_transmit_bytes_total{device!~"lo"}[5m])',
            legend_format="{{device}} out",
        )],
    ))
    panel_id += 1

    # ---- 行：模块状态表 ----
    panels.append({
        "id": panel_id,
        "title": "Module Status",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 23},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 模块状态表
    panels.append(_make_panel(
        panel_id, "Modules", PanelType.TABLE,
        grid_pos={"h": 10, "w": 24, "x": 0, "y": 24},
        targets=[
            _make_prometheus_target(
                'yunxi_module_up{module=~"$module"}',
                legend_format="{{module}} status",
            ),
            _make_prometheus_target(
                'yunxi_module_uptime_seconds{module=~"$module"}',
                legend_format="{{module}} uptime",
                ref_id="B",
            ),
        ],
    ))
    panel_id += 1

    return _make_dashboard(
        title="Yunxi System Overview",
        description="云汐系统总览仪表盘 - 系统资源、模块状态、告警概览",
        tags=["yunxi", "system", "overview"],
        panels=panels,
        time_from="now-6h",
        refresh="30s",
    )


# ============================================================================
# 业务监控仪表盘
# ============================================================================

def generate_business_dashboard() -> Dict[str, Any]:
    """生成业务监控仪表盘

    包含：
    - 请求量趋势
    - 响应时间（P50/P95/P99）
    - 错误率
    - 各模块 QPS 对比
    - 任务队列状态
    - 用户活跃度
    """
    panels = []
    panel_id = 1

    # ---- 行：核心指标 ----
    panels.append({
        "id": panel_id,
        "title": "Key Metrics",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 总请求数
    panels.append(_make_panel(
        panel_id, "Total Requests", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 0, "y": 1},
        targets=[_make_prometheus_target(
            'sum(rate(yunxi_http_requests_total{module=~"$module"}[5m]))',
            legend_format="QPS",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 错误率
    panels.append(_make_panel(
        panel_id, "Error Rate", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 6, "y": 1},
        targets=[_make_prometheus_target(
            'sum(rate(yunxi_http_requests_error_total{module=~"$module"}[5m])) / sum(rate(yunxi_http_requests_total{module=~"$module"}[5m])) * 100',
            legend_format="Error %",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # P95 延迟
    panels.append(_make_panel(
        panel_id, "P95 Latency", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 12, "y": 1},
        targets=[_make_prometheus_target(
            'histogram_quantile(0.95, sum(rate(yunxi_http_request_duration_seconds_bucket{module=~"$module"}[5m])) by (le))',
            legend_format="P95",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 活跃用户
    panels.append(_make_panel(
        panel_id, "Active Users", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 18, "y": 1},
        targets=[_make_prometheus_target(
            'yunxi_user_active_total{period="5m",module=~"$module"}',
            legend_format="Active Users",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # ---- 行：请求趋势 ----
    panels.append({
        "id": panel_id,
        "title": "Request Trends",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 5},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # QPS 趋势
    panels.append(_make_panel(
        panel_id, "QPS by Module", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 6},
        targets=[_make_prometheus_target(
            'rate(yunxi_http_requests_total{module=~"$module"}[5m])',
            legend_format="{{module}}",
        )],
    ))
    panel_id += 1

    # 响应时间分布
    panels.append(_make_panel(
        panel_id, "Response Time", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 6},
        targets=[
            _make_prometheus_target(
                'histogram_quantile(0.50, sum(rate(yunxi_http_request_duration_seconds_bucket{module=~"$module"}[5m])) by (le, module))',
                legend_format="{{module}} P50",
            ),
            _make_prometheus_target(
                'histogram_quantile(0.95, sum(rate(yunxi_http_request_duration_seconds_bucket{module=~"$module"}[5m])) by (le, module))',
                legend_format="{{module}} P95",
                ref_id="B",
            ),
            _make_prometheus_target(
                'histogram_quantile(0.99, sum(rate(yunxi_http_request_duration_seconds_bucket{module=~"$module"}[5m])) by (le, module))',
                legend_format="{{module}} P99",
                ref_id="C",
            ),
        ],
    ))
    panel_id += 1

    # ---- 行：错误与任务 ----
    panels.append({
        "id": panel_id,
        "title": "Errors & Tasks",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 14},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 错误率趋势
    panels.append(_make_panel(
        panel_id, "Error Rate Trend", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 15},
        targets=[_make_prometheus_target(
            'sum(rate(yunxi_http_requests_error_total{module=~"$module"}[5m])) by (module) / sum(rate(yunxi_http_requests_total{module=~"$module"}[5m])) by (module) * 100',
            legend_format="{{module}}",
        )],
    ))
    panel_id += 1

    # 任务队列
    panels.append(_make_panel(
        panel_id, "Task Queue Size", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 15},
        targets=[_make_prometheus_target(
            'yunxi_task_queue_size{module=~"$module"}',
            legend_format="{{module}} - {{queue_name}}",
        )],
    ))
    panel_id += 1

    # ---- 行：状态码分布 ----
    panels.append({
        "id": panel_id,
        "title": "Status Codes",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 23},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 状态码分布
    panels.append(_make_panel(
        panel_id, "Status Code Distribution", PanelType.PIECHART,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 24},
        targets=[_make_prometheus_target(
            'sum(increase(yunxi_http_requests_total{module=~"$module"}[1h])) by (status)',
            legend_format="{{status}}",
        )],
    ))
    panel_id += 1

    # Top 慢接口
    panels.append(_make_panel(
        panel_id, "Top Slow Endpoints", PanelType.TABLE,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 24},
        targets=[_make_prometheus_target(
            'topk(10, sum(rate(yunxi_http_requests_slow_total{module=~"$module"}[1h])) by (path, module))',
            legend_format="{{module}} {{path}}",
        )],
    ))
    panel_id += 1

    return _make_dashboard(
        title="Yunxi Business Monitor",
        description="云汐业务监控仪表盘 - 请求量、响应时间、错误率、用户活跃度",
        tags=["yunxi", "business", "monitoring"],
        panels=panels,
        time_from="now-24h",
        refresh="1m",
    )


# ============================================================================
# 安全监控仪表盘
# ============================================================================

def generate_security_dashboard() -> Dict[str, Any]:
    """生成安全监控仪表盘

    包含：
    - 攻击检测统计
    - WAF 拦截统计
    - 登录异常监控
    - 安全事件趋势
    - API 限流命中
    - 漏洞扫描结果
    """
    panels = []
    panel_id = 1

    # ---- 行：安全总览 ----
    panels.append({
        "id": panel_id,
        "title": "Security Overview",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 今日攻击数
    panels.append(_make_panel(
        panel_id, "Attacks Today", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 0, "y": 1},
        targets=[_make_prometheus_target(
            'sum(increase(yunxi_security_attacks_total[1d]))',
            legend_format="Attacks",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 拦截数
    panels.append(_make_panel(
        panel_id, "Blocked Attacks", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 6, "y": 1},
        targets=[_make_prometheus_target(
            'sum(increase(yunxi_security_attacks_blocked_total[1d]))',
            legend_format="Blocked",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 登录失败数
    panels.append(_make_panel(
        panel_id, "Failed Logins", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 12, "y": 1},
        targets=[_make_prometheus_target(
            'sum(increase(yunxi_security_login_failed_total[1h]))',
            legend_format="Failed/h",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 严重安全事件
    panels.append(_make_panel(
        panel_id, "Critical Events", PanelType.STAT,
        grid_pos={"h": 4, "w": 6, "x": 18, "y": 1},
        targets=[_make_prometheus_target(
            'sum(increase(yunxi_security_events_critical_total[24h]))',
            legend_format="Critical/24h",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # ---- 行：攻击趋势 ----
    panels.append({
        "id": panel_id,
        "title": "Attack Trends",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 5},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 攻击类型分布
    panels.append(_make_panel(
        panel_id, "Attack Types", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 6},
        targets=[_make_prometheus_target(
            'rate(yunxi_security_attacks_total[5m])',
            legend_format="{{attack_type}}",
        )],
    ))
    panel_id += 1

    # WAF 命中
    panels.append(_make_panel(
        panel_id, "WAF Rule Hits", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 6},
        targets=[_make_prometheus_target(
            'rate(yunxi_security_waf_hits_total[5m])',
            legend_format="{{rule_category}}",
        )],
    ))
    panel_id += 1

    # ---- 行：认证安全 ----
    panels.append({
        "id": panel_id,
        "title": "Authentication",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 14},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 登录成功/失败
    panels.append(_make_panel(
        panel_id, "Login Success/Fail", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 15},
        targets=[
            _make_prometheus_target(
                'rate(yunxi_security_login_total{status="success"}[5m])',
                legend_format="Success",
            ),
            _make_prometheus_target(
                'rate(yunxi_security_login_total{status="failed"}[5m])',
                legend_format="Failed",
                ref_id="B",
            ),
        ],
    ))
    panel_id += 1

    # 未授权访问
    panels.append(_make_panel(
        panel_id, "Unauthorized Access", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 15},
        targets=[_make_prometheus_target(
            'rate(yunxi_security_unauthorized_total[5m])',
            legend_format="{{reason}}",
        )],
    ))
    panel_id += 1

    # ---- 行：API 安全 ----
    panels.append({
        "id": panel_id,
        "title": "API Security",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 23},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 限流命中
    panels.append(_make_panel(
        panel_id, "Rate Limit Hits", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 24},
        targets=[_make_prometheus_target(
            'rate(yunxi_security_rate_limit_hits_total[5m])',
            legend_format="{{endpoint}}",
        )],
    ))
    panel_id += 1

    # 安全事件等级分布
    panels.append(_make_panel(
        panel_id, "Security Event Severity", PanelType.PIECHART,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 24},
        targets=[_make_prometheus_target(
            'sum(increase(yunxi_security_events_total[24h])) by (severity)',
            legend_format="{{severity}}",
        )],
    ))
    panel_id += 1

    return _make_dashboard(
        title="Yunxi Security Monitor",
        description="云汐安全监控仪表盘 - 攻击检测、WAF、登录安全、API 安全",
        tags=["yunxi", "security", "monitoring"],
        panels=panels,
        time_from="now-24h",
        refresh="1m",
    )


# ============================================================================
# 模块详情仪表盘
# ============================================================================

def generate_module_detail_dashboard(module_id: str = "m8") -> Dict[str, Any]:
    """生成模块详情仪表盘

    Args:
        module_id: 模块 ID

    包含：
    - 模块基本信息和状态
    - 请求量和响应时间
    - 错误率趋势
    - 资源使用（CPU/内存）
    - 数据库连接和查询
    - 任务队列
    """
    panels = []
    panel_id = 1

    # ---- 行：模块状态 ----
    panels.append({
        "id": panel_id,
        "title": f"Module: {module_id.upper()}",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 健康状态
    panels.append(_make_panel(
        panel_id, "Health Status", PanelType.STAT,
        grid_pos={"h": 4, "w": 4, "x": 0, "y": 1},
        targets=[_make_prometheus_target(
            f'yunxi_module_health_status{{module="{module_id}"}}',
            legend_format="Health",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 运行时间
    panels.append(_make_panel(
        panel_id, "Uptime", PanelType.STAT,
        grid_pos={"h": 4, "w": 4, "x": 4, "y": 1},
        targets=[_make_prometheus_target(
            f'yunxi_module_uptime_seconds{{module="{module_id}"}}',
            legend_format="Uptime (s)",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # QPS
    panels.append(_make_panel(
        panel_id, "QPS", PanelType.STAT,
        grid_pos={"h": 4, "w": 4, "x": 8, "y": 1},
        targets=[_make_prometheus_target(
            f'rate(yunxi_http_requests_total{{module="{module_id}"}}[5m])',
            legend_format="QPS",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 错误率
    panels.append(_make_panel(
        panel_id, "Error Rate", PanelType.STAT,
        grid_pos={"h": 4, "w": 4, "x": 12, "y": 1},
        targets=[_make_prometheus_target(
            f'rate(yunxi_http_requests_error_total{{module="{module_id}"}}[5m]) / rate(yunxi_http_requests_total{{module="{module_id}"}}[5m]) * 100',
            legend_format="Error %",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # P99 延迟
    panels.append(_make_panel(
        panel_id, "P99 Latency", PanelType.STAT,
        grid_pos={"h": 4, "w": 4, "x": 16, "y": 1},
        targets=[_make_prometheus_target(
            f'histogram_quantile(0.99, sum(rate(yunxi_http_request_duration_seconds_bucket{{module="{module_id}"}}[5m])) by (le))',
            legend_format="P99 (s)",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # 内存使用
    panels.append(_make_panel(
        panel_id, "Memory Usage", PanelType.STAT,
        grid_pos={"h": 4, "w": 4, "x": 20, "y": 1},
        targets=[_make_prometheus_target(
            f'yunxi_module_memory_usage_bytes{{module="{module_id}"}}',
            legend_format="Memory",
        )],
        options={
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    ))
    panel_id += 1

    # ---- 行：请求性能 ----
    panels.append({
        "id": panel_id,
        "title": "Request Performance",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 5},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # QPS 趋势
    panels.append(_make_panel(
        panel_id, "QPS Trend", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 12, "x": 0, "y": 6},
        targets=[_make_prometheus_target(
            f'rate(yunxi_http_requests_total{{module="{module_id}"}}[5m])',
            legend_format="{{path}}",
        )],
    ))
    panel_id += 1

    # 延迟分布
    panels.append(_make_panel(
        panel_id, "Latency Distribution", PanelType.HEATMAP,
        grid_pos={"h": 8, "w": 12, "x": 12, "y": 6},
        targets=[_make_prometheus_target(
            f'sum(rate(yunxi_http_request_duration_seconds_bucket{{module="{module_id}"}}[5m])) by (le)',
            legend_format="{{le}}",
        )],
    ))
    panel_id += 1

    # ---- 行：资源使用 ----
    panels.append({
        "id": panel_id,
        "title": "Resource Usage",
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 14},
        "collapsed": False,
        "panels": [],
    })
    panel_id += 1

    # 内存趋势
    panels.append(_make_panel(
        panel_id, "Memory Trend", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 8, "x": 0, "y": 15},
        targets=[_make_prometheus_target(
            f'yunxi_module_memory_usage_bytes{{module="{module_id}"}}',
            legend_format="Memory",
        )],
    ))
    panel_id += 1

    # 活跃连接/线程
    panels.append(_make_panel(
        panel_id, "Active Threads", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 8, "x": 8, "y": 15},
        targets=[_make_prometheus_target(
            f'yunxi_module_goroutines{{module="{module_id}"}}',
            legend_format="Threads",
        )],
    ))
    panel_id += 1

    # 数据库连接
    panels.append(_make_panel(
        panel_id, "DB Connections", PanelType.TIMESERIES,
        grid_pos={"h": 8, "w": 8, "x": 16, "y": 15},
        targets=[
            _make_prometheus_target(
                f'yunxi_db_connections_active{{module="{module_id}"}}',
                legend_format="Active",
            ),
            _make_prometheus_target(
                f'yunxi_db_connections_total{{module="{module_id}"}}',
                legend_format="Total",
                ref_id="B",
            ),
        ],
    ))
    panel_id += 1

    return _make_dashboard(
        title=f"Yunxi Module - {module_id.upper()}",
        description=f"云汐模块 {module_id.upper()} 详情监控仪表盘",
        tags=["yunxi", "module", module_id],
        panels=panels,
        variables=[],
        time_from="now-1h",
        refresh="30s",
    )


# ============================================================================
# 仪表盘注册表
# ============================================================================

DASHBOARD_REGISTRY: Dict[str, Any] = {
    "system_overview": generate_system_overview_dashboard,
    "business_monitor": generate_business_dashboard,
    "security_monitor": generate_security_dashboard,
    "module_detail": generate_module_detail_dashboard,
}


def generate_all_dashboards(output_dir: str = "./dashboards") -> Dict[str, str]:
    """生成所有仪表盘并保存到指定目录

    Args:
        output_dir: 输出目录

    Returns:
        仪表盘名称 -> 文件路径 的映射
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    results = {}

    # 系统总览
    dashboard = generate_system_overview_dashboard()
    path = os.path.join(output_dir, "system_overview.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    results["system_overview"] = path

    # 业务监控
    dashboard = generate_business_dashboard()
    path = os.path.join(output_dir, "business_monitor.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    results["business_monitor"] = path

    # 安全监控
    dashboard = generate_security_dashboard()
    path = os.path.join(output_dir, "security_monitor.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    results["security_monitor"] = path

    # 模块详情（M8）
    dashboard = generate_module_detail_dashboard("m8")
    path = os.path.join(output_dir, "module_m8_detail.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    results["module_m8_detail"] = path

    return results


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    # 仪表盘生成函数
    "generate_system_overview_dashboard",
    "generate_business_dashboard",
    "generate_security_dashboard",
    "generate_module_detail_dashboard",
    "generate_all_dashboards",
    # 注册表
    "DASHBOARD_REGISTRY",
    # 面板类型
    "PanelType",
]
