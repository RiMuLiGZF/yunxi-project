# 文档目录

> 云汐系统文档中心，所有文档的索引和导航。

---

## 文档分类

### 核心文档

| 文档 | 说明 | 面向对象 |
|------|------|---------|
| [架构文档](ARCHITECTURE.md) | 系统架构总览、模块详细说明、技术决策、设计原则、演进路线 | 架构师、技术负责人 |
| [API 文档](API.md) | API 设计规范、认证方式、各模块端点列表、示例请求 | 开发者、集成方 |
| [运维手册](OPS.md) | 日常运维、监控告警、备份恢复、故障排查、性能调优 | 运维工程师 |
| [开发者指南](DEVELOPMENT.md) | 环境搭建、代码规范、测试规范、调试技巧 | 开发者 |

### 专项文档

| 文档 | 说明 | 面向对象 |
|------|------|---------|
| [部署手册](DEPLOYMENT.md) | 生产环境部署指南（裸机 / Docker） | 运维工程师 |
| [安全文档](SECURITY.md) | 安全架构、防护措施、漏洞响应流程 | 安全工程师 |
| [灾难恢复](DISASTER_RECOVERY.md) | 备份策略、灾难恢复、RPO/RTO 目标 | 运维工程师 |
| [发展路线图](云汐系统发展路线图v2.0.md) | 系统演进规划与里程碑 | 产品、管理层 |
| [API 总览](API_OVERVIEW.md) | API 总览（旧版，已整合到 API.md） | 参考 |
| [架构总览](ARCHITECTURE_OVERVIEW.md) | 架构总览（旧版，已整合到 ARCHITECTURE.md） | 参考 |

### 快速索引

| 主题 | 相关文档 |
|------|---------|
| 快速开始 | 顶层 [README.md](../README.md) |
| 架构设计 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 接口对接 | [API.md](API.md) |
| 部署上线 | [DEPLOYMENT.md](DEPLOYMENT.md) |
| 日常运维 | [OPS.md](OPS.md) |
| 故障排查 | [OPS.md - 常见故障排查](OPS.md#7-常见故障排查) |
| 备份恢复 | [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) |
| 开发规范 | [DEVELOPMENT.md](DEVELOPMENT.md) |
| 安全问题 | [SECURITY.md](SECURITY.md) |
| 错误码查询 | [shared/core/ERROR_CODES.md](../shared/core/ERROR_CODES.md) |

---

## 文档规范

### 文档格式

- 所有文档使用 **Markdown** 格式
- 中文编写，专业准确
- 包含目录导航
- 统一的格式风格

### 文档更新

- 代码变更涉及文档时，必须同步更新文档
- 架构变更时更新 `ARCHITECTURE.md`
- API 变更时更新 `API.md`
- 运维流程变更时更新 `OPS.md`
- 版本发布时更新版本信息

### 文档版本

每份文档头部包含：
- 版本号
- 更新日期
- 文档类型
- 适用范围

---

## 其他文档位置

| 位置 | 说明 |
|------|------|
| `../README.md` | 项目顶层 README |
| `../shared/README.md` | Shared 公共组件库说明 |
| `../shared/core/ERROR_CODES.md` | 统一错误码规范 |
| `../shared/core/CONFIG_GUIDE.md` | 配置指南 |
| `../shared/core/HEALTH_GUIDE.md` | 健康检查指南 |
| `../tests/README.md` | 测试体系说明 |
| `../scripts/README.md` | 脚本目录说明 |
| `../M*/README.md` | 各模块文档 |

---

**最后更新**：2026-07-17
**文档版本**：v1.0
