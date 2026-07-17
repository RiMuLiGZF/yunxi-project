"""
云汐故障演练框架 (Chaos Engineering)

提供生产级故障注入和演练能力：
- 故障注入工具（模块故障、网络延迟、错误响应、资源耗尽）
- 演练脚本（模块宕机、数据库切换、网络分区、全系统恢复）
- 演练报告（目标、步骤、响应、恢复时间、改进项）

使用方式：
    from shared.core.chaos import (
        ChaosEngine,
        FaultInjector,
        DrillsRunner,
        DrillReport,
    )
"""

from .fault_injector import (
    FaultInjector,
    FaultType,
    FaultState,
    FaultSeverity,
    InjectedFault,
)
from .drill_runner import (
    DrillsRunner,
    DrillScript,
    DrillStep,
    DrillStatus,
    module_outage_drill,
    database_failover_drill,
    network_partition_drill,
    full_system_recovery_drill,
)
from .drill_report import (
    DrillReport,
    ReportGenerator,
    DrillResult,
    ImprovementItem,
)

__all__ = [
    # 故障注入
    "FaultInjector",
    "FaultType",
    "FaultState",
    "FaultSeverity",
    "InjectedFault",
    # 演练
    "DrillsRunner",
    "DrillScript",
    "DrillStep",
    "DrillStatus",
    "module_outage_drill",
    "database_failover_drill",
    "network_partition_drill",
    "full_system_recovery_drill",
    # 报告
    "DrillReport",
    "ReportGenerator",
    "DrillResult",
    "ImprovementItem",
]
