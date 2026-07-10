#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
云汐系统 - 部署自动化脚本
功能：一键启动/停止/状态检查/健康检测所有模块

使用方式：
    python yunxi_deploy.py start     # 启动所有模块
    python yunxi_deploy.py stop      # 停止所有模块
    python yunxi_deploy.py status    # 查看所有模块状态
    python yunxi_deploy.py health    # 健康检查
    python yunxi_deploy.py restart   # 重启所有模块
    python yunxi_deploy.py start m8  # 只启动指定模块

模块端口分配：
    M1  Agent Cluster    8001
    M2  Skill Cluster    8002
    M3  Edge Cloud       8003
    M4  Scene Engine     8004
    M5  Tide Memory      8005
    M6  Hardware Hub     8006
    M7  Workflow         8007
    M8  Control Tower    8008  (核心入口)
    M9  Dev Workshop     8009
    M10 System Guard     8010

用户入口：
    系统入口页:  http://localhost:8008/
    主理人入口:  http://localhost:8008/owner.html
    M8控制台:   http://localhost:8008/m8/
    M9工坊:     http://localhost:8009/
    API文档:    http://localhost:8008/docs
"""

import os
import sys
import time
import json
import signal
import subprocess
from pathlib import Path
from datetime import datetime

# ==================== 配置 ====================

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()

# 模块配置
MODULES = {
    "m8": {
        "name": "M8 控制塔",
        "port": 8008,
        "entry": "M8-control-tower/backend/main.py",
        "workdir": "M8-control-tower/backend",
        "critical": True,  # 核心模块
    },
    "m9": {
        "name": "M9 开发者工坊",
        "port": 8009,
        "entry": "M9-dev-workshop/backend/main.py",
        "workdir": "M9-dev-workshop/backend",
        "critical": True,
    },
}

# 进程记录文件
PID_FILE = PROJECT_ROOT / ".yunxi_pids.json"

# Python 解释器
PYTHON = sys.executable


# ==================== 工具函数 ====================

def log(msg, level="info"):
    """带颜色的日志输出"""
    colors = {
        "info": "\033[36m",     # cyan
        "success": "\033[32m",  # green
        "warning": "\033[33m",  # yellow
        "error": "\033[31m",    # red
        "dim": "\033[90m",      # gray
    }
    reset = "\033[0m"
    color = colors.get(level, "")
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{timestamp}] {msg}{reset}")


def load_pids():
    """加载进程记录"""
    if PID_FILE.exists():
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_pids(pids):
    """保存进程记录"""
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(pids, f, indent=2, ensure_ascii=False)


def check_port(port):
    """检查端口是否被占用"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            return result == 0
    except Exception:
        return False


def check_health(port, path="/health"):
    """检查模块健康状态"""
    try:
        import urllib.request
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


# ==================== 启动模块 ====================

def start_module(module_key):
    """启动单个模块"""
    if module_key not in MODULES:
        log(f"未知模块: {module_key}", "error")
        return False

    mod = MODULES[module_key]
    pids = load_pids()

    # 检查是否已在运行
    if module_key in pids and pids[module_key].get("pid"):
        pid = pids[module_key]["pid"]
        try:
            os.kill(pid, 0)  # 发送信号0，检查进程是否存在
            log(f"{mod['name']} 已在运行 (PID: {pid})", "warning")
            return True
        except OSError:
            # 进程不存在，清理记录
            del pids[module_key]
            save_pids(pids)

    # 检查端口
    if check_port(mod["port"]):
        log(f"{mod['name']} 端口 {mod['port']} 已被占用", "warning")
        return True

    # 启动进程
    workdir = PROJECT_ROOT / mod["workdir"]
    entry_file = PROJECT_ROOT / mod["entry"]

    if not entry_file.exists():
        log(f"{mod['name']} 入口文件不存在: {entry_file}", "error")
        return False

    log(f"正在启动 {mod['name']} (端口: {mod['port']})...")

    try:
        # 重定向输出到日志文件
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{module_key}.log"

        with open(log_file, "a", encoding="utf-8") as log_f:
            process = subprocess.Popen(
                [PYTHON, str(entry_file)],
                cwd=str(workdir),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # 独立进程组
            )

        pids[module_key] = {
            "pid": process.pid,
            "port": mod["port"],
            "name": mod["name"],
            "started_at": datetime.now().isoformat(),
        }
        save_pids(pids)

        log(f"{mod['name']} 启动成功 (PID: {process.pid})", "success")
        return True

    except Exception as e:
        log(f"{mod['name']} 启动失败: {e}", "error")
        return False


def start_all():
    """启动所有模块"""
    log("=" * 50)
    log("云汐系统 - 启动所有模块", "info")
    log("=" * 50)

    success_count = 0
    total = len(MODULES)

    # 先启动核心模块
    critical = [k for k, v in MODULES.items() if v.get("critical")]
    others = [k for k, v in MODULES.items() if not v.get("critical")]

    for key in critical + others:
        if start_module(key):
            success_count += 1
        # 稍等一下避免端口冲突
        time.sleep(0.5)

    log("-" * 50)
    log(f"启动完成: {success_count}/{total} 个模块", "success" if success_count == total else "warning")

    # 等待健康检查
    log("\n正在等待服务就绪...", "dim")
    time.sleep(2)
    health_check()

    # 显示入口地址
    show_portals()


