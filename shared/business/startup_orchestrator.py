"""
云汐系统渐进式启动编排器
========================

按 Tier 分级有序启动系统模块，每个模块启动后通过健康检查确认就绪，
再启动下一个模块。提供启动进度查询、状态回调、Tier 等待等能力，
支持前端轮询展示启动状态。

CQ-001 改造：模块配置从 ModuleRegistry 读取，Tier 分级也从注册表的
priority 字段推断（priority < 10 = Tier 0, < 20 = Tier 1, 等）。
同时保留旧的 TIER_MODULES 配置作为向后兼容的 fallback。

Tier 分级说明：
  - Tier 0（管控基础设施）：m8（控制塔）、m10（系统卫士）、m12（安全盾）
  - Tier 1（核心能力，优先启动）：m1（代理集群）、m5（潮汐记忆）、m2（技能集群）
  - Tier 2（按需能力，后台加载）：m4（场景引擎）、m7（工作流构建器）、m3（边缘云端）
  - Tier 3（即用即启）：m6（硬件外设）、m0（主理人管控台）、m11（MCP总线）

模块状态：
  - pending:  等待启动
  - starting: 启动中
  - running:  运行中（健康检查通过）
  - error:    启动失败
  - skipped:  跳过（可选）
"""

import os
import sys
import time
import socket
import threading
from typing import Callable, Dict, List, Optional
from pathlib import Path

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.core.module_registry import (
    ModuleRegistry,
    ModuleInfo,
    ModuleStatus,
    get_module_registry,
)


# =============================================================================
#  模块 Tier 分级配置（向后兼容 fallback）
# =============================================================================

# 每个 Tier 内的模块按数组顺序启动
# CQ-001: 优先从 ModuleRegistry 的 priority 字段推断 Tier，
#         本配置仅在注册表不可用时作为 fallback
TIER_MODULES: Dict[int, List[str]] = {
    0: ["m8", "m10", "m12"],
    1: ["m1", "m5", "m2"],
    2: ["m4", "m7", "m3"],
    3: ["m6", "m0", "m11"],
}

# 模块元信息（名称 + 端口），向后兼容
# CQ-001: 优先从 ModuleRegistry 读取，本配置作为 fallback
MODULE_META: Dict[str, dict] = {
    "m0":  {"name": "主理人管控台", "port": 8000},
    "m1":  {"name": "代理集群",     "port": 8001},
    "m2":  {"name": "技能集群",     "port": 8002},
    "m3":  {"name": "边缘云端",     "port": 8003},
    "m4":  {"name": "场景引擎",     "port": 8004},
    "m5":  {"name": "潮汐记忆",     "port": 8005},
    "m6":  {"name": "硬件外设",     "port": 8006},
    "m7":  {"name": "工作流构建器", "port": 8007},
    "m8":  {"name": "控制塔",       "port": 8008},
    "m10": {"name": "系统卫士",     "port": 8010},
    "m11": {"name": "MCP总线",      "port": 8011},
    "m12": {"name": "安全盾",       "port": 8012},
    "gateway": {"name": "API网关",  "port": 8080},
}

# 模块状态常量
STATUS_PENDING = "pending"
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

# 默认模块启动超时时间（秒）
DEFAULT_MODULE_TIMEOUT = 30

# 端口检测重试间隔（秒）
PORT_CHECK_INTERVAL = 0.5


# =============================================================================
#  端口就绪检测工具函数
# =============================================================================

def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """
    快速检测指定端口是否已打开（TCP 连接检测）。

    Args:
        host: 主机地址
        port: 端口号
        timeout: 连接超时时间（秒）

    Returns:
        True 表示端口已打开，False 表示未打开
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except OSError:
        return False
    finally:
        sock.close()


def wait_for_port(
    host: str,
    port: int,
    timeout: float = 30.0,
    interval: float = 0.5,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """
    等待端口打开，直到超时或端口就绪。

    Args:
        host: 主机地址
        port: 端口号
        timeout: 总超时时间（秒）
        interval: 检测间隔（秒）
        stop_event: 可选的停止事件，用于外部中断等待

    Returns:
        True 表示端口已就绪，False 表示超时
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if stop_event and stop_event.is_set():
            return False
        if is_port_open(host, port, timeout=min(interval, 0.5)):
            return True
        time.sleep(interval)
    return False


