# 云汐系统 — 人工安装与配置需求文档

> 版本: v0.6.0 | 更新日期: 2026-07-15
> 本文件列出所有需要人工在目标环境执行的安装、配置和验证步骤。

---

## 目录

1. [安装状态速查](#1-安装状态速查)
2. [系统级依赖安装](#2-系统级依赖安装)
3. [Python 依赖安装](#3-python-依赖安装)
4. [Docker 服务安装](#4-docker-服务安装)
5. [Ollama 与 LLM 模型](#5-ollama-与-llm-模型)
6. [桌面启动器安装](#6-桌面启动器安装)
7. [Trae IDE MCP 集成](#7-trae-ide-mcp-集成)
8. [服务依赖关系图](#8-服务依赖关系图)
9. [常见问题排查](#9-常见问题排查)

---

## 1. 安装状态速查

### 1.1 当前环境状态

| 组件 | 版本 | 状态 | 说明 |
|------|------|------|------|
| Python | 3.10.11 | 已安装 | 符合 >=3.10 要求 |
| Pip | 26.1.2 | 已安装 | 包管理器 |
| Git | 2.55.0.windows.2 | 已安装 | 版本控制 |
| Docker | 29.6.1 | 已安装 | 容器运行时 |
| Docker Compose | 5.3.0 | 已安装 | 容器编排 |
| Ollama | 0.31.1 | 已安装 | 本地 LLM 推理 |
| qwen2.5:7b | 4.7 GB | 已下载 | 主模型 |
| qwen2.5:3b | 1.9 GB | 已下载 | 备用模型 |
| qwen2.5:1.5b | 986 MB | 已下载 | 轻量模型 |

### 1.2 服务依赖总表

| 服务 | 端口 | 安装方式 | 必须/可选 | 运行状态 | 影响 |
|------|------|----------|-----------|----------|------|
| Ollama | 11434 | 系统安装 | **必须** | 运行中 | M4 代码生成、M1 LLM 决策 |
| Redis | 6379 | Docker | **必须** | 未运行 | 统一日志、M11 缓存和限流 |
| ChromaDB | 8100 | Docker | **可选** | 未运行 | 无人使用，可安全移除 |
| Prometheus | 9090 | Docker | 可选 | 未运行 | 指标采集和可视化 |
| Grafana | 3000 | Docker | 可选 | 未安装 | 指标看板 |

---

## 2. 系统级依赖安装

### 2.1 Python

**要求**: Python >= 3.10

```powershell
# 已安装，无需操作
python --version
# 输出: Python 3.10.11
```

> 注意：当前安装的是 Python 3.10.11，不是 3.11。所有模块均兼容 3.10，无需升级。

### 2.2 Git

**要求**: Git >= 2.30

```powershell
# 已安装，无需操作
git --version
# 输出: git version 2.55.0.windows.2
```

### 2.3 Docker Desktop

**要求**: Docker >= 24.0

```powershell
# 已安装，无需操作
docker --version
# 输出: Docker version 29.6.1
docker compose version
# 输出: Docker Compose version v5.3.0
```

> 重要：Docker Desktop 需要在 Windows 中保持运行状态，才能执行 `docker compose up -d`。

---

## 3. Python 依赖安装

### 3.1 核心依赖

```powershell
# 进入项目根目录
cd C:\云汐\工作台\yunxi-project

# 安装核心运行时依赖
pip install fastapi uvicorn[standard] httpx pydantic pydantic-settings
pip install structlog python-dotenv psutil
pip install sqlalchemy aiosqlite
pip install numpy
```

### 3.2 测试依赖

```powershell
pip install pytest pytest-cov pytest-asyncio pytest-timeout
```

### 3.3 向量检索依赖（可选但推荐）

M5 潮汐记忆系统使用 FAISS 进行本地向量检索，无需外部向量数据库：

```powershell
# 推荐安装（FAISS 向量索引，大幅提升记忆检索速度）
pip install faiss-cpu

# 可选安装（本地 Embedding 模型，提升向量质量）
pip install sentence-transformers
```

> 说明：即使不安装这两个库，M5 也能以 TF-IDF+SVD 模式完全独立运行。安装后检索精度和速度会显著提升。

### 3.4 可观测性依赖（可选）

```powershell
pip install prometheus-client
pip install redis
```

### 3.5 桌面启动器依赖（可选）

```powershell
pip install pystray pillow keyboard
```

### 3.6 一键安装

```powershell
pip install fastapi uvicorn[standard] httpx pydantic pydantic-settings structlog python-dotenv psutil sqlalchemy aiosqlite numpy faiss-cpu sentence-transformers pytest pytest-cov pytest-asyncio pytest-timeout prometheus-client redis pystray pillow
```

---

## 4. Docker 服务安装

### 4.1 服务清单

| 服务 | 镜像 | 端口 | 安装必要性 | 若不安装的后果 |
|------|------|------|-----------|---------------|
| Redis | redis:7-alpine | 6379 | **必须** | M11 缓存和限流失效；统一日志降级到文件 |
| ChromaDB | chromadb/chroma:latest | 8100 | **可选** | 无人使用，可以安全移除 |
| Prometheus | prom/prometheus:latest | 9090 | 可选 | 指标无法持久化采集 |
| Grafana | grafana/grafana:latest | 3000 | 可选 | 无可视化看板 |

### 4.2 启动命令

```powershell
# 启动所有服务（推荐）
cd C:\云汐\工作台\yunxi-project
docker compose up -d

# 仅启动必需服务（Redis）
docker compose up -d redis

# 查看服务状态
docker compose ps

# 停止所有服务
docker compose down
```

### 4.3 关于 ChromaDB 的重要说明

**M5 潮汐记忆系统不依赖 ChromaDB。**

经过代码审计确认：
- M5 使用 **FAISS**（本地向量索引库，安装 `faiss-cpu` 即可）进行向量检索
- 向量嵌入由 `sentence-transformers` 本地模型生成，降级到 Ollama 或 TF-IDF+SVD
- 所有检索操作在**进程内内存**中完成，无需任何外部向量数据库服务
- `requirements.txt` 中的 `chromadb>=0.4.0` 是死依赖，代码中从未引用

**结论**：ChromaDB 无需安装。如果 `docker-compose.yml` 中有 Chromadb 服务，可以将其注释掉或删除。

---

## 5. Ollama 与 LLM 模型

### 5.1 安装状态

Ollama 已安装并运行，模型已下载：

| 模型 | 用途 | 大小 | 状态 |
|------|------|------|------|
| qwen2.5:7b | M4 代码生成、M1 Agent 决策 | 4.7 GB | 已下载 |
| qwen2.5:3b | 轻量推理 | 1.9 GB | 已下载 |
| qwen2.5:1.5b | 极轻量推理 | 986 MB | 已下载 |

### 5.2 验证命令

```powershell
# 验证 Ollama 运行状态
curl http://localhost:11434/api/tags

# 验证模型推理
ollama run qwen2.5:7b "你好，请说一句话"
```

### 5.3 Docker 环境中使用 Ollama 的注意事项

由于 Docker Desktop 在 Windows 上不支持 GPU 直通，以下方案可供选择：

| 方案 | 操作 | 适用场景 |
|------|------|----------|
| A: 宿主机 Ollama | 容器内使用 `http://host.docker.internal:11434` 访问宿主机 Ollama | 推荐，最简单 |
| B: WSL2 + GPU | 仅限 NVIDIA GPU，需安装 NVIDIA Container Toolkit | 需要 GPU 加速时 |
| C: CPU 模式 | 直接使用 CPU 运行 Ollama，速度较慢 | 无 GPU 或不想配置 |

---

## 6. 桌面启动器安装

### 6.1 安装步骤

```powershell
# 以管理员身份运行 PowerShell
powershell -ExecutionPolicy Bypass -File "C:\云汐\工作台\yunxi-project\tools\desktop-launcher\install.ps1"
```

### 6.2 安装后功能

- 系统托盘出现云汐图标（深蓝色"汐"字 Logo）
- 左键单击：打开统一门户
- 右键菜单：启动/停止系统、模块状态查看、打开 API 文档
- 后台每 30 秒轮询所有模块健康状态
- 图标颜色反映系统状态（灰=未启动、蓝=启动中、绿=全部就绪、红=有故障）
- 全局快捷键：`Ctrl+Alt+Y` 快速打开门户

### 6.3 卸载

```powershell
# 删除快捷方式
Remove-Item "$env:USERPROFILE\Desktop\云汐启动器.lnk"
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\云汐启动器.lnk"
```

---

## 7. Trae IDE MCP 集成

### 7.1 配置步骤

1. 确保 M11 模块已启动（`http://localhost:8011`）
2. 在 Trae IDE 中：
   - 打开设置 → MCP
   - 点击"添加 Server"
   - 选择文件 → 浏览到 `C:\云汐\工作台\yunxi-project\tools\trae-integration\.mcp.json`
3. 验证连接

### 7.2 可用 MCP 工具

| 模块 | 工具数 | 示例工具 |
|------|--------|----------|
| M2 | 5 | invoke_skill, translate, search |
| M4 | 4 | code_generate, scene_switch |
| M5 | 4 | memory_store, memory_recall |
| M7 | 5 | run_workflow, list_workflows |
| M8 | 5 | list_modules, get_health |
| M10 | 4 | get_metrics, get_gpu_summary |
| M12 | 4 | check_waf, list_audit_logs |
| **总计** | **37** | |

### 7.3 验证对话

在 Trae 对话框中输入：

```
"帮我生成一个 Python 排序函数"
→ 应调用 m4.code_generate 工具

"查一下云汐系统有多少条记忆"
→ 应调用 m5.memory_stats 工具

"切换到工作开发场景"
→ 应调用 m4.scene_switch 工具
```

---

## 8. 服务依赖关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                      外部基础设施 (需人工安装)                      │
│                                                                  │
│  Ollama (必须)      Redis (必须)     Prometheus (可选)            │
│  :11434              :6379           :9090                       │
│    │                    │                │                       │
│    ▼                    ▼                ▼                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    云汐 13 个模块                             │ │
│  │                                                              │ │
│  │  M4 场景引擎 ──→ Ollama ──→ 代码生成                          │ │
│  │  M1 Agent调度 ──→ Ollama ──→ Agent 决策                      │ │
│  │  M5 潮汐记忆 ──→ FAISS ──→ 本地向量检索 (无需外部数据库)       │ │
│  │  M11 MCP总线 ──→ Redis ──→ 缓存/限流                         │ │
│  │  M10 系统卫士 ──→ Prometheus ──→ 指标暴露                     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 关键结论

| 需要安装 | 不需要安装 |
|----------|-----------|
| ✅ Redis (必须) | ❌ ChromaDB (无人使用) |
| ✅ Ollama (必须) | ❌ 任何其他外部向量数据库 |
| ✅ Python 依赖 (必须) | |
| ⚠️ Prometheus (可选) | |
| ⚠️ Grafana (可选) | |

---

## 9. 常见问题排查

### 9.1 Ollama 未运行

**现象**: 端口 11434 无响应，M4 代码生成失败

**解决**:
```powershell
# 启动 Ollama
ollama serve

# 或启动为系统服务
ollama start
```

### 9.2 Docker 未运行

**现象**: `docker compose` 命令报错 "Cannot connect to the Docker daemon"

**解决**: 打开 Docker Desktop 桌面应用，等待其完全启动

### 9.3 Redis 未运行

**现象**: M11 日志中出现 "Redis 不可用" 警告

**解决**:
```powershell
docker compose up -d redis
```

### 9.4 M5 慢速运行

**现象**: 记忆检索耗时 > 1 秒

**解决**:
```powershell
# 安装 FAISS 加速（推荐）
pip install faiss-cpu

# 安装本地 Embedding 模型
pip install sentence-transformers
```

### 9.5 端口冲突

| 端口 | 用途 | 冲突原因 | 解决 |
|------|------|----------|------|
| 8000 | M0 主理人 | ChromaDB 默认端口 | ChromaDB 已改为 8100 |
| 11434 | Ollama | 其他 LLM 服务 | 修改 yunxi.env 中的 OLLAMA_BASE_URL |