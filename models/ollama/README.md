# Ollama 本地模型管理

本目录管理云汐系统的本地 Ollama 模型配置。

## Ollama 基础

### 什么是 Ollama
Ollama 是一个本地大模型运行框架，支持一键拉取、运行多种开源大模型。

### 安装位置
- **程序**: `C:\Users\XiZho\AppData\Local\Programs\Ollama\`
- **模型**: `C:\Users\XiZho\.ollama\models\`
- **版本**: v0.31.1

### 修改模型存储位置
如需将模型存储到其他位置（如D盘），设置环境变量：

```powershell
# 临时设置
$env:OLLAMA_MODELS = "D:\ollama\models"

# 永久设置（用户级）
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\ollama\models", "User")
```

## 常用命令

```powershell
# 启动服务
ollama serve

# 拉取模型
ollama pull qwen2.5:7b

# 列出已安装模型
ollama list

# 运行模型（交互）
ollama run qwen2.5:7b

# 删除模型
ollama rm qwen2.5:7b

# 查看模型信息
ollama show qwen2.5:7b
```

## 自定义模型 (Modelfile)

可以基于现有模型创建自定义版本，例如修改系统提示词、参数等。

### 示例：创建云汐专属模型

```dockerfile
# Modelfile.yunxi-assistant
FROM qwen2.5:7b

# 系统提示词
SYSTEM """
你是云汐智能助手，由云汐系统驱动。
你精通中文对话，擅长协助用户完成各种任务。
你的回答应该准确、简洁、有帮助。
"""

# 参数设置
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 32768

# 模板
TEMPLATE """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
"""
```

### 创建命令
```bash
ollama create yunxi-assistant -f Modelfile.yunxi-assistant
```

## 性能优化

### GPU 加速
Ollama 自动检测并使用 GPU。如需调整：

```powershell
# 设置使用的 GPU 层数（-1 表示全部）
$env:OLLAMA_NUM_GPU = -1

# 限制 GPU 显存开销（MB）
$env:OLLAMA_GPU_OVERHEAD = 1024
```

### 并发设置
```powershell
# 最大并行请求数
$env:OLLAMA_NUM_PARALLEL = 2

# 模型保活时间
$env:OLLAMA_KEEP_ALIVE = "30m"
```

## 故障排查

### 服务无法启动
1. 检查端口 11434 是否被占用
2. 查看日志：`C:\Users\XiZho\.ollama\logs\`
3. 尝试手动启动：`ollama serve`

### 模型下载慢
1. 设置代理：`$env:HTTPS_PROXY = "http://proxy:port"`
2. 使用国内镜像源

### 显存不足
1. 使用更小的模型（如 qwen2.5:1.5b）
2. 减少 GPU 层数
3. 降低上下文窗口大小
