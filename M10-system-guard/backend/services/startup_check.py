"""
云汐 M10 系统卫士 - A3 启动安全检查服务
为其他模块提供启动前安全评估，预防资源耗尽
沙盒模式下使用模拟数据进行评估
"""

from datetime import datetime
from typing import Optional, Dict, Any

# 兼容相对导入和直接运行
try:
    from ..config import get_settings
    from ..mock_data_engine import get_mock_engine
    from ..database import get_session
    from ..models import StartupCheckLog
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import get_settings
    from mock_data_engine import get_mock_engine
    from database import get_session
    from models import StartupCheckLog


class StartupCheckService:
    """
    启动安全检查服务
    实现评分算法、等级判定、智能建议生成和调用日志记录
    """

    def __init__(self):
        """初始化启动安全检查服务"""
        self.settings = get_settings()
        self.mock_engine = get_mock_engine()

        # 同类进程数阈值配置
        self.instance_thresholds = {
            "vscode-instance": {"warning": 5, "danger": 8},
            "browser-instance": {"warning": 10, "danger": 20},
            "model-load": {"warning": 2, "danger": 3},
            "batch-generation": {"warning": 10, "danger": 20},
            "default": {"warning": 5, "danger": 10},
        }

    def check(self, module: str = "m9",
              task_type: str = "vscode-instance",
              expected_memory_mb: int = 500,
              expected_cpu_percent: float = 5.0,
              instance_count: int = 1,
              priority: str = "normal") -> Dict[str, Any]:
        """
        执行启动安全检查

        Args:
            module: 调用模块标识（如 m9, m4, m8）
            task_type: 任务类型（如 vscode-instance, model-load, batch-generation）
            expected_memory_mb: 预期新增内存占用 (MB)
            expected_cpu_percent: 预期新增CPU占用 (%)
            instance_count: 启动实例数量，默认1
            priority: 优先级：high/normal/low，默认normal

        Returns:
            安全检查结果字典
        """
        # 使用模拟引擎生成结果
        result = self.mock_engine.generate_startup_check_result(
            module=module,
            task_type=task_type,
            expected_memory_mb=expected_memory_mb,
            expected_cpu_percent=expected_cpu_percent,
            instance_count=instance_count,
            priority=priority,
        )

        # 记录调用日志
        self._log_check(
            module=module,
            task_type=task_type,
            expected_memory_mb=expected_memory_mb,
            expected_cpu_percent=expected_cpu_percent,
            instance_count=instance_count,
            priority=priority,
            result=result,
        )

        return result

    def _log_check(self, module: str, task_type: str,
                   expected_memory_mb: int, expected_cpu_percent: float,
                   instance_count: int, priority: str,
                   result: dict):
        """
        记录启动安全检查调用日志

        Args:
            module: 调用模块
            task_type: 任务类型
            expected_memory_mb: 预期内存
            expected_cpu_percent: 预期CPU
            instance_count: 实例数
            priority: 优先级
            result: 检查结果
        """
        try:
            db = get_session()
            log = StartupCheckLog(
                module=module,
                task_type=task_type,
                expected_memory_mb=expected_memory_mb,
                expected_cpu_percent=expected_cpu_percent,
                instance_count=instance_count,
                priority=priority,
                score=result["score"],
                level=result["level"],
                can_start=result["can_start"],
                recommendation=result["recommendation"],
                current_state=result["current_state"],
                after_projection=result["after_projection"],
                suggestions=result["suggestions"],
            )
            db.add(log)
            db.commit()
            db.close()
        except Exception as e:
            print(f"[StartupCheck] 记录日志失败: {e}")

    def get_check_history(self, module: Optional[str] = None,
                          limit: int = 20) -> list:
        """
        获取启动检查历史记录

        Args:
            module: 模块筛选（可选）
            limit: 返回数量限制

        Returns:
            检查历史记录列表
        """
        try:
            db = get_session()
            query = db.query(StartupCheckLog)
            if module:
                query = query.filter(StartupCheckLog.module == module)
            query = query.order_by(StartupCheckLog.checked_at.desc()).limit(limit)
            records = query.all()
            result = [r.to_dict() for r in records]
            db.close()
            return result
        except Exception as e:
            print(f"[StartupCheck] 获取历史记录失败: {e}")
            return []

    def get_statistics(self, module: Optional[str] = None,
                       days: int = 7) -> dict:
        """
        获取启动检查统计数据

        Args:
            module: 模块筛选（可选）
            days: 统计天数

        Returns:
            统计数据字典
        """
        try:
            db = get_session()
            query = db.query(StartupCheckLog)
            if module:
                query = query.filter(StartupCheckLog.module == module)

            from datetime import timedelta
            start_time = datetime.now() - timedelta(days=days)
            query = query.filter(StartupCheckLog.checked_at >= start_time)

            records = query.all()
            db.close()

            total = len(records)
            safe_count = sum(1 for r in records if r.level == "safe")
            warning_count = sum(1 for r in records if r.level == "warning")
            danger_count = sum(1 for r in records if r.level == "danger")
            avg_score = sum(r.score for r in records) / total if total > 0 else 0

            return {
                "total_checks": total,
                "safe_count": safe_count,
                "warning_count": warning_count,
                "danger_count": danger_count,
                "average_score": round(avg_score, 1),
                "safe_rate": round(safe_count / total * 100, 1) if total > 0 else 0,
                "period_days": days,
            }
        except Exception as e:
            print(f"[StartupCheck] 获取统计数据失败: {e}")
            return {
                "total_checks": 0,
                "safe_count": 0,
                "warning_count": 0,
                "danger_count": 0,
                "average_score": 0,
                "safe_rate": 0,
                "period_days": days,
            }


# 全局单例
_startup_check_service: Optional[StartupCheckService] = None


def get_startup_check_service() -> StartupCheckService:
    """获取启动安全检查服务单例"""
    global _startup_check_service
    if _startup_check_service is None:
        _startup_check_service = StartupCheckService()
    return _startup_check_service


# 兼容直接运行测试
if __name__ == "__main__":
    service = get_startup_check_service()

    print("=== 启动安全检查测试 ===")
    result = service.check(
        module="m9",
        task_type="vscode-instance",
        expected_memory_mb=500,
        expected_cpu_percent=5.0,
        instance_count=2,
        priority="normal",
    )

    print(f"评分: {result['score']}")
    print(f"等级: {result['level']}")
    print(f"可启动: {result['can_start']}")
    print(f"建议: {result['recommendation']}")
    print(f"当前内存: {result['current_state']['memory_percent']}%")
    print(f"启动后内存: {result['after_projection']['memory_percent']}%")
    print("详细建议:")
    for s in result["suggestions"]:
        print(f"  - {s}")
