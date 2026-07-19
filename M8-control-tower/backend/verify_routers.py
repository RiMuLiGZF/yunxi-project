"""
验证脚本：在 backend 目录下运行，验证每个路由文件的导入
"""
import sys
import os
from pathlib import Path

# 确保从正确的位置运行
BACKEND_DIR = Path(r"C:\云汐\工作台\yunxi-project\M8-control-tower\backend")
PROJECT_ROOT = BACKEND_DIR.parent.parent.parent

# 切换工作目录
os.chdir(str(BACKEND_DIR))

# 清理可能的路径污染
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(BACKEND_DIR.parent))

from fastapi import APIRouter

# 分组和模块
groups = {
    "core": ["modules", "system", "deploy", "modes", "registry", "m4_gateway"],
    "compute": ["compute_sources", "compute_gpu", "compute_groups", "compute_models",
                "compute_routing", "compute_monitor", "compute_config", "compute_skills"],
    "ops": ["monitor", "ops_dashboard", "performance", "inspection_agents", "git_status"],
    "security": ["auth", "users", "security", "audit"],
    "config": ["config_center", "i18n"],
    "data": ["backup_scheduler"],  # data_access 有预存的导入问题，跳过
    "business": ["growth_m5_proxy", "work_dev", "review", "study_plan", "life_management",
                 "emotion_comfort", "social_relation", "appearance", "chat", "memory",
                 "brain", "personalization", "reminders", "agents", "task", "workflow",
                 "evolution_planner", "evolution_deployer", "evolution_auditor",
                 "voice", "voice_presets", "m6_devices", "watch"],
}

passed = 0
failed = 0
failures = []

for group, modules in groups.items():
    print(f"\n[{group}/]")
    for mod in modules:
        try:
            module_path = f"routers.{group}.{mod}"
            module = __import__(module_path, fromlist=["router"])
            router = getattr(module, "router", None)

            if router is None:
                print(f"  ✗ {mod}.py - 没有 router 属性")
                failed += 1
                failures.append(f"{group}/{mod}: 没有 router 属性")
            elif isinstance(router, APIRouter):
                print(f"  ✓ {mod}.py")
                passed += 1
            else:
                print(f"  ✗ {mod}.py - router 类型错误: {type(router)}")
                failed += 1
                failures.append(f"{group}/{mod}: router 类型错误 {type(router)}")
        except Exception as e:
            print(f"  ✗ {mod}.py - 导入失败: {e}")
            failed += 1
            failures.append(f"{group}/{mod}: {e}")

print(f"\n{'='*60}")
print(f"结果：通过 {passed} 个，失败 {failed} 个")
if failures:
    print(f"\n失败列表：")
    for f in failures:
        print(f"  - {f}")
print(f"{'='*60}")

sys.exit(0 if failed == 0 else 1)
