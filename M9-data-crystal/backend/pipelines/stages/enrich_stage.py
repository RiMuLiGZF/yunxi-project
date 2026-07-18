"""
云汐 M9 数据水晶 - 数据增强阶段

P3 优化：数据采集管道 + 连接器生态
支持字段映射、外部数据关联（Lookup）、地理编码（预留）
"""

from __future__ import annotations

import logging
from typing import Iterator, Dict, Any, Optional, Callable

from ..base import PipelineStage, StageRegistry

logger = logging.getLogger(__name__)


@StageRegistry.register
class EnrichStage(PipelineStage):
    """
    数据增强阶段

    功能：
    - 字段映射（字典映射）
    - 外部数据关联（Lookup）
    - 地理编码（预留接口）
    - 自定义增强函数
    """

    name = "enrich"
    description = "数据增强阶段，支持字段映射、外部数据关联"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._lookup_data: Dict[str, Dict[str, Any]] = {}
        self._load_lookup_data()

    def _load_lookup_data(self) -> None:
        """加载 Lookup 数据"""
        lookups = self._config.get("lookups", {})
        for lookup_name, lookup_config in lookups.items():
            lookup_type = lookup_config.get("type", "dict")

            if lookup_type == "dict":
                self._lookup_data[lookup_name] = lookup_config.get("data", {})
            elif lookup_type == "file":
                # 从文件加载
                file_path = lookup_config.get("path", "")
                key_field = lookup_config.get("key_field", "id")
                try:
                    import json
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        self._lookup_data[lookup_name] = {
                            str(item.get(key_field)): item for item in data
                        }
                    else:
                        self._lookup_data[lookup_name] = data
                except Exception as e:
                    logger.warning(f"加载 lookup 数据失败 [{lookup_name}]: {e}")
                    self._lookup_data[lookup_name] = {}

    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """执行数据增强"""
        records_in = 0
        records_out = 0

        for record in data:
            records_in += 1
            try:
                result = self._enrich_record(record)
                records_out += 1
                yield result
            except Exception as e:
                self._record_error()
                logger.warning(f"数据增强出错: {e}")
                continue

        self._record_in(records_in)
        self._record_out(records_out)

    def _enrich_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """增强单条记录"""
        result = dict(record)

        # 1. 字段映射（字典映射）
        field_mappings = self._config.get("field_mappings", {})
        if field_mappings:
            result = self._apply_field_mappings(result, field_mappings)

        # 2. Lookup 关联
        lookups = self._config.get("lookups", {})
        if lookups:
            result = self._apply_lookups(result, lookups)

        # 3. 自定义增强函数
        custom_func = self._config.get("custom_func")
        if custom_func and callable(custom_func):
            result = custom_func(result) or result

        return result

    def _apply_field_mappings(self, record: Dict[str, Any],
                              field_mappings: Dict[str, Any]) -> Dict[str, Any]:
        """应用字段映射"""
        for field_name, mapping_config in field_mappings.items():
            if field_name not in record:
                continue

            original_value = record[field_name]
            mapping_dict = mapping_config.get("mapping", {}) if isinstance(mapping_config, dict) else {}
            target_field = mapping_config.get("target_field", field_name) if isinstance(mapping_config, dict) else field_name
            default_value = mapping_config.get("default", original_value) if isinstance(mapping_config, dict) else original_value

            # 执行映射
            mapped_value = mapping_dict.get(str(original_value), default_value)
            record[target_field] = mapped_value

        return record

    def _apply_lookups(self, record: Dict[str, Any],
                       lookups: Dict[str, Any]) -> Dict[str, Any]:
        """应用 Lookup 关联"""
        for lookup_name, lookup_config in lookups.items():
            if not isinstance(lookup_config, dict):
                continue

            source_field = lookup_config.get("source_field", "")
            if not source_field or source_field not in record:
                continue

            key_value = str(record[source_field])
            lookup_data = self._lookup_data.get(lookup_name, {})

            if key_value in lookup_data:
                matched = lookup_data[key_value]
                prefix = lookup_config.get("prefix", "")
                fields = lookup_config.get("fields", [])  # 只取指定字段，空表示全部

                if isinstance(matched, dict):
                    for k, v in matched.items():
                        if not fields or k in fields:
                            new_field = f"{prefix}{k}" if prefix else k
                            record[new_field] = v
                else:
                    # 非字典值，直接映射到指定字段
                    target_field = lookup_config.get("target_field", f"{lookup_name}_value")
                    record[target_field] = matched

        return record

    def validate_config(self) -> bool:
        """验证配置"""
        if "field_mappings" in self._config:
            if not isinstance(self._config["field_mappings"], dict):
                return False

        if "lookups" in self._config:
            if not isinstance(self._config["lookups"], dict):
                return False

        return True
