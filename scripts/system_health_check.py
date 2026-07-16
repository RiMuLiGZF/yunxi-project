#!/usr/bin/env python3
"""
云汐系统健康巡检脚本
自动检测系统各模块状态，生成体检报告

用法:
    python system_health_check.py [--format html|json] [--output <path>]
"""

import os
import sys
import json
import time
import socket
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# 确保项目根目录在路径中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class SystemHealthChecker:
    """系统健康检查器"""

    def __init__(self):
        self.results = {
            "timestamp": datetime.datetime.now().isoformat(),
            "version": "",
            "overall_status": "unknown",
            "checks": {},
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "warnings": 0,
            },
        }
        self._module_ports = {
            "m8": 8000,
            "m1": 8001,
            "m2": 8002,
            "m3": 8003,
            "m4": 8004,
            "m5": 8005,
            "m6": 8006,
            "m7": 8007,
            "m9": 8009,
            "m10": 8010,
            "m11": 8011,
            "m12": 8012,
        }

    def check_all(self) -> Dict[str, Any]:
        """执行所有检查"""
        checks = [
            ("system", self.check_system),
            ("git", self.check_git),
            ("python", self.check_python),
            ("ollama", self.check_ollama),
            ("modules", self.check_modules),
            ("database", self.check_database),
            ("disk", self.check_disk),
            ("memory", self.check_memory),
            ("network", self.check_network),
        ]

        for name, check_func in checks:
            try:
                result = check_func()
                self.results["checks"][name] = result
            except Exception as e:
                self.results["checks"][name] = {
                    "status": "error",
                    "message": f"检查异常: {str(e)}",
                }

        # 计算总体状态
        self._calculate_overall()

        return self.results

    def _calculate_overall(self):
        """计算总体状态"""
        total = 0
        passed = 0
        failed = 0
        warnings = 0

        for name, check in self.results["checks"].items():
            total += 1
            status = check.get("status", "unknown")
            if status == "healthy":
                passed += 1
            elif status == "degraded":
                warnings += 1
            elif status == "unhealthy":
                failed += 1

        self.results["summary"] = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
        }

        if failed > 0:
            self.results["overall_status"] = "unhealthy"
        elif warnings > 0:
            self.results["overall_status"] = "degraded"
        else:
            self.results["overall_status"] = "healthy"

    # ==================== 各项检查 ====================

    def check_system(self) -> Dict[str, Any]:
        """系统基本信息检查"""
        import platform

        return {
            "status": "healthy",
            "os": platform.system(),
            "os_version": platform.version(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
            "check_time": datetime.datetime.now().isoformat(),
        }

    def check_git(self) -> Dict[str, Any]:
        """Git仓库状态检查"""
        try:
            import subprocess

            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=5, cwd=str(project_root)
            )
            changes = result.stdout.strip().split("\n") if result.stdout.strip() else []

            # 获取当前分支
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=str(project_root)
            )
            branch = branch_result.stdout.strip()

            # 获取最新提交
            commit_result = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                capture_output=True, text=True, timeout=5, cwd=str(project_root)
            )
            last_commit = commit_result.stdout.strip()

            # 读取版本号
            version = ""
            version_file = project_root / "VERSION"
            if version_file.exists():
                version = version_file.read_text().strip()
            self.results["version"] = version

            status = "healthy"
            if len(changes) > 10:
                status = "degraded"  # 过多未提交的改动

            return {
                "status": status,
                "branch": branch,
                "version": version,
                "last_commit": last_commit,
                "pending_changes": len(changes),
                "changes": changes[:20],  # 最多显示20条
                "message": f"Git仓库正常，{len(changes)}个文件待提交" if changes else "Git仓库干净",
            }
        except Exception as e:
            return {
                "status": "degraded",
                "message": f"Git检查失败: {str(e)}",
            }

    def check_python(self) -> Dict[str, Any]:
        """Python环境检查"""
        try:
            # 检查关键依赖
            critical_packages = [
                "fastapi", "uvicorn", "httpx", "pydantic",
            ]
            optional_packages = [
                "torch", "ollama", "numpy",
            ]

            import importlib
            critical_ok = []
            critical_missing = []
            for pkg in critical_packages:
                try:
                    importlib.import_module(pkg)
                    critical_ok.append(pkg)
                except ImportError:
                    critical_missing.append(pkg)

            optional_ok = []
            optional_missing = []
            for pkg in optional_packages:
                try:
                    importlib.import_module(pkg)
                    optional_ok.append(pkg)
                except ImportError:
                    optional_missing.append(pkg)

            status = "healthy"
            if critical_missing:
                status = "unhealthy"
            elif optional_missing:
                status = "degraded"

            return {
                "status": status,
                "python_version": sys.version,
                "critical_ok": critical_ok,
                "critical_missing": critical_missing,
                "optional_ok": optional_ok,
                "optional_missing": optional_missing,
                "message": f"Python环境{'正常' if status == 'healthy' else '有缺失'}",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Python检查异常: {str(e)}",
            }

    def check_ollama(self) -> Dict[str, Any]:
        """Ollama大模型服务检查"""
        try:
            import httpx

            # 检查端口连通性
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", 11434))
            sock.close()

            if result != 0:
                return {
                    "status": "unhealthy",
                    "running": False,
                    "message": "Ollama服务未启动",
                }

            # 获取模型列表
            try:
                resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", [])
                    model_names = [m.get("name", "") for m in models]

                    # 检查关键模型
                    has_3b = any("3b" in m.lower() for m in model_names)
                    has_7b = any("7b" in m.lower() for m in model_names)

                    status = "healthy"
                    if not has_7b:
                        status = "degraded"

                    return {
                        "status": status,
                        "running": True,
                        "models": model_names,
                        "model_count": len(models),
                        "has_3b_model": has_3b,
                        "has_7b_model": has_7b,
                        "message": f"Ollama运行中，{len(models)}个模型可用",
                    }
            except Exception:
                pass

            return {
                "status": "degraded",
                "running": True,
                "message": "Ollama运行中，但无法获取模型列表",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Ollama检查异常: {str(e)}",
            }

    def check_modules(self) -> Dict[str, Any]:
        """模块运行状态检查"""
        running = []
        stopped = []

        for module, port in self._module_ports.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()

                if result == 0:
                    running.append({"name": module, "port": port})
                else:
                    stopped.append({"name": module, "port": port})
            except Exception:
                stopped.append({"name": module, "port": port})

        total = len(self._module_ports)
        running_count = len(running)

        status = "healthy"
        if running_count < 3:
            status = "unhealthy"
        elif running_count < 5:
            status = "degraded"

        return {
            "status": status,
            "total": total,
            "running_count": running_count,
            "stopped_count": len(stopped),
            "running": running,
            "stopped": stopped,
            "message": f"{running_count}/{total} 个模块运行中",
        }

    def check_database(self) -> Dict[str, Any]:
        """数据库检查"""
        try:
            # 检查数据库文件是否存在
            db_file = project_root / "data" / "yunxi.db"
            if db_file.exists():
                size_mb = db_file.stat().st_size / (1024 * 1024)
                return {
                    "status": "healthy",
                    "exists": True,
                    "path": str(db_file),
                    "size_mb": round(size_mb, 2),
                    "message": f"数据库正常，大小 {size_mb:.2f} MB",
                }
            else:
                return {
                    "status": "degraded",
                    "exists": False,
                    "message": "数据库文件不存在（首次运行前为正常状态）",
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"数据库检查异常: {str(e)}",
            }

    def check_disk(self) -> Dict[str, Any]:
        """磁盘空间检查"""
        try:
            import shutil

            total, used, free = shutil.disk_usage(str(project_root))
            total_gb = total / (1024**3)
            used_gb = used / (1024**3)
            free_gb = free / (1024**3)
            usage_percent = (used / total) * 100

            status = "healthy"
            if usage_percent > 90:
                status = "unhealthy"
            elif usage_percent > 80:
                status = "degraded"

            return {
                "status": status,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "usage_percent": round(usage_percent, 1),
                "message": f"磁盘使用 {usage_percent:.1f}%，剩余 {free_gb:.2f} GB",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"磁盘检查异常: {str(e)}",
            }

    def check_memory(self) -> Dict[str, Any]:
        """内存使用检查"""
        try:
            import psutil

            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024**3)
            used_gb = mem.used / (1024**3)
            available_gb = mem.available / (1024**3)
            usage_percent = mem.percent

            status = "healthy"
            if usage_percent > 90:
                status = "unhealthy"
            elif usage_percent > 80:
                status = "degraded"

            return {
                "status": status,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "available_gb": round(available_gb, 2),
                "usage_percent": usage_percent,
                "message": f"内存使用 {usage_percent:.1f}%，剩余 {available_gb:.2f} GB",
            }
        except ImportError:
            return {
                "status": "degraded",
                "message": "psutil未安装，无法检测内存",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"内存检查异常: {str(e)}",
            }

    def check_network(self) -> Dict[str, Any]:
        """网络连通性检查"""
        results = {}
        failed_count = 0

        # 检查常用服务
        endpoints = {
            "localhost": "127.0.0.1",
            "gateway": "192.168.1.1",
            "dns": "8.8.8.8",
        }

        for name, host in endpoints.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect((host, 80))
                sock.close()
                results[name] = "ok"
            except Exception:
                results[name] = "failed"
                failed_count += 1

        status = "healthy"
        if failed_count >= 2:
            status = "degraded"

        return {
            "status": status,
            "results": results,
            "failed_count": failed_count,
            "message": f"网络检查完成，{len(endpoints) - failed_count}/{len(endpoints)} 项通过",
        }

    # ==================== 报告生成 ====================

    def to_json(self, indent: int = 2) -> str:
        """生成JSON格式报告"""
        return json.dumps(self.results, indent=indent, ensure_ascii=False)

    def to_html(self) -> str:
        """生成HTML格式报告"""
        status_colors = {
            "healthy": "#2a9d8f",
            "degraded": "#e9c46a",
            "unhealthy": "#e76f51",
            "error": "#e63946",
            "unknown": "#6c757d",
        }

        overall_status = self.results["overall_status"]
        overall_color = status_colors.get(overall_status, "#6c757d")
        summary = self.results["summary"]

        html_parts = [f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>云汐系统健康体检报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f5f7fa;
            color: #1a1a2e;
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        header {{
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: white;
            padding: 32px;
            border-radius: 12px;
            margin-bottom: 24px;
        }}
        header h1 {{
            font-size: 24px;
            margin-bottom: 8px;
        }}
        header .subtitle {{
            color: rgba(255,255,255,0.7);
            font-size: 14px;
        }}
        .overall {{
            display: flex;
            align-items: center;
            gap: 20px;
            margin-top: 20px;
        }}
        .status-badge {{
            display: inline-block;
            padding: 8px 20px;
            border-radius: 24px;
            font-weight: 600;
            font-size: 16px;
            color: white;
            background: {overall_color};
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .stat-card .num {{
            font-size: 28px;
            font-weight: 700;
            color: {overall_color};
        }}
        .stat-card .label {{
            font-size: 13px;
            color: #6c757d;
            margin-top: 4px;
        }}
        .check-section {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .check-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
        }}
        .check-header h3 {{
            font-size: 16px;
        }}
        .check-status {{
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            color: white;
        }}
        .check-message {{
            font-size: 14px;
            color: #495057;
            margin-bottom: 12px;
        }}
        .check-details {{
            font-size: 13px;
            color: #6c757d;
        }}
        .check-details table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 8px;
        }}
        .check-details td {{
            padding: 6px 8px;
            border-bottom: 1px solid #f1f3f5;
        }}
        .check-details td:first-child {{
            font-weight: 500;
            color: #495057;
            width: 120px;
        }}
        footer {{
            text-align: center;
            color: #adb5bd;
            font-size: 12px;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>云汐系统健康体检报告</h1>
            <div class="subtitle">生成时间：{self.results['timestamp']}</div>
            <div class="overall">
                <span class="status-badge">状态：{overall_status}</span>
                <span style="font-size: 14px; color: rgba(255,255,255,0.8);">
                    版本：{self.results.get('version', 'unknown')}
                </span>
            </div>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="num">{summary['total']}</div>
                <div class="label">检查项总数</div>
            </div>
            <div class="stat-card">
                <div class="num" style="color: #2a9d8f;">{summary['passed']}</div>
                <div class="label">通过</div>
            </div>
            <div class="stat-card">
                <div class="num" style="color: #e9c46a;">{summary['warnings']}</div>
                <div class="label">警告</div>
            </div>
            <div class="stat-card">
                <div class="num" style="color: #e76f51;">{summary['failed']}</div>
                <div class="label">失败</div>
            </div>
        </div>
"""]

        for name, check in self.results["checks"].items():
            status = check.get("status", "unknown")
            color = status_colors.get(status, "#6c757d")
            message = check.get("message", "")

            html_parts.append(f"""
        <div class="check-section">
            <div class="check-header">
                <h3>{name}</h3>
                <span class="check-status" style="background: {color};">{status}</span>
            </div>
            <div class="check-message">{message}</div>
            <div class="check-details">
                <table>
""")

            # 添加详细信息
            skip_keys = {"status", "message"}
            for key, value in check.items():
                if key in skip_keys:
                    continue
                if isinstance(value, (list, dict)):
                    value_str = json.dumps(value, ensure_ascii=False)[:100]
                else:
                    value_str = str(value)[:100]
                html_parts.append(f"""
                    <tr><td>{key}</td><td>{value_str}</td></tr>""")

            html_parts.append("""
                </table>
            </div>
        </div>
""")

        html_parts.append(f"""
        <footer>
            云汐系统健康体检报告 | 生成时间：{self.results['timestamp']}
        </footer>
    </div>
</body>
</html>""")

        return "\n".join(html_parts)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="云汐系统健康巡检")
    parser.add_argument("--format", choices=["html", "json"], default="html", help="报告格式")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径")
    parser.add_argument("--no-save", action="store_true", help="不保存文件，只打印结果")

    args = parser.parse_args()

    # 执行检查
    checker = SystemHealthChecker()
    checker.check_all()

    # 生成报告
    if args.format == "json":
        report = checker.to_json()
    else:
        report = checker.to_html()

    # 输出
    if not args.no_save:
        # 确定输出路径
        if args.output:
            output_path = Path(args.output)
        else:
            reports_dir = project_root / "inspection-reports"
            reports_dir.mkdir(exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            ext = "html" if args.format == "html" else "json"
            output_path = reports_dir / f"health-check-{timestamp}.{ext}"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"体检报告已生成: {output_path}")

    # 打印摘要
    summary = checker.results["summary"]
    overall = checker.results["overall_status"]
    print(f"\n总体状态: {overall}")
    print(f"检查项: {summary['total']} 项 | 通过: {summary['passed']} | 警告: {summary['warnings']} | 失败: {summary['failed']}")

    return 0 if overall in ("healthy", "degraded") else 1


if __name__ == "__main__":
    sys.exit(main())
