# 安全审计与涉密拦截子Agent（Security-Agent）架构文档

## 一、职责定位

Security-Agent 是云汐系统的"安全卫士"，集成输入安检、涉密内容分级、访问控制和审计留痕四大安全能力。它通过多级规则引擎对内容进行自动分级（公开/内部/机密/绝密），基于涉密等级实施访问控制，并将所有安全操作完整记录到审计日志中。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `security.check_input` | `text`(str) | 输入安检（Prompt注入+PII脱敏+涉密分级） |
| `security.classify` | `content`(str) | 内容分级 |
| `security.classify_and_audit` | `content`(str), `agent_id`(str, 可选) | 分级+留痕 |
| `security.check_access` | `agent_id`(str), `resource_level`(str, 默认"PUBLIC") | 访问控制 |
| `security.audit_trail` | `agent_id`(可选), `time_start`(可选), `time_end`(可选) | 审计日志查询 |
| `security.strip` | `content`(str), `target_level`(str, 默认"PUBLIC") | 内容脱敏 |

### 公开API方法签名

```python
def check_input(text: str) -> dict[str, Any]
def classify_and_audit(content: str, agent_id: str) -> dict[str, Any]
def check_access(agent_id: str, resource_level: SecurityClassification) -> bool
def get_audit_trail(agent_id: str | None = None, time_range: tuple[float, float] | None = None) -> list[dict[str, Any]]
def register_agent_clearance(agent_id: str, clearance: SecurityClassification) -> None
```

## 三、核心机制

**涉密内容自动分级（SecurityClassifier）** 采用多级规则引擎，分两阶段执行：第一阶段使用正则模式匹配（最高优先级），包含绝密标识、密钥材料、军事情报、机密标识、社会安全号、银行账户、内部标识等7类正则规则；第二阶段使用关键词密度分析，命中5个以上关键词自动升级为绝密，3个以上INTERNAL关键词升级为CONFIDENTIAL。此设计参考了 **Dify** 的内容安全分级器思想。

**输入安检流水线** check_input 执行四步流水线：Prompt Injection检测（GuardrailsV2）-> PII脱敏（GuardrailsV2）-> 涉密分级（SecurityClassifier）-> 审计留痕（AuditLog）。安全检查结果包含 blocked、risk_score、sanitized_text、classification 和 detections 五类信息。

**按级别脱敏** strip_for_level 根据目标涉密等级，移除所有高于目标等级的涉密内容。关键词替换为 `[已脱敏-X***]` 格式，正则匹配替换为 `[已脱敏-LEVEL]` 格式。关键词按长度降序处理，避免短词先替换导致长词匹配失败。

**审计日志（AuditLog）** 内存存储，最大100,000条，超过上限时FIFO淘汰最旧条目。支持按Agent、时间范围、涉密等级三维查询，并提供完整的统计摘要。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| GuardrailsV2 | 直接依赖 | 提供Prompt注入检测和PII脱敏能力 |
| 所有子Agent | 被调用方 | 各子Agent处理用户输入前调用 check_input 进行安检 |
| Bus-Agent（agent.bus） | 被调用方 | 安全事件可通过Bus广播 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `SecurityClassification` | 枚举值：PUBLIC/INTERNAL/CONFIDENTIAL/TOP_SECRET（IntEnum，支持比较运算） | 涉密等级枚举 |
| `AuditEntry` | `entry_id`, `timestamp`, `agent_id`, `action`, `resource`, `classification`, `result`(allow/deny/error), `detail` | 审计日志条目 |
| `AuditLog` | `_entries`(list[AuditEntry]), `_max_entries`(int, 默认100000) | 审计日志存储 |
| Agent涉密等级缓存 | `_agent_clearances`(dict[str, SecurityClassification]) | Agent ID到涉密等级的映射 |

## 六、测试覆盖

对应测试类 `TestSecurityAgent`，共 **6** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_classify_public` — 验证普通文本分级为 PUBLIC
- `test_classify_confidential` — 验证含内部关键词文本分级 >= INTERNAL
- `test_clearance_check` — 验证权限预检（高等级可访问低等级资源）
- `test_audit_log_record_and_query` — 验证审计日志记录和查询
- `test_check_input` — 验证正常输入不被拦截
- `test_check_access` — 验证注册涉密等级后的访问控制

---

## 七、高涉密传输保护（M1-M5 涉密传输）

### 7.1 端到端加密原则

M1（多Agent集群调度）与 M5（潮汐记忆）之间的所有数据传输须启用端到端加密保护。加密机制采用基于非对称密钥协商的传输层安全方案，确保数据在跨模块流转过程中始终保持密文状态。具体密钥生成、分发、轮换及算法参数细节遵循云汐项目《密钥管理规范》，本文档仅作概念级描述，不暴露实现细节。

### 7.2 涉密四级标记在 A2A 消息头中的传递规则

A2A 消息头中统一携带 `x-security-classification` 字段，用于标识当前消息 payload 的涉密等级。四级标记定义如下：

| 标记值 | 等级名称 | 传递规则 | 处理要求 |
|--------|---------|---------|---------|
| `PUBLIC` | 公开 | 可在所有模块间自由传递 | 常规路由，无需额外脱敏 |
| `INTERNAL` | 内部 | 仅限云汐系统内部模块间传递 | 禁止流向外部系统或第三方服务 |
| `CONFIDENTIAL` | 机密 | 须经 Security-Agent 预检通过后方可传递 | 接收方须具备不低于该等级的 clearance |
| `TOP_SECRET` | 绝密 | 须经 Security-Agent 双重审批 + 字段级脱敏 | payload 中敏感字段替换为脱敏占位符后方可进入传输层 |

传递规则要点：
1. 消息发起方须在构造 A2A Task 时设置 `x-security-classification` 头字段，未设置时默认按 `INTERNAL` 处理。
2. Bus-Agent 在路由前读取该标记，若标记为 `CONFIDENTIAL` 或 `TOP_SECRET`，须将消息先路由至 Security-Agent 进行预检。
3. Security-Agent 对标记为 `TOP_SECRET` 的 payload 执行字段级脱敏：识别并替换所有涉及密钥材料、身份信息、坐标位置等敏感字段，替换格式为 `[已脱敏-绝密]`。
4. 脱敏后的消息在 A2A 协议字段表中不再包含任何可逆向还原的原始敏感字段标识（如 `vector_fingerprint` 等），统一以概念级描述替代。

### 7.3 绝密 Payload 字段级脱敏

当 Security-Agent 检测到 A2A 消息标记为 `TOP_SECRET` 时，执行以下脱敏操作（概念级描述）：
- **结构化字段脱敏**：对 payload 中所有可能暴露原始数据特征的字段（如向量摘要标识、生物特征哈希、密钥指纹等）执行字段级替换，输出统一占位符。
- **元信息剥离**：移除 trace_id 中的设备标识段、timestamp 中的微秒精度等可辅助溯源的元信息。
- **审计强化**：绝密消息的脱敏操作单独记录到审计日志，条目标记为 `audit_level=TOP_SECRET`，不受普通日志 FIFO 淘汰策略影响，须人工归档后方可清理。

### 7.4 安全事件上报

高涉密传输过程中触发的任何安全异常（如未授权降级、标记篡改、脱敏失败）均通过 Bus-Agent 发布到 `security.violation` 主题，由 Security-Agent 同步记录审计日志并通知 Arbiter-Agent 进行异常仲裁。
