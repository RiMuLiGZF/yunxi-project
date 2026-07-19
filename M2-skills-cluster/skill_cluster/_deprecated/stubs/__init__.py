# =============================================================================
# [ARCHIVED - 2026-07-19] 本目录已归档
#
# 原 stubs/ 目录包含 47 个向后兼容存根文件，功能均已迁移至各子模块。
# 兼容逻辑已整合到 skill_cluster/__init__.py 中的 _DEPRECATED_MODULE_MAP 机制。
#
# 本目录仅供历史查阅和回滚参考，请勿在生产代码中引用。
# 回滚锚点: a03050e0b5af573768fd7840dfc376c34440cbbf
# =============================================================================
"""向后兼容存根子模块（已归档）

本目录已归档至 _deprecated/stubs/。
兼容逻辑已整合到 skill_cluster/__init__.py 中的动态模块代理机制。

导入本目录的模块会发出 DeprecationWarning 和归档警告。
"""

import warnings

warnings.warn(
    "skill_cluster._deprecated.stubs 是已归档的废弃目录，"
    "请勿在生产代码中引用。兼容逻辑已迁移至 skill_cluster.__init__。",
    DeprecationWarning,
    stacklevel=2,
)