# =============================================================================
#  模块启动状态信息
# =============================================================================

class ModuleStartupInfo:
    """单个模块的启动状态信息"""

    __slots__ = ("key", "name", "tier", "port", "status", "message",
                 "start_time", "ready_time", "error", "phase", "progress")

    def __init__(self, key: str, name: str, tier: int, port: int):
        self.key = key
        self.name = name
        self.tier = tier
        self.port = port
        self.status = STATUS_PENDING
        self.message = "等待启动"
        self.start_time: Optional[float] = None
        self.ready_time: Optional[float] = None
        self.error: Optional[str] = None
        self.phase = "pending"
        self.progress = 0

    def to_dict(self) -> dict:
        """序列化为字典（用于前端展示）"""
        return {
            "key": self.key,
            "name": self.name,
            "tier": self.tier,
            "port": self.port,
            "status": self.status,
            "message": self.message,
            "start_time": self.start_time,
            "ready_time": self.ready_time,
            "error": self.error,
            "duration": (
                round(self.ready_time - self.start_time, 2)
                if self.start_time and self.ready_time
                else None
            ),
        }


# =============================================================================
#  启动编排器
# =============================================================================

class StartupOrchestrator:
    """
    云汐系统渐进式启动编排器（单例模式）。

    按 Tier 分级有序启动模块，每个模块启动后等待端口就绪再进入下一个。
    启动过程在独立后台线程中运行，不阻塞调用方。

    使用示例：
        orchestrator = StartupOrchestrator()
        orchestrator.start_background()

        # 查询进度
        progress = orchestrator.get_progress()

        # 等待 Tier0 + Tier1 就绪
        if orchestrator.is_ready():
            print("核心能力已就绪")
    """

    _instance: Optional["StartupOrchestrator"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        module_timeout: int = DEFAULT_MODULE_TIMEOUT,
        project_root: Optional[Path] = None,
        registry: Optional[ModuleRegistry] = None,
    ):
        """
        初始化启动编排器。

        Args:
            module_timeout: 单个模块的启动超时时间（秒）
            project_root: 项目根目录，用于定位模块工作目录
            registry: 模块注册表实例，None 时使用全局注册表
        """
        if self._initialized:
            return
        self._initialized = True

        self._module_timeout = module_timeout
        self._project_root = project_root or Path(__file__).resolve().parent.parent.parent

        # 模块注册表（CQ-001）
        self._registry = registry or get_module_registry()

        # 从注册表计算 Tier 分级（基于 priority 字段）
        self._tier_modules = self._compute_tier_modules()

        # 进程管理器（延迟导入，避免循环依赖）
        self._process_manager = None

        # 模块状态表（按启动顺序排列的列表，方便遍历）
        self._modules: List[ModuleStartupInfo] = []
        self._module_map: Dict[str, ModuleStartupInfo] = {}
        self._init_modules()

        # 总模块数
        self._total = len(self._modules)

        # 线程与同步
        self._lock = threading.RLock()
        self._start_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False
        self._finished = False

        # 各 Tier 完成事件（用于 wait_for_tier）
        self._tier_events: Dict[int, threading.Event] = {
            tier: threading.Event() for tier in self._tier_modules.keys()
        }

        # 状态回调列表（每次状态变化时调用）
        self._callbacks: List[Callable[[dict], None]] = []

    # ------------------------------------------------------------------
    #  初始化
    # ------------------------------------------------------------------

    def _compute_tier_modules(self) -> Dict[int, List[str]]:
        """
        从模块注册表的 priority 字段计算 Tier 分级。

        规则：
          - priority < 10: Tier 0（管控基础设施）
          - priority < 20: Tier 1（核心能力）
          - priority < 30: Tier 2（按需能力）
          - priority < 100: Tier 3（即用即启）
          - priority >= 100: Tier 4（其他/自定义）

        每个 Tier 内按 priority 升序排列。
        """
        tiers: Dict[int, List[str]] = {}
        enabled_modules = self._registry.list_modules(enabled_only=True)

        for module in enabled_modules:
            # 根据 priority 计算 Tier
            if module.priority < 10:
                tier = 0
            elif module.priority < 20:
                tier = 1
            elif module.priority < 30:
                tier = 2
            elif module.priority < 100:
                tier = 3
            else:
                tier = 4

            if tier not in tiers:
                tiers[tier] = []
            tiers[tier].append(module.id)

        # 每个 Tier 内按 priority 排序
        for tier in tiers:
            tiers[tier].sort(
                key=lambda mid: self._registry.get_module(mid).priority
                if self._registry.get_module(mid) else 999
            )

        # 如果注册表为空，使用 fallback 配置
        if not tiers:
            return TIER_MODULES.copy()

        return dict(sorted(tiers.items()))

    def _init_modules(self):
        """按 Tier 顺序初始化所有模块的状态信息"""
        for tier in sorted(self._tier_modules.keys()):
            for key in self._tier_modules[tier]:
                # 优先从注册表获取模块信息
                reg_module = self._registry.get_module(key)
                if reg_module:
                    name = reg_module.name
                    port = reg_module.port
                else:
                    # fallback 到 MODULE_META
                    meta = MODULE_META.get(key, {"name": key, "port": 0})
                    name = meta["name"]
                    port = meta["port"]

                info = ModuleStartupInfo(
                    key=key,
                    name=name,
                    tier=tier,
                    port=port,
                )
                self._modules.append(info)
                self._module_map[key] = info

    def _get_process_manager(self):
        """
        延迟获取 ProcessManager 实例，避免循环导入。
        优先使用 shared.process_manager.ProcessManager。
        """
        if self._process_manager is None:
            try:
                from .process_manager import ProcessManager
                self._process_manager = ProcessManager(
                    project_root=self._project_root
                )
            except ImportError:
                # 独立运行测试时，使用 None 占位（由 mock 启动代替）
                self._process_manager = None
        return self._process_manager

    # ------------------------------------------------------------------
    #  回调注册
    # ------------------------------------------------------------------

    def register_callback(self, callback: Callable[[dict], None]):
        """
        注册状态变化回调。

        每次任意模块状态发生变化时，都会调用 callback(progress_dict)，
        可用于前端推送或日志记录。

        Args:
            callback: 回调函数，接收当前进度字典作为参数
        """
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[dict], None]):
        """注销状态变化回调"""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def _notify_callbacks(self):
        """触发所有回调（调用方需已持有锁或确保线程安全）"""
        progress = self._build_progress_locked()
        for cb in self._callbacks:
            try:
                cb(progress)
            except Exception as e:
                # 回调异常不影响启动流程
                print(f"[StartupOrchestrator] 回调执行异常: {e}",
                      file=sys.stderr)

    # ------------------------------------------------------------------
    #  后台启动
    # ------------------------------------------------------------------

    def start_background(self) -> bool:
        """
        在后台线程中启动整个启动流程。

        若已启动则直接返回 False。

        Returns:
            True 表示成功启动后台线程，False 表示已在运行
        """
        with self._lock:
            if self._started:
                return False
            self._started = True
            self._finished = False
            self._stop_event.clear()

        self._start_thread = threading.Thread(
            target=self._run_startup,
            name="StartupOrchestrator",
            daemon=True,
        )
        self._start_thread.start()
        return True

    def _run_startup(self):
        """启动流程主逻辑（在后台线程中执行）"""
        try:
            for tier in sorted(self._tier_modules.keys()):
                if self._stop_event.is_set():
                    break

                tier_modules = self._tier_modules[tier]

                for module_key in tier_modules:
                    if self._stop_event.is_set():
                        break

                    self._start_module(module_key)

                # Tier 内所有模块处理完毕，标记 Tier 完成
                self._tier_events[tier].set()

        except Exception as e:
            print(f"[StartupOrchestrator] 启动流程异常: {e}",
                  file=sys.stderr)
        finally:
            with self._lock:
                self._finished = True
                self._notify_callbacks()

    # ------------------------------------------------------------------
    #  单个模块启动
    # ------------------------------------------------------------------

    def _start_module(self, module_key: str):
        """
        启动单个模块并等待就绪。

        流程：
          1. 设置状态为 starting
          2. 调用 ProcessManager 启动模块进程
          3. 等待端口就绪（健康检查）
          4. 设置状态为 running / error
        """
        info = self._module_map.get(module_key)
        if info is None:
            return

        with self._lock:
            # 跳过已处理的模块
            if info.status not in (STATUS_PENDING, STATUS_SKIPPED):
                return
            info.status = STATUS_STARTING
            info.message = "正在启动..."
            info.start_time = time.time()
            self._notify_callbacks()

        # ---- 启动进程 ----
        pm = self._get_process_manager()
        start_ok = False
        error_msg = None

        if pm is not None:
            try:
                start_ok = pm.start_module(module_key)
                if not start_ok:
                    error_msg = "ProcessManager 启动失败"
            except Exception as e:
                error_msg = f"启动异常: {e}"
                start_ok = False
        else:
            # 无 ProcessManager 时（如测试环境），直接检测端口是否已被占用
            # 若端口已开则视为已在运行，否则标记为跳过
            if is_port_open("127.0.0.1", info.port, timeout=0.3):
                start_ok = True
                info.message = "检测到端口已就绪（进程已存在）"
            else:
                # 测试模式下标记为跳过，避免阻塞
                with self._lock:
                    info.status = STATUS_SKIPPED
                    info.message = "无 ProcessManager，跳过启动"
                    info.ready_time = time.time()
                    self._notify_callbacks()
                return

        if not start_ok:
            with self._lock:
                info.status = STATUS_ERROR
                info.message = error_msg or "启动失败"
                info.error = error_msg
                self._notify_callbacks()
            return

        # ---- 等待就绪（端口检测） ----
        ready = wait_for_port(
            host="127.0.0.1",
            port=info.port,
            timeout=self._module_timeout,
            interval=PORT_CHECK_INTERVAL,
            stop_event=self._stop_event,
        )

        with self._lock:
            if self._stop_event.is_set():
                info.status = STATUS_SKIPPED
                info.message = "启动被中断"
            elif ready:
                info.status = STATUS_RUNNING
                info.message = "运行中"
                info.ready_time = time.time()
            else:
                # 超时：检查进程是否还活着
                if pm and pm.is_module_running(module_key):
                    info.status = STATUS_RUNNING
                    info.message = "进程运行中（健康检查超时）"
                    info.ready_time = time.time()
                else:
                    info.status = STATUS_ERROR
                    info.message = "启动超时，进程可能已退出"
                    info.error = "timeout"
            self._notify_callbacks()

    # ------------------------------------------------------------------
    #  进度查询
    # ------------------------------------------------------------------

    def get_progress(self) -> dict:
        """
        获取当前启动进度。

        Returns:
            包含以下字段的字典：
              - total:     总模块数
              - completed: 已完成（running 或 skipped）的模块数
              - current:   当前正在启动的模块索引（从 1 开始），0 表示未开始
              - percent:   进度百分比（0-100）
              - phases:    各 Tier 的完成状态
              - modules:   每个模块的详细状态列表
              - is_finished: 启动流程是否已结束
        """
        with self._lock:
            return self._build_progress_locked()

    def get_module_state(self, module_key: str) -> Optional[ModuleStartupInfo]:
        """
        获取指定模块的状态信息。

        Args:
            module_key: 模块标识（如 "m8", "m5"）

        Returns:
            ModuleStartupInfo 对象，如果模块不存在则返回 None
        """
        with self._lock:
            for info in self._modules:
                if info.key == module_key:
                    return info
            return None

    def _build_progress_locked(self) -> dict:
        """构建进度字典（调用方需已持有 _lock）"""
        completed = 0
        current_index = 0

        for i, info in enumerate(self._modules):
            if info.status in (STATUS_RUNNING, STATUS_SKIPPED, STATUS_ERROR):
                completed += 1
            elif info.status == STATUS_STARTING and current_index == 0:
                current_index = i + 1

        # 如果全部完成，current = total
        if self._finished and current_index == 0:
            current_index = self._total

        # 各 Tier 状态
        phases = {}
        for tier in sorted(self._tier_modules.keys()):
            tier_keys = self._tier_modules[tier]
            tier_done = all(
                self._module_map[k].status
                in (STATUS_RUNNING, STATUS_SKIPPED, STATUS_ERROR)
                for k in tier_keys
            )
            tier_started = any(
                self._module_map[k].status != STATUS_PENDING
                for k in tier_keys
            )
            if tier_done:
                phase_status = "completed"
            elif tier_started:
                phase_status = "in_progress"
            else:
                phase_status = "pending"
            phases[f"tier{tier}"] = {
                "tier": tier,
                "status": phase_status,
                "modules": tier_keys,
            }

        percent = int((completed / self._total) * 100) if self._total > 0 else 0

        return {
            "total": self._total,
            "completed": completed,
            "current": current_index,
            "percent": percent,
            "phases": phases,
            "modules": [m.to_dict() for m in self._modules],
            "is_finished": self._finished,
        }

    # ------------------------------------------------------------------
    #  Tier 等待 & 就绪判断
    # ------------------------------------------------------------------

    def wait_for_tier(self, tier: int, timeout: Optional[float] = None) -> bool:
        """
        等待指定 Tier 及其之前的所有 Tier 启动完成。

        Args:
            tier: 目标 Tier 编号（0/1/2/3）
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            True 表示 Tier 已完成，False 表示超时
        """
        if tier not in self._tier_events:
            return False

        # 需要等待该 Tier 及所有更低 Tier 都完成
        events = [
            self._tier_events[t]
            for t in sorted(self._tier_events.keys())
            if t <= tier
        ]

        deadline = time.time() + timeout if timeout is not None else None

        for event in events:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.time())
                if remaining <= 0:
                    return False
            if not event.wait(timeout=remaining):
                return False
        return True

    def is_ready(self) -> bool:
        """
        Tier0 + Tier1 是否已全部启动完成。

        这是系统"核心可用"的标志：管控基础设施 + 核心能力都就绪。

        Returns:
            True 表示核心能力已就绪
        """
        return (
            self._tier_events[0].is_set()
            and self._tier_events[1].is_set()
        )

    def is_started(self) -> bool:
        """启动流程是否已开始"""
        with self._lock:
            return self._started

    def is_finished(self) -> bool:
        """启动流程是否已结束"""
        with self._lock:
            return self._finished

    def stop(self):
        """中断启动流程（不会停止已启动的模块）"""
        self._stop_event.set()

    # ------------------------------------------------------------------
    #  重置（用于测试）
    # ------------------------------------------------------------------

    def reset(self):
        """
        重置编排器状态（主要用于测试场景）。

        注意：不会停止已启动的进程，仅重置内部状态。
        """
        with self._lock:
            self._started = False
            self._finished = False
            self._stop_event.clear()
            for info in self._modules:
                info.status = STATUS_PENDING
                info.message = "等待启动"
                info.start_time = None
                info.ready_time = None
                info.error = None
            for event in self._tier_events.values():
                event.clear()


