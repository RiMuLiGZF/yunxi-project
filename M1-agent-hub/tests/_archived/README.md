# 历史测试归档目录

本目录存放 M1 Agent 集群的历史版本测试文件，已于 2026-07-19 从 `tests/_legacy/` 归档至此。

## 归档原因

1. **版本收敛**：orchestrator 版本从 7 个（v2/v3/v4/v5/v7/v8/v9）收敛为 2 个（v8 稳定版 + v9 最新版），对应的历史版本测试随之归档。
2. **代码迁移**：这些测试文件使用旧的导入路径（如 `from orchestrator_v9 import OrchestratorV9`），在当前 `src/` 目录结构下已无法直接运行。
3. **测试重组**：核心测试用例已重组到 `tests/test_orchestrator.py` 等新测试文件中，按功能模块组织。
4. **维护成本**：11 个历史文件共 351 个测试用例中，大部分已因代码重构失效，维护成本高但价值低。

## 归档文件清单

| 文件名 | 对应版本 | 测试用例数 | 状态 |
|--------|---------|-----------|------|
| test_api_v10.py | v10 | ~? | 旧 API 测试 |
| test_round2.py | v9.x 第二轮 | ~? | GuardrailsV2/Ledger/Convergence |
| test_v10_subagents.py | v10 | ~? | 子 Agent 测试 |
| test_v11_1_fixes.py | v11.1 | ~? | v11.1 修复验证 |
| test_v11_1_m8_integration.py | v11.1 | ~? | M8 集成测试 |
| test_v11_federation.py | v11.0 | ~? | 联邦调度测试 |
| test_v8_infra.py | v8 | ~? | v8 基础设施测试 |
| test_v8_innovation.py | v8 | ~? | v8 创新特性测试 |
| test_v9.py | v9 | ~? | v9 编排器测试 |
| test_v95_round1.py | v9.5 | ~? | v9.5 第一轮测试 |
| test_v96_round1.py | v9.6 | ~? | v9.6 第一轮测试 |

## 如何使用

如需查阅历史测试，请直接查看本目录下的文件。这些测试不纳入常规 CI 运行。

如需恢复某个测试：
1. 将文件移回 `tests/` 目录
2. 更新导入路径以适配当前 `src/` 目录结构
3. 确保测试与当前代码版本兼容

## 相关变更

- Orchestrator 版本收敛：v2/v3/v4/v5/v7 → 归档至 `src/orchestration/_deprecated/`
- 保留版本：v8（稳定版）、v9（最新生产/开发版）
- 向后兼容：归档版本仍可通过原路径 import，但会触发 DeprecationWarning
