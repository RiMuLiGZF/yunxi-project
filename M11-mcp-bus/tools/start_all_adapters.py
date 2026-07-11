"""M11 MCP Bus - 统一适配器启动管理脚本.

同时启动多个适配器（语音/M2/M7等），自动注册到 M11 总线，
并监控适配器状态，异常退出自动重启。

提供命令行控制：
- 启动所有适配器
- 查看状态
- 停止所有适配器
- 重启指定适配器
- 支持 --only 参数指定只启动某些适配器

用法:
    # 启动所有适配器
    python tools/start_all_adapters.py start

    # 只启动语音和 M2 适配器
    python tools/start_all_adapters.py start --only voice,m2

    # 查看状态
    python tools/start_all_adapters.py status

    # 停止所有适配器
    python tools/start_all_adapters.py stop

    # 重启某个适配器
    python tools/start_all_adapters.py restart m7

环境变量:
    M11_BUS_URL: M11 总线地址（默认 http://localhost:8011）
    ADAPTERS_ENABLED: 启用的适配器列表，逗号分隔（默认 voice,m2,m7）
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


# ============================================================
# 适配器配置
# ============================================================

# 所有可用的适配器配置
ADAPTER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "voice": {
        "name": "语音模块适配器",
        "script": "tools/start_voice_adapter.py",
        "port_env": "VOICE_ADAPTER_PORT",
        "default_port": 8101,
        "endpoint_env": "VOICE_ADAPTER_ENDPOINT",
        "heartbeat_env": "VOICE_HEARTBEAT_INTERVAL",
        "health_url": "http://localhost:{port}/health",
    },
    "m2": {
        "name": "M2 技能集群适配器",
        "script": "tools/start_m2_adapter.py",
        "port_env": "M2_ADAPTER_PORT",
        "default_port": 8102,
        "endpoint_env": "M2_ADAPTER_ENDPOINT",
        "heartbeat_env": "M2_HEARTBEAT_INTERVAL",
        "health_url": "http://localhost:{port}/health",
    },
    "m7": {
        "name": "M7 积木平台适配器",
        "script": "tools/start_m7_adapter.py",
        "port_env": "M7_ADAPTER_PORT",
        "default_port": 8103,
        "endpoint_env": "M7_ADAPTER_ENDPOINT",
        "heartbeat_env": "M7_HEARTBEAT_INTERVAL",
        "health_url": "http://localhost:{port}/health",
    },
}

# PID 文件目录
PID_DIR = PROJECT_ROOT / "data" / "adapter_pids"


# ============================================================
# 适配器进程管理
# ============================================================

class AdapterProcess:
    """单个适配器进程的管理.

    封装子进程的启动、停止、状态检查、重启等操作。
    """

    def __init__(self, adapter_key: str, config: Dict[str, Any]) -> None:
        """初始化适配器进程管理.

        Args:
            adapter_key: 适配器标识（voice/m2/m7）
            config: 适配器配置字典
        """
        self.key = adapter_key
        self.config = config
        self.name = config["name"]
        self.script_path = PROJECT_ROOT / config["script"]
        self.process: Optional[subprocess.Popen] = None
        self._pid_file = PID_DIR / f"{adapter_key}.pid"
        self._restart_count = 0
        self._last_start_time: Optional[float] = None
        self._should_run = False

    @property
    def port(self) -> int:
        """获取适配器监听端口."""
        port_str = os.environ.get(self.config["port_env"], "")
        if port_str:
            try:
                return int(port_str)
            except ValueError:
                pass
        return self.config["default_port"]

    @property
    def health_url(self) -> str:
        """获取健康检查 URL."""
        return self.config["health_url"].format(port=self.port)

    @property
    def is_running(self) -> bool:
        """检查进程是否正在运行."""
        if self.process is None:
            return False
        return self.process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        """获取进程 PID."""
        if self.process is not None:
            return self.process.pid
        # 尝试从 PID 文件读取
        if self._pid_file.exists():
            try:
                return int(self._pid_file.read_text().strip())
            except (ValueError, OSError):
                pass
        return None

    def start(self) -> bool:
        """启动适配器子进程.

        Returns:
            是否启动成功
        """
        if self.is_running:
            print(f"[{self.key}] 适配器已在运行（PID={self.pid}），跳过启动")
            return True

        if not self.script_path.exists():
            print(f"[{self.key}] 错误：启动脚本不存在: {self.script_path}")
            return False

        print(f"[{self.key}] 正在启动 {self.name}...")

        try:
            # 启动子进程，继承当前环境变量
            self.process = subprocess.Popen(
                [sys.executable, str(self.script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
                cwd=str(PROJECT_ROOT),
            )
            self._should_run = True
            self._last_start_time = time.time()
            self._save_pid()

            print(f"[{self.key}] 启动成功，PID={self.process.pid}，端口={self.port}")
            return True

        except Exception as e:
            print(f"[{self.key}] 启动失败: {e}")
            return False

    def stop(self, timeout: int = 10) -> bool:
        """停止适配器进程.

        Args:
            timeout: 等待进程退出的超时时间（秒）

        Returns:
            是否成功停止
        """
        self._should_run = False

        if self.process is None:
            # 尝试从 PID 文件查找并停止
            pid = self.pid
            if pid is not None:
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    proc.terminate()
                    proc.wait(timeout=timeout)
                    print(f"[{self.key}] 已停止（PID={pid}）")
                    self._remove_pid()
                    return True
                except Exception as e:
                    print(f"[{self.key}] 停止失败（PID={pid}）: {e}")
                    return False
            print(f"[{self.key}] 适配器未在运行")
            return True

        if not self.is_running:
            print(f"[{self.key}] 适配器已停止")
            self._remove_pid()
            return True

        print(f"[{self.key}] 正在停止（PID={self.process.pid}）...")
        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
            print(f"[{self.key}] 已停止")
            self._remove_pid()
            return True
        except subprocess.TimeoutExpired:
            print(f"[{self.key}] 进程未响应，强制终止...")
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except Exception:
                pass
            self._remove_pid()
            return True
        except Exception as e:
            print(f"[{self.key}] 停止失败: {e}")
            return False

    def restart(self) -> bool:
        """重启适配器.

        Returns:
            是否重启成功
        """
        print(f"[{self.key}] 正在重启...")
        self.stop()
        time.sleep(1)
        success = self.start()
        if success:
            self._restart_count += 1
        return success

    def check_health(self) -> Dict[str, Any]:
        """检查适配器健康状态.

        Returns:
            健康状态字典
        """
        if not self.is_running:
            return {
                "status": "stopped",
                "pid": self.pid,
                "port": self.port,
                "restart_count": self._restart_count,
            }

        # 尝试调用健康检查接口
        try:
            import httpx
            with httpx.Client(timeout=3.0) as client:
                response = client.get(self.health_url)
                if response.status_code == 200:
                    return {
                        "status": "healthy",
                        "pid": self.pid,
                        "port": self.port,
                        "restart_count": self._restart_count,
                        "uptime": int(time.time() - (self._last_start_time or 0)),
                    }
        except Exception:
            pass

        return {
            "status": "running",
            "pid": self.pid,
            "port": self.port,
            "restart_count": self._restart_count,
            "uptime": int(time.time() - (self._last_start_time or 0)),
        }

    def _save_pid(self) -> None:
        """保存 PID 到文件."""
        PID_DIR.mkdir(parents=True, exist_ok=True)
        if self.process and self.process.pid:
            try:
                self._pid_file.write_text(str(self.process.pid))
            except OSError:
                pass

    def _remove_pid(self) -> None:
        """删除 PID 文件."""
        try:
            if self._pid_file.exists():
                self._pid_file.unlink()
        except OSError:
            pass


# ============================================================
# 统一适配器管理器
# ============================================================

class AdapterManager:
    """统一适配器管理器.

    管理多个适配器的启动、停止、监控和自动重启。
    """

    # 最大自动重启次数
    MAX_RESTARTS = 5
    # 重启冷却时间（秒）
    RESTART_COOLDOWN = 60

    def __init__(self, adapter_keys: Optional[List[str]] = None) -> None:
        """初始化适配器管理器.

        Args:
            adapter_keys: 要管理的适配器列表，None 则使用配置中的全部
        """
        if adapter_keys is None:
            adapter_keys = list(ADAPTER_CONFIGS.keys())

        # 过滤有效适配器
        self.adapter_keys = [k for k in adapter_keys if k in ADAPTER_CONFIGS]

        self.adapters: Dict[str, AdapterProcess] = {}
        for key in self.adapter_keys:
            self.adapters[key] = AdapterProcess(key, ADAPTER_CONFIGS[key])

        self._monitor_running = False
        self._monitor_thread: Optional[Any] = None

    # --------------------------------------------------------
    # 批量操作
    # --------------------------------------------------------

    def start_all(self) -> Dict[str, bool]:
        """启动所有适配器.

        Returns:
            各适配器启动结果
        """
        print("=" * 60)
        print(f"M11 MCP 适配器统一启动（共 {len(self.adapters)} 个）")
        print(f"适配器: {', '.join(self.adapter_keys)}")
        print("=" * 60)

        results = {}
        for key, adapter in self.adapters.items():
            success = adapter.start()
            results[key] = success
            if success:
                # 等待一下再启动下一个，避免端口冲突
                time.sleep(1)

        print("\n" + "=" * 60)
        print("启动完成：")
        for key, success in results.items():
            status = "成功" if success else "失败"
            adapter = self.adapters[key]
            print(f"  {key:6s} - {adapter.name:20s} [{status}] PID={adapter.pid}")
        print("=" * 60)

        return results

    def stop_all(self) -> Dict[str, bool]:
        """停止所有适配器.

        Returns:
            各适配器停止结果
        """
        print("正在停止所有适配器...")
        results = {}
        for key, adapter in self.adapters.items():
            success = adapter.stop()
            results[key] = success
        return results

    def status_all(self) -> Dict[str, Dict[str, Any]]:
        """获取所有适配器状态.

        Returns:
            各适配器状态字典
        """
        statuses = {}
        for key, adapter in self.adapters.items():
            statuses[key] = adapter.check_health()
        return statuses

    def restart_adapter(self, adapter_key: str) -> bool:
        """重启指定适配器.

        Args:
            adapter_key: 适配器标识

        Returns:
            是否重启成功
        """
        if adapter_key not in self.adapters:
            print(f"未知适配器: {adapter_key}")
            print(f"可用适配器: {', '.join(self.adapter_keys)}")
            return False
        return self.adapters[adapter_key].restart()

    # --------------------------------------------------------
    # 监控与自动重启
    # --------------------------------------------------------

    def start_monitor(self) -> None:
        """启动监控线程.

        定期检查适配器状态，异常退出自动重启。
        """
        if self._monitor_running:
            return

        self._monitor_running = True
        import threading

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="adapter-monitor",
        )
        self._monitor_thread.start()
        print("[监控] 适配器监控已启动")

    def stop_monitor(self) -> None:
        """停止监控线程."""
        self._monitor_running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None
        print("[监控] 适配器监控已停止")

    def _monitor_loop(self) -> None:
        """监控循环（后台线程）."""
        check_interval = 10  # 检查间隔（秒）
        restart_timestamps: Dict[str, List[float]] = {k: [] for k in self.adapter_keys}

        while self._monitor_running:
            try:
                for key, adapter in self.adapters.items():
                    # 检查进程是否还在运行
                    if not adapter.is_running and adapter._should_run:
                        # 进程异常退出，检查是否可以重启
                        now = time.time()
                        timestamps = restart_timestamps[key]
                        # 清理超过冷却时间的记录
                        timestamps = [t for t in timestamps if now - t < self.RESTART_COOLDOWN]
                        restart_timestamps[key] = timestamps

                        if len(timestamps) < self.MAX_RESTARTS:
                            print(f"[监控] {key} 适配器异常退出，正在重启...")
                            success = adapter.start()
                            if success:
                                timestamps.append(now)
                                adapter._restart_count += 1
                                print(f"[监控] {key} 重启成功（第 {adapter._restart_count} 次重启）")
                            else:
                                print(f"[监控] {key} 重启失败")
                        else:
                            print(
                                f"[监控] {key} 重启次数已达上限（{self.MAX_RESTARTS}次/{self.RESTART_COOLDOWN}s），"
                                "停止自动重启"
                            )
                            adapter._should_run = False

            except Exception as e:
                print(f"[监控] 检查异常: {e}")

            # 等待检查间隔
            for _ in range(check_interval * 10):
                if not self._monitor_running:
                    break
                time.sleep(0.1)

    # --------------------------------------------------------
    # 状态展示
    # --------------------------------------------------------

    def print_status(self) -> None:
        """打印所有适配器状态."""
        statuses = self.status_all()
        print("=" * 60)
        print("适配器状态")
        print("=" * 60)
        print(f"{'适配器':<8s} {'名称':<20s} {'状态':<10s} {'PID':>8s} {'端口':>6s} {'重启':>4s}")
        print("-" * 60)
        for key, status in statuses.items():
            adapter = self.adapters[key]
            print(
                f"{key:<8s} {adapter.name:<20s} {status['status']:<10s} "
                f"{str(status.get('pid', '-')):>8s} {status.get('port', '-'):>6} "
                f"{status.get('restart_count', 0):>4d}"
            )
        print("=" * 60)

    def run_forever(self) -> None:
        """运行管理器并阻塞等待，直到收到退出信号."""
        # 注册信号处理
        def _handle_signal(signum, frame):
            print("\n收到退出信号，正在停止所有适配器...")
            self.stop_monitor()
            self.stop_all()
            print("所有适配器已停止，再见！")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        # 启动监控
        self.start_monitor()

        print("\n适配器管理运行中，按 Ctrl+C 退出...")
        print("输入 'status' 查看状态，'stop' 停止，'quit' 退出\n")

        # 简单的命令行交互
        try:
            while True:
                try:
                    cmd = input("> ").strip().lower()
                except EOFError:
                    break

                if cmd == "status":
                    self.print_status()
                elif cmd == "stop":
                    self.stop_all()
                elif cmd == "start":
                    self.start_all()
                    self.start_monitor()
                elif cmd in ("quit", "exit"):
                    break
                elif cmd.startswith("restart "):
                    adapter_key = cmd.split()[1]
                    self.restart_adapter(adapter_key)
                elif cmd == "help":
                    print("可用命令: status, start, stop, restart <adapter>, quit")
                elif cmd:
                    print(f"未知命令: {cmd}（输入 help 查看帮助）")
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_monitor()
            self.stop_all()


# ============================================================
# 命令行入口
# ============================================================

def _parse_args() -> argparse.Namespace:
    """解析命令行参数.

    Returns:
        解析后的参数
    """
    parser = argparse.ArgumentParser(
        description="M11 MCP 总线 - 统一适配器管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s start                  启动所有适配器
  %(prog)s start --only voice,m2  只启动语音和 M2 适配器
  %(prog)s status                 查看适配器状态
  %(prog)s stop                   停止所有适配器
  %(prog)s restart m7             重启 M7 适配器
  %(prog)s run                    启动并持续运行（交互模式）
        """,
    )
    parser.add_argument(
        "command",
        choices=["start", "stop", "status", "restart", "run"],
        help="操作命令",
    )
    parser.add_argument(
        "adapter",
        nargs="?",
        default=None,
        help="适配器名称（仅 restart 命令需要）",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="只启动指定的适配器，逗号分隔（如 voice,m2,m7）",
    )
    parser.add_argument(
        "--bus-url",
        default=None,
        help="M11 总线地址（覆盖环境变量 M11_BUS_URL）",
    )
    return parser.parse_args()


