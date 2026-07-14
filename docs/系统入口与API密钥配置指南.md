# 云汐系统 - 入口与 API 密钥配置指南

> 用途：帮助你快速找到系统入口和配置 API 密钥的位置
> 更新日期：2026-07-09

---

## 一、系统入口总览

### 1.1 主入口（最重要）

| 入口 | 地址 | 说明 |
|------|------|------|
| **云汐统一门户** | `http://localhost:8000` | 主入口，所有功能从这里进入 |
| **M8 管理台登录** | `http://localhost:8000/m8/login.html` | 后台管理入口 |
| **M8 API 文档** | `http://localhost:8000/docs` | Swagger UI，调试接口用 |

**默认登录账号：**
- 用户名：`admin`
- 密码：`admin123456`

### 1.2 各模块服务端口

所有后端服务都是独立进程，各占一个端口：

| 模块 | 端口 | 入口文件 | 启动命令 |
|------|------|---------|---------|
| M8 管理工作台（主入口） | **8000** | `M8-control-tower/server.py` | `python server.py` |
| M1 多Agent集群调度 | 8001 | `M1-agent-hub/server.py` | `python server.py` |
| M2 技能集群 | 8002 | `M2-skills-cluster/start_server.py` | `python start_server.py` |
| M3 端云协同内核 | 8003 | `M3-edge-cloud/server.py` | `python server.py` |
| M4 场景引擎 | 8004 | `M4-scene-engine/server.py` | `python server.py` |
| M5 潮汐记忆 | 8005 | `M5-tide-memory/server.py` | `python server.py` |
| M6 硬件外设 | 8006 | `M6-hardware-peripheral/server.py` | `python server.py` |
| M7 积木平台 | 8007 | `M7-workflow-builder/server.py` | `python server.py` |
| M9 编程开发 | 8009 | `M9-programming-dev/server.py` | `python server.py` |
| M10 系统卫士 | 8010 | `M10-system-guard/server.py` | `python server.py` |

### 1.3 主要功能页面

登录 M8 管理台后，可以访问以下主要页面：

| 页面 | 路径 | 功能 |
|------|------|------|
| 门户首页 | `/` 或 `/index.html` | 6 大入口卡片导航 |
| 云汐聊天 | `/modes/main-chat.html` | 主对话界面 |
| 管理台仪表盘 | `/m8/dashboard.html` | 系统总览监控 |
| 模块管理 | `/m8/modules.html` | 各模块启停管理 |
| 算力调度中台 | `/m8/compute.html` | ⭐ API 密钥配置、算力源管理 |
| Agent 管理 | `/m8/agents.html` | ⭐ Agent 配置、密钥管理 |
| 系统设置 | `/m8/settings.html` | ⭐ 基础设置、API 密钥 |
| 积木平台 | `/m7/workflow-list.html` | 工作流编辑器 |
| 任务监控 | `/xian/main-running.html` | 汐舷任务运行监控 |
| 部署中心 | `/m8/deploy.html` | Ollama、Git、蓝牙部署 |

---

## 二、API 密钥配置位置

### 2.1 配置文件方式（推荐首次配置）

**核心配置文件：** `config/yunxi.env`

这是所有模块共享的全局配置文件，改这里最省事。

**需要配置的核心密钥（按优先级排序）：**

| 配置项 | 说明 | 示例值 | 必须？ |
|--------|------|--------|-------|
| `LLM_API_KEY` | 大模型 API 密钥 | `sk-xxxxxxxxxx` | ⭐ 核心 |
| `LLM_BASE_URL` | API 地址 | `https://api.openai.com/v1` | ⭐ 核心 |
| `LLM_MODEL` | 默认模型 | `gpt-4o` 或 `qwen-plus` | 推荐 |
| `EMBEDDING_MODEL` | 向量嵌入模型 | `text-embedding-3-small` | 可选 |
| `M8_ADMIN_PASSWORD` | 管理员密码 | 自定义 | 推荐修改 |
| `M8_JWT_SECRET` | JWT 签名密钥 | 随机字符串 | 推荐修改 |

