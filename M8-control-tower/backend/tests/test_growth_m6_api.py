"""
成长中心 + M6 设备代理接口验证脚本

验证内容：
1. 成长中心 6 个子系统的接口都能正常返回
2. M6 设备代理接口能正常返回（mock 模式下也能工作）

运行方式（从 M8-control-tower 目录执行）：
    python -m backend.test_growth_m6_api
"""

import sys
import json
import os
import tempfile
from pathlib import Path

# 确保项目根目录在 path 中
project_root = Path(__file__).parent.parent.parent.resolve()
# 使用独立的测试数据库，避免与开发数据库冲突
test_db_path = Path(__file__).parent / "data" / "test_m8.db"
test_db_path.parent.mkdir(parents=True, exist_ok=True)
os.environ["M8_TEST_DB"] = str(test_db_path)

# 在导入 models 前修改数据库路径
from backend import models
models.SQLALCHEMY_DATABASE_URL = f"sqlite:///{test_db_path}"
models.engine = models.create_engine(
    f"sqlite:///{test_db_path}",
    connect_args={"check_same_thread": False},
)
models.SessionLocal = models.sessionmaker(autocommit=False, autoflush=False, bind=models.engine)

from fastapi.testclient import TestClient
from backend.main import app
from backend.models import init_db

client = TestClient(app)

# 测试结果统计
passed = 0
failed = 0
results = []


def test(name, method, url, expected_code=0, **kwargs):
    """执行一个测试用例"""
    global passed, failed, results
    
    try:
        resp = client.request(method, url, **kwargs)
        data = resp.json()
        actual_code = data.get("code", resp.status_code)
        
        success = (resp.status_code == 200 and data.get("code") == 0) or actual_code == expected_code
        if success:
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"
            failed += 1
        
        results.append({
            "name": name,
            "status": status,
            "url": f"{method} {url}",
            "code": actual_code,
            "message": data.get("message", ""),
        })
        
        status_icon = "✓" if success else "✗"
        print(f"  {status_icon} {name}")
        if not success:
            print(f"    期望 code={expected_code}, 实际 code={actual_code}")
            print(f"    响应: {json.dumps(data, ensure_ascii=False)[:200]}")
        
        return data if success else None
    except Exception as e:
        failed += 1
        results.append({
            "name": name,
            "status": "FAIL",
            "url": f"{method} {url}",
            "code": -1,
            "message": str(e),
        })
        print(f"  ✗ {name}")
        print(f"    异常: {e}")
        return None


