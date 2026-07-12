"""
M5 潮汐分层记忆系统
启动入口

⚠️ 高涉密模块 - 所有用户记忆数据本地加密存储，绝不上传云端
"""

import os
import sys
from pathlib import Path

# 确保 src 目录在路径中
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tide_memory.core.config import TideConfig
from tide_memory.core.skill_interface import TideSkillInterface
from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
from tide_memory.audit.audit_logger import AuditLogger


def create_app(config_path: str = None) -> dict:
    """
    创建并初始化潮汐记忆系统应用实例
    
    Args:
        config_path: 配置文件路径，默认使用环境变量或默认配置
    
    Returns:
        应用上下文字典
    """
    # 1. 加载配置
    config = TideConfig(config_path)
    
    # 2. 安全标记系统初始化
    secret_marker = SecretMarker(default_level=ClassificationLevel.TOP_SECRET)
    
    # 3. 审计日志初始化
    audit = AuditLogger(config.get("audit.log_path", "./logs/m5-audit.log"))
    
    # 4. 初始化记忆层
    from tide_memory.layers.l0_beach import BeachLayer
    from tide_memory.layers.l1_shallow import ShallowLayer
    from tide_memory.layers.l2_deep import DeepLayer
    from tide_memory.layers.l3_abyss import AbyssLayer
    
    l0 = BeachLayer(config.get("memory.layers.l0_beach", {}))
    l1 = ShallowLayer(config.get("memory.layers.l1_shallow", {}))
    l2 = DeepLayer(config.get("memory.layers.l2_deep", {}))
    l3 = AbyssLayer(config.get("memory.layers.l3_abyss", {}))
    
    # 5. 情绪引擎初始化
    from tide_memory.emotion.ei_model import EIEngine
    from tide_memory.emotion.valence_arousal import ValenceArousalModel
    va_model = ValenceArousalModel()
    ei_engine = EIEngine(va_model)
    
    # 6. 检索引擎初始化
    from tide_memory.recall.recall_engine import RecallEngine
    recall = RecallEngine(l0, l1, l2, l3, ei_engine)
    
    # 7. 域权限管理器
    from tide_memory.security.domain_manager import DomainManager
    domain_manager = DomainManager()
    
    # 8. 睡眠巩固引擎
    from tide_memory.sleep.consolidation import ConsolidationEngine
    consolidation = ConsolidationEngine(l0, l1, l2, l3, ei_engine)
    
    # 9. Skill接口
    skill_if = TideSkillInterface(recall, domain_manager, audit)
    
    app = {
        "config": config,
        "layers": {"l0": l0, "l1": l1, "l2": l2, "l3": l3},
        "emotion": ei_engine,
        "recall": recall,
        "domain_manager": domain_manager,
        "consolidation": consolidation,
        "secret_marker": secret_marker,
        "audit": audit,
        "skill_interface": skill_if,
    }
    
    # 10. 启动定时巩固调度器（如果配置开启）
    if config.get("memory.sleep_consolidation", True):
        from tide_memory.sleep.scheduler import start_scheduler
        scheduler = start_scheduler(app)
        app["scheduler"] = scheduler
    
    return app


def main():
    """命令行启动入口"""
    import argparse
    parser = argparse.ArgumentParser(description="M5 潮汐分层记忆系统")
    parser.add_argument("--config", "-c", help="配置文件路径")
    parser.add_argument("--check", action="store_true", help="环境检查")
    parser.add_argument("--consolidate", action="store_true", help="手动触发巩固")
    args = parser.parse_args()
    
    app = create_app(args.config)
    
    if args.check:
        print("✅ M5潮汐记忆系统环境检查通过")
        print(f"   版本: {SYSTEM_VERSION}")
        print(f"   四层存储: L0沙滩 / L1浅水 / L2深水 / L3深海")
        print(f"   密级: 高涉密 - 数据仅本地存储")
        return 0
    
    if args.consolidate:
        app["consolidation"].run_consolidation()
        print("✅ 记忆巩固完成")
        return 0
    
    print(f"M5潮汐记忆系统 {SYSTEM_VERSION}")
    print("高涉密模块 - 数据仅本地加密存储")
    return 0


# 系统版本号（统一从 shared.version 导入）
def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        # 查找项目根目录并加入 sys.path
        from pathlib import Path
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        # 回退到模块内定义的版本
        try:
            from tide_memory import __version__
            return __version__
        except Exception:
            return "v2.4.0-REV2"


SYSTEM_VERSION = _load_system_version()


if __name__ == "__main__":
    sys.exit(main())
# vim: set et ts=4 sw=4:
