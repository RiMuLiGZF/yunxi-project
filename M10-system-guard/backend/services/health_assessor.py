"""
云汐 M10 系统卫士 - A4 健康评估与风险预测服务
负责系统健康度综合评分、各维度评估和风险预测
沙盒模式下使用模拟数据进行评估
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# 兼容相对导入和直接运行
try:
    from ..config import get_settings
    from ..mock_data_engine import get_mock_engine
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import get_settings
    from mock_data_engine import get_mock_engine


class HealthAssessorService:
    """
    健康评估与风险预测服务
    提供综合健康评分、各维度详细评分、风险预测和健康趋势
    """

    def __init__(self):
        """初始化健康评估服务"""
        self.settings = get_settings()
        self.mock_engine = get_mock_engine()

    def get_health_score(self) -> Dict[str, Any]:
        """
        获取综合健康评分

        Returns:
            综合健康评分结果字典
        """
        return self.mock_engine.generate_health_score()

    def get_dimension_scores(self) -> Dict[str, Any]:
        """
        获取各维度详细评分

        Returns:
            各维度评分详情字典
        """
        health = self.mock_engine.generate_health_score()

        dimensions = health["dimensions"]
        result = {
            "total_score": health["total_score"],
            "level": health["level"],
            "level_text": health["level_text"],
            "description": health["description"],
            "dimensions": [],
            "timestamp": health["timestamp"],
        }

        for key, dim in dimensions.items():
            dimension_detail = {
                "key": key,
                "name": dim["name"],
                "score": dim["score"],
                "weight": dim["weight"],
                "weighted_score": round(dim["score"] * dim["weight"] / 100, 1),
                "level": self._get_level(dim["score"]),
            }

            # 添加各维度的详细指标
            metrics = self.mock_engine.generate_system_metrics()
            if key == "cpu":
                dimension_detail["metrics"] = {
                    "usage_percent": metrics["cpu"]["percent"],
                    "temp": metrics["cpu"]["temp"],
                    "load_avg_1min": metrics["cpu"]["load_avg"][0],
                }
            elif key == "memory":
                dimension_detail["metrics"] = {
                    "usage_percent": metrics["memory"]["percent"],
                    "available_gb": metrics["memory"]["available_gb"],
                    "swap_percent": metrics["memory"]["swap_percent"],
                }
            elif key == "disk":
                c_usage = metrics["disk"]["usage"].get("C:", {})
                dimension_detail["metrics"] = {
                    "c_usage_percent": c_usage.get("percent", 0),
                    "c_free_gb": c_usage.get("free_gb", 0),
                    "busy_percent": metrics["disk"]["busy_percent"],
                }
            elif key == "network":
                dimension_detail["metrics"] = {
                    "latency_ms": metrics["network"]["latency_ms"],
                    "packet_loss": metrics["network"]["packet_loss"],
                    "connection_count": metrics["network"]["connection_count"],
                }
            elif key == "temperature":
                dimension_detail["metrics"] = {
                    "cpu_temp": metrics["cpu"]["temp"],
                    "gpu_temp": metrics["gpu"]["temp"],
                }
            elif key == "battery":
                dimension_detail["metrics"] = {
                    "percent": metrics["battery"]["percent"],
                    "power_plugged": metrics["battery"]["power_plugged"],
                    "health_percent": metrics["battery"]["health_percent"],
                }
            elif key == "process":
                dimension_detail["metrics"] = {
                    "process_count": metrics["system"]["process_count"],
                }

            result["dimensions"].append(dimension_detail)

        return result

    def _get_level(self, score: float) -> str:
        """
        根据分数获取等级

        Args:
            score: 分数

        Returns:
            等级标识
        """
        if score >= 90:
            return "excellent"
        elif score >= 70:
            return "good"
        elif score >= 50:
            return "fair"
        else:
            return "poor"

    def get_risk_prediction(self) -> Dict[str, Any]:
        """
        获取风险预测（未来10分钟）

        Returns:
            风险预测结果字典
        """
        return self.mock_engine.generate_risk_prediction()

    def get_health_trend(self, minutes: int = 30) -> List[dict]:
        """
        获取健康趋势数据

        Args:
            minutes: 趋势时长（分钟）

        Returns:
            趋势数据点列表
        """
        return self.mock_engine.generate_health_trend(minutes=minutes)

    def get_health_report(self) -> Dict[str, Any]:
        """
        获取完整健康报告

        Returns:
            健康报告字典
        """
        health_score = self.get_health_score()
        dimensions = self.get_dimension_scores()
        risk = self.get_risk_prediction()
        trend = self.get_health_trend(60)

        # 生成建议
        suggestions = self._generate_suggestions(health_score, risk)

        return {
            "score": health_score["total_score"],
            "level": health_score["level"],
            "level_text": health_score["level_text"],
            "description": health_score["description"],
            "dimensions": dimensions["dimensions"],
            "risk_prediction": risk,
            "trend_1h": trend,
            "suggestions": suggestions,
            "generated_at": datetime.now().isoformat(),
        }

    def _generate_suggestions(self, health_score: dict, risk: dict) -> List[str]:
        """
        根据健康状况生成优化建议

        Args:
            health_score: 健康评分
            risk: 风险预测

        Returns:
            建议列表
        """
        suggestions = []
        dims = health_score["dimensions"]

        if dims["memory"]["score"] < 70:
            suggestions.append("内存使用率偏高，建议关闭不必要的应用程序")
            suggestions.append("可考虑增加内存或使用更轻量的替代方案")

        if dims["cpu"]["score"] < 70:
            suggestions.append("CPU负载较高，建议减少并发任务数量")
            suggestions.append("检查是否有后台进程占用过多CPU资源")

        if dims["temperature"]["score"] < 70:
            suggestions.append("系统温度偏高，建议改善散热条件")
            suggestions.append("可考虑降低高负载任务的运行频率")

        if dims["disk"]["score"] < 70:
            suggestions.append("磁盘空间不足，建议清理临时文件和回收站")
            suggestions.append("可使用磁盘清理工具释放空间")

        if dims["battery"]["score"] < 70:
            suggestions.append("电池电量较低，请及时充电")
            suggestions.append("可开启节能模式延长续航时间")

        if dims["network"]["score"] < 70:
            suggestions.append("网络状况不佳，建议检查网络连接")
            suggestions.append("可尝试切换网络或重启路由器")

        # 风险相关建议
        for warning in risk.get("warnings", []):
            if warning["type"] == "memory_exhaustion":
                suggestions.append("⚠️ 内存即将耗尽，请立即关闭占用内存的程序")
            elif warning["type"] == "high_cpu_load":
                suggestions.append("⚠️ CPU持续高负载，注意系统稳定性")
            elif warning["type"] == "overheat_risk":
                suggestions.append("⚠️ 存在过热风险，请降低系统负载")

        if not suggestions:
            suggestions.append("系统状态良好，继续保持")
            suggestions.append("建议定期进行系统维护和清理")

        return suggestions


# 全局单例
_health_assessor: Optional[HealthAssessorService] = None


def get_health_assessor() -> HealthAssessorService:
    """获取健康评估服务单例"""
    global _health_assessor
    if _health_assessor is None:
        _health_assessor = HealthAssessorService()
    return _health_assessor


# 兼容直接运行测试
if __name__ == "__main__":
    service = get_health_assessor()

    print("=== 综合健康评分 ===")
    score = service.get_health_score()
    print(f"总分: {score['total_score']} ({score['level_text']})")

    print("\n=== 各维度评分 ===")
    dims = service.get_dimension_scores()
    for d in dims["dimensions"]:
        print(f"  {d['name']}: {d['score']}分 (权重{d['weight']}%)")

    print("\n=== 风险预测 ===")
    risk = service.get_risk_prediction()
    print(f"总体风险等级: {risk['overall_risk_level']}")
    print(f"预警数量: {len(risk['warnings'])}")
    for w in risk["warnings"]:
        print(f"  - [{w['level']}] {w['message']}")
