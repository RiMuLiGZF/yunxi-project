"""
云汐 M12 安全盾 - 安全仪表盘 API
提供安全态势概览、攻击趋势、威胁分布等仪表盘数据接口
"""

from fastapi import APIRouter

# 兼容相对导入和直接运行
try:
    from ..models import make_response, make_error_response
    from ..services.audit_service import get_audit_service
    from ..services.waf_engine import get_waf_engine
    from ..services.ip_filter import get_ip_filter
    from ..services.rate_limiter import get_rate_limiter
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from models import make_response, make_error_response
    from services.audit_service import get_audit_service
    from services.waf_engine import get_waf_engine
    from services.ip_filter import get_ip_filter
    from services.rate_limiter import get_rate_limiter

router = APIRouter(prefix="/api/m12/dashboard", tags=["M12-安全仪表盘"])


# ===========================================================================
# 仪表盘概览
# ===========================================================================

@router.get("/summary", summary="安全概览")
def dashboard_summary():
    """
    获取安全仪表盘概览数据，包含核心安全指标
    """
    try:
        audit = get_audit_service()
        waf = get_waf_engine()
        ipf = get_ip_filter()
        rl = get_rate_limiter()

        audit_stats = audit.get_stats()
        waf_status = waf.get_status()
        bl_count, wl_count = ipf.get_counts()

        # 计算安全评分（基于事件数量和级别）
        score = calculate_security_score(audit_stats)

        summary = {
            # 安全评分
            "security_score": score["score"],
            "security_level": score["level"],
            "security_trend": score["trend"],

            # 核心指标
            "total_events_today": audit_stats["events_today"],
            "waf_blocks_today": waf_status["today_blocks"],
            "high_risk_events": audit_stats["high_severity_count"],
            "blocked_ips": bl_count,

            # 组件状态
            "components": {
                "waf": {
                    "status": "active" if waf_status["enabled"] else "inactive",
                    "rules": waf_status["total_rules"],
                    "active_rules": waf_status["active_rules"],
                },
                "rate_limiter": {
                    "status": "active" if rl.is_active() else "inactive",
                    "default_rate": rl.default_rate,
                },
                "ip_filter": {
                    "status": "active",
                    "blacklist": bl_count,
                    "whitelist": wl_count,
                },
                "audit": {
                    "status": "active",
                    "total_logs": audit_stats["total_audit_logs"],
                },
            },

            # 告警信息
            "alerts": {
                "critical": audit_stats["high_severity_count"],
                "warning": audit_stats["medium_severity_count"],
                "info": audit_stats["low_severity_count"],
            },
        }

        return make_response(data=summary)
    except Exception as e:
        return make_error_response(f"获取安全概览失败: {str(e)}")


# ===========================================================================
# 攻击趋势
# ===========================================================================

@router.get("/attack-trend", summary="攻击趋势")
def attack_trend():
    """
    获取攻击趋势数据（最近 24 小时，按小时统计）
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        trend_data = stats["trend_data"]

        # 计算趋势方向
        if len(trend_data) >= 2:
            recent = sum(d["count"] for d in trend_data[-6:])  # 最近 6 小时
            earlier = sum(d["count"] for d in trend_data[-12:-6])  # 前 6 小时
            if earlier == 0:
                trend = "stable" if recent == 0 else "rising"
            else:
                change_rate = (recent - earlier) / earlier
                if change_rate > 0.2:
                    trend = "rising"
                elif change_rate < -0.2:
                    trend = "falling"
                else:
                    trend = "stable"
        else:
            trend = "stable"

        return make_response(data={
            "trend_data": trend_data,
            "period": "24h",
            "granularity": "hour",
            "trend": trend,
            "total_events": sum(d["count"] for d in trend_data),
        })
    except Exception as e:
        return make_error_response(f"获取攻击趋势失败: {str(e)}")


# ===========================================================================
# 威胁分布
# ===========================================================================

@router.get("/threat-distribution", summary="威胁分布")
def threat_distribution():
    """
    获取威胁类型分布数据
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        # 按类型分布
        by_type = stats["events_by_type"]
        type_list = [
            {"type": k, "count": v, "percentage": round(v / stats["total_events"] * 100, 2) if stats["total_events"] > 0 else 0}
            for k, v in by_type.items()
        ]
        type_list.sort(key=lambda x: x["count"], reverse=True)

        # 按级别分布
        by_severity = stats["events_by_severity"]
        severity_list = [
            {"level": k, "count": v, "percentage": round(v / stats["total_events"] * 100, 2) if stats["total_events"] > 0 else 0}
            for k, v in by_severity.items()
        ]

        return make_response(data={
            "by_type": type_list,
            "by_severity": severity_list,
            "total_events": stats["total_events"],
        })
    except Exception as e:
        return make_error_response(f"获取威胁分布失败: {str(e)}")


