# ExternalAgentRegistry 外部 Agent 注册表

## 一、组件职责

ExternalAgentRegistry 是联邦调度系统的"Agent 花名册"，负责所有外部 Agent 的全生命周期管理。核心职责包括：Agent 的注册、查询、更新与注销（CRUD）；能力画像（Profile）的存储与检索；健康检查调度与状态维护；API Key 的加密存储与安全读取；以及开源协议合规性检查（GPL 风险提示）。注册表初始化时自动注册一个默认本地模型 Agent（零成本、最高隐私等级），作为降级兜底选项。

## 二、核心数据结构

| 结构 | 关键字段 | 说明 |
|------|---------|------|
| `ExternalAgentProfile` | `agent_id`, `display_name`, `provider`, `agent_type`, `capabilities`, `quality_rating`, `cost_model`, `privacy_level`, `license`, `status` | 外部 Agent 能力画像（Pydantic Model） |
| `_agents: dict[str, ExternalAgentProfile]` | 以 agent_id 为键 | 内存中的 Agent 注册表 |
| `_api_keys_encrypted: dict[str, str]` | agent_id -> 密文 | 加密存储的 API Key，与 profile 分离 |
| `_adapters: dict[str, Any]` | agent_id -> 适配器实例 | 懒加载的通信适配器缓存 |
| `GPL_LIKE_LICENSES: set` | `GPL-2.0/3.0`, `AGPL`, `LGPL` | 具有传染性的协议列表 |

## 三、关键方法

- **`register_agent()`** — 注册新 Agent，执行协议风险检查（GPL 类需显式确认），API Key 通过 Fernet 加密后独立存储，不写入 profile。
- **`get_api_key(agent_id, caller_id)`** — 获取解密后的 API Key，仅受信任调用者（`federation.registry`、各 adapter 等）可获取明文，未鉴权调用仅返回脱敏预览。
- **`rotate_all_keys(new_master_key)`** — 主密钥轮换：先解密所有 Key，轮换主密钥后用新密钥重新加密，返回轮换统计。
- **`check_health(agent_id)`** / **`check_all_health()`** — 通过适配器执行健康检查，自动更新 Agent 状态（active/unhealthy）。
- **`_get_or_create_adapter()`** — 根据 provider 自动选择对应适配器（OpenAI / Anthropic / Gemini / LocalModel），懒加载并缓存。

## 四、依赖关系

| 依赖方 | 依赖类型 | 说明 |
|--------|---------|------|
| `federation.crypto_utils` | 强依赖 | 提供 Fernet 加密/解密、密钥轮换、调用者鉴权、API Key 脱敏 |
| `shared_models` | 强依赖 | `ExternalAgentProfile`, `ExternalAgentType`, `CostModel`, `LicenseType` 等数据模型 |
| `federation.adapters.*` | 弱依赖（懒加载） | OpenAI / Anthropic / Gemini / LocalModel 适配器，按 provider 按需导入 |
| `structlog` | 工具依赖 | 结构化日志输出 |

调用方向：`FederatedScheduler` -> `ExternalAgentRegistry`（查询候选 Agent）；API 层 -> `ExternalAgentRegistry`（管理 Agent 注册）。

## 五、V11.1 改进点

1. **Fernet 加密存储**：API Key 不再明文存储，改用 `cryptography.Fernet`（AES-128-CBC + HMAC-SHA256）对称加密，密文与 profile 分离存放，内存中无明文残留。
2. **调用者鉴权**：`get_api_key()` 新增 `caller_id` 参数，通过 `is_trusted_caller()` 校验调用者身份，仅受信任内部组件可读取明文，未授权调用仅返回脱敏预览并记录告警日志。
3. **GPL 协议风险提示**：新增 `license` 字段与 `GPL_LIKE_LICENSES` 列表，注册 GPL/AGPL/LGPL 类协议 Agent 时必须设置 `confirm_license_risk=True`，否则抛出 `ValueError` 并提示传染性开源义务风险。
4. **主密钥轮换支持**：新增 `rotate_all_keys()` 方法，支持批量解密-换钥-重加密全流程，确保密钥泄露时可快速应急。
5. **日志脱敏**：所有涉及 API Key 的日志输出自动调用 `mask_api_key()` 脱敏，防止密钥泄露到日志系统。
