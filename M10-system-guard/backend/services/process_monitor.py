"""
云汐 M10 系统卫士 - A2 进程监控与画像服务
负责进程列表管理、进程树构建、黑白名单管理等功能
沙盒模式下全部使用模拟数据，不调用真实系统API
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 兼容相对导入和直接运行
try:
    from ..config import get_settings
    from ..mock_data_engine import get_mock_engine
    from ..database import get_session
    from ..models import ProcessWhitelist, ProcessBlacklist
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import get_settings
    from mock_data_engine import get_mock_engine
    from database import get_session
    from models import ProcessWhitelist, ProcessBlacklist


class ProcessMonitorService:
    """
    进程监控与画像服务
    提供进程列表查询、进程树、Top N排行、黑白名单管理等功能
    """

    def __init__(self):
        """初始化进程监控服务"""
        self.settings = get_settings()
        self.mock_engine = get_mock_engine()
        # 内置黑白名单
        self._init_builtin_whitelist()
        self._init_builtin_blacklist()

    def _init_builtin_whitelist(self):
        """初始化内置白名单"""
        try:
            db = get_session()
            existing = db.query(ProcessWhitelist).filter_by(is_builtin=True).first()
            if existing:
                db.close()
                return

            builtin_processes = [
                ("svchost.exe", "system", "系统服务主机进程"),
                ("explorer.exe", "system", "Windows资源管理器"),
                ("winlogon.exe", "system", "Windows登录进程"),
                ("csrss.exe", "system", "客户端运行时子系统"),
                ("smss.exe", "system", "会话管理器子系统"),
                ("services.exe", "system", "服务控制管理器"),
                ("lsass.exe", "system", "本地安全授权进程"),
                ("dwm.exe", "system", "桌面窗口管理器"),
                ("spoolsv.exe", "system", "打印后台处理程序"),
                ("WmiPrvSE.exe", "system", "WMI提供程序主机"),
                ("RuntimeBroker.exe", "system", "运行时代理"),
                ("SearchUI.exe", "system", "搜索UI"),
                ("ShellExperienceHost.exe", "system", "Shell体验主机"),
                ("python.exe", "yunxi", "云汐系统Python进程"),
                ("Code.exe", "yunxi", "VS Code编辑器（M9）"),
                ("ollama.exe", "yunxi", "Ollama大模型服务"),
            ]

            for name, category, desc in builtin_processes:
                item = ProcessWhitelist(
                    process_name=name,
                    category=category,
                    description=desc,
                    added_by="system",
                    is_builtin=True,
                    enabled=True,
                )
                db.add(item)
            db.commit()
            db.close()
        except Exception as e:
            print(f"[ProcessMonitor] 初始化白名单失败: {e}")

    def _init_builtin_blacklist(self):
        """初始化内置黑名单"""
        try:
            db = get_session()
            existing = db.query(ProcessBlacklist).filter_by(is_builtin=True).first()
            if existing:
                db.close()
                return

            builtin_processes = [
                ("miner.exe", "high", "挖矿程序"),
                ("xmrig.exe", "high", "XMRig挖矿程序"),
                ("trojan.exe", "critical", "木马程序特征"),
                ("ransomware.exe", "critical", "勒索软件特征"),
            ]

            for name, threat, desc in builtin_processes:
                item = ProcessBlacklist(
                    process_name=name,
                    threat_level=threat,
                    description=desc,
                    added_by="system",
                    is_builtin=True,
                    enabled=True,
                )
                db.add(item)
            db.commit()
            db.close()
        except Exception as e:
            print(f"[ProcessMonitor] 初始化黑名单失败: {e}")

    def get_process_list(self, category: Optional[str] = None,
                         sort_by: str = "cpu_percent",
                         limit: int = 100,
                         search: Optional[str] = None) -> List[dict]:
        """
        获取进程列表

        Args:
            category: 进程分类筛选（system/yunxi/browser/development等）
            sort_by: 排序字段（cpu_percent/mem_rss_mb/mem_percent/name/pid）
            limit: 返回数量限制
            search: 搜索关键词

        Returns:
            进程信息列表
        """
        if self.settings.sandbox_mode:
            processes = self.mock_engine.generate_process_list(count=200)
        else:
            processes = self.mock_engine.generate_process_list(count=200)

        # 分类筛选
        if category:
            processes = [p for p in processes if p.get("category") == category]

        # 搜索筛选
        if search:
            search_lower = search.lower()
            processes = [
                p for p in processes
                if search_lower in p["name"].lower()
                or search_lower in p.get("cmdline", "").lower()
                or search_lower in p.get("display_name", "").lower()
            ]

        # 排序
        reverse = sort_by != "name" and sort_by != "pid"
        processes.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)

        return processes[:limit]

    def get_process_tree(self) -> dict:
        """
        获取进程树

        Returns:
            进程树结构字典
        """
        processes = self.get_process_list(limit=200)

        # 构建父子关系
        children_map = {}
        for p in processes:
            ppid = p["ppid"]
            if ppid not in children_map:
                children_map[ppid] = []
            children_map[ppid].append(p)

        # 从PID 0/4开始构建树
        root_processes = [p for p in processes if p["ppid"] == 0 or p["ppid"] == 4]

        def build_tree(process: dict) -> dict:
            """递归构建子树"""
            pid = process["pid"]
            children = children_map.get(pid, [])
            result = {
                "pid": process["pid"],
                "name": process.get("display_name") or process["name"],
                "cpu_percent": process["cpu_percent"],
                "mem_rss_mb": process["mem_rss_mb"],
                "is_yunxi": process.get("is_yunxi", False),
                "category": process.get("category", "unknown"),
                "children": [build_tree(c) for c in children[:10]],  # 限制每层子进程数
                "children_count": len(children),
            }
            return result

        tree = [build_tree(p) for p in root_processes[:20]]

        return {
            "total_processes": len(processes),
            "tree": tree,
            "root_count": len(root_processes),
        }

    def get_top_n(self, n: int = 20, sort_by: str = "cpu_percent") -> List[dict]:
        """
        获取Top N进程排行

        Args:
            n: 排名数量
            sort_by: 排序字段

        Returns:
            Top N 进程列表
        """
        processes = self.get_process_list(sort_by=sort_by, limit=n)
        return [
            {
                "rank": i + 1,
                "pid": p["pid"],
                "name": p.get("display_name") or p["name"],
                "raw_name": p["name"],
                "cpu_percent": p["cpu_percent"],
                "mem_rss_mb": p["mem_rss_mb"],
                "mem_percent": p["mem_percent"],
                "category": p.get("category", "unknown"),
                "is_yunxi": p.get("is_yunxi", False),
            }
            for i, p in enumerate(processes)
        ]

    def get_process_detail(self, pid: int) -> Optional[dict]:
        """
        获取进程详情

        Args:
            pid: 进程ID

        Returns:
            进程详情字典，找不到返回None
        """
        processes = self.get_process_list(limit=200)
        for p in processes:
            if p["pid"] == pid:
                # 补充详细信息
                detail = dict(p)
                detail["details"] = {
                    "num_handles": p.get("num_handles", 0),
                    "num_threads": p.get("num_threads", 0),
                    "io_read_mb": p.get("io_read_mb", 0),
                    "io_write_mb": p.get("io_write_mb", 0),
                    "net_connections": p.get("net_connections", 0),
                    "cpu_time_user": p.get("cpu_time_user", 0),
                    "cpu_time_system": p.get("cpu_time_system", 0),
                }
                # 查找子进程
                children = [c for c in processes if c["ppid"] == pid]
                detail["children_count"] = len(children)
                detail["children"] = [
                    {"pid": c["pid"], "name": c.get("display_name") or c["name"]}
                    for c in children[:10]
                ]
                return detail
        return None

    def get_yunxi_processes(self) -> dict:
        """
        获取云汐系统进程列表

        Returns:
            云汐进程分组统计
        """
        processes = self.get_process_list(limit=200)
        yunxi_procs = [p for p in processes if p.get("is_yunxi", False)]

        # 按模块分组
        modules = {}
        for p in yunxi_procs:
            module = p.get("yunxi_module", "unknown")
            if module not in modules:
                modules[module] = {
                    "module": module,
                    "process_count": 0,
                    "total_cpu_percent": 0.0,
                    "total_mem_mb": 0.0,
                    "processes": [],
                }
            modules[module]["process_count"] += 1
            modules[module]["total_cpu_percent"] += p["cpu_percent"]
            modules[module]["total_mem_mb"] += p["mem_rss_mb"]
            modules[module]["processes"].append({
                "pid": p["pid"],
                "name": p.get("display_name") or p["name"],
                "cpu_percent": p["cpu_percent"],
                "mem_rss_mb": p["mem_rss_mb"],
                "status": p.get("status", "running"),
            })

        total_cpu = sum(m["total_cpu_percent"] for m in modules.values())
        total_mem = sum(m["total_mem_mb"] for m in modules.values())

        return {
            "total_count": len(yunxi_procs),
            "total_cpu_percent": round(total_cpu, 2),
            "total_mem_mb": round(total_mem, 2),
            "modules": list(modules.values()),
        }

    def get_process_events(self, limit: int = 50) -> List[dict]:
        """
        获取进程事件历史

        Args:
            limit: 返回数量限制

        Returns:
            进程事件列表
        """
        return self.mock_engine.get_process_events(limit=limit)

    # ===== 白名单管理 =====

    def get_whitelist(self) -> List[dict]:
        """
        获取白名单列表

        Returns:
            白名单条目列表
        """
        try:
            db = get_session()
            items = db.query(ProcessWhitelist).order_by(ProcessWhitelist.id.asc()).all()
            result = [item.to_dict() for item in items]
            db.close()
            return result
        except Exception as e:
            print(f"[ProcessMonitor] 获取白名单失败: {e}")
            return []

    def add_whitelist(self, process_name: str, process_path: str = "",
                      category: str = "custom", description: str = "",
                      added_by: str = "user") -> dict:
        """
        添加白名单

        Args:
            process_name: 进程名
            process_path: 进程路径
            category: 分类
            description: 说明
            added_by: 添加者

        Returns:
            添加结果
        """
        try:
            db = get_session()
            # 检查是否已存在
            existing = db.query(ProcessWhitelist).filter_by(process_name=process_name).first()
            if existing:
                db.close()
                return {"success": False, "message": "进程已在白名单中", "id": existing.id}

            item = ProcessWhitelist(
                process_name=process_name,
                process_path=process_path,
                category=category,
                description=description,
                added_by=added_by,
                is_builtin=False,
                enabled=True,
            )
            db.add(item)
            db.commit()
            new_id = item.id
            db.close()
            return {"success": True, "message": "添加成功", "id": new_id}
        except Exception as e:
            print(f"[ProcessMonitor] 添加白名单失败: {e}")
            return {"success": False, "message": str(e), "id": None}

    def remove_whitelist(self, item_id: int) -> bool:
        """
        删除白名单

        Args:
            item_id: 白名单ID

        Returns:
            是否删除成功
        """
        try:
            db = get_session()
            item = db.query(ProcessWhitelist).filter_by(id=item_id).first()
            if not item:
                db.close()
                return False
            if item.is_builtin:
                db.close()
                return False
            db.delete(item)
            db.commit()
            db.close()
            return True
        except Exception as e:
            print(f"[ProcessMonitor] 删除白名单失败: {e}")
            return False

    # ===== 黑名单管理 =====

    def get_blacklist(self) -> List[dict]:
        """
        获取黑名单列表

        Returns:
            黑名单条目列表
        """
        try:
            db = get_session()
            items = db.query(ProcessBlacklist).order_by(ProcessBlacklist.id.asc()).all()
            result = [item.to_dict() for item in items]
            db.close()
            return result
        except Exception as e:
            print(f"[ProcessMonitor] 获取黑名单失败: {e}")
            return []

    def add_blacklist(self, process_name: str, process_path: str = "",
                      threat_level: str = "medium", description: str = "",
                      added_by: str = "user") -> dict:
        """
        添加黑名单

        Args:
            process_name: 进程名
            process_path: 进程路径
            threat_level: 威胁等级
            description: 说明
            added_by: 添加者

        Returns:
            添加结果
        """
        try:
            db = get_session()
            # 检查是否已存在
            existing = db.query(ProcessBlacklist).filter_by(process_name=process_name).first()
            if existing:
                db.close()
                return {"success": False, "message": "进程已在黑名单中", "id": existing.id}

            item = ProcessBlacklist(
                process_name=process_name,
                process_path=process_path,
                threat_level=threat_level,
                description=description,
                added_by=added_by,
                is_builtin=False,
                enabled=True,
            )
            db.add(item)
            db.commit()
            new_id = item.id
            db.close()
            return {"success": True, "message": "添加成功", "id": new_id}
        except Exception as e:
            print(f"[ProcessMonitor] 添加黑名单失败: {e}")
            return {"success": False, "message": str(e), "id": None}

    def remove_blacklist(self, item_id: int) -> bool:
        """
        删除黑名单

        Args:
            item_id: 黑名单ID

        Returns:
            是否删除成功
        """
        try:
            db = get_session()
            item = db.query(ProcessBlacklist).filter_by(id=item_id).first()
            if not item:
                db.close()
                return False
            if item.is_builtin:
                db.close()
                return False
            db.delete(item)
            db.commit()
            db.close()
            return True
        except Exception as e:
            print(f"[ProcessMonitor] 删除黑名单失败: {e}")
            return False


# 全局单例
_process_monitor: Optional[ProcessMonitorService] = None


def get_process_monitor() -> ProcessMonitorService:
    """获取进程监控服务单例"""
    global _process_monitor
    if _process_monitor is None:
        _process_monitor = ProcessMonitorService()
    return _process_monitor


# 兼容直接运行测试
if __name__ == "__main__":
    service = get_process_monitor()

    print("=== 进程列表（Top 5 CPU） ===")
    procs = service.get_top_n(5)
    for p in procs:
        print(f"  #{p['rank']} {p['name']} - CPU: {p['cpu_percent']}%, MEM: {p['mem_rss_mb']}MB")

    print("\n=== 云汐进程 ===")
    yunxi = service.get_yunxi_processes()
    print(f"共 {yunxi['total_count']} 个云汐进程")
    print(f"总CPU: {yunxi['total_cpu_percent']}%, 总内存: {yunxi['total_mem_mb']}MB")

    print("\n=== 白名单 ===")
    wl = service.get_whitelist()
    print(f"共 {len(wl)} 条白名单")

    print("\n=== 黑名单 ===")
    bl = service.get_blacklist()
    print(f"共 {len(bl)} 条黑名单")
