#!/usr/bin/env python3
"""
云汐系统安全审计工具

功能：
- 敏感信息扫描（密钥、密码、token等）
- 依赖安全检查
- API端点安全评估
- 配置安全审计
- 代码安全模式检查
"""
import os
import re
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SecurityAuditor:
    """安全审计器"""
    
    def __init__(self, root_path: str = None):
        self.root_path = Path(root_path) if root_path else PROJECT_ROOT
        self.findings: List[Dict[str, Any]] = []
        self.stats = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }
        
        # 跳过的目录
        self.skip_dirs = {
            '.git', '__pycache__', '.pytest_cache', 'node_modules',
            'archive', 'M5-tide-memory', 'data', 'logs', 'backup',
            '.venv', 'venv', 'env',
        }
        
        # 敏感信息正则模式
        self.secret_patterns = {
            "api_key_generic": (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "API Key"),
            "secret_key": (r'(?i)(secret[_-]?key|secret)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "Secret Key"),
            "password": (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?([^"\'\s]{6,})["\']?', "Password"),
            "token": (r'(?i)(token|auth[_-]?token)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "Token"),
            "private_key": (r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----', "Private Key"),
            "aws_key": (r'(?i)aws[_-]?(access[_-]?key|secret[_-]?key)\s*[:=]\s*["\']?([A-Za-z0-9/+=]{20,})["\']?', "AWS Key"),
        }
        
        # 不安全代码模式
        self.code_patterns = {
            "hardcoded_sql": (r'(?i)(execute|cursor\.execute)\s*\(\s*["\'][^"\']*%(?:s|d|i)[^"\']*["\']\s*%', "SQL注入风险"),
            "eval_usage": (r'\beval\s*\(', "eval使用"),
            "exec_usage": (r'\bexec\s*\(', "exec使用"),
            "pickle_load": (r'pickle\.loads?\s*\(', "pickle反序列化风险"),
            "yaml_unsafe_load": (r'yaml\.load\s*\(', "yaml不安全加载"),
            "subprocess_shell": (r'subprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*True', "命令注入风险"),
            "debug_mode": (r'(?i)debug\s*[:=]\s*True', "调试模式开启"),
        }
    
    def add_finding(self, severity: str, category: str, description: str,
                    file_path: str = None, line: int = None, code: str = None):
        """添加发现项"""
        finding = {
            "severity": severity,
            "category": category,
            "description": description,
            "file_path": str(file_path) if file_path else None,
            "line": line,
            "code": code.strip() if code else None,
            "timestamp": datetime.now().isoformat(),
        }
        self.findings.append(finding)
        self.stats[severity] = self.stats.get(severity, 0) + 1
    
    def _find_files(self, suffix: str = None, patterns: List[str] = None) -> List[Path]:
        """
        安全地查找文件（使用os.walk避免损坏的符号链接）
        
        Args:
            suffix: 文件后缀过滤（如 '.py'）
            patterns: 文件名匹配模式列表（如 ['.env', '.env.test']）
        """
        results = []
        root = str(self.root_path)
        
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            # 跳过排除的目录
            dirnames[:] = [d for d in dirnames if d not in self.skip_dirs]
            
            for filename in filenames:
                file_path = Path(dirpath) / filename
                
                # 后缀过滤
                if suffix and not filename.endswith(suffix):
                    # 检查是否匹配pattern
                    if patterns and not any(p in filename for p in patterns):
                        continue
                    elif not patterns:
                        continue
                
                # pattern过滤
                if patterns and not any(p in filename for p in patterns):
                    continue
                
                try:
                    if file_path.is_file():
                        results.append(file_path)
                except OSError:
                    pass
        
        return results
    
    def scan_secrets(self):
        """扫描敏感信息泄露"""
        print("  扫描敏感信息...")
        
        # 扫描 .env 和配置文件
        env_files = self._find_files(patterns=['.env', '.env.', '.json'])
        for f in env_files:
            rel_str = str(f.relative_to(self.root_path))
            if 'config' in rel_str or '.env' in f.name:
                self._scan_file_secrets(f)
        
        # 扫描Python文件
        py_files = self._find_files(suffix='.py')
        for f in py_files:
            self._scan_file_secrets(f)
    
    def _scan_file_secrets(self, file_path: Path):
        """扫描单个文件的敏感信息"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            rel_path = file_path.relative_to(self.root_path)
            
            for i, line in enumerate(lines, 1):
                # 跳过注释行
                if line.strip().startswith('#'):
                    continue
                
                # 跳过示例/模板文件
                if 'example' in str(file_path).lower() or 'template' in str(file_path).lower():
                    continue
                
                # 跳过明显是占位符的值
                if any(placeholder in line.lower() for placeholder in 
                       ['your_', 'xxx', 'changeme', 'replace_me', 'example']):
                    continue
                
                for pattern_name, (pattern, label) in self.secret_patterns.items():
                    matches = re.findall(pattern, line)
                    for match in matches:
                        value = match[1] if isinstance(match, tuple) else match
                        # 排除常见假阳性
                        if len(value) < 8:
                            continue
                        if value in ('None', 'null', 'true', 'false'):
                            continue
                        
                        self.add_finding(
                            severity="high",
                            category="sensitive_data",
                            description=f"可能的{label}泄露",
                            file_path=rel_path,
                            line=i,
                            code=line,
                        )
        except Exception as e:
            pass
    
    def scan_code_security(self):
        """扫描代码安全问题"""
        print("  扫描代码安全...")
        
        for f in self._find_files(suffix='.py'):
            try:
                with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
                    lines = fh.readlines()
                
                rel_path = f.relative_to(self.root_path)
                
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith('#'):
                        continue
                    
                    for pattern_name, (pattern, label) in self.code_patterns.items():
                        if re.search(pattern, line):
                            severity = "medium"
                            if pattern_name in ("hardcoded_sql", "subprocess_shell"):
                                severity = "high"
                            elif pattern_name in ("eval_usage", "exec_usage"):
                                severity = "medium"
                            elif pattern_name == "debug_mode":
                                severity = "low"
                            
                            self.add_finding(
                                severity=severity,
                                category="code_security",
                                description=label,
                                file_path=rel_path,
                                line=i,
                                code=line,
                            )
            except Exception:
                pass
    
    def scan_config_security(self):
        """扫描配置安全"""
        print("  扫描配置安全...")
        
        # 检查 .env 文件
        env_files = self._find_files(patterns=['.env'])
        if not env_files:
            self.add_finding(
                severity="info",
                category="config",
                description="未找到.env文件，确保配置通过环境变量管理",
            )
        
        # 检查是否有默认密码
        for env_file in env_files:
            try:
                content = env_file.read_text(encoding='utf-8', errors='ignore')
                if 'password=admin' in content.lower() or 'password=123456' in content.lower():
                    self.add_finding(
                        severity="critical",
                        category="config",
                        description="发现默认密码",
                        file_path=env_file.relative_to(self.root_path),
                    )
            except Exception:
                pass
    
    def scan_dependencies(self):
        """扫描依赖文件"""
        print("  扫描依赖文件...")
        
        req_files = self._find_files(patterns=['requirements.txt'])
        if not req_files:
            self.add_finding(
                severity="low",
                category="dependencies",
                description="未找到requirements.txt，建议显式声明依赖",
            )
        
        # 检查是否有未固定版本的依赖
        for req_file in req_files:
            try:
                lines = req_file.read_text(encoding='utf-8', errors='ignore').split('\n')
                for i, line in enumerate(lines, 1):
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('-'):
                        if '==' not in line and '>=' not in line and '<=' not in line:
                            self.add_finding(
                                severity="low",
                                category="dependencies",
                                description=f"未固定版本的依赖: {line}",
                                file_path=req_file.relative_to(self.root_path),
                                line=i,
                            )
            except Exception:
                pass
    
    def generate_report(self) -> Dict[str, Any]:
        """生成审计报告"""
        return {
            "audit_time": datetime.now().isoformat(),
            "project_root": str(self.root_path),
            "summary": {
                "total_findings": len(self.findings),
                **self.stats,
            },
            "findings": self.findings,
        }
    
    def print_report(self):
        """打印报告"""
        report = self.generate_report()
        
        print("\n" + "=" * 60)
        print("云汐系统 - 安全审计报告")
        print("=" * 60)
        print(f"审计时间: {report['audit_time']}")
        print(f"项目路径: {report['project_root']}")
        print()
        
        s = report['summary']
        print(f"总计发现: {s['total_findings']} 个问题")
        print(f"  严重: {s.get('critical', 0)}")
        print(f"  高危: {s.get('high', 0)}")
        print(f"  中危: {s.get('medium', 0)}")
        print(f"  低危: {s.get('low', 0)}")
        print(f"  信息: {s.get('info', 0)}")
        print()
        
        # 按严重程度排序显示
        severity_order = ["critical", "high", "medium", "low", "info"]
        severity_label = {"critical": "严重", "high": "高危", "medium": "中危", "low": "低危", "info": "信息"}
        
        for sev in severity_order:
            sev_findings = [f for f in self.findings if f["severity"] == sev]
            if not sev_findings:
                continue
            
            print(f"\n--- {severity_label[sev]} ({len(sev_findings)}) ---")
            for f in sev_findings[:10]:  # 每类最多显示10个
                loc = f"{f['file_path']}:{f['line']}" if f['file_path'] else "N/A"
                print(f"  [{f['category']}] {f['description']}")
                print(f"    位置: {loc}")
            
            if len(sev_findings) > 10:
                print(f"  ... 还有 {len(sev_findings) - 10} 个")
    
    def save_report(self, output_path: str):
        """保存报告到文件"""
        report = self.generate_report()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n报告已保存到: {output}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="云汐系统安全审计工具")
    parser.add_argument("--path", help="要扫描的路径（默认项目根目录）")
    parser.add_argument("--output", default="reports/security-audit.json", help="报告输出路径")
    parser.add_argument("--secrets-only", action="store_true", help="只扫描敏感信息")
    args = parser.parse_args()
    
    auditor = SecurityAuditor(args.path)
    
    print("开始安全审计...")
    print(f"扫描路径: {auditor.root_path}")
    print()
    
    auditor.scan_secrets()
    
    if not args.secrets_only:
        auditor.scan_code_security()
        auditor.scan_config_security()
        auditor.scan_dependencies()
    
    auditor.print_report()
    auditor.save_report(args.output)
    
    report = auditor.generate_report()
    s = report['summary']
    
    # 有严重或高危问题时返回非零退出码
    if s.get('critical', 0) > 0 or s.get('high', 0) > 0:
        print("\n⚠ 发现高危问题，请及时处理！")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
