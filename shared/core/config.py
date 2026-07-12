"""
核心配置工具
"""

from typing import Dict, Any


_module_tokens: Dict[str, int] = {}


def get_module_tokens(module_key: str) -> int:
    """获取模块的 token 配额

    Args:
        module_key: 模块标识（如 m1, m8 等）

    Returns:
        可用 token 数
    """
    # 默认配额
    defaults = {
        "m0": 500000,
        "m1": 100000,
        "m4": 50000,
        "m5": 30000,
        "m8": 200000,
        "m9": 150000,
        "m10": 10000,
    }
    return _module_tokens.get(module_key, defaults.get(module_key, 10000))


def set_module_tokens(module_key: str, tokens: int):
    """设置模块的 token 配额"""
    _module_tokens[module_key] = tokens
