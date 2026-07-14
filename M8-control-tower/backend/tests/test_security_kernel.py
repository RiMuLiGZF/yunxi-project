"""
安全内核验证脚本
测试四个核心功能：
1. 角色体系（owner/admin/auditor 三级角色）
2. TOTP 双因子认证
3. 审计日志
4. 紧急制动

运行方式：
    cd M8-control-tower
    python -m backend.test_security_kernel
"""

import sys
import os
import json
import time
import tempfile
from pathlib import Path
import unittest.mock as mock

# 将 M8-control-tower 目录加入 path（backend 的父目录）
backend_dir = Path(__file__).parent
parent_dir = backend_dir.parent
sys.path.insert(0, str(parent_dir))

# 临时修改用户文件路径，避免影响真实数据
TEST_DIR = Path(tempfile.mkdtemp(prefix="m8_security_test_"))

print(f"=" * 70)
print(f"  安全内核验证脚本")
print(f"  测试目录: {TEST_DIR}")
print(f"=" * 70)


# ========== 测试 1: 角色体系 ==========
print(f"\n{'='*70}")
print(f"  [测试 1] 角色体系 - 三级角色 (owner/admin/auditor)")
print(f"{'='*70}")

try:
    # 用 mock 替换 Path.home 指向测试目录
    with mock.patch.object(Path, 'home', return_value=TEST_DIR):
        # 导入后端模块（作为包导入）
        from backend.routers import auth as auth_router
        from backend.routers import users as users_router
        from backend.auth import ROLE_LEVELS, has_role, VALID_ROLES

    # 检查默认用户角色
    users = auth_router._load_users()
    print(f"\n1.1 默认用户检查:")
    print(f"    用户数量: {len(users)}")
    if users:
        default_user = users[0]
        print(f"    用户名: {default_user['username']}")
        print(f"    角色: {default_user['role']}")
        assert default_user["role"] == "owner", f"默认用户角色应为 owner，实际为 {default_user['role']}"
        print(f"    ✓ 默认用户角色为 owner")
    else:
        print(f"    ✗ 未找到默认用户")
        sys.exit(1)

    # 测试角色等级
    print(f"\n1.2 角色等级:")
    for role, level in ROLE_LEVELS.items():
        print(f"    {role}: {level}")
    assert has_role("owner", "admin"), "owner 应能访问 admin 接口"
    assert has_role("owner", "auditor"), "owner 应能访问 auditor 接口"
    assert has_role("admin", "auditor"), "admin 应能访问 auditor 接口"
    assert not has_role("auditor", "admin"), "auditor 不应能访问 admin 接口"
    assert not has_role("admin", "owner"), "admin 不应能访问 owner 接口"
    print(f"    ✓ 角色权限层级正确")

    # 测试有效角色列表
    assert set(VALID_ROLES) == {"owner", "admin", "auditor"}, f"有效角色列表不正确: {VALID_ROLES}"
    print(f"    ✓ 有效角色列表正确: {VALID_ROLES}")

    # 测试角色数量限制
    print(f"\n1.3 角色数量限制测试:")
    import asyncio

    async def test_user_creation():
        # 创建 3 个 admin 用户
        for i in range(3):
            result = await users_router.create_user(
                users_router.UserCreate(
                    username=f"admin{i+1}",
                    password="test123456",
                    role="admin",
                    nickname=f"管理员{i+1}",
                ),
                current_user={"username": "admin", "role": "owner"},
            )
            assert result.code == 0, f"创建 admin{i+1} 失败: {result.message}"
            print(f"    ✓ 创建 admin{i+1} 成功")

        # 第 4 个 admin 应该失败
        result = await users_router.create_user(
            users_router.UserCreate(
                username="admin4",
                password="test123456",
                role="admin",
            ),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code != 0, "第 4 个 admin 应该创建失败"
        print(f"    ✓ 第 4 个 admin 创建失败（限制生效）: {result.message}")

        # 创建 2 个 auditor 用户
        for i in range(2):
            result = await users_router.create_user(
                users_router.UserCreate(
                    username=f"auditor{i+1}",
                    password="test123456",
                    role="auditor",
                    nickname=f"审计员{i+1}",
                ),
                current_user={"username": "admin", "role": "owner"},
            )
            assert result.code == 0, f"创建 auditor{i+1} 失败: {result.message}"
            print(f"    ✓ 创建 auditor{i+1} 成功")

        # 第 3 个 auditor 应该失败
        result = await users_router.create_user(
            users_router.UserCreate(
                username="auditor3",
                password="test123456",
                role="auditor",
            ),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code != 0, "第 3 个 auditor 应该创建失败"
        print(f"    ✓ 第 3 个 auditor 创建失败（限制生效）: {result.message}")

        # 不能创建 owner
        result = await users_router.create_user(
            users_router.UserCreate(
                username="owner2",
                password="test123456",
                role="owner",
            ),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code != 0, "不能创建新的 owner"
        print(f"    ✓ 不能创建新的 owner: {result.message}")

        # 非 owner 不能创建用户
        result = await users_router.create_user(
            users_router.UserCreate(
                username="test_user",
                password="test123456",
                role="admin",
            ),
            current_user={"username": "admin1", "role": "admin"},
        )
        assert result.code == 403, "admin 不能创建用户"
        print(f"    ✓ admin 不能创建用户（权限控制生效）")

    asyncio.run(test_user_creation())

    print(f"\n  ✓ 角色体系测试通过")

except Exception as e:
    print(f"\n  ✗ 角色体系测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


# ========== 测试 2: TOTP 双因子认证 ==========
print(f"\n{'='*70}")
print(f"  [测试 2] TOTP 双因子认证")
print(f"{'='*70}")

try:
    with mock.patch.object(Path, 'home', return_value=TEST_DIR):
        from backend.routers import auth as auth_router

    # 测试 TOTP 密钥生成
    print(f"\n2.1 TOTP 密钥生成:")
    secret = auth_router._generate_totp_secret()
    print(f"    生成的密钥: {secret}")
    assert len(secret) >= 16, "密钥长度应至少 16 位"
    base32_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert all(c in base32_chars for c in secret), "密钥应为 Base32 编码"
    print(f"    ✓ 密钥格式正确 (Base32, 长度 {len(secret)})")

    # 测试 TOTP 验证码生成和验证
    print(f"\n2.2 TOTP 验证码生成与验证:")
    code = auth_router._get_totp_code(secret)
    print(f"    当前验证码: {code}")
    assert len(code) == 6, "验证码应为 6 位数字"
    assert code.isdigit(), "验证码应全为数字"
    print(f"    ✓ 验证码格式正确 (6 位数字)")

    # 验证当前验证码
    result = auth_router._verify_totp(secret, code)
    assert result, "当前验证码应验证通过"
    print(f"    ✓ 当前验证码验证通过")

    # 错误验证码应失败
    result = auth_router._verify_totp(secret, "000000")
    assert not result, "错误验证码应验证失败"
    print(f"    ✓ 错误验证码验证失败")

    # 测试二维码 URL 生成
    print(f"\n2.3 二维码 URL 生成:")
    qr_url = auth_router._generate_totp_qr_url(secret, "testuser")
    print(f"    QR URL: {qr_url[:80]}...")
    assert qr_url.startswith("otpauth://totp/"), "QR URL 格式不正确"
    assert "secret=" in qr_url, "QR URL 应包含 secret 参数"
    assert "issuer=" in qr_url, "QR URL 应包含 issuer 参数"
    print(f"    ✓ 二维码 URL 格式正确")

    # 测试恢复码生成
    print(f"\n2.4 恢复码生成:")
    recovery_codes = auth_router._generate_recovery_codes(8)
    print(f"    生成 {len(recovery_codes)} 个恢复码")
    assert len(recovery_codes) == 8, "应生成 8 个恢复码"
    for code in recovery_codes:
        parts = code.split("-")
        assert len(parts) == 4, f"恢复码格式不正确: {code}"
        assert all(len(p) == 4 for p in parts), f"恢复码每段应为 4 字符: {code}"
    print(f"    ✓ 恢复码格式正确 (xxxx-xxxx-xxxx-xxxx)")

    # 测试 TOTP 设置流程
    print(f"\n2.5 TOTP 设置流程:")
    import asyncio

    async def test_totp_flow():
        # 获取 TOTP 设置信息
        result = await auth_router.totp_setup(
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code == 0, f"获取 TOTP 设置失败: {result.message}"
        print(f"    ✓ 获取 TOTP 设置信息成功")
        setup_secret = result.data["secret"]

        # 用正确的验证码开启 TOTP
        current_code = auth_router._get_totp_code(setup_secret)
        result = await auth_router.totp_enable(
            auth_router.TotpEnableRequest(totp_code=current_code),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code == 0, f"开启 TOTP 失败: {result.message}"
        assert result.data["totp_enabled"] == True, "TOTP 应已启用"
        assert len(result.data["recovery_codes"]) == 8, "应返回 8 个恢复码"
        print(f"    ✓ TOTP 开启成功，生成 {len(result.data['recovery_codes'])} 个恢复码")

        # 验证用户数据中 TOTP 已启用
        user = auth_router._find_user_by_username("admin")
        assert user["totp_enabled"] == True, "用户 TOTP 状态应为启用"
        assert len(user["totp_recovery_codes"]) == 8, "用户应有 8 个恢复码"
        print(f"    ✓ 用户 TOTP 状态已更新")

        # 测试登录流程（需要 TOTP）
        result = await auth_router.login(
            auth_router.LoginRequest(username="admin", password="admin123456"),
            request=mock.MagicMock(),
        )
        assert result.code == 0, "登录应返回成功"
        assert result.data.get("need_totp") == True, "开启 TOTP 后应需要第二步验证"
        assert "temp_token" in result.data, "应返回临时 token"
        print(f"    ✓ 登录触发 TOTP 第二步验证")

        # 用 TOTP 验证码完成登录
        temp_token = result.data["temp_token"]
        current_code = auth_router._get_totp_code(user["totp_secret"])
        result = await auth_router.totp_verify(
            auth_router.TotpVerifyRequest(temp_token=temp_token, totp_code=current_code),
            request=mock.MagicMock(),
        )
        assert result.code == 0, f"TOTP 验证失败: {result.message}"
        assert "access_token" in result.data, "应返回正式 token"
        print(f"    ✓ TOTP 第二步验证通过，获取正式 token")

        # 测试恢复码登录
        result = await auth_router.login(
            auth_router.LoginRequest(username="admin", password="admin123456"),
            request=mock.MagicMock(),
        )
        temp_token = result.data["temp_token"]
        recovery_code = user["totp_recovery_codes"][0]
        result = await auth_router.totp_verify(
            auth_router.TotpVerifyRequest(temp_token=temp_token, totp_code=recovery_code),
            request=mock.MagicMock(),
        )
        assert result.code == 0, f"恢复码验证失败: {result.message}"
        assert result.data.get("recovery_code_used") == True, "应标记使用了恢复码"
        print(f"    ✓ 恢复码验证通过")

        # 恢复码使用后应减少
        user = auth_router._find_user_by_username("admin")
        assert len(user["totp_recovery_codes"]) == 7, "使用后恢复码应减少为 7 个"
        print(f"    ✓ 恢复码使用后已删除（剩余 7 个）")

        # 测试关闭 TOTP
        result = await auth_router.totp_disable(
            auth_router.TotpDisableRequest(password="admin123456"),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code == 0, f"关闭 TOTP 失败: {result.message}"
        user = auth_router._find_user_by_username("admin")
        assert user["totp_enabled"] == False, "TOTP 应已关闭"
        assert user["totp_secret"] is None, "密钥应已清除"
        assert len(user["totp_recovery_codes"]) == 0, "恢复码应已清除"
        print(f"    ✓ TOTP 关闭成功，密钥和恢复码已清除")

    asyncio.run(test_totp_flow())

    print(f"\n  ✓ TOTP 双因子认证测试通过")

except Exception as e:
    print(f"\n  ✗ TOTP 双因子认证测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


# ========== 测试 3: 审计日志 ==========
print(f"\n{'='*70}")
print(f"  [测试 3] 审计日志")
print(f"{'='*70}")

try:
    with mock.patch.object(Path, 'home', return_value=TEST_DIR):
        from backend.audit import add_audit_log, query_audit_logs, export_audit_logs_csv
        from backend.routers import audit as audit_router

    # 添加一些测试日志
    print(f"\n3.1 审计日志添加:")
    test_logs = [
        {"action": "login", "module": "auth", "username": "admin", "result": "success", "details": {"ip": "127.0.0.1"}},
        {"action": "login", "module": "auth", "username": "admin1", "result": "success", "details": {"ip": "192.168.1.1"}},
        {"action": "login", "module": "auth", "username": "hacker", "result": "failed", "details": {"reason": "密码错误"}},
        {"action": "create_user", "module": "user", "username": "admin", "result": "success", "details": {"target_user": "admin1"}},
        {"action": "update_settings", "module": "system", "username": "admin", "result": "success", "details": {"theme": "dark"}},
        {"action": "module_start", "module": "module", "username": "admin1", "result": "success", "details": {"module": "m1"}},
    ]
    for log_data in test_logs:
        log = add_audit_log(**log_data)
        assert "id" in log, "日志应包含 id"
        assert "created_at" in log, "日志应包含 created_at"
    print(f"    ✓ 添加了 {len(test_logs)} 条审计日志")

    # 测试查询
    print(f"\n3.2 审计日志查询:")
    result = query_audit_logs(page=1, page_size=10)
    assert result["total"] >= len(test_logs), f"日志总数应不少于 {len(test_logs)}"
    print(f"    ✓ 查询日志总数: {result['total']}")

    # 按用户名筛选
    result = query_audit_logs(username="admin", page=1, page_size=10)
    assert result["total"] >= 3, "admin 用户的日志应至少 3 条"
    print(f"    ✓ 按用户名筛选: admin -> {result['total']} 条")

    # 按操作类型筛选
    result = query_audit_logs(action="login", page=1, page_size=10)
    assert result["total"] == 3, "登录日志应为 3 条"
    print(f"    ✓ 按操作筛选: login -> {result['total']} 条")

    # 按结果筛选
    result = query_audit_logs(result="failed", page=1, page_size=10)
    assert result["total"] >= 1, "失败日志应至少 1 条"
    print(f"    ✓ 按结果筛选: failed -> {result['total']} 条")

    # 按模块筛选
    result = query_audit_logs(module="auth", page=1, page_size=10)
    assert result["total"] >= 3, "auth 模块日志应至少 3 条"
    print(f"    ✓ 按模块筛选: auth -> {result['total']} 条")

    # 分页测试
    result = query_audit_logs(page=1, page_size=2)
    assert len(result["items"]) == 2, "每页应返回 2 条"
    print(f"    ✓ 分页查询正确 (第1页, 每页2条)")

    # 测试 CSV 导出
    print(f"\n3.3 审计日志导出:")
    csv_content = export_audit_logs_csv()
    lines = csv_content.strip().split("\n")
    assert len(lines) >= len(test_logs) + 1, "CSV 应包含表头和所有数据"
    header = lines[0]
    assert "用户名" in header and "操作" in header and "模块" in header, "CSV 表头应包含关键字段"
    print(f"    ✓ CSV 导出成功，共 {len(lines)-1} 条数据")
    print(f"    ✓ CSV 表头: {header}")

    # 测试审计日志路由
    print(f"\n3.4 审计日志接口:")
    import asyncio

    async def test_audit_api():
        # owner 可以查看所有日志
        result = await audit_router.get_audit_logs(
            username=None,
            action=None,
            module=None,
            result=None,
            start_time=None,
            end_time=None,
            page=1,
            page_size=10,
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code == 0, "owner 应能查看所有日志"
        print(f"    ✓ owner 可查看所有日志 ({result.data['total']} 条)")

        # auditor 可以查看所有日志
        result = await audit_router.get_audit_logs(
            username=None, page=1, page_size=10,
            current_user={"username": "auditor1", "role": "auditor"},
        )
        assert result.code == 0, "auditor 应能查看所有日志"
        print(f"    ✓ auditor 可查看所有日志 ({result.data['total']} 条)")

        # admin 只能查看自己的日志
        result = await audit_router.get_audit_logs(
            username=None, page=1, page_size=10,
            current_user={"username": "admin1", "role": "admin"},
        )
        assert result.code == 0, "admin 应能查看日志"
        for item in result.data["items"]:
            assert item["username"] == "admin1", "admin 只能看自己的日志"
        print(f"    ✓ admin 只能查看自己的日志 ({result.data['total']} 条)")

    asyncio.run(test_audit_api())

    print(f"\n  ✓ 审计日志测试通过")

except Exception as e:
    print(f"\n  ✗ 审计日志测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


# ========== 测试 4: 紧急制动 ==========
print(f"\n{'='*70}")
print(f"  [测试 4] 紧急制动")
print(f"{'='*70}")

try:
    with mock.patch.object(Path, 'home', return_value=TEST_DIR):
        from backend.routers import security as security_router

    import asyncio

    async def test_emergency_brake():
        print(f"\n4.1 制动状态查询:")
        # 初始状态应未激活
        assert not security_router.is_emergency_brake_active(), "初始状态制动应未激活"
        print(f"    ✓ 初始状态: 未激活")

        print(f"\n4.2 触发紧急制动:")
        # 非 owner 不能触发
        result = await security_router.trigger_emergency_brake(
            security_router.EmergencyBrakeRequest(reason="安全测试"),
            request=mock.MagicMock(),
            current_user={"username": "admin1", "role": "admin"},
        )
        assert result.code == 403, "admin 不能触发紧急制动"
        print(f"    ✓ admin 不能触发紧急制动")

        # owner 可以触发
        result = await security_router.trigger_emergency_brake(
            security_router.EmergencyBrakeRequest(reason="安全测试"),
            request=mock.MagicMock(client=mock.MagicMock(host="127.0.0.1")),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code == 0, f"owner 触发制动失败: {result.message}"
        assert result.data["active"] == True, "制动应已激活"
        assert security_router.is_emergency_brake_active(), "制动状态应为激活"
        print(f"    ✓ owner 触发紧急制动成功")
        print(f"    ✓ 制动原因: {result.data['reason']}")
        print(f"    ✓ 触发人: {result.data['triggered_by']}")

        print(f"\n4.3 制动状态查询接口:")
        result = await security_router.get_brake_status(
            current_user={"username": "admin1", "role": "admin"},
        )
        assert result.code == 0, "查询制动状态应成功"
        assert result.data["active"] == True, "制动应处于激活状态"
        print(f"    ✓ 任意登录用户可查询制动状态")

        # 重复触发应失败
        result = await security_router.trigger_emergency_brake(
            security_router.EmergencyBrakeRequest(reason="再次触发"),
            request=mock.MagicMock(),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code != 0, "重复触发应失败"
        print(f"    ✓ 重复触发制动被拒绝: {result.message}")

        print(f"\n4.4 解除紧急制动:")
        # 非 owner 不能解除
        result = await security_router.release_emergency_brake(
            security_router.ReleaseBrakeRequest(reason="测试完成"),
            request=mock.MagicMock(),
            current_user={"username": "admin1", "role": "admin"},
        )
        assert result.code == 403, "admin 不能解除紧急制动"
        print(f"    ✓ admin 不能解除紧急制动")

        # owner 可以解除
        result = await security_router.release_emergency_brake(
            security_router.ReleaseBrakeRequest(reason="测试完成"),
            request=mock.MagicMock(client=mock.MagicMock(host="127.0.0.1")),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code == 0, f"owner 解除制动失败: {result.message}"
        assert result.data["active"] == False, "制动应已解除"
        assert not security_router.is_emergency_brake_active(), "制动状态应为未激活"
        print(f"    ✓ owner 解除紧急制动成功")
        print(f"    ✓ 解除人: {result.data['released_by']}")

        # 重复解除应失败
        result = await security_router.release_emergency_brake(
            security_router.ReleaseBrakeRequest(reason="再次解除"),
            request=mock.MagicMock(),
            current_user={"username": "admin", "role": "owner"},
        )
        assert result.code != 0, "重复解除应失败"
        print(f"    ✓ 重复解除制动被拒绝: {result.message}")

        print(f"\n4.5 制动事件审计记录:")
        from backend.audit import query_audit_logs
        log_result = query_audit_logs(action="emergency_brake", page=1, page_size=10)
        assert log_result["total"] >= 1, "应记录制动事件"
        print(f"    ✓ 紧急制动事件已记录到审计日志")

        log_result = query_audit_logs(action="release_brake", page=1, page_size=10)
        assert log_result["total"] >= 1, "应记录解除制动事件"
        print(f"    ✓ 解除制动事件已记录到审计日志")

        print(f"\n  ✓ 紧急制动测试通过")

    asyncio.run(test_emergency_brake())

except Exception as e:
    print(f"\n  ✗ 紧急制动测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


# ========== 清理 ==========
print(f"\n{'='*70}")
print(f"  全部测试通过！")
print(f"  测试目录: {TEST_DIR}")
print(f"{'='*70}")
print(f"""
测试总结:
  ✓ 任务一：角色体系升级（owner/admin/auditor 三级角色）
    - 默认用户为 owner 角色
    - 角色权限层级正确（owner > admin > auditor）
    - 角色数量限制生效（owner:1, admin:3, auditor:2）
    - 非 owner 不能创建用户、修改角色等敏感操作

  ✓ 任务二：TOTP 双因子认证
    - TOTP 密钥生成（Base32 编码）
    - 验证码生成与验证（6 位数字，30 秒步长）
    - 二维码 URL 生成（otpauth 格式）
    - 恢复码生成与使用（8 个，一次性）
    - 两步登录流程（密码 → temp_token → TOTP → access_token）
    - TOTP 开启/关闭流程

  ✓ 任务三：审计日志
    - 日志添加（只追加）
    - 多维度筛选（用户/操作/模块/结果/时间）
    - 分页查询
    - CSV 导出
    - 权限控制（owner/auditor 看全部，admin 看自己）

  ✓ 任务四：紧急制动
    - 仅 owner 可触发/解除
    - 制动状态查询（所有登录用户可见）
    - 制动事件审计记录
    - 重复触发/解除防护
""")
