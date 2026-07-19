"""废弃代码归档目录.

本目录存放已废弃但尚未删除的历史代码，仅供查阅历史和回滚参考。
请勿在生产代码中引用本目录下的任何模块。

归档说明：
- stubs/ : 原 skill_cluster/stubs/ 目录，47 个向后兼容存根文件
  归档日期: 2026-07-19
  替代方案: skill_cluster/__init__.py 中的 _DEPRECATED_MODULE_MAP 动态模块机制
  回滚锚点: a03050e0b5af573768fd7840dfc376c34440cbbf
"""