# ===========================================================================
# 攻击来源
# ===========================================================================

@router.get("/attack-sources", summary="攻击来源")
def attack_sources(
    limit: int = 10,
):
    """
    获取攻击来源 IP 排行及地理位置分布
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        top_ips = stats["top_source_ips"][:limit]

        # 模拟地理位置分布（实际需对接 IP 地理位置库）
        regions = {
            "国内": 0,
            "国外": 0,
            "未知": 0,
        }
        for ip_item in top_ips:
            ip = ip_item.get("ip", "")
            if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
                regions["国内"] += 1
            else:
                regions["未知"] += 1

        return make_response(data={
            "top_ips": top_ips,
            "region_distribution": regions,
            "total_sources": len(stats["top_source_ips"]),
        })
    except Exception as e:
        return make_error_response(f"获取攻击来源失败: {str(e)}")


# ===========================================================================
# 实时数据
# ===========================================================================

@router.get("/realtime", summary="实时安全数据")
def realtime_data():
    """
    获取实时安全数据（最近事件、实时拦截等）
    """
    try:
        audit = get_audit_service()
        waf = get_waf_engine()

        # 获取最近事件
        recent_events = audit.get_security_events(page=1, page_size=10)

        # WAF 实时状态
        waf_status = waf.get_status()

        return make_response(data={
            "recent_events": recent_events["items"],
            "waf_status": {
                "enabled": waf_status["enabled"],
                "today_blocks": waf_status["today_blocks"],
                "total_blocks": waf_status["total_blocks"],
            },
            "last_updated": __import__("time").time(),
        })
    except Exception as e:
        return make_error_response(f"获取实时数据失败: {str(e)}")


# ===========================================================================
# 辅助函数
# ===========================================================================

def calculate_security_score(stats: dict) -> dict:
    """
    计算安全评分

    基于事件数量和严重级别计算综合安全评分（满分 100）

    Args:
        stats: 统计数据字典

    Returns:
        包含评分、等级、趋势的字典
    """
    score = 100

    # 高危事件扣分
    high_count = stats.get("high_severity_count", 0)
    score -= min(high_count * 10, 40)  # 最多扣 40 分

    # 中危事件扣分
    medium_count = stats.get("medium_severity_count", 0)
    score -= min(medium_count * 3, 20)  # 最多扣 20 分

    # 低危事件扣分
    low_count = stats.get("low_severity_count", 0)
    score -= min(low_count * 0.5, 10)  # 最多扣 10 分

    # 确保分数在 0-100 之间
    score = max(0, min(100, int(score)))

    # 等级划分
    if score >= 90:
        level = "excellent"  # 优秀
    elif score >= 75:
        level = "good"  # 良好
    elif score >= 60:
        level = "fair"  # 一般
    elif score >= 40:
        level = "poor"  # 较差
    else:
        level = "critical"  # 危险

    # 趋势（简化：根据今日事件数判断）
    today_events = stats.get("events_today", 0)
    if today_events == 0:
        trend = "stable"
    elif today_events < 5:
        trend = "stable"
    elif today_events < 20:
        trend = "rising"
    else:
        trend = "alert"

    return {
        "score": score,
        "level": level,
        "trend": trend,
    }
