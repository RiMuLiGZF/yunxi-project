# PrivacyGuard 隐私卫士

## 一、组件职责

PrivacyGuard 是联邦调度系统的"安全闸门"，负责在数据流出内部系统前进行 PII（个人可识别信息）检测、风险评估和脱敏处理。核心职责包括：10 类 PII 的检测与识别、综合风险等级评估（low/medium/high/critical）、分级强度脱敏、外传内容审批（检查是否可以传输给特定隐私等级的外部 Agent）、以及完整的审计日志记录。它确保敏感数据在传输到外部 Agent 之前得到妥善处理，防止隐私泄露。

## 二、核心数据结构

| 结构 | 关键字段 | 说明 |
|------|---------|------|
| `PII_PATTERNS: dict[str, Pattern]` | 10 类 PII 正则表达式 | email / phone_cn / id_card_cn / bank_card / api_key / password / token / private_key / url_internal / custom_keyword |
| `PII_SEVERITY: dict[str, str]` | PII 类型 -> 严重等级 | 每类 PII 的基础风险级别（medium/high/critical） |
| `SEVERITY_WEIGHT: dict[str, float]` | critical: 10, high: 5, medium: 2, low: 1 | 严重程度权重，用于综合评分 |
| `SECURITY_LEVEL_WEIGHT: dict` | PUBLIC: 0.5 ~ TOP_SECRET: 3.0 | 涉密等级加权系数 |
| `_audit_log: list[dict]` | 审计条目列表 | 含 content_hash、content_length、sanitized_preview 等摘要字段 |

## 三、关键方法

- **`scan_content(content, security_level, context)`** — PII 扫描：预处理归一化 -> 10 类 PII 检测 -> 综合风险评估 -> 生成审计条目，返回检测结果和风险等级。
- **`sanitize_content(content, security_level, target_risk)`** — 内容脱敏：先扫描检测，再按风险等级执行不同强度脱敏（critical 完全替换 / high 强脱敏 / medium 中等脱敏 / low 轻脱敏），所有检测到 PII 的内容均进入脱敏分支。
- **`check_external_transfer(content, target_agent_id, agent_privacy_level, security_level)`** — 外传审批：TOP_SECRET + high/critical 风险阻止；CONFIDENTIAL + critical + 标准隐私 Agent 阻止；含私钥内容一律阻止。
- **`_normalize_content()`** — 预处理归一化：移除零宽字符、全角转半角、还原常见绕过手法（如 `[at]` -> `@`），防检测绕过。
- **`_assess_risk_level()`** — 加权评分制：风险分 = Σ(PII 权重 × 数量) × 涉密等级权重，存在 critical 类 PII 直接判定为 critical 级。
- **`_validate_pii()`** — 二次校验：身份证校验码验证、银行卡 Luhn 算法、手机号位数校验，减少误报。

## 四、依赖关系

| 依赖方 | 依赖类型 | 说明 |
|--------|---------|------|
| `shared_models` | 强依赖 | `SecurityClassification` 涉密等级枚举 |
| `re` / `hashlib` / `time` | 标准库 | 正则匹配、内容哈希、时间戳 |
| `structlog` | 工具依赖 | 结构化日志记录检测、脱敏、阻断事件 |
| `FederatedScheduler` | 协作 | Scheduler 的隐私检查步骤调用 PrivacyGuard 进行外传审批 |

调用方向：数据外发前 -> `PrivacyGuard.scan_content()` / `sanitize_content()` / `check_external_transfer()`；审计查询 -> `get_audit_log()`。

## 五、V11.1 改进点

1. **风险分级逻辑重写（P0-001 修复）**：从"仅 high 以上才脱敏"改为"所有检测到 PII 的内容均进入脱敏分支，按风险等级采用不同脱敏强度"，low/medium 风险不再被跳过。
2. **10 类 PII 检测脱敏**：从原有 3 类扩展到 10 类，新增身份证、银行卡、API Key、密码、Token、私钥、内网 URL、自定义关键词，覆盖主流敏感信息场景。
3. **预处理防绕过（P1-001 修复）**：新增 `_normalize_content()` 归一化步骤，处理零宽字符、全角半角混合、`[at]/(dot)` 替换、手机号加空格/横线等常见绕过手法，检测准确率大幅提升。
4. **PII 有效性二次校验**：身份证使用校验码算法、银行卡使用 Luhn 算法、手机号验证位数前缀，显著降低误报率。
5. **审计摘要字段增强**：审计条目新增 `content_hash`（SHA-256）、`content_length`、`sanitized_preview`、`pii_types_detected` 四个摘要字段，便于审计追溯且不存储明文内容。