# =============================================================================
#  全局单例获取
# =============================================================================

_orchestrator: Optional[StartupOrchestrator] = None


def get_startup_orchestrator(
    module_timeout: int = DEFAULT_MODULE_TIMEOUT,
    project_root: Optional[Path] = None,
    self_module_key: Optional[str] = None,
) -> StartupOrchestrator:
    """
    获取全局启动编排器单例。

    Args:
        module_timeout: 单个模块启动超时（秒）
        project_root: 项目根目录
        self_module_key: 当前模块标识（可选，用于日志标识）

    Returns:
        StartupOrchestrator 单例
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = StartupOrchestrator(
            module_timeout=module_timeout,
            project_root=project_root,
        )
    return _orchestrator


# =============================================================================
#  独立运行测试
# =============================================================================

def _run_selftest():
    """
    自检模式：验证编排器基本逻辑（不启动真实进程）。

    输出启动进度变化，用于快速验证代码正确性。
    """
    print("=" * 60)
    print("云汐启动编排器 - 自检模式")
    print("=" * 60)

    # 重置单例（确保测试环境干净）
    StartupOrchestrator._instance = None
    global _orchestrator
    _orchestrator = None

    orch = StartupOrchestrator(module_timeout=2)

    # 注册回调，观察状态变化
    update_count = 0

    def on_progress(progress):
        nonlocal update_count
        update_count += 1
        current_name = "-"
        if 0 < progress["current"] <= len(progress["modules"]):
            current_name = progress["modules"][progress["current"] - 1]["name"]
        print(
            f"  [回调#{update_count:02d}] "
            f"进度: {progress['percent']:3d}% "
            f"({progress['completed']}/{progress['total']}) "
            f"当前: {current_name}"
        )

    orch.register_callback(on_progress)

    # 初始状态
    print("\n初始状态:")
    p = orch.get_progress()
    print(f"  总模块数: {p['total']}")
    print(f"  is_ready: {orch.is_ready()}")
    print(f"  is_started: {orch.is_started()}")

    # 启动后台流程（测试环境下模块会被标记为 skipped）
    print("\n启动后台编排...")
    started = orch.start_background()
    print(f"  start_background 返回: {started}")

    # 重复调用应返回 False
    started2 = orch.start_background()
    print(f"  再次调用返回: {started2} (应为 False)")

    # 等待一段时间观察进度
    for i in range(5):
        time.sleep(0.3)
        p = orch.get_progress()
        statuses = [m["status"] for m in p["modules"]]
        running = statuses.count(STATUS_RUNNING)
        skipped = statuses.count(STATUS_SKIPPED)
        error = statuses.count(STATUS_ERROR)
        print(
            f"  第 {i + 1} 次轮询: {p['percent']}% | "
            f"running={running} skipped={skipped} error={error}"
        )

    # 等待完成
    print("\n等待启动流程结束...")
    timeout = 10
    start = time.time()
    while not orch.is_finished() and time.time() - start < timeout:
        time.sleep(0.2)

    p = orch.get_progress()
    print(f"\n最终状态:")
    print(f"  完成: {p['is_finished']}")
    print(f"  进度: {p['percent']}% ({p['completed']}/{p['total']})")
    print(f"  is_ready: {orch.is_ready()}")

    # 打印各 Tier 状态
    print(f"\n各 Tier 状态:")
    for tier_name, tier_info in sorted(p["phases"].items()):
        print(f"  {tier_name}: {tier_info['status']}")

    # 打印各模块最终状态
    print(f"\n各模块状态:")
    for m in p["modules"]:
        print(f"  Tier{m['tier']} {m['key']:>4} {m['name']:<10} - {m['status']}")

    # wait_for_tier 测试
    print("\nwait_for_tier 测试:")
    t0_ok = orch.wait_for_tier(0, timeout=1)
    t1_ok = orch.wait_for_tier(1, timeout=1)
    print(f"  wait_for_tier(0): {t0_ok}")
    print(f"  wait_for_tier(1): {t1_ok}")

    # 端口检测工具测试
    print("\n端口检测工具测试:")
    port_open = is_port_open("127.0.0.1", 9999, timeout=0.3)
    print(f"  is_port_open(127.0.0.1:9999): {port_open} (应为 False)")

    print("\n" + "=" * 60)
    print("自检完成 ✓")
    print("=" * 60)


if __name__ == "__main__":
    _run_selftest()
