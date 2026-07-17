"""
数据主权与去重管理工具
==================

提供数据主权查询、重叠检测和去重管理的工具函数。
各模块可通过本模块查询数据主权信息，
避免直接依赖数据主权清单。

使用方式：
    from data_governance.sovereignty import get_module_sovereignty, check_data_owner
"""

import json
import os
from pathlib import Path
from typing import Optional


# 数据主权清单文件路径
_SOVEREIGNTY_FILE = Path(__file__).parent / "data_sovereignty.json"

# 缓存
_cache: Optional[dict] = None


def load_sovereignty() -> dict:
    """加载数据主权清单"""
    global _cache
    if _cache is not None:
        return _cache

    if not _SOVEREIGNTY_FILE.exists():
        return {"modules": {}, "version": "unknown"}

    with open(_SOVEREIGNTY_FILE, "r", encoding="utf-8") as f:
        _cache = json.load(f)
    return _cache


def get_module_sovereignty(module_id: str) -> Optional[dict]:
    """获取指定模块的数据主权信息"""
    data = load_sovereignty()
    return data.get("modules", {}).get(module_id)


def check_data_owner(domain: str) -> Optional[str]:
    """
    查询某个数据域的权威拥有者模块
    
    Args:
        domain: 数据域名称，如 "life_management", "study_plan", "growth",
                "watch", "workflow", "work_dev" 等
    
    Returns:
        模块 ID（如 "M4"），如果找不到返回 None
    """
    domain_map = {
        # 生活管理 - M4
        "life": "M4",
        "life_management": "M4",
        "life_schedule": "M4",
        "life_todo": "M4",
        "life_habit": "M4",
        "life_finance": "M4",
        # 学业规划 - M4
        "study": "M4",
        "study_plan": "M4",
        "study_goal": "M4",
        "education": "M4",
        # 复盘总结 - M4
        "review": "M4",
        "diary": "M4",
        # 人际关系 - M4
        "social": "M4",
        "social_contact": "M4",
        "relationship": "M4",
        # 情绪陪伴 - M4/M5
        "emotion": "M4",
        "mood": "M4",
        "relax": "M4",
        "sleep": "M4",
        # 形象工坊 - M4
        "appearance": "M4",
        "personality": "M4",
        # 场景引擎 - M4
        "scene": "M4",
        "scene_engine": "M4",
        # 成长系统 - M5
        "growth": "M5",
        "achievement": "M5",
        "talent": "M5",
        "season": "M5",
        # 记忆系统 - M5
        "memory": "M5",
        "tide_memory": "M5",
        # 手表/可穿戴 - M6
        "watch": "M6",
        "wearable": "M6",
        "health_data": "M6",
        # 工作流 - M7
        "workflow": "M7",
        # 工作开发 - M9
        "work": "M9",
        "work_dev": "M9",
        "dev_workshop": "M9",
        # 算力调度 - M8
        "compute": "M8",
        "compute_scheduling": "M8",
        # 自进化 - M8
        "evolution": "M8",
        "self_evolution": "M8",
        # 系统监控 - M10
        "system_guard": "M10",
        "monitoring": "M10",
        "metrics": "M10",
        # 安全 - M12
        "security": "M12",
        "safety": "M12",
    }
    return domain_map.get(domain.lower())


def list_overlapping_domains() -> list[dict]:
    """
    列出所有存在数据重叠的域及其去重方案"""
    data = load_sovereignty()
    overlaps = []

    m8 = data.get("modules", {}).get("M8", {})
    to_deprecate = m8.get("tables_to_deprecate", {})

    # 只保留值为 dict 的条目（跳过 note 等说明字段）
    domain_items = {
        k: v for k, v in to_deprecate.items()
        if isinstance(v, dict) and "target" in v
    }

    priority_map = {"P0": 0, "P1": 1, "P2": 2}
    sorted_domains = sorted(
        domain_items.items(),
        key=lambda x: priority_map.get(x[1].get("priority", "P2"), 99)
    )

    for domain_key, info in sorted_domains:
        overlaps.append({
            "domain": domain_key,
            "target_module": info.get("target"),
            "table_count": info.get("tables", 0),
            "priority": info.get("priority", "P2"),
            "note": info.get("note", ""),
        })

    return overlaps


def get_deduplication_progress() -> dict:
    """
    获取去重工作总体进度概览
    """
    data = load_sovereignty()
    summary = data.get("deduplication_summary", {})
    return {
        "total_overlapping_domains": summary.get("total_overlapping_domains", 0),
        "total_overlapping_tables": summary.get("total_overlapping_tables_approx", 0),
        "priority_distribution": summary.get("priority_distribution", {}),
        "phases": summary.get("estimated_phases", 0),
    }


# 便捷别名
# 导出
if __name__ == "__main__":
    # 测试
    print("=== 数据主权清单测试")
    print(f"版本: {load_sovereignty().get('version', 'unknown')}")
    print()
    
    print("=== 各模块核心数据域:")
    for mod_id, mod_info in load_sovereignty().get("modules", {}).items():
        print(f"  {mod_id} ({mod_info.get('name')}: {len(mod_info.get('core_domains', []))} 个核心域")
    
    print()
    print("=== 数据域权威方查询:")
    for domain in ["life", "growth", "watch", "workflow", "compute"]:
        owner = check_data_owner(domain)
        print(f"  {domain} -> {owner}")
    
    print()
    print("=== 去重任务清单 (按优先级):")
    for item in list_overlapping_domains():
        print(f"  [{item['priority']}] {item['domain']}: {item['table_count']}张表 -> {item['target_module']}")
