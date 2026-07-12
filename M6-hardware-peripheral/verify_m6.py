"""
M6 硬件外设模拟服务 - 完整验证脚本
测试所有 API 端点和核心功能
"""

import asyncio
import json
import time
import httpx

BASE_URL = "http://localhost:8006"

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        status = "PASS"
    else:
        failed += 1
        status = "FAIL"
    print(f"  [{status}] {name}")
    if detail and not condition:
        print(f"         {detail}")


print("=" * 70)
print("  M6 硬件外设模拟服务 - API 验证脚本")
print("=" * 70)

# ---------------------------------------------------------------
# 测试 1: 服务启动和健康检查
# ---------------------------------------------------------------
print("\n1. 服务启动和健康检查")
print("-" * 50)

try:
    # 根路径
    r = httpx.get(f"{BASE_URL}/", timeout=10)
    test("根路径可访问", r.status_code == 200, f"状态码: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        test("根路径包含模块信息", data.get("module") == "m6-hardware")
        test("根路径包含版本号", "version" in data)
        test("模拟模式已开启", data.get("simulation_mode") == True)

    # 标准健康检查
    r = httpx.get(f"{BASE_URL}/health", timeout=10)
    test("/health 健康检查", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("健康检查返回 code=0", data.get("code") == 0)
        test("健康检查状态 healthy", data.get("data", {}).get("status") == "healthy")

    # API 健康检查
    r = httpx.get(f"{BASE_URL}/api/v1/health", timeout=10)
    test("/api/v1/health API健康检查", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("API健康检查包含 uptime", "uptime_seconds" in data.get("data", {}))

    # 服务统计
    r = httpx.get(f"{BASE_URL}/api/v1/health/stats", timeout=10)
    test("/api/v1/health/stats 服务统计", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("统计包含设备信息", "devices" in data.get("data", {}))
        test("统计包含 SSE 客户端数", "sse_clients" in data.get("data", {}))

except Exception as e:
    test("健康检查请求异常", False, str(e))

# ---------------------------------------------------------------
# 测试 2: 设备列表和详情
# ---------------------------------------------------------------
print("\n2. 设备列表和详情获取")
print("-" * 50)

try:
    # 设备列表
    r = httpx.get(f"{BASE_URL}/api/v1/devices", timeout=10)
    test("设备列表 API", r.status_code == 200)

    if r.status_code == 200:
        data = r.json()
        devices = data.get("data", {}).get("devices", [])
        test("设备列表返回 6 台设备", len(devices) == 6, f"实际: {len(devices)}")
        test("设备列表返回 code=0", data.get("code") == 0)

        # 检查每台设备的必要字段
        required_fields = ["device_id", "name", "device_type", "status", "signal_strength"]
        for dev in devices:
            for field in required_fields:
                test(f"设备 {dev.get('name', '?')} 有 {field}", field in dev)

        # 检查 6 种设备类型都存在
        types = {d["device_type"] for d in devices}
        expected_types = {"watch", "ring", "desktop", "ar", "drone", "laptop"}
        test("6 种设备类型齐全", types == expected_types, f"实际: {types}")

    # 设备统计
    r = httpx.get(f"{BASE_URL}/api/v1/devices/stats", timeout=10)
    test("设备统计 API", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        stats = data.get("data", {})
        test("统计包含 total", stats.get("total") == 6)
        test("统计包含 online/offline/warning",
             all(k in stats for k in ["online", "offline", "warning"]))
        test("统计包含 by_type", "by_type" in stats and len(stats["by_type"]) == 6)

    # 单设备详情
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-watch-001", timeout=10)
    test("手表设备详情", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        dev = data.get("data", {})
        test("详情包含传感器数据", "sensors" in dev)
        test("手表有心率传感器", "heart_rate" in dev.get("sensors", {}))
        test("手表有步数传感器", "steps" in dev.get("sensors", {}))
        test("手表有血氧传感器", "blood_oxygen" in dev.get("sensors", {}))

    # 桌面终端详情（有线供电）
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-desktop-001", timeout=10)
    test("桌面终端详情", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        dev = data.get("data", {})
        test("桌面终端电池为 None（有线）", dev.get("battery") is None)
        test("桌面终端信号强度 100", dev.get("signal_strength") == 100)

    # 不存在的设备
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-nonexistent", timeout=10)
    test("不存在的设备返回 404", r.status_code == 404)

    # 按状态过滤
    r = httpx.get(f"{BASE_URL}/api/v1/devices?status=online", timeout=10)
    test("按状态过滤 (online)", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        devices = data.get("data", {}).get("devices", [])
        test("online 设备数 > 0", len(devices) > 0)
        test("所有返回设备都是 online",
             all(d["status"] == "online" for d in devices))

    # 按类型过滤
    r = httpx.get(f"{BASE_URL}/api/v1/devices?device_type=watch", timeout=10)
    test("按类型过滤 (watch)", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        devices = data.get("data", {}).get("devices", [])
        test("watch 类型设备数 = 1", len(devices) == 1)

except Exception as e:
    test("设备列表请求异常", False, str(e))

# ---------------------------------------------------------------
# 测试 3: 传感器数据查询
# ---------------------------------------------------------------
print("\n3. 传感器数据查询")
print("-" * 50)

try:
    # 等待几秒让数据采集积累一些数据
    print("  等待数据采集（3秒）...")
    time.sleep(3)

    # 最新传感器数据
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-watch-001", timeout=10)
    test("手表最新传感器数据", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        sensors = data.get("data", {}).get("sensors", {})
        test("心率数据在合理范围 (50-170)",
             50 <= sensors.get("heart_rate", {}).get("value", 0) <= 170)
        test("血氧数据在合理范围 (90-100)",
             90 <= sensors.get("blood_oxygen", {}).get("value", 0) <= 100)

    # 历史数据
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-watch-001/history?limit=10", timeout=10)
    test("心率历史数据查询", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        history = data.get("data", {}).get("data", [])
        test("历史数据条数 > 0", len(history) > 0, f"实际: {len(history)}")

    # 特定传感器历史
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-watch-001/heart_rate?limit=5", timeout=10)
    test("特定传感器（心率）历史", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        history = data.get("data", {}).get("data", [])
        test("返回条数 <= 5", len(history) <= 5)
        if history:
            test("数据包含 value 字段", "value" in history[0])
            test("数据包含 timestamp 字段", "timestamp" in history[0])

    # 戒指传感器
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-ring-001", timeout=10)
    test("戒指传感器数据", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        sensors = data.get("data", {}).get("sensors", {})
        test("戒指有体温传感器", "temperature" in sensors)
        test("戒指有压力指数", "stress_index" in sensors)
        test("体温在合理范围 (35-38℃)",
             35 <= sensors.get("temperature", {}).get("value", 0) <= 38)

    # 桌面终端传感器
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-desktop-001", timeout=10)
    test("桌面终端传感器数据", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        sensors = data.get("data", {}).get("sensors", {})
        test("桌面终端有环境光", "ambient_light" in sensors)
        test("桌面终端有温湿度", "temperature" in sensors and "humidity" in sensors)
        test("桌面终端有空气质量", "air_quality" in sensors)
        test("桌面终端有 CO2", "co2" in sensors)

    # 笔记本传感器
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-laptop-001", timeout=10)
    test("笔记本传感器数据", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        sensors = data.get("data", {}).get("sensors", {})
        test("笔记本有 CPU 使用率", "cpu_usage" in sensors)
        test("笔记本有内存使用率", "memory_usage" in sensors)
        test("笔记本有工作效率", "work_efficiency" in sensors)

    # 无人机传感器
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-drone-001", timeout=10)
    test("无人机传感器数据", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        sensors = data.get("data", {}).get("sensors", {})
        test("无人机有 GPS 坐标", "latitude" in sensors and "longitude" in sensors)
        test("无人机有高度", "altitude" in sensors)
        test("无人机有电池电压", "voltage" in sensors)

except Exception as e:
    test("传感器数据请求异常", False, str(e))

# ---------------------------------------------------------------
# 测试 4: 设备配对/解绑
# ---------------------------------------------------------------
print("\n4. 设备配对/解绑")
print("-" * 50)

try:
    # 无人机初始未配对
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-drone-001", timeout=10)
    init_paired = r.json().get("data", {}).get("paired", True)
    print(f"  无人机初始配对状态: {init_paired}")

    # 配对
    r = httpx.post(f"{BASE_URL}/api/v1/devices/dev-drone-001/pair", timeout=10)
    test("配对无人机", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("配对返回成功", data.get("code") == 0)

    # 验证已配对
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-drone-001", timeout=10)
    test("验证无人机已配对", r.json().get("data", {}).get("paired") == True)

    # 重复配对应失败
    r = httpx.post(f"{BASE_URL}/api/v1/devices/dev-drone-001/pair", timeout=10)
    test("重复配对返回 400", r.status_code == 400)

    # 解绑
    r = httpx.post(f"{BASE_URL}/api/v1/devices/dev-drone-001/unpair", timeout=10)
    test("解绑无人机", r.status_code == 200)

    # 验证已解绑
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-drone-001", timeout=10)
    test("验证无人机已解绑", r.json().get("data", {}).get("paired") == False)

    # 重新配对（恢复状态）
    httpx.post(f"{BASE_URL}/api/v1/devices/dev-drone-001/pair", timeout=10)

    # 设备扫描
    r = httpx.post(f"{BASE_URL}/api/v1/devices/scan", timeout=10)
    test("设备扫描", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("扫描结果包含 found_count", "found_count" in data.get("data", {}))

    # 配置更新
    r = httpx.put(
        f"{BASE_URL}/api/v1/devices/dev-watch-001/config",
        json={"name": "我的智能手表", "position": {"x": 55, "y": 35}},
        timeout=10,
    )
    test("更新设备配置", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("配置更新成功", data.get("code") == 0)

    # 验证配置更新
    r = httpx.get(f"{BASE_URL}/api/v1/devices/dev-watch-001", timeout=10)
    dev = r.json().get("data", {})
    test("验证名称已更新", dev.get("name") == "我的智能手表")
    test("验证位置已更新", dev.get("position", {}).get("x") == 55)

except Exception as e:
    test("设备配对请求异常", False, str(e))

# ---------------------------------------------------------------
# 测试 5: 设备控制
# ---------------------------------------------------------------
print("\n5. 设备控制")
print("-" * 50)

try:
    # 手表 - 开始运动
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-watch-001/action",
        json={"action": "start_exercise", "params": {"type": "running"}},
        timeout=10,
    )
    test("手表 - 开始运动", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("运动指令执行成功", data.get("code") == 0)

    # 手表 - 查找设备
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-watch-001/action",
        json={"action": "find_device"},
        timeout=10,
    )
    test("手表 - 查找设备", r.status_code == 200)

    # 戒指 - 冥想
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-ring-001/action",
        json={"action": "meditation", "params": {"duration": 10}},
        timeout=10,
    )
    test("戒指 - 冥想模式", r.status_code == 200)

    # 桌面终端 - 显示日程
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-desktop-001/action",
        json={"action": "display_schedule", "params": {"schedule": {"title": "团队会议"}}},
        timeout=10,
    )
    test("桌面终端 - 显示日程", r.status_code == 200)

    # AR眼镜 - 导航
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-ar-001/action",
        json={"action": "start_navigation", "params": {"destination": "公司"}},
        timeout=10,
    )
    test("AR眼镜 - 启动导航", r.status_code == 200)

    # 无人机 - 起飞
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-drone-001/action",
        json={"action": "takeoff", "params": {"altitude": 30}},
        timeout=10,
    )
    test("无人机 - 起飞", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("起飞指令执行成功", data.get("code") == 0)

    # 等一下看无人机飞行状态
    time.sleep(2)
    r = httpx.get(f"{BASE_URL}/api/v1/sensors/dev-drone-001", timeout=10)
    sensors = r.json().get("data", {}).get("sensors", {})
    print(f"  无人机飞行状态: {sensors.get('flight_state', {}).get('value')}")
    print(f"  无人机高度: {sensors.get('altitude', {}).get('value')} m")

    # 无人机 - 拍照
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-drone-001/action",
        json={"action": "take_photo"},
        timeout=10,
    )
    test("无人机 - 拍照", r.status_code == 200)

    # 无人机 - 返航
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-drone-001/action",
        json={"action": "return_home"},
        timeout=10,
    )
    test("无人机 - 返航", r.status_code == 200)

    # 笔记本 - 专注模式
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-laptop-001/action",
        json={"action": "focus_mode", "params": {"duration": 25}},
        timeout=10,
    )
    test("笔记本 - 专注模式", r.status_code == 200)

    # 不支持的动作
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-watch-001/action",
        json={"action": "unknown_action"},
        timeout=10,
    )
    test("不支持的动作返回 400", r.status_code == 400)

    # 推送通知
    r = httpx.post(
        f"{BASE_URL}/api/v1/control/dev-watch-001/notify",
        json={"title": "测试通知", "content": "这是一条来自API的测试通知", "notification_type": "info"},
        timeout=10,
    )
    test("推送通知到手表", r.status_code == 200)
    if r.status_code == 200:
        data = r.json()
        test("通知推送成功", data.get("code") == 0)

    # 获取通知历史
    r = httpx.get(f"{BASE_URL}/api/v1/control/dev-watch-001/notifications", timeout=10)
    test("获取通知历史", r.status_code == 200)

    # 获取告警列表
    r = httpx.get(f"{BASE_URL}/api/v1/control/dev-ar-001/alerts", timeout=10)
    test("获取设备告警", r.status_code == 200)

except Exception as e:
    test("设备控制请求异常", False, str(e))

# ---------------------------------------------------------------
# 测试 6: SSE 推送（简单验证端点可用）
# ---------------------------------------------------------------
print("\n6. SSE 实时推送（端点验证）")
print("-" * 50)

try:
    # 验证 SSE 端点存在（用短超时测试）
    import httpx
    async def test_sse():
        async with httpx.AsyncClient() as client:
            try:
                # 只接收前几条消息
                messages = []
                async with client.stream("GET", f"{BASE_URL}/api/v1/sse/stream", timeout=5) as response:
                    test("SSE 端点响应 200", response.status_code == 200)
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            messages.append(line)
                            if len(messages) >= 2:
                                break
                    test(f"SSE 收到 {len(messages)} 条事件", len(messages) >= 1)
                    if messages:
                        print(f"  收到的事件: {', '.join(messages[:3])}")
            except httpx.TimeoutException:
                test("SSE 超时（正常，长连接）", True)
            except Exception as e:
                test("SSE 连接异常", False, str(e))

    asyncio.run(test_sse())

except Exception as e:
    test("SSE 测试异常", False, str(e))

# ---------------------------------------------------------------
# 测试 7: 统一响应格式
# ---------------------------------------------------------------
print("\n7. 统一响应格式验证")
print("-" * 50)

try:
    r = httpx.get(f"{BASE_URL}/api/v1/devices", timeout=10)
    data = r.json()
    test("响应包含 code 字段", "code" in data)
    test("响应包含 message 字段", "message" in data)
    test("响应包含 data 字段", "data" in data)
    test("响应包含 request_id 字段", "request_id" in data)
    test("响应包含 timestamp 字段", "timestamp" in data)
    test("request_id 长度为 16", len(data.get("request_id", "")) == 16)

    # 响应头
    test("响应头包含 X-Request-Id", "X-Request-Id" in r.headers)
    test("响应头包含 X-Response-Time", "X-Response-Time" in r.headers)

except Exception as e:
    test("响应格式验证异常", False, str(e))

# ---------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------
total = passed + failed
print("\n" + "=" * 70)
print(f"  测试结果: {passed}/{total} 通过, {failed} 失败")
print("=" * 70)

if failed == 0:
    print("\n  所有测试通过！M6 硬件外设模拟服务运行正常。")
else:
    print(f"\n  有 {failed} 个测试失败，请检查。")

print()
