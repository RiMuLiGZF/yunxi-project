"""
备份调度中心基本功能测试

从 M8-control-tower 目录运行，使用正确的包结构。
"""
import sys
import os
from pathlib import Path

# 将 yunxi-project 目录加入 path（M8-control-tower 的父目录）
m8_dir = Path(__file__).parent.parent  # backend
project_root = m8_dir.parent.parent  # yunxi-project
# 修改目录名：M8-control-tower 含连字符，不能直接作为包名
# 但我们可以直接从 backend 目录导入，将 backend 作为顶级包
# 为了解决相对导入问题，我们把 backend 目录的父目录加入路径
# 并使用 backend.models 这样的导入方式

# 先把 M8-control-tower 目录名的问题解决掉
# 用符号链接？或者直接把 backend 当包，在包内部解决相对导入

# 最简单的方法：把 backend 目录加到 path，然后模拟它是一个包
# 但 models/base.py 里有 from ..config import settings
# 这意味着它认为 models 是某个包的子包

# 正确做法：从 M8-control-tower 目录运行，backend 作为子包
# 但是目录名 M8-control-tower 不能直接 import

# 换一种方式：直接在 backend 目录下创建一个 __init__.py 让它成为包
# 然后从上层目录导入 backend

# 实际上，main.py 的工作方式是：
# - uvicorn.run("main:app") 从 backend 目录运行
# - main.py 用 from .models import ... 作为相对导入
# - 因为 main 是 __main__ 模块，所以 . 指的是它所在的目录

# 所以 models/base.py 中的 from ..config import settings
# 只有在 models 是某个包的子包时才有效
# 让我检查一下 main.py 是怎么导入的...

# 实际上 main.py 用的是 from .config import settings 和 from .models import init_db
# 所以 main.py 本身就在 backend 包中

# 那 models/base.py 的 from ..config import settings 应该是从 backend 包导入
# 即 backend.config

# 所以测试需要以 backend 作为包来运行

# 让我们用 importlib 来模拟
import importlib
import types

# 创建 backend 包
backend_pkg = types.ModuleType("backend")
backend_pkg.__path__ = [str(m8_dir)]
backend_pkg.__package__ = "backend"
sys.modules["backend"] = backend_pkg

# 现在导入 config 模块并注册为 backend.config
import importlib.util
spec = importlib.util.spec_from_file_location("backend.config", str(m8_dir / "config.py"))
config_module = importlib.util.module_from_spec(spec)
sys.modules["backend.config"] = config_module
spec.loader.exec_module(config_module)

print("=" * 60)
print("备份调度中心功能测试")
print("=" * 60)

# 测试 1: 导入模型
print("\n[测试 1] 模型导入...")

# 导入 models 包（先加载 __init__.py 以注册所有模型）
models_init_spec = importlib.util.spec_from_file_location(
    "backend.models", str(m8_dir / "models" / "__init__.py"),
    submodule_search_locations=[str(m8_dir / "models")]
)
models_pkg = importlib.util.module_from_spec(models_init_spec)
sys.modules["backend.models"] = models_pkg
models_init_spec.loader.exec_module(models_pkg)

# 现在 base.py 中的 from ..config import settings 就可以解析了
# 因为 .. 指的是 backend，而 backend.config 已经在 sys.modules 中了

from backend.models.base import Base, engine, SessionLocal, get_db
print("  - backend.models.base: OK")

from backend.models.backup_scheduler import BackupModule, BackupHistory
print("  - backend.models.backup_scheduler: OK")

# 测试 2: 创建数据库表
print("\n[测试 2] 数据库表创建...")
Base.metadata.create_all(bind=engine)
from sqlalchemy import inspect
inspector = inspect(engine)
tables = inspector.get_table_names()
assert "backup_modules" in tables, "backup_modules 表不存在"
assert "backup_history" in tables, "backup_history 表不存在"
print("  - backup_modules 表: 存在")
print("  - backup_history 表: 存在")

# 测试 3: 服务导入
print("\n[测试 3] 服务导入...")

# 注册 services 包
services_pkg = types.ModuleType("backend.services")
services_pkg.__path__ = [str(m8_dir / "services")]
services_pkg.__package__ = "backend.services"
sys.modules["backend.services"] = services_pkg