def _get_enabled_adapters(only_arg: Optional[str]) -> List[str]:
    """获取要启用的适配器列表.

    优先级：--only 参数 > 环境变量 ADAPTERS_ENABLED > 默认全部

    Args:
        only_arg: --only 参数值

    Returns:
        适配器标识列表
    """
    if only_arg:
        adapters = [a.strip().lower() for a in only_arg.split(",") if a.strip()]
    else:
        env_val = os.environ.get("ADAPTERS_ENABLED", "")
        if env_val:
            adapters = [a.strip().lower() for a in env_val.split(",") if a.strip()]
        else:
            adapters = list(ADAPTER_CONFIGS.keys())

    # 验证适配器名称
    valid = []
    invalid = []
    for a in adapters:
        if a in ADAPTER_CONFIGS:
            valid.append(a)
        else:
            invalid.append(a)

    if invalid:
        print(f"警告：未知的适配器将被忽略: {', '.join(invalid)}")
        print(f"可用适配器: {', '.join(ADAPTER_CONFIGS.keys())}")

    return valid


def main() -> None:
    """主函数 - 统一适配器管理入口."""
    args = _parse_args()

    # 设置总线地址
    if args.bus_url:
        os.environ["M11_BUS_URL"] = args.bus_url

    # 确定要管理的适配器
    adapter_keys = _get_enabled_adapters(args.only)

    if not adapter_keys:
        print("错误：没有有效的适配器")
        print(f"可用适配器: {', '.join(ADAPTER_CONFIGS.keys())}")
        sys.exit(1)

    manager = AdapterManager(adapter_keys)

    if args.command == "start":
        # 启动所有适配器并持续运行
        manager.start_all()
        manager.run_forever()

    elif args.command == "stop":
        manager.stop_all()

    elif args.command == "status":
        manager.print_status()

    elif args.command == "restart":
        if not args.adapter:
            print("错误：restart 命令需要指定适配器名称")
            sys.exit(1)
        success = manager.restart_adapter(args.adapter)
        sys.exit(0 if success else 1)

    elif args.command == "run":
        # 启动并持续运行
        manager.start_all()
        manager.run_forever()


if __name__ == "__main__":
    main()
