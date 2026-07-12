"""
shared.utils 模块单元测试

测试内容：
- generate_id()：长度、唯一性、字符集、边界情况
- now_timestamp()：数值型、接近当前时间
- now_iso()：ISO 格式、可解析
- safe_get()：正常取值、key 不存在、字典为 None
- truncate_text()：短文本、长文本截断、None/空字符串
- format_file_size()：各单位区间、0 B、负数、保留两位小数
"""

import re
import time
import pytest
from datetime import datetime, timezone

from shared.utils import (
    generate_id,
    now_timestamp,
    now_iso,
    safe_get,
    truncate_text,
    format_file_size,
)


# ============================================================
# generate_id 测试
# ============================================================

class TestGenerateId:
    """generate_id 函数测试"""

    def test_默认长度为16(self):
        """默认生成 16 位长度的 ID"""
        id_str = generate_id()
        assert len(id_str) == 16

    def test_自定义长度生效(self):
        """自定义长度参数生效"""
        for length in [1, 4, 8, 16, 32, 64, 100]:
            id_str = generate_id(length)
            assert len(id_str) == length, f"长度 {length} 不匹配"

    def test_每次生成不同(self):
        """多次生成的 ID 不重复"""
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100, "生成的 ID 存在重复"

    def test_只包含十六进制字符(self):
        """生成的 ID 只包含十六进制字符（0-9, a-f）"""
        id_str = generate_id(32)
        assert re.match(r'^[0-9a-f]+$', id_str), f"ID 包含非十六进制字符: {id_str}"

    def test_返回字符串类型(self):
        """返回值为字符串类型"""
        assert isinstance(generate_id(), str)

    def test_长度为0时抛出ValueError(self):
        """length 为 0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="length 必须为正整数"):
            generate_id(0)

    def test_负长度抛出ValueError(self):
        """length 为负数时抛出 ValueError"""
        with pytest.raises(ValueError, match="length 必须为正整数"):
            generate_id(-1)

    def test_奇数长度正确(self):
        """奇数长度也能正确生成（截断逻辑验证）"""
        for length in [1, 3, 5, 7, 9, 15, 17]:
            id_str = generate_id(length)
            assert len(id_str) == length


# ============================================================
# now_timestamp 测试
# ============================================================

class TestNowTimestamp:
    """now_timestamp 函数测试"""

    def test_返回整数类型(self):
        """返回值为整数类型"""
        ts = now_timestamp()
        assert isinstance(ts, int)

    def test_接近当前时间(self):
        """返回的时间戳接近当前真实时间（误差 2 秒内）"""
        before = int(time.time())
        ts = now_timestamp()
        after = int(time.time())
        assert before <= ts <= after + 1

    def test_为合理的时间戳值(self):
        """时间戳值在合理范围内（2020年 ~ 2100年）"""
        ts = now_timestamp()
        # 2020-01-01 00:00:00 UTC = 1577836800
        # 2100-01-01 00:00:00 UTC = 4102444800
        assert 1577836800 < ts < 4102444800


# ============================================================
# now_iso 测试
# ============================================================

class TestNowIso:
    """now_iso 函数测试"""

    def test_返回字符串类型(self):
        """返回值为字符串类型"""
        assert isinstance(now_iso(), str)

    def test_可被fromisoformat解析(self):
        """返回的字符串可被 datetime.fromisoformat 解析"""
        iso_str = now_iso()
        dt = datetime.fromisoformat(iso_str)
        assert isinstance(dt, datetime)

    def test_为UTC时间(self):
        """返回的时间带 UTC 时区信息"""
        iso_str = now_iso()
        dt = datetime.fromisoformat(iso_str)
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0

    def test_接近当前时间(self):
        """返回的时间接近当前时间（误差 5 秒内）"""
        iso_str = now_iso()
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
        diff = abs((now - dt).total_seconds())
        assert diff < 5, f"时间差 {diff} 秒，超出预期"

    def test_格式包含T分隔符(self):
        """ISO 格式包含 T 分隔符"""
        iso_str = now_iso()
        assert "T" in iso_str


# ============================================================
# safe_get 测试
# ============================================================

class TestSafeGet:
    """safe_get 函数测试"""

    def test_正常字典能获取值(self):
        """存在的 key 能正确获取值"""
        d = {"a": 1, "b": "hello", "c": [1, 2, 3]}
        assert safe_get(d, "a") == 1
        assert safe_get(d, "b") == "hello"
        assert safe_get(d, "c") == [1, 2, 3]

    def test_key不存在返回默认值None(self):
        """key 不存在时默认返回 None"""
        d = {"a": 1}
        assert safe_get(d, "b") is None

    def test_key不存在返回自定义默认值(self):
        """key 不存在时返回自定义默认值"""
        d = {"a": 1}
        assert safe_get(d, "b", 0) == 0
        assert safe_get(d, "b", "default") == "default"
        assert safe_get(d, "b", []) == []

    def test_字典为None时返回默认值(self):
        """字典为 None 时返回默认值，不抛出异常"""
        assert safe_get(None, "a") is None
        assert safe_get(None, "a", "fallback") == "fallback"
        assert safe_get(None, "a", 0) == 0

    def test_空字典返回默认值(self):
        """空字典获取任意 key 返回默认值"""
        assert safe_get({}, "key") is None
        assert safe_get({}, "key", -1) == -1

    def test_value为None时返回None而非默认值(self):
        """key 存在但值为 None 时，返回 None 而不是默认值"""
        d = {"a": None}
        assert safe_get(d, "a", "default") is None

    def test_value为False或0时正常返回(self):
        """value 为 False 或 0 等假值时，正常返回而非默认值"""
        d = {"flag": False, "count": 0, "name": ""}
        assert safe_get(d, "flag", True) is False
        assert safe_get(d, "count", -1) == 0
        assert safe_get(d, "name", "default") == ""


# ============================================================
# truncate_text 测试
# ============================================================

class TestTruncateText:
    """truncate_text 函数测试"""

    def test_短文本不截断(self):
        """文本长度小于等于 max_length 时原样返回"""
        assert truncate_text("hello", 10) == "hello"
        assert truncate_text("hello", 5) == "hello"
        assert truncate_text("", 10) == ""

    def test_长文本截断并加省略号(self):
        """超出 max_length 的文本被截断并添加省略号"""
        text = "abcdefghij"  # 10个字符
        result = truncate_text(text, 8)
        assert len(result) == 8
        assert result.endswith("...")
        assert result == "abcde..."

    def test_None返回空字符串(self):
        """text 为 None 时返回空字符串"""
        assert truncate_text(None) == ""
        assert truncate_text(None, 50) == ""

    def test_空字符串不截断(self):
        """空字符串原样返回"""
        assert truncate_text("") == ""

    def test_max_length过小抛出ValueError(self):
        """max_length <= 3 时抛出 ValueError（需容纳省略号）"""
        with pytest.raises(ValueError, match="max_length 必须大于 3"):
            truncate_text("hello", 3)

        with pytest.raises(ValueError, match="max_length 必须大于 3"):
            truncate_text("hello", 2)

        with pytest.raises(ValueError, match="max_length 必须大于 3"):
            truncate_text("hello", 0)

    def test_截断后总长度等于max_length(self):
        """截断后的文本总长度等于 max_length"""
        for max_len in [4, 10, 20, 50, 100]:
            text = "a" * 200
            result = truncate_text(text, max_len)
            assert len(result) == max_len, f"max_len={max_len} 时长度不匹配"

    def test_省略号为三个点(self):
        """省略号为三个英文点号"""
        result = truncate_text("hello world", 8)
        assert result.endswith("...")
        assert not result.endswith("…")  # 不是省略号字符

    def test_中文文本截断(self):
        """中文文本也能正确截断"""
        text = "这是一段很长的中文文本用于测试截断功能"
        result = truncate_text(text, 10)
        assert len(result) == 10
        assert result.endswith("...")


# ============================================================
# format_file_size 测试
# ============================================================

class TestFormatFileSize:
    """format_file_size 函数测试"""

    def test_0字节显示正确(self):
        """0 字节显示为 '0 B'"""
        assert format_file_size(0) == "0 B"

    def test_负数显示为0B(self):
        """负数大小显示为 '0 B'"""
        assert format_file_size(-1) == "0 B"
        assert format_file_size(-1024) == "0 B"

    def test_B区间(self):
        """小于 1024 字节以 B 为单位，整数显示"""
        assert format_file_size(1) == "1 B"
        assert format_file_size(500) == "500 B"
        assert format_file_size(1023) == "1023 B"

    def test_KB区间(self):
        """1 KB ~ 1023 KB 以 KB 为单位，保留两位小数"""
        assert format_file_size(1024) == "1.00 KB"
        assert format_file_size(1536) == "1.50 KB"  # 1.5 KB
        assert format_file_size(1024 * 100) == "100.00 KB"

    def test_MB区间(self):
        """1 MB ~ 1023 MB 以 MB 为单位"""
        assert format_file_size(1024 * 1024) == "1.00 MB"
        assert format_file_size(1024 * 1024 * 5) == "5.00 MB"
        assert format_file_size(int(1024 * 1024 * 2.5)) == "2.50 MB"

    def test_GB区间(self):
        """1 GB ~ 1023 GB 以 GB 为单位"""
        assert format_file_size(1024 ** 3) == "1.00 GB"
        assert format_file_size(1024 ** 3 * 10) == "10.00 GB"

    def test_TB区间(self):
        """1 TB 及以上以 TB 为单位"""
        assert format_file_size(1024 ** 4) == "1.00 TB"
        assert format_file_size(1024 ** 4 * 2) == "2.00 TB"

    def test_保留两位小数(self):
        """非 B 单位保留两位小数"""
        # 1 KB + 512 B = 1.5 KB
        assert format_file_size(1024 + 512) == "1.50 KB"
        # 3 MB + 一些
        size = int(1024 * 1024 * 3.14159)
        result = format_file_size(size)
        assert result.endswith(" MB")
        # 验证小数位数
        num_part = result.replace(" MB", "")
        decimal_part = num_part.split(".")[1] if "." in num_part else ""
        assert len(decimal_part) == 2, f"小数位数不为2: {result}"

    def test_B单位为整数无小数(self):
        """B 单位时为整数，不包含小数点"""
        result = format_file_size(500)
        assert result == "500 B"
        assert "." not in result

    def test_极大值不越界(self):
        """极大值（超过 TB）仍以 TB 显示，不越界"""
        huge = 1024 ** 5  # 1 PB
        result = format_file_size(huge)
        # 超过 TB 后停在 TB 单位
        assert result.endswith(" TB")
        # 1 PB = 1024 TB
        assert "1024.00 TB" in result or float(result.replace(" TB", "")) >= 1024
