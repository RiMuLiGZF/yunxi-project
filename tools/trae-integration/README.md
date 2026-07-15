# Trae MCP 集成说明

本文档介绍如何在 Trae IDE 中配置云汐项目的 MCP Server，以及可用工具和使用示例。

---

## 1. 配置 MCP Server

### 步骤

1. 打开 Trae IDE，进入 **设置**（Settings）
2. 在左侧导航栏找到并点击 **MCP**
3. 点击 **添加 Server**（Add Server）
4. 选择 **从配置文件导入**（Import from config file）
5. 浏览并选择本目录下的 `.mcp.json` 文件
6. 确认导入后，Trae 会自动读取配置并尝试连接 `yunxi-mcp-bus`

### 配置文件说明

`.mcp.json` 使用 **stdio** 传输模式，通过本地 Python 模块启动 MCP 服务：

| 字段 | 说明 |
|------|------|
| `command` | 启动命令，固定为 `python` |
| `args` | 模块入口参数 `[-m, "src.main"]` |
| `cwd` | MCP 服务的工作目录，指向 `M11-mcp-bus` |
| `env.PYTHONPATH` | Python 模块搜索路径 |
| `env.M4_BASE_URL` | M4 代码生成服务地址 |
| `env.M5_BASE_URL` | M5 记忆服务地址 |

---

## 2. 可用工具列表

以下工具通过 `yunxi-mcp-bus` 暴露给 Trae：

### M4 代码生成模块

| 工具名 | 功能描述 |
|--------|----------|
| `m4.code_generate` | 根据自然语言描述生成代码片段 |
| `m4.scene_switch` | 切换当前工作场景（如开发、测试、文档） |
| `m4.code_review` | 对代码进行审查并给出优化建议 |
| `m4.refactor` | 执行代码重构任务 |

### M5 记忆模块

| 工具名 | 功能描述 |
|--------|----------|
| `m5.memory_store` | 将信息存储到云汐记忆系统 |
| `m5.memory_recall` | 从记忆系统中检索相关信息 |
| `m5.memory_stats` | 查询记忆系统的统计信息（条数、容量等） |
| `m5.memory_delete` | 删除指定记忆条目 |

---

## 3. 使用示例对话

在 Trae 的 AI 对话中，可以直接使用自然语言触发 MCP 工具：

### 示例 1：代码生成

**用户输入：**
> 帮我生成一个 Python 排序函数

**Trae 行为：**
- 识别意图为代码生成
- 调用 `m4.code_generate`
- 参数：`{"language": "python", "description": "一个排序函数"}`
- 返回生成的代码片段并展示给用户

### 示例 2：记忆查询

**用户输入：**
> 查一下云汐系统有多少条记忆

**Trae 行为：**
- 识别意图为记忆统计
- 调用 `m5.memory_stats`
- 返回：`{"total_memories": 128, "last_updated": "2026-07-15T09:00:00Z"}`

### 示例 3：场景切换

**用户输入：**
> 切换到工作开发场景

**Trae 行为：**
- 识别意图为场景切换
- 调用 `m4.scene_switch`
- 参数：`{"scene": "development", "context": "工作开发"}`
- 返回切换成功确认，后续代码生成将基于开发场景上下文

---

## 4. 故障排查

### 问题："Module not found" 或 "Connection refused"

**现象：** Trae 提示无法连接 MCP Server，或工具调用超时。

**排查步骤：**

1. **确认 M11-mcp-bus 模块存在**
   ```powershell
   Test-Path "C:\云汐\工作台\yunxi-project\M11-mcp-bus\src\main.py"
   ```
   若不存在，请先部署或启动 M11-mcp-bus 服务。

2. **确认依赖已安装**
   ```powershell
   cd "C:\云汐\工作台\yunxi-project\M11-mcp-bus"
   pip install -r requirements.txt
   ```

3. **手动测试启动**
   ```powershell
   $env:PYTHONPATH="C:\云汐\工作台\yunxi-project\M11-mcp-bus\src"
   $env:M4_BASE_URL="http://localhost:8004"
   $env:M5_BASE_URL="http://localhost:8005"
   python -m src.main
   ```
   若手动启动成功但 Trae 仍报错，检查 Trae 的 Python 环境是否与系统一致。

4. **检查端口可用性**
   - M4 服务默认监听 `8004`
   - M5 服务默认监听 `8005`
   ```powershell
   Get-NetTCPConnection -LocalPort 8004, 8005 -ErrorAction SilentlyContinue
   ```

5. **查看 Trae MCP 日志**
   - 在 Trae 设置 → MCP → `yunxi-mcp-bus` 详情页查看 stderr/stdout 输出

### 问题：工具调用返回 "Not Found"

**现象：** MCP 连接正常，但特定工具报错。

**原因：** 对应的后端模块（M4 或 M5）可能未启动，或该工具尚未注册。

**解决：**
- 启动 M4 服务：`python -m m4.server`（端口 8004）
- 启动 M5 服务：`python -m m5.server`（端口 8005）
- 检查工具注册列表是否包含目标工具名