**各模块独立密钥（一般不用改，用默认值即可）：**

| 配置项 | 模块 | 用途 |
|--------|------|------|
| `M1_ADMIN_TOKEN` | M1 | M8 调用 M1 的鉴权令牌 |
| `M2_ADMIN_TOKEN` | M2 | M8 调用 M2 的鉴权令牌 |
| `M3_ADMIN_TOKEN` | M3 | M8 调用 M3 的鉴权令牌 |
| `M4_ADMIN_TOKEN` | M4 | M8 调用 M4 的鉴权令牌 |
| `M5_ADMIN_TOKEN` | M5 | M8 调用 M5 的鉴权令牌 |
| `M5_EMBEDDING_API_KEY` | M5 | M5 独立的嵌入 API 密钥（不设则用全局 LLM_API_KEY） |
| `M6_ADMIN_TOKEN` | M6 | M8 调用 M6 的鉴权令牌 |
| `M7_ADMIN_TOKEN` | M7 | M8 调用 M7 的鉴权令牌 |
| `M9_ADMIN_TOKEN` | M9 | M8 调用 M9 的鉴权令牌 |
| `M10_ADMIN_TOKEN` | M10 | M8 调用 M10 的鉴权令牌 |
| `M1_ENCRYPTION_KEY` | M1 | 数据加密密钥 |
| `M5_ENCRYPTION_KEY` | M5 | 记忆数据加密密钥 |

> 💡 **提示**：M1-M10 的 ADMIN_TOKEN 是模块间通信的内部令牌，不是给用户用的。如果只是自己用，保持默认值就行。如果部署到公网，一定要改成强随机字符串。

### 2.2 UI 界面方式（运行时配置）

系统提供 **3 个** UI 界面可以配置密钥，按功能强弱排序：

#### 🥇 算力调度中台（功能最全）
- **位置**：登录后 → 左侧菜单 → 算力调度中台
- **路径**：`/m8/compute.html`
- **功能**：
  - 添加/编辑/删除算力源（OpenAI、DeepSeek、通义千问、Ollama 等）
  - 每个算力源独立配置：API Key、Base URL、模型列表、权重
  - 密钥分组管理（按项目/用途分组）
  - 路由策略配置（轮询、优先级、最低延迟等）
  - 配置导入/导出（JSON 格式）
- **适合场景**：有多个 API 密钥、需要智能路由、负载均衡

#### 🥈 Agent 管理 - 密钥管理
- **位置**：登录后 → 左侧菜单 → Agent 管理 → 密钥管理 Tab
- **路径**：`/m8/agents.html`
- **功能**：
  - 添加密钥（选择服务商、填 API Key）
  - 密钥列表展示
  - 编辑、删除密钥
- **适合场景**：给 Agent 调用配置密钥，简单直接

#### 🥉 系统设置 - API 密钥
- **位置**：登录后 → 右上角设置 → API 密钥 Tab
- **路径**：`/m8/settings.html`
- **状态**：UI 已搭建，部分功能开发中
- **功能**：展示密钥列表，创建功能待完善

---

## 三、快速操作：配置你的第一个 API 密钥

### 方案 A：改配置文件（最快）

1. 打开文件：`C:\Yunxi\workspace\yunxi-project\config\yunxi.env`
2. 找到以下几行，修改成你的配置：

```env
# ====== 大模型配置 ======
LLM_PROVIDER=openai
LLM_API_KEY=sk-你的密钥在这里
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

3. 保存文件
4. 重启相关模块（M1、M8 等），或者直接重启所有服务

### 方案 B：UI 界面配置（最直观）

1. 启动 M8 服务：
   ```powershell
   cd C:\Yunxi\workspace\yunxi-project\M8-control-tower
   python server.py
   ```

2. 打开浏览器访问：`http://localhost:8000/m8/login.html`

