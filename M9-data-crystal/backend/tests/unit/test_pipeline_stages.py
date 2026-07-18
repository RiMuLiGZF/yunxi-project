"""
管道阶段测试

测试 6 个内置处理阶段的功能
"""

import sys
from pathlib import Path
import pytest

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pipelines import (
    FilterStage,
    TransformStage,
    CleanStage,
    EnrichStage,
    AggregateStage,
    ValidateStage,
    StageRegistry,
)


# 测试数据
SAMPLE_DATA = [
    {"id": 1, "name": "Alice", "age": 25, "city": "Beijing", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "age": 30, "city": "Shanghai", "email": "bob@example.com"},
    {"id": 3, "name": "Charlie", "age": 35, "city": "Beijing", "email": "charlie@example.com"},
    {"id": 4, "name": "David", "age": 40, "city": "Guangzhou", "email": "david@example.com"},
    {"id": 5, "name": "Eve", "age": 25, "city": "Beijing", "email": "eve@example.com"},
]


# ============================================================
# FilterStage 测试
# ============================================================

class TestFilterStage:
    """测试过滤阶段"""

    def test_condition_eq(self):
        """测试等于条件过滤"""
        stage = FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "city", "operator": "eq", "value": "Beijing"}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 3
        assert all(r["city"] == "Beijing" for r in result)

    def test_condition_gt(self):
        """测试大于条件过滤"""
        stage = FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "age", "operator": "gt", "value": 30}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 2
        assert all(r["age"] > 30 for r in result)

    def test_condition_or_logic(self):
        """测试 OR 逻辑"""
        stage = FilterStage(config={
            "type": "condition",
            "logic": "or",
            "conditions": [
                {"field": "age", "operator": "gt", "value": 35},
                {"field": "city", "operator": "eq", "value": "Shanghai"},
            ],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 2  # David(40) + Bob(Shanghai)

    def test_null_filter_exclude(self):
        """测试空值过滤（排除）"""
        data = [
            {"name": "Alice", "email": "a@b.com"},
            {"name": "Bob", "email": ""},
            {"name": "Charlie", "email": None},
        ]
        stage = FilterStage(config={
            "type": "null",
            "fields": ["email"],
            "mode": "exclude",
        })
        result = stage.process_batch(data)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_duplicate_filter(self):
        """测试去重过滤"""
        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 1, "name": "Alice"},  # 重复
            {"id": 3, "name": "Charlie"},
        ]
        stage = FilterStage(config={
            "type": "duplicate",
            "fields": ["id"],
        })
        result = stage.process_batch(data)
        assert len(result) == 3

    def test_contains_operator(self):
        """测试 contains 操作符"""
        stage = FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "email", "operator": "contains", "value": "example"}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 5

    def test_in_operator(self):
        """测试 in 操作符"""
        stage = FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "city", "operator": "in", "value": ["Beijing", "Shanghai"]}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 4  # 3 Beijing + 1 Shanghai

    def test_regex_operator(self):
        """测试正则操作符"""
        stage = FilterStage(config={
            "type": "condition",
            "conditions": [{"field": "name", "operator": "regex", "value": "^A.*"}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"


# ============================================================
# TransformStage 测试
# ============================================================

class TestTransformStage:
    """测试转换阶段"""

    def test_rename_field(self):
        """测试字段重命名"""
        stage = TransformStage(config={
            "rename": {"name": "full_name", "age": "user_age"},
        })
        result = stage.process_batch([{"name": "Alice", "age": 25}])
        assert "full_name" in result[0]
        assert "user_age" in result[0]
        assert "name" not in result[0]
        assert "age" not in result[0]

    def test_type_conversion(self):
        """测试类型转换"""
        stage = TransformStage(config={
            "type_map": {"age": "str", "id": "int"},
        })
        result = stage.process_batch([{"id": "1", "age": 25}])
        assert isinstance(result[0]["age"], str)
        assert isinstance(result[0]["id"], int)

    def test_keep_fields(self):
        """测试字段保留"""
        stage = TransformStage(config={
            "keep_fields": ["id", "name"],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 5
        assert set(result[0].keys()) == {"id", "name"}

    def test_drop_fields(self):
        """测试字段删除"""
        stage = TransformStage(config={
            "drop_fields": ["email", "city"],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert "email" not in result[0]
        assert "city" not in result[0]
        assert "name" in result[0]

    def test_default_values(self):
        """测试默认值"""
        data = [{"name": "Alice", "age": None}, {"name": "Bob"}]
        stage = TransformStage(config={
            "default_values": {"age": 0, "city": "Unknown"},
        })
        result = stage.process_batch(data)
        assert result[0]["age"] == 0
        assert result[1]["city"] == "Unknown"

    def test_computed_fields_add(self):
        """测试计算字段（加法）"""
        stage = TransformStage(config={
            "computed_fields": {
                "next_age": {"operation": "add", "fields": ["age", "age"]}
            },
        })
        result = stage.process_batch([{"age": 25}])
        assert result[0]["next_age"] == 50

    def test_computed_fields_concat(self):
        """测试计算字段（拼接）"""
        stage = TransformStage(config={
            "computed_fields": {
                "full": {"operation": "concat", "fields": ["first", "last"]}
            },
        })
        result = stage.process_batch([{"first": "Alice", "last": "Smith"}])
        assert result[0]["full"] == "AliceSmith"

    def test_validate_config(self):
        """测试配置验证"""
        stage = TransformStage(config={"rename": {"a": "b"}})
        assert stage.validate_config() is True


# ============================================================
# CleanStage 测试
# ============================================================

class TestCleanStage:
    """测试清洗阶段"""

    def test_strip_whitespace(self):
        """测试去除首尾空白"""
        data = [{"name": "  Alice  ", "city": " Beijing "}]
        stage = CleanStage(config={"strip_whitespace": True})
        result = stage.process_batch(data)
        assert result[0]["name"] == "Alice"
        assert result[0]["city"] == "Beijing"

    def test_collapse_whitespace(self):
        """测试折叠空白"""
        data = [{"text": "hello   world   test"}]
        stage = CleanStage(config={"collapse_whitespace": True})
        result = stage.process_batch(data)
        assert result[0]["text"] == "hello world test"

    def test_case_lower(self):
        """测试转小写"""
        data = [{"name": "Alice", "email": "A@B.COM"}]
        stage = CleanStage(config={"case_mode": "lower"})
        result = stage.process_batch(data)
        assert result[0]["name"] == "alice"
        assert result[0]["email"] == "a@b.com"

    def test_case_upper(self):
        """测试转大写"""
        data = [{"name": "alice"}]
        stage = CleanStage(config={"case_mode": "upper"})
        result = stage.process_batch(data)
        assert result[0]["name"] == "ALICE"

    def test_strip_html(self):
        """测试去除 HTML 标签"""
        data = [{"content": "<p>Hello <b>World</b></p>"}]
        stage = CleanStage(config={"strip_html": True})
        result = stage.process_batch(data)
        assert result[0]["content"] == "Hello World"

    def test_empty_to_null(self):
        """测试空字符串转 None"""
        data = [{"name": "Alice", "desc": ""}]
        stage = CleanStage(config={"empty_to_null": True})
        result = stage.process_batch(data)
        assert result[0]["name"] == "Alice"
        assert result[0]["desc"] is None

    def test_naming_snake_case(self):
        """测试 snake_case 命名转换"""
        data = [{"firstName": "Alice", "userAge": 25}]
        stage = CleanStage(config={"naming_style": "snake_case"})
        result = stage.process_batch(data)
        assert "first_name" in result[0]
        assert "user_age" in result[0]

    def test_validate_config(self):
        """测试配置验证"""
        stage = CleanStage(config={"case_mode": "invalid"})
        assert stage.validate_config() is False

        stage2 = CleanStage(config={"case_mode": "lower"})
        assert stage2.validate_config() is True


# ============================================================
# EnrichStage 测试
# ============================================================

class TestEnrichStage:
    """测试增强阶段"""

    def test_field_mapping(self):
        """测试字段映射"""
        data = [{"status": "1"}, {"status": "2"}, {"status": "3"}]
        stage = EnrichStage(config={
            "field_mappings": {
                "status": {
                    "mapping": {"1": "active", "2": "inactive", "3": "pending"},
                    "target_field": "status_name",
                }
            }
        })
        result = stage.process_batch(data)
        assert result[0]["status_name"] == "active"
        assert result[1]["status_name"] == "inactive"
        assert result[2]["status_name"] == "pending"

    def test_field_mapping_default(self):
        """测试字段映射默认值"""
        data = [{"type": "unknown"}]
        stage = EnrichStage(config={
            "field_mappings": {
                "type": {
                    "mapping": {"a": "Type A"},
                    "default": "Unknown Type",
                }
            }
        })
        result = stage.process_batch(data)
        assert result[0]["type"] == "Unknown Type"

    def test_lookup_dict(self):
        """测试字典 Lookup"""
        data = [{"user_id": "1"}, {"user_id": "2"}]
        stage = EnrichStage(config={
            "lookups": {
                "users": {
                    "type": "dict",
                    "source_field": "user_id",
                    "data": {
                        "1": {"name": "Alice", "email": "a@b.com"},
                        "2": {"name": "Bob", "email": "b@b.com"},
                    },
                    "prefix": "user_",
                }
            }
        })
        result = stage.process_batch(data)
        assert result[0]["user_name"] == "Alice"
        assert result[0]["user_email"] == "a@b.com"
        assert result[1]["user_name"] == "Bob"

    def test_validate_config(self):
        """测试配置验证"""
        stage = EnrichStage(config={"field_mappings": "invalid"})
        assert stage.validate_config() is False


# ============================================================
# AggregateStage 测试
# ============================================================

class TestAggregateStage:
    """测试聚合阶段"""

    def test_count(self):
        """测试计数聚合"""
        stage = AggregateStage(config={
            "group_by": ["city"],
            "aggregations": [{"function": "count", "alias": "total"}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 3  # Beijing, Shanghai, Guangzhou
        # 找 Beijing 的计数
        beijing = [r for r in result if r["city"] == "Beijing"][0]
        assert beijing["total"] == 3

    def test_sum(self):
        """测试求和"""
        stage = AggregateStage(config={
            "group_by": ["city"],
            "aggregations": [{"field": "age", "function": "sum", "alias": "total_age"}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        beijing = [r for r in result if r["city"] == "Beijing"][0]
        assert beijing["total_age"] == 25 + 35 + 25  # 85

    def test_avg(self):
        """测试平均值"""
        stage = AggregateStage(config={
            "group_by": ["city"],
            "aggregations": [{"field": "age", "function": "avg", "alias": "avg_age"}],
        })
        result = stage.process_batch(SAMPLE_DATA)
        beijing = [r for r in result if r["city"] == "Beijing"][0]
        assert beijing["avg_age"] == pytest.approx((25 + 35 + 25) / 3)

    def test_min_max(self):
        """测试最小/最大值"""
        stage = AggregateStage(config={
            "group_by": ["city"],
            "aggregations": [
                {"field": "age", "function": "min", "alias": "min_age"},
                {"field": "age", "function": "max", "alias": "max_age"},
            ],
        })
        result = stage.process_batch(SAMPLE_DATA)
        beijing = [r for r in result if r["city"] == "Beijing"][0]
        assert beijing["min_age"] == 25
        assert beijing["max_age"] == 35

    def test_no_group(self):
        """测试无分组的全局聚合"""
        stage = AggregateStage(config={
            "group_by": [],
            "aggregations": [
                {"function": "count", "alias": "total"},
                {"field": "age", "function": "sum", "alias": "sum_age"},
            ],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 1
        assert result[0]["total"] == 5
        assert result[0]["sum_age"] == 25 + 30 + 35 + 40 + 25

    def test_count_distinct(self):
        """测试去重计数"""
        stage = AggregateStage(config={
            "aggregations": [
                {"field": "city", "function": "count_distinct", "alias": "unique_cities"},
            ],
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert result[0]["unique_cities"] == 3


# ============================================================
# ValidateStage 测试
# ============================================================

class TestValidateStage:
    """测试校验阶段"""

    def test_required_fields_pass(self):
        """测试必填字段通过"""
        stage = ValidateStage(config={
            "required_fields": ["name", "age"],
            "error_output": "skip",
        })
        result = stage.process_batch(SAMPLE_DATA)
        assert len(result) == 5

    def test_required_fields_fail(self):
        """测试必填字段失败"""
        data = [
            {"name": "Alice", "age": 25},
            {"name": "Bob"},  # 缺少 age
            {"age": 30},  # 缺少 name
        ]
        stage = ValidateStage(config={
            "required_fields": ["name", "age"],
            "error_output": "skip",
        })
        result = stage.process_batch(data)
        assert len(result) == 1

    def test_type_validation(self):
        """测试类型校验"""
        data = [
            {"name": "Alice", "age": 25},
            {"name": "Bob", "age": "not_a_number"},
        ]
        stage = ValidateStage(config={
            "schema": {
                "fields": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                }
            },
            "error_output": "flag",
        })
        result = stage.process_batch(data)
        assert len(result) == 2
        assert result[0]["_is_valid"] is True
        assert result[1]["_is_valid"] is False

    def test_range_validation(self):
        """测试范围校验"""
        data = [
            {"age": 25},
            {"age": 150},
            {"age": 10},
        ]
        stage = ValidateStage(config={
            "field_rules": {
                "age": {"min": 18, "max": 100},
            },
            "error_output": "skip",
        })
        result = stage.process_batch(data)
        assert len(result) == 1
        assert result[0]["age"] == 25

    def test_pattern_validation(self):
        """测试正则校验"""
        data = [
            {"email": "test@example.com"},
            {"email": "invalid-email"},
        ]
        stage = ValidateStage(config={
            "field_rules": {
                "email": {"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
            },
            "error_output": "skip",
        })
        result = stage.process_batch(data)
        assert len(result) == 1

    def test_enum_validation(self):
        """测试枚举校验"""
        data = [
            {"status": "active"},
            {"status": "invalid_status"},
        ]
        stage = ValidateStage(config={
            "schema": {
                "fields": {
                    "status": {"type": "string", "enum": ["active", "inactive", "pending"]},
                }
            },
            "error_output": "skip",
        })
        result = stage.process_batch(data)
        assert len(result) == 1

    def test_collect_errors(self):
        """测试收集错误模式"""
        data = [
            {"name": "Alice"},
            {"name": ""},
        ]
        stage = ValidateStage(config={
            "required_fields": ["name"],
            "error_output": "collect",
        })
        result = stage.process_batch(data)
        assert len(result) == 1  # 只有有效记录
        assert len(stage.validation_errors) == 1  # 收集了 1 个错误

    def test_validate_config(self):
        """测试配置验证"""
        stage = ValidateStage(config={"error_output": "invalid"})
        assert stage.validate_config() is False

        stage2 = ValidateStage(config={"error_output": "skip"})
        assert stage2.validate_config() is True


# ============================================================
# 阶段注册表测试
# ============================================================

class TestStageRegistry:
    """测试阶段注册表"""

    def test_all_stages_registered(self):
        """测试所有 6 个阶段都已注册"""
        registered = StageRegistry.list_all()
        expected = [
            "FilterStage",
            "TransformStage",
            "CleanStage",
            "EnrichStage",
            "AggregateStage",
            "ValidateStage",
        ]
        for name in expected:
            assert name in registered, f"{name} 未注册"

    def test_create_stage(self):
        """测试创建阶段实例"""
        stage = StageRegistry.create("FilterStage", config={"type": "null"})
        assert stage is not None
        assert isinstance(stage, FilterStage)

    def test_create_invalid_stage(self):
        """测试创建不存在的阶段"""
        import pytest
        with pytest.raises(ValueError):
            StageRegistry.create("NonExistentStage")
