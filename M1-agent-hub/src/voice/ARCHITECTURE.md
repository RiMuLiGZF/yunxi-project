# 云汐人格润色输出子Agent（YunxiVoice-Agent）架构文档

## 一、职责定位

YunxiVoice-Agent 是云汐系统的"人格出口"，负责将上游各 Agent 产出的结构化原始内容，润色成有云汐人格温度的自然语言，作为面向用户输出的最后一道工序。它只负责「怎么说」，不负责「说什么」——事实性内容的正确性由上游专业 Agent 保证。

**核心定位**：L3 执行子 Agent 层（跨模块共享），归属 M1 Orchestrator-Agent 总管调度，M4 场景引擎在 SceneResult 输出前最后调用。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `voice.polish` | `raw_content`(str), `scene_type`(str, 默认"life"), `user_context`(dict, 可选), `output_format`(str, 默认"text"), `length_hint`(str, 默认"medium") | 标准人格润色（自动应用场景语气偏移） |
| `voice.polish_with_tone` | `raw_content`(str), `personality_params`(dict), `scene_type`(str, 可选) | 使用自定义人格参数润色 |
| `voice.quality_check` | `raw_content`(str), `polished_content`(str), `scene_type`(str) | 质量校验（事实完整性/语气一致性/红线检测） |
| `voice.red_line_check` | `content`(str) | 仅执行红线违规检测 |
| `voice.get_personality` | `scene_type`(str, 默认"life"), `user_context`(dict, 可选) | 获取指定场景的人格参数 |

### 公开API方法签名

```python
def polish(raw_content: str, scene_type: str = "life", user_context: dict | None = None,
           output_format: str = "text", length_hint: str = "medium") -> dict[str, Any]
def polish_with_custom_tone(raw_content: str, personality: dict[str, float],
                            scene_type: str = "life") -> dict[str, Any]
def quality_check(raw_content: str, polished_content: str, scene_type: str = "life") -> dict[str, Any]
def red_line_check(content: str) -> dict[str, Any]
def get_personality_for_scene(scene_type: str = "life",
                              user_context: dict | None = None) -> dict[str, Any]
def set_user_preferences(user_id: str, preferences: dict[str, Any]) -> None
```

## 三、核心机制

**人格五维参数体系** 基于云汐人设设定五维基础值：温暖度 8.5、理性度 7.5、幽默感 6.0、同理心 9.0、可靠度 9.5。所有维度钳位在 0-10 区间。

**两层命名映射体系**（底层模式 + 上层场景，共 12 组配置）：
- **L1 底层模式层**（M4 全局标准 `DOCUMENT/CODING/REVIEW/DESIGN/MENTAL/PLANNING）：决定「做什么类型的事」，定义基础语气基调
- **L2 上层场景层**（`work_dev/study_plan/review_summary/relationship/emotion_companion/life_management）：业务语义层，在基础语气上叠加细腻微调

**语气计算链路**：基础五维人格 → 底层模式偏移 → 上层场景微调 → 用户偏好微调 → 钳位 0-10。`_resolve_identifier()` 自动判断输入是模式名还是场景名，支持两种输入都能正确解析。

**底层模式语气偏移**（6 组）：
- CODING（代码开发）：温暖度-1、理性度+1、幽默感-0.5
- DOCUMENT（文档写作）：温暖度-0.5、理性度+1、可靠度+0.5
- REVIEW（评审复盘）：温暖度+0.5、理性度+0.5、同理心+0.5
- DESIGN（设计规划）：温暖度+0.5、幽默感+0.5、同理心+0.5
- MENTAL（情绪支持）：温暖度+2、理性度-1、同理心+2、幽默感-1
- PLANNING（计划管理）：理性度+1、可靠度+0.5

**上层场景语气微调**（6 组，在对应底层模式基础上叠加）：
- work_dev（工作开发）→ CODING 基础 + 幽默感+0.5、同理心+0.5
- study_plan（学业规划）→ DOCUMENT 基础 + 温暖度+1、理性度-0.5、同理心+0.5
- review_summary（复盘总结）→ REVIEW 基础 + 温暖度+0.5、理性度-0.5、同理心+0.5
- relationship（人际关系）→ DESIGN 基础 + 温暖度+1、理性度-0.5、同理心+1
- emotion_companion（情绪陪伴）→ MENTAL 基础（无额外偏移）
- life_management（生活综合管理）→ PLANNING 基础 + 温暖度+0.5、理性度-0.5、幽默感+0.5、同理心+0.5、可靠度-0.5

