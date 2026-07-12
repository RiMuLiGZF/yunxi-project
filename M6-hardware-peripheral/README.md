# M6 穿戴硬件外设 (Hardware Peripheral)

**模块代号**：M6
**模块名称**：穿戴硬件外设
**版本**：v1.0.0
**端口**：8006
**技术栈**：FastAPI + SSE 实时推送 + 设备模拟器

---

## 一、模块概述

M6 穿戴硬件外设模块是云汐系统的硬件接入层，负责管理各类穿戴设备和物联网硬件，提供设备发现、状态监控、数据采集、远程控制等能力。当前版本以模拟器模式运行，支持 6 种设备类型的模拟。

### 核心能力

| 能力 | 说明 |
|------|------|
| **多设备管理** | 支持智能手表、智能戒指、AR眼镜、桌面屏、无人机、笔记本电脑 6 种设备 |
| **实时数据推送** | SSE 实时流推送传感器数据 |
| **设备模拟器** | 完整的设备行为模拟，支持心率/血氧/步数等生理数据 |
| **远程控制** | 设备动作指令、通知推送、配置更新 |
| **M8 标准对接** | 完整实现 /m8/health、/m8/metrics、/m8/config |

---

## 二、目录结构

```
M6-hardware-peripheral/
├── server.py              # 服务启动入口
├── requirements.txt       # 依赖列表
├── .env.example           # 配置示例
├── README.md              # 本文件
└── m6_hardware/           # 核心代码包
    ├── __init__.py
    └── config.py          # 配置管理
```

> 注：当前版本核心代码在 server.py 中，后续将逐步拆分为独立模块。

---

## 三、支持设备

| 设备类型 | 设备ID前缀 | 传感器 | 控制能力 |
|----------|-----------|--------|----------|
| 智能手表 | `watch_` | 心率、血氧、步数、睡眠、体温 | 通知、震动、闹钟 |
| 智能戒指 | `ring_` | 心率、血氧、体温、睡眠 | 查找设备 |
| AR眼镜 | `glass_` | 姿态、亮度、电池 | 显示内容、拍照 |
| 桌面屏 | `desktop_` | 环境光、温湿度 | 显示内容、亮度调节 |
| 无人机 | `drone_` | GPS、高度、电池 | 起飞/降落、返航、拍照 |
| 笔记本 | `laptop_` | CPU、内存、电池 | 锁屏、通知 |

---

## 四、配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `M6_HOST` | `0.0.0.0` | 监听地址 |
| `M6_PORT` | `8006` | 监听端口 |
| `M6_ENV` | `development` | 运行环境 |
| `M6_SIMULATION_MODE` | `true` | 模拟器模式 |
| `M6_ADMIN_TOKEN` | `""` | M8 对接管理 Token |
| `M6_DATA_RETENTION_DAYS` | `7` | 传感器数据保留天数 |
| `M6_SCAN_INTERVAL` | `5` | 设备扫描间隔（秒） |

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py

# 健康检查
curl http://localhost:8006/health

# API 文档
http://localhost:8006/docs
```

---

## 五、API 接口

### 5.1 M8 标准接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/m8/health` | GET | M8 标准健康检查 |
| `/m8/metrics` | GET | M8 标准性能指标 |
| `/m8/config` | GET | M8 标准配置查询 |

### 5.2 设备管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/devices` | GET | 获取设备列表 |
| `/api/v1/devices/{device_id}` | GET | 获取设备详情 |
| `/api/v1/devices/stats` | GET | 设备统计信息 |
| `/api/v1/devices/types` | GET | 支持的设备类型列表 |
| `/api/v1/devices/scan` | POST | 扫描新设备 |
| `/api/v1/devices/{device_id}/pair` | POST | 配对设备 |
| `/api/v1/devices/{device_id}/unpair` | POST | 取消配对 |
| `/api/v1/devices/{device_id}/config` | PUT | 更新设备配置 |

### 5.3 传感器数据

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/sensors/{device_id}/latest` | GET | 获取最新传感器数据 |
| `/api/v1/sensors/{device_id}/history` | GET | 获取历史传感器数据 |
| `/api/v1/sensors/stream` | GET | SSE 实时数据流 |

### 5.4 设备控制

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/control/{device_id}/action` | POST | 发送动作指令 |
| `/api/v1/control/{device_id}/notify` | POST | 推送通知 |

---

## 六、SSE 实时数据流

客户端可以通过 SSE 接口接收实时传感器数据：

```javascript
const eventSource = new EventSource('http://localhost:8006/api/v1/sensors/stream');
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('传感器数据:', data);
};
```

---

## 七、测试

```bash
# 运行验证脚本
python verify_m6.py
```

---

## 八、与其他模块关系

- **上游**：M8 管理台通过 M8 标准接口纳管 M6
- **下游**：M6 向上层业务模块（如成长中心、健康监测）提供设备数据
- **前端**：手表端 H5 页面通过 M6 API 交互
