# M0 主理人管控台 (Principal Console)

> 云汐系统的「舰长室」——主理人的专属工作台，最高权限，可以俯视和操控整个云汐系统。

## 定位

M0 是云汐系统的最高管控节点，仅对主理人（Owner）开放。
从这里可以俯视所有模块状态、管理全局配置、执行紧急操作、审计系统行为。

## 技术栈

- **后端**: FastAPI + SQLite
- **前端**: 纯 HTML/CSS/JS（深色科技感主题）
- **认证**: 复用 M8 JWT 认证体系，增加 Owner 角色校验
- **端口**: 8010

## 目录结构

```
M0-principal-console/
├── server.py                    # 启动入口
├── requirements.txt             # 依赖
├── config.example.yaml          # 配置示例
├── data/                        # 数据目录
├── src/
│   ├── main.py                  # FastAPI 应用创建 + 路由注册
│   ├── config.py                # 配置管理
│   ├── models.py                # 数据模型（Pydantic）
│   ├── database.py              # SQLite 数据库连接
│   ├── errors.py                # 错误处理
│   ├── auth.py                  # 认证（JWT + Owner校验）
│   ├── routers/                 # 路由层
│   │   ├── dashboard.py         # 仪表盘
│   │   ├── modules.py           # 模块配置管理
│   │   ├── config.py            # 全局配置中心
│   │   ├── access_control.py    # 权限与角色管理
│   │   ├── audit.py             # 审计日志
│   │   ├── upgrade.py           # 系统升级与回滚
│   │   ├── emergency.py         # 紧急操作中心
│   │   └── principal_tools.py   # 主理人专属工具
│   ├── services/                # 服务层
│   │   ├── m8_client.py         # M8 API 客户端
│   │   └── config_service.py    # 配置服务
│   └── m8_api/                  # M8 标准对接
│       ├── health_endpoints.py  # 健康检查
│       └── m8_auth_middleware.py # M8 认证中间件
├── frontend/                    # 前端页面
│   ├── index.html               # 入口重定向
│   ├── login.html               # 登录页
│   ├── dashboard.html           # 全局仪表盘
│   ├── modules.html             # 模块管理
│   ├── config.html              # 全局配置
│   ├── access.html              # 权限管理
│   ├── audit.html               # 审计日志
│   ├── upgrade.html             # 系统升级
│   ├── emergency.html           # 紧急操作
│   └── common/style.css         # 公共样式
└── tests/                       # 测试
    └── test_basic.py
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置
cp config.example.yaml config.yaml

# 启动服务
python server.py
```

访问 http://localhost:8010 ，使用主理人账号登录。

## MVP 功能

- [x] 系统健康检查
- [x] JWT 认证 + Owner 角色校验
- [x] 全局仪表盘（模块状态 / 系统资源 / 告警 / 版本等）
- [x] 模块管理（列表 + 详情，调用 M8 接口）
- [x] 全局配置中心（读取 + 更新）
- [x] 权限管理页面骨架
- [x] 审计日志页面骨架
- [x] 系统升级页面骨架
- [x] 紧急操作中心骨架
- [x] 主理人专属工具骨架

## 与 M8 的关系

M0 通过 HTTP 调用 M8 的管理接口获取数据和下发指令。
M8 未启动时，M0 提供 fallback mock 数据，保证界面可用。

- M8 默认地址: `http://localhost:8000`
- M0 端口: `8010`