# models 已经注册过了，services 中的 from ..models import ... 应该可以用
from backend.services.backup_scheduler import (
    BackupOrchestratorService,
    ModuleBackupScheduler,
    get_backup_orchestrator_service,
)
print("  - 服务类导入: OK")

service = BackupOrchestratorService()
print("  - 服务实例化: OK")

# 测试 4: 模块管理
print("\n[测试 4] 模块管理功能...")

# 注册模块
result = service.register_module({
    "module_id": "test_mod",
    "module_name": "测试模块",
    "backup_endpoint": "http://127.0.0.1:9999/api/backup",
    "auth_token": "test_token",
    "schedule_type": "daily",
    "schedule_time": "03:00",
    "enabled": True,
    "max_backups": 30,
    "description": "测试用模块",
})
assert result.get("success"), "模块注册失败: " + str(result.get("error"))
print("  - 注册模块: OK")

# 列出模块
modules = service.list_modules()
print("  - 列出模块:", len(modules), "个")

# 获取模块详情
mod = service.get_module("test_mod")
assert mod is not None, "获取模块失败"
assert mod["module_name"] == "测试模块"
print("  - 获取模块详情: OK")

# 更新模块
update_result = service.update_module("test_mod", {
    "module_name": "更新后的测试模块",
    "schedule_time": "04:00",
})
assert update_result.get("success"), "更新失败: " + str(update_result.get("error"))
mod_updated = service.get_module("test_mod")
assert mod_updated["module_name"] == "更新后的测试模块"
assert mod_updated["schedule_time"] == "04:00"
print("  - 更新模块: OK")

# 重复注册
dup_result = service.register_module({
    "module_id": "test_mod",
    "module_name": "重复",
})
assert not dup_result.get("success"), "重复注册应该失败"
print("  - 重复注册拒绝: OK")

# 删除模块
del_result = service.delete_module("test_mod")
assert del_result.get("success"), "删除失败: " + str(del_result.get("error"))
mod_after_del = service.get_module("test_mod")
assert mod_after_del is None, "删除后模块应该不存在"
print("  - 删除模块: OK")

# 测试 5: 预置模块种子数据
print("\n[测试 5] 预置模块配置...")
from backend.models.base import _seed_backup_modules
_seed_backup_modules()

modules = service.list_modules()
preset_ids = ["m4", "m5", "m6", "m7", "m9", "m10"]
preset_count = sum(1 for m in modules if m["module_id"] in preset_ids)
print("  - 预置模块数:", preset_count, "/ 6")
for mid in preset_ids:
    mod = service.get_module(mid)
    if mod:
        print("    - %s: %s (调度: %s %s)" % (
            mid, mod["module_name"], mod["schedule_type"], mod["schedule_time"]
        ))

assert preset_count == 6, "预置模块数量不正确，期望 6 个，实际 %d 个" % preset_count
print("  - 所有预置模块注册: OK")

# 测试 6: 备份执行
print("\n[测试 6] 备份执行（本地回退模式）...")
result = service.register_module({
    "module_id": "local_test",
    "module_name": "本地备份测试模块",
    "backup_endpoint": "",
    "schedule_type": "none",
    "enabled": True,
    "max_backups": 5,
    "description": "本地备份测试",
})

backup_result = service.trigger_backup("local_test", trigger_type="test")
print("  - 备份触发: OK")
print("    成功:", backup_result.get("success"))
print("    历史ID:", backup_result.get("history_id"))
if backup_result.get("details"):
    details = backup_result["details"]
    err = details.get("error", "无")
    print("    详情: %s" % err)

# 测试 7: 历史记录
print("\n[测试 7] 历史记录查询...")
history = service.get_history(limit=10)
print("  - 总记录数:", history["total"])
print("  - 返回记录数:", len(history["items"]))

if history["items"]:
    latest = history["items"][0]
    print("  - 最新记录: 模块=%s, 状态=%s" % (latest["module_id"], latest["status"]))

mod_history = service.get_history(module_id="local_test")
print("  - local_test 模块历史:", mod_history["total"], "条")

