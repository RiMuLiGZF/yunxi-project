# M4 业务场景引擎 (Scene Engine)

**模块代号**：M4
**模块名称**：业务场景引擎
**版本**：v1.0.0
**端口**：8004
**技术栈**：FastAPI + SQLAlchemy + SQLite

---

## 一、模块概述

M4 业务场景引擎是云汐系统的核心业务调度层，负责根据用户行为、环境上下文和语义识别，自动在不同业务场景之间进行智能切换，确保用户在正确的场景下获得最合适的服务响应。

### 核心能力

| 能力 | 说明 |
|------|------|
| **多场景管理** | 支持工作、学习、生活、休闲等多种场景，可自定义扩展 |
| **智能识别** | 基于关键词匹配 + LLM 语义增强，识别用户当前场景 |
| **暖切换** | 场景切换时保留上下文，支持快速切换不丢失状态 |
| **上下文存储** | 每个场景独立的上下文存储空间，支持持久化 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config 接口 |

---

## 二、目录结构

```
M4-scene-engine/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── .env.example           # 配置示例
├── README.md              # 本文件
├── data/                  # 数据目录
│   └── m4.db             # SQLite 数据库
├── src/
│   ├── main.py            # FastAPI 主入口
│   ├── models.py          # Pydantic 数据模型
│   ├── database.py        # 数据库模型 & 连接
│   ├── routers/           # API 路由
│   │   ├── scene.py       # 场景管理接口
│   │   ├── context.py     # 上下文管理接口
│   │   ├── config_route.py # 配置管理接口
│   │   └── admin.py       # 管理接口
│   ├── services/          # 业务服务
│   │   ├── recognizer.py  # 场景识别器
│   │   ├── switcher.py    # 场景切换管理器
│   │   └── context_store.py # 上下文存储
│   └── m8_api/            # M8 标准对接
│       ├── health_endpoints.py  # 健康/指标/配置接口
│       └── m8_auth_middleware.py # M8 Token 鉴权中间件
└── tests/                 # 单元测试
    ├── test_recognizer.py
    ├── test_switcher.py
    └── test_context.py
```

---

## 三、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M4_PORT` | `8004` | 服务监听端口 |
| `M4_ENV` | `development` | 运行环境 |
| `M4_DEFAULT_SCENE` | `work` | 默认场景 |
| `M4_AUTO_SWITCH` | `true` | 是否启用自动切换 |
| `M4_SWITCH_THRESHOLD` | `0.7` | 场景切换置信度阈值 |
| `M4_KEYWORD_THRESHOLD` | `0.7` | 关键词识别阈值 |
| `M4_ENABLE_LLM` | `false` | 是否启用 LLM 语义增强 |
| `M4_LLM_BASE_URL` | `""` | LLM API 地址 |
| `M4_LLM_MODEL` | `""` | LLM 模型名称 |
| `M4_MAX_HISTORY` | `100` | 最大历史记录数 |
| `M4_DATA_PATH` | `""` | 数据持久化路径 |
| `M4_ADMIN_TOKEN` | `""` | M8 对接管理 Token |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8004/health

# API 文档
http://localhost:8004/docs
```

---

## 四、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 场景管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/scenes` | GET | 获取所有场景列表 |
| `/api/v1/scenes/{scene_id}` | GET | 获取场景详情 |
| `/api/v1/scenes` | POST | 创建新场景 |
| `/api/v1/scenes/{scene_id}` | PUT | 更新场景配置 |
| `/api/v1/scenes/{scene_id}` | DELETE | 删除场景 |

### 4.3 场景切换

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/scenes/current` | GET | 获取当前场景 |
| `/api/v1/scenes/switch` | POST | 手动切换场景 |
| `/api/v1/scenes/recognize` | POST | 识别用户输入对应场景 |
| `/api/v1/scenes/history` | GET | 获取切换历史 |

### 4.4 上下文管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/context/{scene}` | GET | 获取场景上下文 |
| `/api/v1/context/{scene}` | PUT | 更新场景上下文 |
| `/api/v1/context/{scene}` | DELETE | 清空场景上下文 |

---

## 五、场景识别算法

### 基础识别（关键词匹配）

基于 TF-IDF 和关键词权重计算场景匹配度：

1. 每个场景配置一组关键词及权重
2. 用户输入分词后与关键词库匹配
3. 计算加权匹配度，超过阈值则触发切换

### LLM 增强（可选）

当关键词匹配置信度在灰色区间（0.5-0.7）时，调用 LLM 进行语义判断：

- 优点：更高的识别准确率，支持模糊语义
- 缺点：增加延迟和成本

---

## 六、测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_recognizer.py -v
```

---

## 七、与其他模块关系

- **上游**：M8 管理台通过 M8 标准接口纳管 M4
- **下游**：M4 从 M5 获取用户历史数据辅助场景判断
