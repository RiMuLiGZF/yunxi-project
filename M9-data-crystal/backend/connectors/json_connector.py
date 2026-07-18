"""
云汐 M9 数据水晶 - JSON 连接器

P3 优化：数据采集管道 + 连接器生态
JSON / JSONL 文件连接器，支持嵌套字段展平
"""

from __future__ import annotations

import json
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
class JSONConnector(BaseConnector):
    """
    JSON / JSONL 文件连接器

    特性：
    - 支持 JSON 数组格式
    - 支持 JSONL（每行一个 JSON 对象）
    - 嵌套字段展平
    - 流式读取（JSONL
    - 写入/追加
    """

    meta = ConnectorMeta(
        name="json",
        connector_type=ConnectorType.FILE,
        description="JSON/JSONL 文件连接器，支持嵌套字段展平",
        version="1.0.0",
        supported_operations=["read", "write", "batch_read", "batch_write", "stream_read", "stream_write"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._file_path: str = ""
        self._encoding: str = "utf-8"
        self._format: str = "json"  # json / jsonl
        self._flatten: bool = False
        self._flatten_separator: str = "_"
        self._file_handle = None

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        连接（打开）JSON 文件

        config 参数：
        - file_path: JSON/JSONL 文件路径
        - encoding: 文件编码（默认 utf-8）
        - format: json / jsonl / auto（默认 auto，根据扩展名判断）
        - flatten: 是否展平嵌套字段（默认 False）
        - flatten_separator: 展平分隔符（默认 _）
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
            self._flatten = self._config.get("flatten", False)
            self._flatten_separator = self._config.get("flatten_separator", "_")
            mode = self._config.get("mode", "r")

            # 自动检测格式
            fmt = self._config.get("format", "auto")
            if fmt == "auto":
                if self._file_path.lower().endswith(".jsonl"):
                    self._format = "jsonl"
                else:
                    self._format = "json"
            else:
                self._format = fmt

            # 确保目录存在（写入模式）
            if mode in ("w", "a"):
                Path(self._file_path).parent.mkdir(parents=True, exist_ok=True)

            self._file_handle = open(
                self._file_path,
                mode=mode,
                encoding=self._encoding,
            )
            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"JSON 文件已打开: {self._file_path} (format={self._format})")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"JSON 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """关闭 JSON 文件"""
        try:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("JSON 文件已关闭")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._record_error()
            return False

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        """展平嵌套字典"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式读取 JSON 数据

        query 参数：
        - limit: 最大读取条数
        - offset: 跳过条数
        - filter: 过滤条件 dict
        - json_path: JSON 路径（对于嵌套数据）
        """
        self._ensure_connected()
        query = query or {}

        try:
            limit = query.get("limit")
            offset = query.get("offset", 0)
            filter_cond = query.get("filter", {})
            json_path = query.get("json_path", "")

            count = 0
            skipped = 0

            if self._format == "jsonl":
                # JSONL 格式：逐行读取
                self._file_handle.seek(0)
                for line in self._file_handle:
                    line = line.strip()
                    if not line:
                        continue

                    record = json.loads(line)

                    # JSON 路径提取
                    if json_path:
                        record = self._extract_by_path(record, json_path)
                        if record is None:
                            continue

                    # 展平
                    if self._flatten and isinstance(record, dict):
                        record = self._flatten_dict(record, sep=self._flatten_separator)

                    # 跳过
                    if skipped < offset:
                        skipped += 1
                        continue

                    # 过滤
                    if filter_cond and isinstance(record, dict):
                        if not self._match_filter(record, filter_cond):
                            continue

                    count += 1
                    yield record if isinstance(record, dict) else {"value": record}

                    if limit and count >= limit:
                        break

            else:
                # JSON 数组格式：一次性加载后流式输出
                self._file_handle.seek(0)
                data = json.load(self._file_handle)

                # 如果是字典，尝试找到数组
                if isinstance(data, dict):
                    if json_path:
                        data = self._extract_by_path(data, json_path) or []
                    else:
                        # 尝试找第一个数组字段
                        v = next((v for v in data.values() if isinstance(v, list)), None)
                        data = v if v is not None else []

                if not isinstance(data, list):
                    data = [data] if data else []

                for record in data:
                    # 跳过
                    if skipped < offset:
                        skipped += 1
                        continue

                    # 展平
                    if self._flatten and isinstance(record, dict):
                        record = self._flatten_dict(record, sep=self._flatten_separator)

                    # 过滤
                    if filter_cond and isinstance(record, dict):
                        if not self._match_filter(record, filter_cond):
                            continue

                    count += 1
                    yield record if isinstance(record, dict) else {"value": record}

                    if limit and count >= limit:
                        break

            self._record_read(count=count, bytes_read=count * 100)

        except Exception as e:
            self._record_error()
            logger.error(f"JSON 读取失败: {e}")
            raise

    def _extract_by_path(self, data: Any, path: str) -> Any:
        """按 JSON 路径提取数据"""
        if not path:
            return data
        keys = path.strip(".").split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def _match_filter(self, record: Dict[str, Any], filter_cond: Dict[str, Any]) -> bool:
        """检查记录是否匹配过滤条件"""
        for key, value in filter_cond.items():
            if str(record.get(key)) != str(value):
                return False
        return True

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取"""
        query = query or {}
        query["limit"] = batch_size
        return super().read_batch(batch_size, query)

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        批量写入 JSON

        配置：
        - write_mode: overwrite / append（默认 append）
        - write_format: json / jsonl（默认与读取格式一致）
        - json_root: JSON 数组根键名（仅 json 格式）
        """
        self._ensure_connected()

        if not data:
            return 0

        try:
            write_format = self._config.get("write_format", self._format)
            write_mode = self._config.get("write_mode", "append")

            # 如果当前是读取模式，需要重新打开
            if self._config.get("mode", "r") == "r":
                self.disconnect()
                mode = "w" if write_mode == "overwrite" else "a"
                self._config["mode"] = mode
                self.connect()

            if write_format == "jsonl":
                # JSONL 格式
                for record in data:
                    self._file_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            else:
                # JSON 数组格式
                json_root = self._config.get("json_root", "")
                if write_mode == "overwrite" or self._file_handle.tell() == 0:
                    # 新文件：写入完整 JSON 数组
                    if json_root:
                        output = {json_root: data}
                    else:
                        output = data
                    json.dump(output, self._file_handle, ensure_ascii=False, indent=2)
                else:
                    # 追加模式：对于 JSON 数组格式需要特殊处理
                    # 简化处理：读取现有数据，追加后重写
                    self._file_handle.seek(0)
                    try:
                        existing = json.load(self._file_handle)
                        if json_root:
                            if json_root in existing and isinstance(existing[json_root], list):
                                existing[json_root].extend(data)
                        elif isinstance(existing, list):
                            existing.extend(data)
                        else:
                            existing = data
                    except (json.JSONDecodeError, ValueError):
                        existing = data

                    self._file_handle.seek(0)
                    self._file_handle.truncate()
                    json.dump(existing, self._file_handle, ensure_ascii=False, indent=2)

            self._file_handle.flush()
            count = len(data)
            self._record_write(count=count, bytes_written=count * 100)
            return count

        except Exception as e:
            self._record_error()
            logger.error(f"JSON 写入失败: {e}")
            raise

    def list_tables(self) -> List[str]:
        """列出目录下的 JSON 文件"""
        try:
            file_path = Path(self._file_path)
            if file_path.is_dir():
                return sorted([
                    f.name for f in file_path.glob("*.json")] +
                    [f.name for f in file_path.glob("*.jsonl")
                ])
            else:
                return [file_path.name]
        except Exception as e:
            self._record_error()
            raise

    def get_schema(self, table: str) -> Dict[str, Any]:
        """根据第一条记录推断 Schema"""
        try:
            # 读取第一条记录推断字段
            sample = None
            if self._format == "jsonl":
                with open(self._file_path, "r", encoding=self._encoding) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            sample = json.loads(line)
                            break
            else:
                with open(self._file_path, "r", encoding=self._encoding) as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        sample = data[0]
                    elif isinstance(data, dict):
                        sample = data

            fields = {}
            if sample and isinstance(sample, dict):
                if self._flatten:
                    sample = self._flatten_dict(sample, sep=self._flatten_separator)
                for key, value in sample.items():
                    fields[key] = {
                        "type": type(value).__name__,
                        "nullable": value is None,
                        "sample": str(value)[:100] if value is not None else None,
                    }

            return {
                "table": table,
                "format": self._format,
                "fields": fields,
            }
        except Exception as e:
            self._record_error()
            raise

    def _health_probe(self) -> None:
        """健康探针"""
        if self._file_handle:
            self._file_handle.tell()
