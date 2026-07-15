#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云汐桌面启动器 - Windows 系统托盘应用
提供一键启动/停止云汐系统、模块健康检查、状态可视化等功能。

依赖: pip install pystray pillow psutil httpx
可选: pip install keyboard  (全局快捷键 Ctrl+Alt+Y)
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
import subprocess
import socket
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Callable, Optional

# ============ 可选依赖检测与导入 ============
try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pystray
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False


# ============ 配置常量 ============
BASE_DIR = Path(r"c:\云汐\工作台\yunxi-project")
START_SCRIPT = BASE_DIR / "start-all.ps1"
STOP_SCRIPT = BASE_DIR / "stop-all.ps1"
PORTAL_HTML = BASE_DIR / "frontend" / "portal" / "index.html"
API_DOCS_HTML = BASE_DIR / "frontend" / "portal" / "api-docs.html"

MODULE_PORTS: List[int] = list(range(8000, 8013))  # 8000-8012，共 13 个模块
MODULE_NAMES: List[str] = [
    "网关服务", "认证中心", "用户服务", "消息服务",
    "文件服务", "任务调度", "日志服务", "监控服务",
    "配置中心", "搜索服务", "通知服务", "数据服务", "AI引擎"
]

POLL_INTERVAL = 30          # 健康检查轮询间隔（秒）
HEALTH_TIMEOUT = 5.0        # 单次健康检查超时（秒）
ICON_SIZE = 64              # 托盘图标尺寸（像素）

# 颜色定义 (R, G, B)
COLOR_IDLE = (128, 128, 128)      # 灰色 - 未启动
COLOR_STARTING = (59, 130, 246)   # 蓝色 - 启动中
COLOR_READY = (34, 197, 94)       # 绿色 - 全部就绪
COLOR_ERROR = (239, 68, 68)       # 红色 - 有故障
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)


# ============ 图标绘制 ============
def _draw_xi_character(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    """
    用基础几何图形绘制简化版"汐"字（氵 + 夕）。
    不依赖任何外部字体，纯矢量线条拼接。
    """
    s = size / 2.0  # 半高/半宽基准
    white = COLOR_WHITE + (255,)
    width = max(2, int(size / 12))

    # ---- 三点水 (氵) ----
    left_x = int(cx - s * 0.30)
    for i, dy in enumerate([-0.22, 0.00, 0.22]):
        y = int(cy + s * dy)
        # 用短横线模拟点（不同角度更自然）
        draw.line(
            [(left_x - 2, y), (left_x + 3, y - 1)],
            fill=white, width=width
        )

    # ---- 夕 ----
    right_cx = int(cx + s * 0.08)
    top_y = int(cy - s * 0.25)
    mid_y = int(cy + s * 0.05)
    bot_y = int(cy + s * 0.30)

    # 撇（从右上向左下）
    draw.line(
        [(right_cx + int(s * 0.28), top_y), (right_cx - int(s * 0.10), bot_y)],
        fill=white, width=width
    )
    # 横折钩的横
    draw.line(
        [(right_cx - int(s * 0.12), mid_y), (right_cx + int(s * 0.30), mid_y)],
        fill=white, width=width
    )
    # 横折钩的折（向下微弯）
    draw.line(
        [(right_cx + int(s * 0.30), mid_y), (right_cx + int(s * 0.18), bot_y + int(s * 0.05))],
        fill=white, width=width
    )
    # 夕右上角的小点/短撇
    draw.line(
        [(right_cx + int(s * 0.05), top_y + int(s * 0.08)), (right_cx + int(s * 0.18), top_y - int(s * 0.02))],
        fill=white, width=width
    )


def generate_icon(color: tuple[int, int, int]) -> Image.Image:
    """
    生成指定颜色的圆形"汐"字图标。

    Args:
        color: RGB 元组

    Returns:
        PIL Image 对象 (RGBA, 64x64)
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 3
    # 外圆（主色）
    draw.ellipse(
        [(margin, margin), (ICON_SIZE - margin, ICON_SIZE - margin)],
        fill=color + (255,)
    )
    # 内圆细边（增加立体感）
    inner_margin = margin + 2
    draw.ellipse(
        [(inner_margin, inner_margin), (ICON_SIZE - inner_margin, ICON_SIZE - inner_margin)],
        outline=(255, 255, 255, 80), width=1
    )

    _draw_xi_character(draw, ICON_SIZE // 2, ICON_SIZE // 2, ICON_SIZE - margin * 4)
    return img


# ============ 网络 / 进程工具 ============
def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """通过 TCP 连接快速检测端口是否被占用/监听。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def fetch_health(port: int, timeout: float = HEALTH_TIMEOUT) -> bool:
    """尝试访问模块的 /health 端点。优先使用 httpx，回退到 urllib。"""
    url = f"http://127.0.0.1:{port}/health"
    if HTTPX_AVAILABLE:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url)
                return resp.status_code == 200
        except Exception:
            return False
    else:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode() == 200
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout):
            return False


