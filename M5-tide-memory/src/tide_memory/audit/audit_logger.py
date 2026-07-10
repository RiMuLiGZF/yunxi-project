"""
审计日志系统

每次记忆读写操作都有记录，确保可追溯
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class AuditLogger:
    """
    审计日志记录器
    
    记录所有对记忆数据的访问操作：
    - 读取（read）
    - 写入（write）
    - 删除（delete）
    - 修改（update）
    - 导出（export）
    
    ⚠️ 审计日志只记录操作元数据，绝不记录记忆内容
    """

    # 操作类型
    OP_READ = "read"
    OP_WRITE = "write"
    OP_DELETE = "delete"
    OP_UPDATE = "update"
    OP_EXPORT = "export"
    OP_LOGIN = "login"
    OP_PERMISSION_DENIED = "permission_denied"

    def __init__(self, log_path: str = "./logs/m5-audit.log",
                 max_file_size_mb: int = 100,
                 max_files: int = 10,
                 enabled: bool = True):
        self._log_path = log_path
        self._max_size = max_file_size_mb * 1024 * 1024
        self._max_files = max_files
        self._enabled = enabled
        self._buffer: List[str] = []
        self._buffer_size = 0
        self._flush_threshold = 50  # 满50条刷盘
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    def record(self, memory_id: str, operation: str, agent_id: str,
               domain: str, success: bool, failure_reason: str = "",
               metadata: Dict = None) -> None:
        """
        记录一条审计日志
        
        ⚠️ 不记录任何记忆内容，只记录操作元数据
        
        Args:
            memory_id: 记忆ID（不含内容）
            operation: 操作类型
            agent_id: 操作者ID
            domain: 操作域
            success: 是否成功
            failure_reason: 失败原因
            metadata: 附加元数据（不能包含敏感内容）
        """
        if not self._enabled:
            return

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "memory_id": memory_id,  # 只存ID，不存内容
            "agent_id": agent_id,
            "domain": domain,
            "success": success,
            "failure_reason": failure_reason,
            "client_ip": (metadata or {}).get("client_ip", ""),
            "request_id": (metadata or {}).get("request_id", ""),
        }

        log_line = json.dumps(log_entry, ensure_ascii=False)
        self._buffer.append(log_line)
        self._buffer_size += 1

        if self._buffer_size >= self._flush_threshold:
            self.flush()

    def flush(self) -> None:
        """将缓冲区写入磁盘"""
        if not self._buffer:
            return

        self._rotate_if_needed()

        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                for line in self._buffer:
                    f.write(line + "\n")
        except IOError:
            pass  # 写日志失败不影响主流程

        self._buffer.clear()
        self._buffer_size = 0

    def _rotate_if_needed(self) -> None:
        """日志轮转"""
        if not os.path.exists(self._log_path):
            return

        size = os.path.getsize(self._log_path)
        if size < self._max_size:
            return

        # 轮转：log.1, log.2, ...
        for i in range(self._max_files - 1, 0, -1):
            src = f"{self._log_path}.{i}"
            dst = f"{self._log_path}.{i + 1}"
            if os.path.exists(src):
                if i + 1 < self._max_files:
                    os.rename(src, dst)
                else:
                    os.remove(src)

        if os.path.exists(self._log_path):
            os.rename(self._log_path, f"{self._log_path}.1")

    def query(self, start_time: str = None, end_time: str = None,
              agent_id: str = None, operation: str = None,
              memory_id: str = None, limit: int = 100) -> List[Dict]:
        """
        查询审计日志
        
        ⚠️ 返回结果不含任何记忆内容
        """
        results = []
        if not os.path.exists(self._log_path):
            return results

        # 先刷盘
        self.flush()

        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except IOError:
            return results

        for line in reversed(lines):
            if len(results) >= limit:
                break
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            # 过滤
            if start_time and entry.get("timestamp", "") < start_time:
                continue
            if end_time and entry.get("timestamp", "") > end_time:
                continue
            if agent_id and entry.get("agent_id") != agent_id:
                continue
            if operation and entry.get("operation") != operation:
                continue
            if memory_id and entry.get("memory_id") != memory_id:
                continue

            results.append(entry)

        return results

    def get_stats(self) -> Dict:
        """获取审计统计"""
        stats = {
            "total_logs": 0,
            "by_operation": {},
            "by_agent": {},
            "success_rate": 1.0,
        }
        if not os.path.exists(self._log_path):
            return stats

        self.flush()

        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                success_count = 0
                total = 0
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        total += 1
                        op = entry.get("operation", "unknown")
                        agent = entry.get("agent_id", "unknown")
                        stats["by_operation"][op] = stats["by_operation"].get(op, 0) + 1
                        stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1
                        if entry.get("success"):
                            success_count += 1
                    except json.JSONDecodeError:
                        continue
                stats["total_logs"] = total
                stats["success_rate"] = round(success_count / total, 4) if total > 0 else 1.0
        except IOError:
            pass

        return stats

    def __del__(self):
        """析构时刷盘"""
        try:
            self.flush()
        except Exception:
            pass
