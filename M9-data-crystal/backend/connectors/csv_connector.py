"""
云汐 M9 数据水晶 - CSV 连接器

P3 优化：数据采集管道 + 连接器生态
CSV 文件连接器，支持多种编码、自定义分隔符、大文件流式读取
"""

from __future__ import annotations

import csv
import os
import logging
from typing import Iterator, List, Dict, Any, Optional
from pathlib import Path

from .base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
)

logger = logging.getLogger(__name__)


@ConnectorRegistry.register
class CSVConnector(BaseConnector):
    """
    CSV 文件连接器

    特性：
    - 支持多种编码（utf-8, gbk, gb2312 等）
    - 自定义分隔符
    - 大文件流式读取
    - 写入/追加模式
    - 表头自动识别
    """

    meta = ConnectorMeta(
        name="csv",
        connector_type=ConnectorType.FILE,
        description="CSV 文件连接器，支持流式读取、多编码、自定义分隔符",
        version="1.0.0",
        supported_operations=["read", "write", "batch_read", "batch_write", "stream_read", "stream_write"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._file_path: str = ""
        self._encoding: str = "utf-8"
        self._delimiter: str = ","
        self._has_header: bool = True
        self._file_handle = None
        self._reader = None

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        连接（打开）CSV 文件

        config 参数：
        - file_path: CSV 文件路径
        - encoding: 文件编码（默认 utf-8）
        - delimiter: 分隔符（默认 ,）
        - has_header: 是否有表头（默认 True）
        - mode: 打开模式（r/w/a，默认 r）
        """
        if config:
            self._config.update(config)

        self._status = ConnectionStatus.CONNECTING
        try:
            self._file_path = self._config.get("file_path", "")
            if not self._file_path:
                raise ValueError("必须指定 file_path")

            self._encoding = self._config.get("encoding", "utf-8")
            self._delimiter = self._config.get("delimiter", ",")
            self._has_header = self._config.get("has_header", True)
            mode = self._config.get("mode", "r")

            # 确保目录存在（写入模式）
            if mode in ("w", "a"):
                Path(self._file_path).parent.mkdir(parents=True, exist_ok=True)

            self._file_handle = open(
                self._file_path,
                mode=mode,
                encoding=self._encoding,
                newline="",
            )
            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"CSV 文件已打开: {self._file_path} (mode={mode})")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"CSV 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """关闭 CSV 文件"""
        try:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
                self._reader = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("CSV 文件已关闭")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._record_error()
            return False

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式读取 CSV 数据

        query 参数：
        - skip_rows: 跳过的行数（默认 0）
        - limit: 最大读取行数
        - columns: 只读取指定列
        - filter: 过滤条件 dict
        """
        self._ensure_connected()
        query = query or {}

        try:
            self._file_handle.seek(0)
            reader = csv.DictReader(
                self._file_handle,
                delimiter=self._delimiter,
            )

            skip_rows = query.get("skip_rows", 0)
            limit = query.get("limit")
            columns = query.get("columns")
            filter_cond = query.get("filter", {})

            count = 0
            skipped = 0

            for row in reader:
                # 跳过行
                if skipped < skip_rows:
                    skipped += 1
                    continue

                # 过滤
                if filter_cond:
                    match = True
                    for key, value in filter_cond.items():
                        if row.get(key) != str(value):
                            match = False
                            break
                    if not match:
                        continue

                # 只保留指定列
                if columns:
                    row = {col: row.get(col, "") for col in columns}

                count += 1
                yield dict(row)

                if limit and count >= limit:
                    break

            self._record_read(count=count, bytes_read=count * 50)

        except Exception as e:
            self._record_error()
            logger.error(f"CSV 读取失败: {e}")
            raise

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取"""
        query = query or {}
        query["limit"] = batch_size
        return super().read_batch(batch_size, query)

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        批量写入 CSV

        配置：
        - write_mode: overwrite / append（默认 append）
        - include_header: 是否写入表头（默认 True）
        """
        self._ensure_connected()

        if not data:
            return 0

        try:
            # 如果当前是读取模式，需要重新以写入模式打开
            if self._config.get("mode", "r") == "r":
                self.disconnect()
                write_mode = self._config.get("write_mode", "append")
                mode = "w" if write_mode == "overwrite" else "a"
                self._config["mode"] = mode
                self.connect()

            columns = list(data[0].keys())
            writer = csv.DictWriter(
                self._file_handle,
                fieldnames=columns,
                delimiter=self._delimiter,
            )

            # 如果文件为空或覆盖模式，写入表头
            include_header = self._config.get("include_header", True)
            file_is_empty = self._file_handle.tell() == 0
            if include_header and (file_is_empty or self._config.get("write_mode") == "overwrite"):
                writer.writeheader()

            writer.writerows(data)
            self._file_handle.flush()

            count = len(data)
            self._record_write(count=count, bytes_written=count * 50)
            return count

        except Exception as e:
            self._record_error()
            logger.error(f"CSV 写入失败: {e}")
            raise

    def list_tables(self) -> List[str]:
        """列出目录下的 CSV 文件"""
        self._ensure_connected()
        try:
            file_path = Path(self._file_path)
            if file_path.is_dir():
                return sorted([f.name for f in file_path.glob("*.csv")])
            else:
                return [file_path.name]
        except Exception as e:
            self._record_error()
            raise

    def get_schema(self, table: str) -> Dict[str, Any]:
        """获取 CSV 文件的列名作为 schema"""
        try:
            # 读取第一行获取列名
            with open(self._file_path, "r", encoding=self._encoding, newline="") as f:
                reader = csv.reader(f, delimiter=self._delimiter)
                headers = next(reader, [])

            fields = {}
            for header in headers:
                fields[header] = {
                    "type": "string",
                    "nullable": True,
                }

            return {
                "table": table,
                "fields": fields,
                "row_count_estimate": self._estimate_row_count(),
            }
        except Exception as e:
            self._record_error()
            raise

    def _estimate_row_count(self) -> int:
        """估算行数"""
        try:
            count = 0
            with open(self._file_path, "r", encoding=self._encoding) as f:
                for _ in f:
                    count += 1
            return max(0, count - 1) if self._has_header else count
        except Exception:
            return -1

    def _health_probe(self) -> None:
        """健康探针：检查文件是否可读"""
        if self._file_handle:
            self._file_handle.tell()