# ==================== 停止模块 ====================

def stop_module(module_key):
    """停止单个模块"""
    pids = load_pids()

    if module_key not in pids:
        log(f"{module_key} 未在运行（无进程记录）", "warning")
        return True

    pid = pids[module_key]["pid"]
    mod_name = pids[module_key].get("name", module_key)

    try:
        # 检查进程是否存在
        os.kill(pid, 0)
    except OSError:
        log(f"{mod_name} 进程已不存在 (PID: {pid})", "warning")
        del pids[module_key]
        save_pids(pids)
        return True

    log(f"正在停止 {mod_name} (PID: {pid})...")

    try:
        # 优雅停止：发送 SIGTERM
        os.kill(pid, signal.SIGTERM)

        # 等待最多5秒
        for i in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                break
        else:
            # 强制停止
            log(f"{mod_name} 未响应，强制停止", "warning")
            os.kill(pid, signal.SIGKILL)

        del pids[module_key]
        save_pids(pids)
        log(f"{mod_name} 已停止", "success")
        return True

    except Exception as e:
        log(f"停止 {mod_name} 失败: {e}", "error")
        return False


def stop_all():
    """停止所有模块"""
    log("=" * 50)
    log("云汐系统 - 停止所有模块", "info")
    log("=" * 50)

    pids = load_pids()
    if not pids:
        log("没有运行中的模块", "warning")
        return

    for key in reversed(list(pids.keys())):
        stop_module(key)

    log("所有模块已停止", "success")


# ==================== 状态检查 ====================

def show_status():
    """显示所有模块状态"""
    log("=" * 50)
    log("云汐系统 - 模块状态", "info")
    log("=" * 50)

    pids = load_pids()

    print(f"{'模块':<20} {'端口':<8} {'状态':<10} {'PID':<8}")
    print("-" * 50)

    for key, mod in MODULES.items():
        port = mod["port"]
        name = mod["name"]
        pid = pids.get(key, {}).get("pid", "-")
        running = check_port(port)

        status = "运行中" if running else "已停止"
        status_color = "success" if running else "dim"

        print(f"{name:<20} {port:<8} ", end="")
        # 用颜色打印状态
        colors = {"success": "\033[32m", "dim": "\033[90m"}
        reset = "\033[0m"
        print(f"{colors.get(status_color, '')}{status:<10}{reset} {pid:<8}")

    print()


def health_check():
    """健康检查"""
    log("=" * 50)
    log("云汐系统 - 健康检查", "info")
    log("=" * 50)

    healthy = 0
    total = len(MODULES)

    for key, mod in MODULES.items():
        port = mod["port"]
        name = mod["name"]
        is_healthy = check_health(port)

        if is_healthy:
            log(f"  ✓ {name} (端口 {port}) - 正常", "success")
            healthy += 1
        else:
            log(f"  ✗ {name} (端口 {port}) - 未响应", "warning")

    log("-" * 50)
    log(f"健康状态: {healthy}/{total} 个模块正常", "success" if healthy == total else "warning")


# ==================== 入口展示 ====================

def show_portals():
    """显示用户入口地址"""
    m8_port = MODULES["m8"]["port"]
    m9_port = MODULES["m9"]["port"]

    print()
    log("=" * 50, "dim")
    log("🚪 用户入口", "info")
    log("=" * 50, "dim")

    portals = [
        ("系统入口页", f"http://localhost:{m8_port}/"),
        ("主理人入口", f"http://localhost:{m8_port}/owner.html"),
        ("M8 控制塔", f"http://localhost:{m8_port}/m8/"),
        ("M9 开发者工坊", f"http://localhost:{m9_port}/"),
        ("API 文档 (M8)", f"http://localhost:{m8_port}/docs"),
        ("API 文档 (M9)", f"http://localhost:{m9_port}/docs"),
    ]

    for name, url in portals:
        log(f"  → {name:<15} {url}", "dim")

    print()


# ==================== 主入口 ====================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "start":
        if len(sys.argv) > 2:
            # 启动指定模块
            for mod in sys.argv[2:]:
                start_module(mod.lower())
        else:
            start_all()

    elif command == "stop":
        if len(sys.argv) > 2:
            for mod in sys.argv[2:]:
                stop_module(mod.lower())
        else:
            stop_all()

    elif command == "status":
        show_status()

    elif command == "health":
        health_check()

    elif command == "restart":
        stop_all()
        time.sleep(1)
        start_all()

    elif command == "portals" or command == "urls":
        show_portals()

    elif command == "help" or command == "-h" or command == "--help":
        print(__doc__)

    else:
        log(f"未知命令: {command}", "error")
        print(__doc__)


if __name__ == "__main__":
    main()
