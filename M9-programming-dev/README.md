# M9 编程开发 (Programming Dev)

**模块代号**：M9
**模块名称**：编程开发
**版本**：v0.1.0
**端口**：8009
**技术栈**：FastAPI + VSCode 管理 + 代码执行沙箱

---

## 一、模块概述

M9 编程开发模块是云汐系统的开发工具层，提供 VSCode 实例管理、多语言代码执行、项目管理等能力，支持开发者快速搭建开发环境和执行代码片段。

### 核心能力

| 能力 | 说明 |
|------|------|
| **VSCode 管理** | 启动/停止/列出 VSCode 实例，打开指定文件 |
| **代码执行** | 支持 Python/JS/TS/Bash 多语言代码执行 |
| **项目管理** | 创建/删除/列出项目，项目文件浏览 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、目录结构

```
M9-programming-dev/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── .env.example           # 配置示例
├── README.md              # 本文件
├── tests/                 # 单元测试
│   └── test_vscode_manager.py
└── src/
    └── m9_programming_dev/
        ├── __init__.py
        ├── main.py        # FastAPI 主入口
        ├── config.py      # 配置管理
        ├── models.py      # 数据模型
        ├── code_executor.py   # 代码执行器
        ├── project_manager.py # 项目管理器
        ├── vscode_manager.py  # VSCode 管理器
        └── routers/        # API 路由
            ├── __init__.py
            ├── code.py      # 代码执行接口
            ├── projects.py  # 项目管理接口
            └── vscode.py    # VSCode 管理接口
```

---

## 三、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M9_HOST` | `0.0.0.0` | 监听地址 |
| `M9_PORT` | `8009` | 监听端口 |
| `M9_ENV` | `development` | 运行环境 |
| `M9_DEBUG` | `false` | 调试模式 |
| `M9_ADMIN_TOKEN` | `""` | M8 对接管理 Token |
| `M9_VSCODE_CODE_COMMAND` | `code` | VSCode 命令 |
| `M9_VSCODE_DEFAULT_WORKSPACE` | `~/projects` | 默认工作空间 |
| `M9_CODE_EXEC_TIMEOUT` | `30` | 代码执行超时（秒） |
| `M9_CODE_EXEC_MAX_MEMORY` | `512` | 最大内存（MB） |
| `M9_PROJECTS_ROOT_DIR` | `~/yunxi-projects` | 项目根目录 |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8009/health

# API 文档
http://localhost:8009/docs
```

---

## 四、API 接口

### 4.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 4.2 VSCode 管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v1/vscode` | GET | 列出 VSCode 实例 |
| `GET /api/v1/vscode/{instance_id}` | GET | 获取实例详情 |
| `POST /api/v1/vscode` | POST | 启动 VSCode 实例 |
| `DELETE /api/v1/vscode/{instance_id}` | DELETE | 停止实例 |
| `POST /api/v1/vscode/{instance_id}/open-file` | POST | 打开指定文件 |

### 4.3 代码执行

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /api/v1/code/execute` | POST | 执行代码 |
| `GET /api/v1/code/languages` | GET | 列出支持的语言 |

### 4.4 项目管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v1/projects` | GET | 列出项目 |
| `GET /api/v1/projects/{project_id}` | GET | 获取项目详情 |
| `POST /api/v1/projects` | POST | 创建项目 |
| `DELETE /api/v1/projects/{project_id}` | DELETE | 删除项目 |
| `GET /api/v1/projects/{project_id}/files` | GET | 列出项目文件 |

---

## 五、支持的编程语言

| 语言 | 状态 | 说明 |
|------|------|------|
| Python | ✅ 支持 | 本地 Python 解释器 |
| JavaScript | ✅ 支持 | Node.js 执行 |
| TypeScript | ✅ 支持 | 需 ts-node |
| Bash | ✅ 支持 | 系统 shell |
| Java | ⚠️ 计划中 | 需 JDK |
| Go | ⚠️ 计划中 | 需 Go SDK |
| Rust | ⚠️ 计划中 | 需 Rustc |
| C/C++ | ⚠️ 计划中 | 需 GCC |

---

## 六、测试

```bash
# 运行所有测试
pytest tests/ -v
```

---

## 七、与其他模块关系

- **上游**：M8 管理台通过 M8 标准接口纳管 M9
- **下游**：调用本地编译器/解释器执行代码
- **前端**：M8 管理台的开发管理页面通过 API 交互