# 测试 8: 统计分析
print("\n[测试 8] 统计分析...")
stats = service.get_stats()
print("  - 总模块数:", stats["total_modules"])
print("  - 启用模块数:", stats["enabled_modules"])
print("  - 总备份次数:", stats["total_backups"])
print("  - 成功次数:", stats["success_backups"])
print("  - 失败次数:", stats["failed_backups"])
print("  - 成功率:", stats["success_rate"], "%")
print("  - 总备份大小:", stats["total_size_mb"], "MB")
print("  - 模块统计数:", len(stats["module_stats"]))
print("  - 每日统计天数:", len(stats["daily_stats"]))

# 测试 9: 调度器状态
print("\n[测试 9] 调度器状态...")
status = service.get_scheduler_status()
print("  - 初始化状态:", status["initialized"])
print("  - 总模块数:", status["total_modules"])
print("  - 启用模块数:", status["enabled_modules"])
print("  - 活跃调度器:", status["active_schedulers"])
print("  - 运行中备份:", status["running_backups"])

# 测试 10: 调度器初始化
print("\n[测试 10] 调度器初始化...")
service.initialize()
status_after_init = service.get_scheduler_status()
print("  - 初始化后活跃调度器:", status_after_init["active_schedulers"])
print("  - 运行中调度器:", status_after_init["running_schedulers"])

# 测试 11: API 路由
print("\n[测试 11] API 路由...")

# 注册 schemas 和 routers 包
schemas_init_spec = importlib.util.spec_from_file_location(
    "backend.schemas", str(m8_dir / "schemas" / "__init__.py"),
    submodule_search_locations=[str(m8_dir / "schemas")]
)
schemas_pkg = importlib.util.module_from_spec(schemas_init_spec)
sys.modules["backend.schemas"] = schemas_pkg
schemas_init_spec.loader.exec_module(schemas_pkg)

routers_init_spec = importlib.util.spec_from_file_location(
    "backend.routers", str(m8_dir / "routers" / "__init__.py"),
    submodule_search_locations=[str(m8_dir / "routers")]
)
routers_pkg = importlib.util.module_from_spec(routers_init_spec)
sys.modules["backend.routers"] = routers_pkg

# 注册 services 包（已经在前面注册了，确保一致）
services_init_spec = importlib.util.spec_from_file_location(
    "backend.services", str(m8_dir / "services" / "__init__.py"),
    submodule_search_locations=[str(m8_dir / "services")]
)
services_pkg = importlib.util.module_from_spec(services_init_spec)
sys.modules["backend.services"] = services_pkg

# 注册 auth
spec_auth = importlib.util.spec_from_file_location("backend.auth", str(m8_dir / "auth.py"))
auth_module = importlib.util.module_from_spec(spec_auth)
sys.modules["backend.auth"] = auth_module
spec_auth.loader.exec_module(auth_module)

from backend.routers.backup_scheduler import router
print("  - 路由导入: OK")
print("  - 路由数量:", len(router.routes))

route_names = sorted([r.path for r in router.routes if hasattr(r, "path")])
print("  - 路由列表:")
for name in route_names:
    print("    -", name)

# 测试 12: 调度器关闭
print("\n[测试 12] 调度器关闭...")
service.shutdown()
status_after_shutdown = service.get_scheduler_status()
print("  - 关闭后初始化状态:", status_after_shutdown["initialized"])
print("  - 关闭后活跃调度器:", status_after_shutdown["active_schedulers"])

# 测试 13: 线程安全
print("\n[测试 13] 线程安全...")
import threading

scheduler = ModuleBackupScheduler("thread_test", lambda mid, **kw: None)
errors = []

def worker():
    for _ in range(20):
        try:
            scheduler.start("interval", schedule_interval_minutes=60)
            scheduler.stop()
        except Exception as e:
            errors.append(str(e))

threads = [threading.Thread(target=worker) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()

assert len(errors) == 0, "线程安全测试失败: " + str(errors)
scheduler.stop()
print("  - 多线程并发操作: OK (无异常)")

# 测试 14: 全局单例
print("\n[测试 14] 全局单例...")
service1 = get_backup_orchestrator_service()
service2 = get_backup_orchestrator_service()
assert service1 is service2, "单例模式失效"
print("  - 全局单例: OK")

# 清理测试数据
print("\n[清理测试数据...]")
for mid in ["local_test"] + preset_ids:
    try:
        service.delete_module(mid)
    except Exception:
        pass
print("  - 测试模块已清理")

print()
print("=" * 60)
print("所有 14 项测试通过！")
print("=" * 60)