def get_processes_by_ports(ports: List[int]) -> List[psutil.Process]:
    """返回监听指定端口的进程列表（需要 psutil）。"""
    if not PSUTIL_AVAILABLE:
        return []
    procs: set = set()
    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr and conn.laddr.port in ports:
            if conn.pid and conn.pid != os.getpid():
                try:
                    procs.add(psutil.Process(conn.pid))
                except psutil.NoSuchProcess:
                    pass
    return list(procs)


def kill_processes_by_ports(ports: List[int]) -> int:
    """优雅终止监听指定端口的进程，返回终止数量。"""
    if not PSUTIL_AVAILABLE:
        return 0
    count = 0
    for proc in get_processes_by_ports(ports):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # 等待 3 秒后强制结束未退出的进程
    time.sleep(3)
    for proc in get_processes_by_ports(ports):
        try:
            proc.kill()
            count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return count


def run_powershell(script_path: Path) -> None:
    """在新窗口中异步执行 PowerShell 脚本。"""
    if not script_path.exists():
        print(f"[错误] 脚本不存在: {script_path}")
        return
    cmd = [
        "powershell",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script_path)
    ]
    try:
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        print(f"[错误] 启动 PowerShell 失败: {e}")


# ============ 托盘应用主类 ============
class YunxiTrayApp:
    def __init__(self) -> None:
        self.tray_icon: Optional[pystray.Icon] = None
        self.status: str = "idle"           # idle | starting | ready | error
        self.module_health: Dict[int, bool] = {port: False for port in MODULE_PORTS}
        self.health_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    # ---------- 状态计算 ----------
    def _update_aggregate_status(self) -> None:
        """根据各模块健康状态计算整体状态。"""
        with self._lock:
            ready = sum(self.module_health.values())
            total = len(MODULE_PORTS)

            if ready == 0:
                new_status = "idle"
            elif ready == total:
                new_status = "ready"
            else:
                # 部分在线视为 error（有故障）
                new_status = "error"

            self.status = new_status
            self._refresh_tray_ui(ready, total)

    def _refresh_tray_ui(self, ready: int, total: int) -> None:
        """刷新图标和悬浮提示（必须在持有 _lock 时调用或保证线程安全）。"""
        if not PYSTRAY_AVAILABLE or self.tray_icon is None:
            return

        color_map = {
            "idle": COLOR_IDLE,
            "starting": COLOR_STARTING,
            "ready": COLOR_READY,
            "error": COLOR_ERROR,
        }
        color = color_map.get(self.status, COLOR_IDLE)

        # 生成新图标
        try:
            new_icon = generate_icon(color)
            self.tray_icon.icon = new_icon
        except Exception as e:
            print(f"[警告] 图标更新失败: {e}")

        # 更新 tooltip
        if self.status == "error":
            failed_names = [
                MODULE_NAMES[i]
                for i, port in enumerate(MODULE_PORTS)
                if not self.module_health[port]
            ]
            tip = f"云汐系统 - {ready}/{total} 就绪\n故障: {', '.join(failed_names[:4])}"
            if len(failed_names) > 4:
                tip += f" 等共 {len(failed_names)} 个模块"
        elif self.status == "ready":
            tip = f"云汐系统 - {ready}/{total} 全部就绪"
        elif self.status == "starting":
            tip = f"云汐系统 - {ready}/{total} 启动中..."
        else:
            tip = f"云汐系统 - 未启动 ({ready}/{total})"

        self.tray_icon.title = tip

    # ---------- 菜单动作 ----------
    def start_system(self, icon: Optional[pystray.Icon] = None, item: Optional[pystray.MenuItem] = None) -> None:
        """启动云汐系统。"""
        print("[动作] 启动云汐系统")

        # 启动前检查端口占用
        occupied: List[int] = [p for p in MODULE_PORTS if is_port_open(p)]
        if occupied:
            msg = f"检测到以下端口已被占用: {occupied}\n请先停止现有实例再启动。"
            print(f"[警告] {msg}")
            # 尝试更新 tooltip 提示用户
            if self.tray_icon:
                self.tray_icon.title = f"云汐系统 - 端口占用: {occupied}"
            return

        self.status = "starting"
        with self._lock:
            self._refresh_tray_ui(0, len(MODULE_PORTS))

        run_powershell(START_SCRIPT)

    def stop_system(self, icon: Optional[pystray.Icon] = None, item: Optional[pystray.MenuItem] = None) -> None:
        """停止云汐系统。"""
        print("[动作] 停止云汐系统")

        if PSUTIL_AVAILABLE:
            count = kill_processes_by_ports(MODULE_PORTS)
            print(f"[信息] 已终止 {count} 个相关进程")

        run_powershell(STOP_SCRIPT)

        # 重置状态
        with self._lock:
            self.module_health = {port: False for port in MODULE_PORTS}
            self.status = "idle"
            self._refresh_tray_ui(0, len(MODULE_PORTS))

    def open_portal(self, icon: Optional[pystray.Icon] = None, item: Optional[pystray.MenuItem] = None) -> None:
        """打开统一门户页面。"""
        url = PORTAL_HTML.resolve().as_uri()
        print(f"[动作] 打开统一门户: {url}")
        webbrowser.open(url)

    def open_api_docs(self, icon: Optional[pystray.Icon] = None, item: Optional[pystray.MenuItem] = None) -> None:
        """打开 API 文档页面。"""
        url = API_DOCS_HTML.resolve().as_uri()
        print(f"[动作] 打开 API 文档: {url}")
        webbrowser.open(url)

    def exit_app(self, icon: Optional[pystray.Icon] = None, item: Optional[pystray.MenuItem] = None) -> None:
        """退出托盘应用。"""
        print("[动作] 退出云汐桌面启动器")
        self._running = False

        if KEYBOARD_AVAILABLE:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass

        if self.tray_icon:
            self.tray_icon.stop()

        # 给后台线程一点时间退出
        time.sleep(0.3)
        sys.exit(0)

    # ---------- 动态菜单构建 ----------
    def _build_menu(self) -> pystray.Menu:
        """每次打开右键菜单时动态构建（确保状态最新）。"""
        with self._lock:
            ready = sum(self.module_health.values())
            total = len(MODULE_PORTS)

            # 模块状态子菜单项
            module_items: List[pystray.MenuItem] = []
            for i, port in enumerate(MODULE_PORTS):
                name = MODULE_NAMES[i]
                is_ok = self.module_health[port]
                bullet = "●" if is_ok else "○"
                label = f"{bullet} {name}  ({port})"
                module_items.append(
                    pystray.MenuItem(label, lambda: None, enabled=False)
                )

            # 主菜单
            return pystray.Menu(
                pystray.MenuItem("启动云汐系统", self.start_system),
                pystray.MenuItem("停止云汐系统", self.stop_system),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("打开统一门户", self.open_portal, default=True),
                pystray.MenuItem("打开 API 文档", self.open_api_docs),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    f"模块状态  ({ready}/{total})",
                    pystray.Menu(*module_items)
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self.exit_app),
            )

    # ---------- 后台健康检查 ----------
    def _health_polling_loop(self) -> None:
        """后台线程：定期轮询所有模块 /health 端点。"""
        print("[后台] 健康检查线程已启动")
        while self._running:
            new_health: Dict[int, bool] = {}
            for port in MODULE_PORTS:
                # 先快速端口探测，减少等待
                if not is_port_open(port, timeout=1.0):
                    new_health[port] = False
                    continue
                # 端口开放后再访问 /health
                new_health[port] = fetch_health(port)

            with self._lock:
                self.module_health = new_health

            self._update_aggregate_status()

            # 分段睡眠，便于及时退出
            for _ in range(POLL_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)
        print("[后台] 健康检查线程已退出")

    # ---------- 主入口 ----------
    def run(self) -> None:
        """启动托盘应用主循环。"""
        if not PYSTRAY_AVAILABLE:
            print("=" * 50)
            print("错误: pystray 未安装，无法启动系统托盘应用。")
            print("请执行以下命令安装依赖:")
            print('    pip install pystray pillow psutil httpx')
            print("=" * 50)
            sys.exit(1)

        if not PIL_AVAILABLE:
            print("错误: Pillow 未安装，图标生成需要 Pillow。")
            sys.exit(1)

        self._running = True

        # 启动健康检查后台线程
        self.health_thread = threading.Thread(target=self._health_polling_loop, daemon=True)
        self.health_thread.start()

        # 注册全局快捷键 (Ctrl+Alt+Y)
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey("ctrl+alt+y", self.open_portal)
                print("[信息] 已注册全局快捷键 Ctrl+Alt+Y")
            except Exception as e:
                print(f"[警告] 全局快捷键注册失败（可能需要管理员权限）: {e}")

        # 初始化图标
        init_icon = generate_icon(COLOR_IDLE)

        # 创建托盘图标实例（menu 传入 callable 实现动态刷新）
        self.tray_icon = pystray.Icon(
            name="yunxi-tray",
            icon=init_icon,
            title="云汐系统 - 初始化中",
            menu=self._build_menu,
        )

        print("[信息] 云汐桌面启动器已启动，图标常驻系统托盘。")
        self.tray_icon.run()


# ============ 入口 ============
def main() -> None:
    app = YunxiTrayApp()
    app.run()


if __name__ == "__main__":
    main()
