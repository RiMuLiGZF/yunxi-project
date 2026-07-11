# Shared 公共组件库

**模块代号**：shared
**版本**：v1.0.0
**说明**：云汐系统全局共享组件库，被所有模块引用

---

## 一、模块概述

shared 是云汐系统的公共基础组件库，提供全局配置、统一日志、模块调用客户端、进程管理器等通用能力，供所有模块复用，避免重复造轮子。

---

## 二、子模块一览

| 子模块 | 文件 | 功能 |
|--------|------|------|
| **全局配置** | `config.py` | 统一从 yunxi.env 加载，管理 10 模块的端口/Host/Token/BaseURL |
| **统一日志** | `logger.py` | 结构化日志，统一格式，避免重复 handler |
| **LLM 客户端** | `llm_client.py` | 多后端切换（DeepSeek/OpenAI/Ollama），流式对话，文本嵌入 |
| **模块调用** | `module_client.py` | HTTP 客户端封装，重试/超时/鉴权，模块注册中心，健康检查 |
| **进程管理** | `process_manager.py` | 模块进程启动/停止/重启，状态跟踪，健康检查轮询 |

---

## 三、子模块详情

### 3.1 config.py — 全局配置

**功能**：
- 单例模式，统一从 `config/yunxi.env` 加载配置
- 管理 M1-M10 所有模块的端口、地址、Token、Base URL
- 大模型配置（DeepSeek/OpenAI/Ollama + Embedding）
- 安全配置（CORS、超时、重试）

**使用方式**：
```python
from shared.config import get_config

config = get_config()
port = config.get_module_port("m8")
base_url = config.get_module_base_url("m1")
```

### 3.2 logger.py — 统一日志

**功能**：
- 统一日志格式（时间 + 级别 + logger 名 + 消息）
- 避免重复 handler（多次 get_logger 不会重复添加 handler）
- 支持从全局配置读取日志级别

**使用方式**：
```python
from shared.logger import get_logger

logger = get_logger("m8.backend")
logger.info("服务启动成功")
```

### 3.3 llm_client.py — LLM 客户端

**功能**：
- 三个 Provider：DeepSeek / OpenAI / Ollama
- 支持 chat / chat_stream / embed 三种核心能力
- 单例模式，运行时切换 Provider
- 统一的错误处理和日志记录

**使用方式**：
```python
from shared.llm_client import get_llm_client

client = get_llm_client()
response = client.chat("你好")
```

### 3.4 module_client.py — 模块调用客户端

**功能**：
- HTTP 客户端封装（GET/POST/PUT/DELETE）
- 支持重试、超时、鉴权 Token
- ModuleRegistry 模块注册中心，管理 10 个模块
- 健康检查和状态汇总

**使用方式**：
```python
from shared.module_client import get_module_client, get_module_registry

# 模块注册中心
reg = get_module_registry()
modules = reg.get_all_modules()

# 调用其他模块
client = get_module_client("m1")
result = client.get("/health")
```

### 3.5 process_manager.py — 进程管理器

**功能**：
- 支持 Windows/Linux 跨平台进程管理
- 启动/停止/重启/状态查询
- 异步等待启动完成（健康检查轮询）
- 进程异常退出检测
- 支持 M1-M10 共 10 个模块

**使用方式**：
```python
from shared.process_manager import get_process_manager

pm = get_process_manager()
pm.start_module("m10")
status = pm.get_module_status("m10")
```

---

## 四、配置文件

全局配置文件路径：`config/yunxi.env`

包含以下配置块：
- 全局基础配置
- M1-M10 各模块配置（端口/Host/Token/BaseURL）
- 大模型配置（DeepSeek/OpenAI/Ollama）
- 模块间调用配置

---

## 五、使用说明

### 路径约定

所有模块的项目根目录为 `yunxi-project/`，shared 模块位于 `shared/` 目录下。

### 导入方式

```python
import sys
from pathlib import Path

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent  # 根据实际层级调整
sys.path.insert(0, str(project_root))

# 导入 shared 组件
from shared.config import get_config
from shared.logger import get_logger
from shared.module_client import get_module_client
from shared.process_manager import get_process_manager
```

---

## 六、与其他模块关系

```
              ┌──────────────┐
              │   shared     │
              │  公共组件库   │
              └──────┬───────┘
       ┌───────────┼───────────┐
       │           │           │
  ┌────▼───┐  ┌───▼────┐  ┌──▼─────┐
  │  M1-M10 │  │  M8    │  │  前端   │
  │  各模块  │  │ 管理台 │  │        │
  └────────┘  └────────┘  └────────┘
```

shared 被所有模块引用，是系统的基础依赖层。
