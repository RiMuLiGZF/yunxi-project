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
| **统一错误** | `errors.py` | 自定义异常体系，统一错误码，异常转字典工具 |
| **统一响应** | `responses.py` | 标准化 API 响应格式，标准错误码常量 |
| **通用工具** | `utils.py` | 随机 ID、时间戳、安全取值、文本截断、文件大小格式化 |

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

### 3.6 errors.py — 统一错误处理

**功能**：
- `YunxiError` 基类：所有自定义异常的基类，统一 code/message/details 属性
- 7 种常用异常：ConfigError、ModuleNotFoundError、ModuleCallError、ValidationError、AuthenticationError、AuthorizationError
- `error_to_dict()` 工具函数：将异常转为字典，便于 API 响应输出

**使用方式**：
```python
from shared.errors import ValidationError, error_to_dict

# 抛出业务异常
raise ValidationError("用户名不能为空", details={"field": "username"})

# 统一捕获并转换
try:
    ...
except Exception as e:
    err_dict = error_to_dict(e)
```

### 3.7 responses.py — 统一 API 响应格式

**功能**：
- `ApiResponse` 类：标准化的响应结构（code / message / data / details / request_id）
- `success()` 类方法：创建成功响应
- `error()` 类方法：创建错误响应
- `to_dict()` 方法：转为字典用于 JSON 序列化
- 标准错误码常量：SUCCESS、ERROR_INVALID_PARAMS、ERROR_UNAUTHORIZED、ERROR_FORBIDDEN、ERROR_NOT_FOUND、ERROR_INTERNAL、ERROR_MODULE_UNAVAILABLE

**使用方式**：
```python
from shared.responses import ApiResponse, ERROR_INVALID_PARAMS

# 成功响应
return ApiResponse.success({"user": "alice"}, message="获取成功").to_dict()

# 错误响应
return ApiResponse.error(ERROR_INVALID_PARAMS, "参数错误", details={"field": "name"}).to_dict()
```

### 3.8 utils.py — 通用工具函数

**功能**：
- `generate_id(length=16)`：生成加密安全的随机十六进制 ID
- `now_timestamp()`：当前 Unix 时间戳（秒）
- `now_iso()`：当前 ISO 8601 格式时间字符串（UTC）
- `safe_get(dict_obj, key, default)`：安全获取字典值，支持 None 字典
- `truncate_text(text, max_length=100)`：截断文本并添加省略号
- `format_file_size(bytes_size)`：格式化文件大小（B / KB / MB / GB / TB）

**使用方式**：
```python
from shared.utils import generate_id, now_timestamp, format_file_size

request_id = generate_id(16)
ts = now_timestamp()
size_str = format_file_size(1048576)  # "1.00 MB"
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
