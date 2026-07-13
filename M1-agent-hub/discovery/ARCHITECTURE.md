# 注册发现与负载均衡子Agent（Discovery-Agent）架构文档

## 一、职责定位

Discovery-Agent 是云汐系统的"服务注册中心+负载均衡器"，维护所有可用Agent的注册信息，根据能力需求匹配最优Agent，并综合多维指标评估Agent负载。它在端云协同场景下通过调度策略决定任务在本地还是云端执行，是系统资源分配的关键决策者。

## 二、输入输出

### handle_task 支持的 intent

| intent | payload 关键字段 | 说明 |
|--------|-----------------|------|
| `discovery.register` | `agent_info`(dict, 含 `agent_id` 必填, `capabilities`, `role`, `endpoint`, `metadata`) | 注册Agent |
| `discovery.unregister` | `agent_id`(str, 必填) | 注销Agent |
| `discovery.find` | `capabilities`(list[str]), `load_preference`(str, 默认"lowest") | 按能力查找Agent |
| `discovery.load_update` | `agent_id`(str, 必填), `metrics`(dict, 含 vram_usage/cpu_usage/battery_pct/network_latency/active_tasks) | 更新负载评分 |
| `discovery.find_best` | `candidates`(list[str]) | 从候选列表中查找最优Agent |
| `discovery.ranking` | 无 | 获取所有Agent负载排名 |
| `discovery.schedule` | `battery_pct`(float), `network_available`(bool), `task_complexity`(float), `strategy`(可选) | 调度决策 |
| `discovery.list` | 无 | 列出所有已注册Agent |
| `discovery.stats` | 无 | 统计信息 |

### 公开API方法签名

```python
def register_agent(agent_info: dict[str, Any]) -> bool
def find_agent(capabilities: list[str], load_preference: str = "lowest") -> str | None
def get_load_ranking() -> list[tuple[str, float]]
```

## 三、核心机制

**多维负载评估（LoadEvaluator）** 综合五个维度计算Agent负载评分：VRAM使用率、CPU使用率、电量百分比、网络延迟、活跃任务数。各维度独立归一化到 [0.0, 1.0]，其中电量采用反向归一化（越低负载越高），网络延迟采用 sigmoid 函数映射（50ms为半程点）。综合评分使用加权融合 + tanh 任务密度因子，具体权重为技术秘密。过载阈值为 0.85。此设计借鉴了 **Dify** 的资源调度器对端侧设备多维感知的思想。

**端云调度策略（SchedulingPolicy）** 支持三种策略模式：`LOCAL_FIRST`（优先本地，资源不足回退云端）、`AUTO`（综合评分自动决策）、`CLOUD_FIRST`（优先云端，离线时缓存任务）。策略可通过 payload 动态切换。`CLOUD_FIRST` 模式下无网络时自动将任务缓存到离线队列，网络恢复后通过 `drain_offline_tasks()` 取出重试。

**能力匹配** 采用全量子集匹配：候选Agent必须具备请求的所有能力标签。匹配后按负载偏好（默认最低负载优先）选择最优Agent。无负载评分时回退到第一个匹配结果。

## 四、协作关系

| 协作方 | 协作方式 | 说明 |
|--------|---------|------|
| Bus-Agent（agent.bus） | Bus消息发布 | 发布注册事件到 `discovery.agent_registered`、发现事件到 `discovery.agent_found`、负载更新到 `discovery.load_update`、调度决策到 `discovery.scheduling` |
| Orchestrator-Agent | 被调用方 | Orchestrator 构建 DAG 时使用 available_agents 列表进行能力匹配 |

## 五、数据模型

| 类名 | 关键字段 | 说明 |
|------|---------|------|
| `LoadScore` | `agent_id`, `vram_score`, `cpu_score`, `battery_score`, `network_score`, `composite`, `timestamp` | 多维负载评分 |
| `SchedulingDecision` | 枚举值：LOCAL_FIRST/AUTO/CLOUD_FIRST | 调度决策枚举 |
| 注册信息字典 | `agent_id`, `capabilities`, `role`, `endpoint`, `metadata`, `registered_at`, `status` | 内存注册表 |

## 六、测试覆盖

对应测试类 `TestDiscoveryAgent`，共 **4** 个测试用例：

- `test_agent_identity` — 验证 agent_id 正确性
- `test_load_evaluator_scoring` — 验证负载评估器评分在 [0, 1] 范围内
- `test_scheduling_policy_local_first` — 验证 LOCAL_FIRST 策略在电量充足+网络可用时返回 LOCAL_FIRST
- `test_scheduling_policy_cloud_no_network` — 验证无网络场景下的调度决策
- `test_register_and_find` — 验证注册Agent后能通过能力查找找到
