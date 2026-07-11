# 云汐系统 - 模型管理中心

本目录是云汐系统的大模型与 Agent 管理层，负责统一管理本地模型、远程 API、Agent 框架的接入与调度。

## 目录结构

```
models/
├── README.md              # 本文件 - 模型管理总说明
├── config/                # 模型配置
│   └── models.yaml        # 可用模型清单与参数配置
├── ollama/                # 本地 Ollama 模型管理
│   ├── Modelfile.*        # 自定义模型文件
│   └── README.md          # Ollama 使用指南
├── agents/                # Agent 框架集成（未来扩展）
│   └── README.md          # Agent 集成说明
└── scripts/               # 管理脚本（Windows）
    ├── start-ollama.bat   # 启动 Ollama 服务
    ├── pull-model.bat     # 拉取指定模型
    ├── list-models.bat    # 列出已安装模型
    └── setup-ollama.ps1   # 一键配置脚本
```

## 模型存储说明

### 模型二进制文件
模型权重文件体积较大（数GB~数十GB），**不存入 Git 仓库**，由 Ollama 统一管理：
- **默认位置**: `C:\Users\<用户名>\.ollama\models\`
- **修改方式**: 设置环境变量 `OLLAMA_MODELS` 指向自定义路径

### 项目内管理内容
本目录仅管理：
1. 模型配置与清单（`config/`）
2. 自定义 Modelfile（`ollama/`）
3. 管理脚本与工具（`scripts/`）
4. Agent 框架集成代码（`agents/`）

## 当前可用模型

| 模型名称 | 提供方 | 类型 | 大小 | 状态 | 用途 |
|---------|--------|------|------|------|------|
| qwen2.5:7b | Ollama (本地) | 对话 | ~4.7GB | 已安装 | 主力对话模型 |
| deepseek-chat | DeepSeek (云端) | 对话 | - | 可用 | 云端备选 |

## 切换模型提供方

修改 `config/yunxi.env` 中的 `LLM_PROVIDER`：

```env
# 使用本地 Ollama
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# 使用云端 DeepSeek
LLM_PROVIDER=deepseek
LLM_API_KEY=your-api-key
LLM_MODEL=deepseek-chat
```

## 快速开始

### 1. 启动 Ollama 服务
```bat
scripts\start-ollama.bat
```

### 2. 拉取模型
```bat
scripts\pull-model.bat qwen2.5:7b
```

### 3. 验证安装
```bat
scripts\list-models.bat
```

## 未来扩展规划

### 更多本地模型
- 嵌入模型：`nomic-embed-text`, `bge-m3`
- 代码模型：`qwen2.5-coder:7b`, `deepseek-coder:6.7b`
- 多模态：`qwen2.5-vl:7b`
- 更小/更大规格：`qwen2.5:1.5b`, `qwen2.5:14b`

### Agent 框架集成
- AutoGPT / MetaGPT 等多 Agent 框架
- 自定义 Agent 工作流编排
- 工具调用（Function Calling）支持

### 模型微调
- LoRA 微调数据集管理
- 微调脚本与评估工具
- 模型版本管理

## 相关模块

- `shared/llm_client.py` - 统一大模型客户端
- `config/yunxi.env` - 全局配置文件
- `M1 模块` - 多 Agent 集群调度