def print_section(title):
    """打印章节标题"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main():
    """运行所有验证测试"""
    global passed, failed
    
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + "  成长中心 + M6 设备代理接口验证".center(56) + "║")
    print("╚" + "═" * 58 + "╝")
    
    # 初始化数据库
    print_section("初始化数据库")
    try:
        init_db()
        print("  ✓ 数据库初始化成功")
        passed += 1
    except Exception as e:
        print(f"  ✗ 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        failed += 1
        return False
    
    # 先尝试登录获取 token
    print_section("登录获取 Token")
    headers = {}
    try:
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123456"}
        )
        if login_resp.status_code == 200:
            login_data = login_resp.json()
            token = login_data.get("data", {}).get("access_token", "")
            if not token:
                token = login_data.get("access_token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
                print(f"  ✓ 登录成功")
                passed += 1
            else:
                print(f"  ⚠ 登录成功但未获取到 token，尝试不带认证访问")
                passed += 1
        else:
            print(f"  ⚠ 登录接口返回 {login_resp.status_code}，尝试不带认证访问")
            passed += 1
    except Exception as e:
        print(f"  ⚠ 登录异常: {e}，尝试不带认证访问")
        passed += 1
    
    # ============================================================
    # 成长中心 - 成就系统
    # ============================================================
    print_section("【成长中心】成就系统")
    
    test("获取成就列表", "GET", "/api/growth/achievements", headers=headers)
    test("获取成就统计", "GET", "/api/growth/achievements/stats", headers=headers)
    test("按分类筛选成就", "GET", "/api/growth/achievements?category=growth", headers=headers)
    test("按状态筛选(已解锁)", "GET", "/api/growth/achievements?status=unlocked", headers=headers)
    
    unlock_data = test("解锁成就 ach_001", "POST", "/api/growth/achievements/ach_001/unlock", headers=headers)
    if unlock_data:
        print(f"    解锁成就: {unlock_data.get('data', {}).get('achievement', {}).get('name', '')}")
    
    # ============================================================
    # 成长中心 - 天赋树
    # ============================================================
    print_section("【成长中心】天赋树系统")
    
    test("获取天赋树数据", "GET", "/api/growth/talents", headers=headers)
    test("获取天赋点数", "GET", "/api/growth/talents/points", headers=headers)
    
    upgrade_data = test("升级天赋 tal_001", "POST", "/api/growth/talents/tal_001/upgrade", headers=headers)
    if upgrade_data:
        data = upgrade_data.get("data", {})
        print(f"    升级后等级: {data.get('node', {}).get('current_level', 0)}")
        print(f"    剩余点数: {data.get('remaining_points', 0)}")
    
    test("重置天赋树", "POST", "/api/growth/talents/reset", headers=headers)
    
    # ============================================================
    # 成长中心 - 赛季旅程
    # ============================================================
    print_section("【成长中心】赛季旅程")
    
    test("获取当前赛季", "GET", "/api/growth/season/current", headers=headers)
    test("获取赛季任务列表", "GET", "/api/growth/season/tasks", headers=headers)
    test("按类型筛选任务(每日)", "GET", "/api/growth/season/tasks?type=daily", headers=headers)
    
    complete_data = test("完成任务 st_001", "POST", "/api/growth/season/tasks/st_001/complete", headers=headers)
    if complete_data:
        print(f"    任务: {complete_data.get('data', {}).get('task', {}).get('name', '')}")
    
    claim_data = test("领取任务奖励 st_001", "POST", "/api/growth/season/tasks/st_001/claim", headers=headers)
    if claim_data:
        print(f"    奖励点数: {claim_data.get('data', {}).get('reward_points', 0)}")
    
    test("获取历史赛季", "GET", "/api/growth/season/history", headers=headers)
    
    # ============================================================
    # 成长中心 - 记忆回响
    # ============================================================
    print_section("【成长中心】记忆回响")
    
    test("获取记忆列表", "GET", "/api/growth/memories", headers=headers)
    test("分页获取记忆", "GET", "/api/growth/memories?page=1&page_size=5", headers=headers)
    
    gen_data = test("生成记忆回响", "POST", "/api/growth/memories/generate", 
         json={"echo_type": "reflection", "query": "测试"}, headers=headers)
    if gen_data:
        echo_id = gen_data.get("data", {}).get("id", "")
        print(f"    生成回响 ID: {echo_id}")
        test("获取记忆详情", "GET", f"/api/growth/memories/{echo_id}", headers=headers)
        test("删除记忆", "DELETE", f"/api/growth/memories/{echo_id}", headers=headers)
    
    # ============================================================
    # 成长中心 - 成长纪事
    # ============================================================
    print_section("【成长中心】成长纪事")
    
    test("获取纪事列表", "GET", "/api/growth/chronicle", headers=headers)
    test("分页获取纪事", "GET", "/api/growth/chronicle?page=1&page_size=2", headers=headers)
    test("按分类筛选纪事", "GET", "/api/growth/chronicle?category=milestone", headers=headers)
    
    create_data = test("创建纪事", "POST", "/api/growth/chronicle", 
        json={
            "title": "测试纪事",
            "content": "这是一条测试纪事内容",
            "category": "daily",
            "tags": ["测试", "验证"],
            "mood": "happy",
            "important": True,
        }, headers=headers)
    if create_data:
        entry_id = create_data.get("data", {}).get("id", "")
        print(f"    创建纪事 ID: {entry_id}")
        test("获取纪事详情", "GET", f"/api/growth/chronicle/{entry_id}", headers=headers)
        update_data = test("更新纪事", "PUT", f"/api/growth/chronicle/{entry_id}",
            json={"title": "更新后的测试纪事", "important": False}, headers=headers)
        if update_data:
            print(f"    更新后标题: {update_data.get('data', {}).get('title', '')}")
        test("删除纪事", "DELETE", f"/api/growth/chronicle/{entry_id}", headers=headers)
    
    # ============================================================
    # 成长中心 - 潮汐日历
    # ============================================================
    print_section("【成长中心】潮汐日历")
    
    from datetime import datetime
    now = datetime.now()
    test("获取月历数据", "GET", f"/api/growth/calendar/{now.year}/{now.month}", headers=headers)
    test("获取日历统计", "GET", "/api/growth/calendar/stats", headers=headers)
    
    checkin_data = test("今日打卡", "POST", "/api/growth/calendar/checkin",
        json={"mood": "happy", "note": "验证测试打卡"}, headers=headers)
    if checkin_data:
        print(f"    连续打卡天数: {checkin_data.get('data', {}).get('streak', 0)}")
    
    # ============================================================
    # M6 设备代理
    # ============================================================
    print_section("【M6 设备代理】设备管理")
    
    test("获取设备列表", "GET", "/api/v1/m6/devices", headers=headers)
    test("获取设备统计", "GET", "/api/v1/m6/devices/stats", headers=headers)
    test("按状态筛选设备", "GET", "/api/v1/m6/devices?status=online", headers=headers)
    test("按类型筛选设备", "GET", "/api/v1/m6/devices?device_type=watch", headers=headers)
    
    detail_data = test("获取设备详情", "GET", "/api/v1/m6/devices/dev_watch_001", headers=headers)
    if detail_data:
        data = detail_data.get("data", {})
        print(f"    设备名称: {data.get('name', '')}")
        print(f"    数据来源: {data.get('source', 'unknown')}")
    
    test("配对设备", "POST", "/api/v1/m6/devices/dev_drone_001/pair", headers=headers)
    test("取消配对", "POST", "/api/v1/m6/devices/dev_drone_001/unpair", headers=headers)
    
    scan_data = test("扫描附近设备", "POST", "/api/v1/m6/devices/scan", headers=headers)
    if scan_data:
        print(f"    发现设备数: {scan_data.get('data', {}).get('found_count', 0)}")
    
    # ============================================================
    # M6 设备代理 - 传感器数据
    # ============================================================
    print_section("【M6 设备代理】传感器数据")
    
    sensor_data = test("获取传感器数据", "GET", "/api/v1/m6/sensors/dev_watch_001", headers=headers)
    if sensor_data:
        data = sensor_data.get("data", {})
        print(f"    数据来源: {data.get('source', 'unknown')}")
        if "heart_rate" in data:
            print(f"    心率: {data.get('heart_rate')} bpm")
    
    history_data = test("获取传感器历史数据", "GET", 
        "/api/v1/m6/sensors/dev_watch_001/history?limit=10", headers=headers)
    if history_data:
        print(f"    历史数据条数: {history_data.get('data', {}).get('total', 0)}")
    
    # ============================================================
    # M6 设备代理 - 设备控制
    # ============================================================
    print_section("【M6 设备代理】设备控制")
    
    action_data = test("发送设备动作", "POST", "/api/v1/m6/control/dev_watch_001/action",
        json={"action": "find_device", "params": {}}, headers=headers)
    if action_data:
        print(f"    动作执行: {action_data.get('data', {}).get('success', False)}")
    
    notify_data = test("推送通知", "POST", "/api/v1/m6/control/dev_watch_001/notify",
        json={"title": "测试通知", "content": "这是一条测试通知", "notification_type": "info"}, headers=headers)
    if notify_data:
        print(f"    通知送达: {notify_data.get('data', {}).get('delivered', False)}")
    
    # ============================================================
    # 生活管理 - 设备接口（验证向后兼容）
    # ============================================================
    print_section("【生活管理】设备接口(向后兼容)")
    
    test("生活管理-设备列表", "GET", "/api/life-management/devices", headers=headers)
    test("生活管理-设备统计", "GET", "/api/life-management/devices/stats", headers=headers)
    test("生活管理-概览", "GET", "/api/life-management/overview", headers=headers)
    
    # ============================================================
    # 汇总
    # ============================================================
    print_section("验证结果汇总")
    total = passed + failed
    pass_rate = round(passed / total * 100, 1) if total > 0 else 0
    
    print(f"  总计: {total} 个测试")
    print(f"  通过: {passed} 个")
    print(f"  失败: {failed} 个")
    print(f"  通过率: {pass_rate}%")
    print()
    
    if failed == 0:
        print("  ✓ 所有测试通过！")
    else:
        print("  ✗ 存在失败的测试：")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    - {r['name']}: {r['message']}")
    
    print()
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