3. 登录：
   - 用户名：`admin`
   - 密码：`admin123456`

4. 进入「算力调度中台」（左侧菜单）

5. 点击「添加算力源」，填写：
   - 名称：随便起，比如 "我的 OpenAI"
   - 服务商：选择对应服务商（OpenAI / DeepSeek / 通义千问 / 自定义）
   - API Key：粘贴你的密钥
   - Base URL：API 地址
   - 可用模型：填入支持的模型名

6. 保存后，在「路由策略」里设置为默认算力源

7. 完成！现在系统调用 LLM 时就会用你配置的密钥了

---

## 四、安全建议

1. **不要把密钥提交到 Git**
   - `.env` 文件已经在 `.gitignore` 里了，放心
   - 但不要把密钥写到代码里！

2. **生产环境务必修改默认密码**
   - `M8_ADMIN_PASSWORD`：管理员登录密码
   - `M8_JWT_SECRET`：JWT 签名密钥（随便来一串长的随机字符）
   - 所有 `M*_ADMIN_TOKEN`：模块间通信令牌

3. **密钥权限最小化**
   - 如果只是测试用，用额度低的 API Key
   - 定期轮换密钥

4. **本地 Ollama 不需要 API Key**
   - 如果用本地 Ollama，`LLM_API_KEY` 填 `ollama` 或随便什么都行
   - `LLM_BASE_URL` 填 `http://localhost:11434/v1`

---

## 五、常见问题

### Q1：改了 yunxi.env 怎么不生效？

**原因**：服务是启动时读取配置的，运行中改文件不会自动生效。

**解决**：重启对应的服务。如果不确定改了哪个模块，就全部重启。

### Q2：怎么验证 API 密钥配置成功了？

**方法一**：打开云汐聊天，发一句话，看能不能正常回复。

**方法二**：在 M8 管理台 → 算力调度中台 → 点击「测试连接」按钮（如果有的话）。

**方法三**：看日志，启动时会打印配置信息（注意日志里不会打印完整密钥，只会打掩码）。

### Q3：有多个 API 密钥怎么配置？

用「算力调度中台」：
1. 添加多个算力源，每个填不同的密钥
2. 在「密钥分组」里把它们归为一组
3. 在「路由策略」里选择策略：
   - 轮询：每个请求轮流用不同的 key（分摊压力）
   - 优先级：按优先级顺序，失败了自动切下一个
   - 最低延迟：自动选最快的

### Q4：M*_ADMIN_TOKEN 和 LLM_API_KEY 有什么区别？

- **LLM_API_KEY**：调用外部大模型用的，比如 OpenAI、DeepSeek 的 API 密钥，**这个是要花钱的**
- **M*_ADMIN_TOKEN**：云汐内部各模块之间通信用的，相当于内部暗号，**不花钱**，自己随便设

### Q5：本地 Ollama 还需要配置密钥吗？

不需要。本地 Ollama 不需要 API Key，配置方式：

```env
LLM_PROVIDER=ollama
LLM_API_KEY=ollama  # 随便填什么都行
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
```

---

## 六、配置文件位置速查表

| 文件 | 作用 | 重要性 |
|------|------|--------|
| `config/yunxi.env` | 全局主配置，所有模块共享 | ⭐⭐⭐ 最重要 |
| `M1-agent-hub/.env` | M1 独立配置（覆盖全局） | ⭐⭐ |
| `M2-skills-cluster/.env` | M2 独立配置 | ⭐⭐ |
| `M5-tide-memory/.env` | M5 独立配置 | ⭐⭐ |
| `M8-control-tower/backend/.env` | M8 独立配置 | ⭐⭐ |
| `M10-system-guard/.env` | M10 独立配置 | ⭐⭐ |
| `shared/core/config.py` | 全局默认值（代码里） | 一般不用改 |

> 💡 **一般规则**：先看 `config/yunxi.env`，绝大多数配置都在那里。各模块的 `.env` 文件是用来覆盖全局配置的，没有特殊需求不用管。
