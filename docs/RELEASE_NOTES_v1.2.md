# 云汐系统 v1.2.0 发布说明

> **版本号**: v1.2.0
> **发布日期**: 2026-07-19
> **代号**: 大二轮完成版
> **类型**: 体验优化版本（P3 级）

---

## 概述

v1.2.0 是云汐系统大二轮迭代的完成版本，核心交付 i18n 国际化框架与日期时间本地化能力，为多语言用户提供一致的体验。本版本统一了全系统版本号，新增了完整的国际化基础设施，同时保持了完全的向后兼容性。

---

## 新功能

### 核心框架

#### i18n 国际化框架 (shared/i18n)
- **核心翻译管理**: `I18nManager` 支持多语言切换、翻译加载、嵌套键查找、回退机制
- **翻译资源**: 支持 JSON / YAML 格式的翻译文件，按命名空间组织
- **变量替换**: 支持 `{name}` 风格的变量占位符替换
- **复数形式**: 支持 zero / one / two / few / many / other 复数规则
- **语言检测**: 支持 Accept-Language 请求头、Cookie、查询参数、用户偏好多级检测
- **支持语言**: 简体中文 (zh-CN)、英语 (en-US)、日语 (ja-JP)

#### FastAPI 集成
- **中间件**: `I18nMiddleware` 自动检测请求语言并设置上下文
- **依赖注入**: `get_i18n()` / `gettext()` / `_()` 快捷依赖
- **上下文管理**: 使用 `contextvars` 实现请求级语言隔离

#### 工具函数
- 数字格式化（千分位分隔、货币符号）
- 日期时间格式化（按语言区域）
- 相对时间（"5 分钟前" / "5 minutes ago"）
- 文本方向检测（LTR / RTL）

#### 日期时间本地化
- 时区支持（IANA 时区）
- 相对时间计算
- 日历本地化（星期、月份名称）
- 多格式日期解析
- 周/月起止计算

### M8 控制塔 - i18n API
- `GET /api/i18n/languages` - 获取支持的语言列表
- `GET /api/i18n/translations/{lang}` - 获取指定语言的翻译
- `POST /api/i18n/set-language` - 设置用户语言偏好
- `GET /api/i18n/current` - 获取当前语言
- `GET /api/i18n/missing` - 查看缺失的翻译键
- `POST /api/i18n/reload` - 重新加载翻译文件
- `GET /api/i18n/stats` - 国际化统计信息

---

## 优化改进

### 版本统一
- 统一所有模块版本号为 v1.2.0
- 统一系统版本标识：SYSTEM_VERSION = "v1.2.0"
- 更新 VERSION 文件与构建信息

### 翻译覆盖
- 通用文案：80+ 条（确定、取消、保存、删除等）
- 错误信息：60+ 条（HTTP 错误、数据库、文件、认证、校验等）
- 模块名称：15+ 个模块的中英文名称
- 校验提示：60+ 条（表单验证、密码强度、文件验证等）

---

## 安全增强

- 翻译文件使用 UTF-8 编码，防止编码注入
- 变量替换使用安全的 `str.format()` 机制
- 语言代码规范化，防止路径遍历
- 中间件设置 Vary 头，确保缓存正确性

---

## 已知问题

1. **日语翻译不完整**: ja-JP 目前仅包含 common.json 命名空间，errors / modules / validation 待补充
2. **RTL 语言未测试**: 阿拉伯语、希伯来语等从右到左语言的支持未经充分测试
3. **复数规则简化**: 复杂语言（如俄语、波兰语）的复数规则使用简化版本
4. **时区依赖**: 完整时区功能需要 Python 3.9+ 的 zoneinfo 模块

---

## 升级说明

### 兼容性
- **完全向后兼容**: i18n 默认为中文 (zh-CN)，不影响现有代码
- **版本号变更**: 仅修改版本标识，不改变任何功能行为
- **新增模块**: `shared/i18n/` 为全新模块，无冲突风险

### 升级步骤
1. 拉取 v1.2.0 代码
2. 无需数据库迁移
3. 无需配置变更
4. 重启所有服务即可

### 使用 i18n

```python
# 方式一：直接使用
from shared.i18n import _

print(_("common.ok"))  # "确定"

# 方式二：指定语言
from shared.i18n import I18nManager

i18n = I18nManager()
print(i18n.t("common.greeting", language="en-US", name="Yunxi"))
# "Hello, Yunxi!"

# 方式三：FastAPI 依赖注入
from fastapi import Depends
from shared.i18n.dependencies import gettext

@app.get("/hello")
def hello(_: gettext = Depends()):
    return {"message": _("common.welcome")}
```

### 中间件集成

```python
from fastapi import FastAPI
from shared.i18n import I18nMiddleware

app = FastAPI()
app.add_middleware(I18nMiddleware)
```

---

## 模块版本清单

| 模块 | 版本 | 说明 |
|------|------|------|
| shared (共享核心库) | v1.2.0 | 新增 i18n 子模块 |
| M0 主理人管控台 | v1.2.0 | 版本统一 |
| M1 多Agent集群调度 | v1.2.0 | 版本统一 |
| M2 技能集群 | v1.2.0 | 版本统一 |
| M3 端云协同 | v1.2.0 | 版本统一 |
| M4 场景引擎 | v1.2.0 | 版本保持 |
| M5 潮汐记忆 | v1.2.0 | 版本统一 |
| M6 硬件外设 | v1.2.0 | 版本统一 |
| M7 工作流引擎 | v1.2.0 | 版本统一 |
| M8 控制塔 | v1.2.0 | 新增 i18n API |
| M9 开发者工坊 | v1.2.0 | 版本统一 |
| M10 系统卫士 | v1.2.0 | 版本统一 |
| M11 MCP总线 | v1.2.0 | 版本统一 |
| M12 安全盾 | v1.2.0 | 版本统一 |
| API 网关 | v1.2.0 | 版本统一 |

---

## 技术细节

- 新增文件：15+ 个
- 新增代码：约 1500 行
- 翻译条目：300+ 条（三种语言合计）
- 测试用例：30+ 个
- 影响模块：shared + M8

---

## 回滚方案

如遇问题，可回滚至 v1.1.1：
- Git 提交哈希: `e635f33dc6c0d002fe2d985a695fb8238600d779`
- 回滚命令: `git checkout e635f33dc6c0d002fe2d985a695fb8238600d779`