**质量自检流水线** 润色结果输出前执行三重校验：
1. 事实完整性：比对原始内容与润色内容的关键数据点（数字/专有名词）
2. 语气一致性：验证人格参数是否在场景预期范围内，检测场景语气词
3. 红线违规检测：扫描禁忌词（「本AI」「作为人工智能」「我调用了Agent」等）

**MENTAL 场景涉密保护** 情绪陪伴场景下执行额外隐私检查：
- 禁止输出原始情绪对话内容
- 仅基于结构化指标（情绪类型、强度、建议）进行润色
- 检测对话标记词（「用户说：」「原始对话」等），命中即打回

**用户偏好动态微调** 支持用户自定义语气温度、正式程度、话量、幽默感、称呼方式，在基础人格+场景偏移之上叠加微调。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| M1 Orchestrator-Agent | 上游调用方 | 多Agent结果整合后，将结构化输出传入本Agent润色 |
| M4 六模式子Agent | 上游内容提供方 | 各模式产出原始内容，不经润色直接交给M1整合 |
| M5 潮汐记忆 | 只读参考 | 读取用户偏好记忆（语气偏好、习惯称呼、历史互动风格） |
| M6 硬件外设 | 状态感知 | 根据生理状态（如压力大时）调整语气温度 |
| Security-Agent | 被调用方 | MENTAL场景涉密预检，确保无原始对话泄漏 |
| UI 层 | 下游消费方 | 接收润色后的最终文本，直接渲染给用户 |

## 五、数据模型

| 类名/结构体 | 关键字段 | 说明 |
|------------|---------|------|
| `YunxiVoiceAgent` | `agent_id`, `version`, `capabilities`, `_default_scene`, `_enable_quality_check`, `_user_preferences` | 主Agent类 |
| `DEFAULT_PERSONALITY` | warmth(8.5), rationality(7.5), humor(6.0), empathy(9.0), reliability(9.5) | 基础五维人格参数 |
| `SCENE_TONE_OFFSETS` | 6场景 × 5维度偏移量 + 场景关键词 | 场景语气偏移配置表 |
| `RED_LINE_PATTERNS` | 10个禁忌词模式 | 红线违规检测词表 |
| 润色结果输出 | `result_type`, `polished_content`, `tone_applied`, `personality_params`, `content_modified`, `facts_preserved`, `privacy_check` | 标准返回格式 |
| 用户偏好缓存 | `_user_preferences`(dict[str, dict]) | user_id到偏好字典的映射 |

## 六、测试覆盖

对应测试类 `TestYunxiVoiceAgent`，核心测试点：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_polish_basic` — 验证基础润色功能（语气词注入）
- `test_six_scene_offsets` — 验证6种场景的人格参数偏移正确
- `test_red_line_check` — 验证红线违规检测准确性
- `test_quality_check` — 验证质量校验（事实完整性/语气一致性）
- `test_mental_privacy` — 验证MENTAL场景隐私保护
- `test_user_preferences` — 验证用户偏好微调
- `test_polish_empty_content` — 验证空内容边界情况

## 七、接入架构改动清单

| 改动点 | 位置 | 状态 |
|--------|------|------|
| M1子Agent编制 | M1配置 | 新增 `agent.yunxi_voice` 到子Agent清单 |
| M1 Orchestrator调度 | 输出管道 | 结果合并后、返回M4前调用本Agent |
| M4 SceneResult | 输出管道 | 增加 `voice_polish` 管道节点 |
| M5记忆系统 | 读取接口 | 用户语气偏好只读接口（M5实现） |
| 涉密体系 | 校验规则 | MENTAL场景输出脱敏校验 |
| 调试工具 | 开发模式 | 「关闭人格润色」开关（便于调试原始输出） |
