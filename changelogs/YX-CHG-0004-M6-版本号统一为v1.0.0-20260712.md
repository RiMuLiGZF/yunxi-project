# YX-CHG-0004 — M6 版本号统一为 v1.0.0

- **编号**：YX-CHG-0004
- **日期**：2026-07-12
- **模块**：M6 硬件外设
- **优先级**：P1
- **来源**：第一阶段修复（版本号统一）

---

## 改动背景

体检报告发现 M6 的 `SYSTEM_VERSION` 硬编码为 `"0.4.0"`，与系统整体版本 `v1.0.0` 不一致。注释声称与 `shared/version.py` 同步但实际并未导入。

## 改动内容

**文件**：`M6-hardware-peripheral/m6_hardware/config.py`

修改前：
```python
SYSTEM_VERSION = "0.4.0"  # 与 shared/version.py 保持同步
```

修改后：
```python
def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，失败时返回默认值。"""
    try:
        import sys
        from pathlib import Path
        _project_root = Path(__file__).parent.parent.parent
        if str(_project_root) not in sys.path:
            sys.path.insert(0, str(_project_root))
        from shared.version import SYSTEM_VERSION as _ver
        return _ver
    except Exception:
        return "v1.0.0"

SYSTEM_VERSION = _load_system_version()
```

**实现方式**：
- 自动向上查找项目根目录并加入 sys.path
- 从 `shared.version` 导入 `SYSTEM_VERSION`
- 导入失败时返回 `"v1.0.0"` 作为默认值，确保不会因路径问题导致启动失败

## 影响范围

- 影响接口：所有返回版本号的接口（/m8/health 等）
- 影响功能：版本号显示
- 风险等级：低

## 验证方式

1. 启动 M6 服务
2. 访问健康检查接口
3. 确认版本号为 `v1.0.0`（与 shared/version.py 一致）

## 回滚方案

通过 git 回滚 config.py 即可。

## 关联文档

- 体检报告：`health-reports/modules/YX-MOD-06-硬件外设-体检报告-v1.0.md`
