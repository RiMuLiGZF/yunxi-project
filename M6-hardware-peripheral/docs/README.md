# M6 硬件外设模块 - 文档

## 模块简介

M6 硬件外设模块（Hardware Peripheral）是云汐系统的硬件接入层，负责各类智能硬件设备的发现、连接、数据采集和控制。

## 支持设备

- 智能手表（Smart Watch）
- 智能戒指（Smart Ring）
- AR 眼镜（AR Glasses）
- 桌面终端（Desktop Screen）
- 无人机（Drone）
- 笔记本电脑（Laptop）

## 目录结构

`
M6-hardware-peripheral/
├── m6_hardware/          # 主包
│   ├── api/              # API 路由层
│   ├── devices/          # 设备模拟器
│   ├── models/           # 数据模型
│   ├── realtime/         # 实时推送（SSE）
│   ├── services/         # 业务服务层
│   └── config.py         # 配置管理
├── tests/                # 单元测试
├── docs/                 # 文档
├── data/                 # 数据存储
├── server.py             # 启动入口
└── .env.example          # 环境变量示例
`

## API 接口

- GET /health - 健康检查
- GET /m8/health - M8 标准健康检查
- GET /m8/metrics - M8 标准性能指标
- GET /m8/config - M8 标准配置查询
- GET /api/v1/devices - 设备列表
- GET /api/v1/devices/stats - 设备统计
- GET /api/v1/devices/{id} - 设备详情
- GET /api/v1/sensors/latest - 最新传感器数据
- POST /api/v1/control/{device_id}/{action} - 设备控制
- GET /api/v1/realtime/stream - SSE 实时数据流

## 启动方式

`ash
cd M6-hardware-peripheral
python server.py
`

默认端口：8006

## 鉴权

业务 API 使用 M8 Token 鉴权，通过 X-M8-Token 请求头传递。
环境变量 M6_ADMIN_TOKEN 配置令牌。

## 数据存储

- 设备数据：data/devices.json
- 传感器数据：内存存储（实时流）
