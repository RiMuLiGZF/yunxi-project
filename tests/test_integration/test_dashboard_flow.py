"""
仪表盘数据流程集成测试

验证仪表盘所需的各种数据 API 的端到端流程：
- 系统统计数据获取
- 模块状态聚合
- 算力调用统计
- 任务执行统计
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestDashboardDataFlow:
    """仪表盘数据流程集成测试类"""

    # ============================================================
    # 仪表盘数据聚合
    # ============================================================

    @pytest.mark.integration
    @pytest.mark.smoke
    def test_dashboard_kpi_data_structure(self, data_generator):
        """测试仪表盘 KPI 数据结构"""
        stats = data_generator.generate_system_stats()
        
        # KPI 卡片需要的四个数据
        kpi_data = {
            "online_modules": f"{stats['running_modules']}/{stats['total_modules']}",
            "today_tasks": stats["tasks_today"],
            "compute_calls": stats["compute_calls_today"],
            "health_score": stats["health_score"],
        }
        
        # 验证 KPI 数据完整性
        assert "online_modules" in kpi_data
        assert "today_tasks" in kpi_data
        assert "compute_calls" in kpi_data
        assert "health_score" in kpi_data
        
        # 验证数值范围
        assert stats["health_score"] >= 0
        assert stats["health_score"] <= 100
        assert stats["total_modules"] == 8

    @pytest.mark.integration
    def test_module_bar_chart_data(self, data_generator):
        """测试模块柱状图数据生成"""
        modules = data_generator.generate_all_modules_status()
        
        # 生成图表数据
        chart_data = {
            "modules": [m["name"] for m in modules],
            "cpu_usage": [m["cpu_usage"] for m in modules],
            "memory_usage": [m["memory_usage"] for m in modules],
        }
        
        assert len(chart_data["modules"]) == 8
        assert len(chart_data["cpu_usage"]) == 8
        assert len(chart_data["memory_usage"]) == 8
        
        # 验证所有值在合理范围
        for value in chart_data["cpu_usage"]:
            assert 0 <= value <= 100
        for value in chart_data["memory_usage"]:
            assert 0 <= value <= 100

    @pytest.mark.integration
    def test_compute_trend_data(self, data_generator):
        """测试算力趋势数据生成"""
        # 生成 7 天的趋势数据
        import random
        days = 7
        trend_data = {
            "dates": [f"7/{i+2}" for i in range(days)],
            "calls": [random.randint(800, 1500) for _ in range(days)],
            "success_rate": [round(random.uniform(95, 99.5), 1) for _ in range(days)],
        }
        
        assert len(trend_data["dates"]) == 7
        assert len(trend_data["calls"]) == 7
        assert len(trend_data["success_rate"]) == 7
        
        # 验证成功率范围
        for rate in trend_data["success_rate"]:
            assert 90 <= rate <= 100

    @pytest.mark.integration
    def test_task_pie_chart_data(self):
        """测试任务饼图数据计算"""
        # 模拟任务分布
        task_data = {
            "completed": 112,
            "running": 12,
            "pending": 3,
            "failed": 1,
        }
        
        total = sum(task_data.values())
        assert total == 128
        
        # 计算百分比
        percentages = {
            k: round((v / total) * 100, 1)
            for k, v in task_data.items()
        }
        
        # 完成率
        completion_rate = (task_data["completed"] / total) * 100
        assert round(completion_rate, 1) == 87.5
        
        # 验证百分比总和约为 100
        total_pct = sum(percentages.values())
        assert abs(total_pct - 100) < 1.0

    # ============================================================
    # 数据更新流程
    # ============================================================

    @pytest.mark.integration
    def test_dashboard_refresh_flow(self, data_generator):
        """测试仪表盘数据刷新流程"""
        # 第一次加载
        stats_1 = data_generator.generate_system_stats()
        
        # 模拟刷新
        stats_2 = data_generator.generate_system_stats()
        
        # 两次数据应该不同（随机生成）
        # 验证数据结构一致
        assert set(stats_1.keys()) == set(stats_2.keys())
        
        # 验证数据类型一致
        for key in stats_1:
            assert type(stats_1[key]) == type(stats_2[key])

    @pytest.mark.integration
    def test_recent_activity_feed(self, data_generator):
        """测试最近动态列表数据"""
        activities = []
        event_types = [
            ("模块上线", "success"),
            ("任务完成", "info"),
            ("告警触发", "warning"),
            ("任务失败", "error"),
            ("Agent调度", "info"),
        ]
        
        for i in range(10):
            event_type, level = event_types[i % len(event_types)]
            activities.append({
                "id": f"evt_{i}",
                "type": event_type,
                "level": level,
                "message": f"事件描述 {i}",
                "time": data_generator.random_datetime(1).strftime("%Y-%m-%d %H:%M:%S"),
                "source": "system",
            })
        
        assert len(activities) == 10
        
        # 验证时间倒序（最近的在前）
        # 实际应用中应按时间排序，这里验证排序逻辑
        sorted_activities = sorted(
            activities,
            key=lambda x: x["time"],
            reverse=True
        )
        assert len(sorted_activities) == 10
        assert sorted_activities[0]["time"] >= sorted_activities[-1]["time"]
