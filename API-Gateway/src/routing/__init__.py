"""
云汐 API 网关 - 高级路由模块

包含：
- 权重路由 / 灰度发布
- 一致性哈希路由
- 路径重写（正则、前缀剥离、前缀添加）
- 请求/响应头转换
"""

from .weighted_router import WeightedRouter, RouteTarget
from .path_rewriter import PathRewriter, RewriteRule
from .header_transformer import HeaderTransformer, HeaderRule

__all__ = [
    "WeightedRouter",
    "RouteTarget",
    "PathRewriter",
    "RewriteRule",
    "HeaderTransformer",
    "HeaderRule",
]
