"""P1 修复验证脚本.

验证两个 P1 问题的修复：
1. OfflineShadowProxy 无 sync_api 时能否正常初始化
2. LocalDataManager 能否正常 initialize_db 和建表
3. 基本的 CRUD 操作是否正常

运行方式:
    python verify_p1_fixes.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 sys.path 中
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import structlog

logger = structlog.get_logger(__name__)

# 测试结果汇总
_passed = 0
_failed = 0


def _assert(condition: bool, msg: str) -> None:
    """简易断言，不抛出异常，只计数."""
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {msg}")
    else:
        _failed += 1
        print(f"  [FAIL] {msg}")


# ===========================================================================
# 测试 1：OfflineShadowProxy 无 sync_api 初始化
# ===========================================================================

async def test_offline_shadow_proxy_no_sync_api() -> None:
    """测试 OfflineShadowProxy 在无 sync_api 时能否正常初始化."""
    print("\n" + "=" * 60)
    print("测试 1：OfflineShadowProxy 无 sync_api 初始化")
    print("=" * 60)

    from edge_cloud_kernel.sync.offline_shadow_proxy import (
        ConnectionState,
        OfflineShadowProxy,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_queue.db")

        # ---- 1.1 无 sync_api 初始化不报错 ----
        try:
            proxy = OfflineShadowProxy(db_path=db_path)
            _assert(True, "无 sync_api 初始化不报错")
        except Exception as e:
            _assert(False, f"无 sync_api 初始化报错: {e}")
            return

        # ---- 1.2 初始状态为 OFFLINE ----
        _assert(
            proxy.state == ConnectionState.OFFLINE,
            f"初始状态为 OFFLINE (实际: {proxy.state.value})",
        )
        _assert(
            proxy.is_online is False,
            f"is_online 为 False (实际: {proxy.is_online})",
        )
        _assert(
            proxy._sync_api is None,
            "_sync_api 为 None",
        )

        # ---- 1.3 check_connectivity 返回 False ----
        result = await proxy.check_connectivity()
        _assert(result is False, f"check_connectivity 返回 False (实际: {result})")

        # ---- 1.4 start() 和 stop() 正常工作 ----
        try:
            await proxy.start()
            _assert(True, "start() 正常执行")
        except Exception as e:
            _assert(False, f"start() 报错: {e}")

        # ---- 1.5 离线模式下 push 能正常入队 ----
        from edge_cloud_kernel.sync.sync_api import SyncPushRequest

        try:
            request = SyncPushRequest(
                changes=[],
                version_vector={"test": 1},
            )
            resp = await proxy.push("test_session", request)
            _assert(resp.accepted == [], "离线 push 返回空 accepted 列表")
            queue_size = await proxy.get_queue_size()
            _assert(queue_size == 1, f"队列大小为 1 (实际: {queue_size})")
        except Exception as e:
            _assert(False, f"离线 push 报错: {e}")

        # ---- 1.6 离线模式下 create_session 正常入队 ----
        from edge_cloud_kernel.sync.sync_api import SyncSessionRequest

        try:
            req = SyncSessionRequest(device_id="dev_001", scopes=["test"])
            resp = await proxy.create_session(req)
            _assert(
                resp.session_id == "__offline_pending__",
                f"离线 create_session 返回占位 session_id (实际: {resp.session_id})",
            )
            queue_size = await proxy.get_queue_size()
            _assert(queue_size == 2, f"队列大小为 2 (实际: {queue_size})")
        except Exception as e:
            _assert(False, f"离线 create_session 报错: {e}")

        # ---- 1.7 离线模式下 pull 返回空 ----
        try:
            resp = await proxy.pull("test_session", {"test": 0})
            _assert(resp.changes == [], "离线 pull 返回空变更列表")
            _assert(resp.server_version == "offline", "离线 pull server_version 为 offline")
        except Exception as e:
            _assert(False, f"离线 pull 报错: {e}")

        # ---- 1.8 离线模式下 resolve 正常入队 ----
        from edge_cloud_kernel.sync.sync_api import SyncResolveRequest

        try:
            req = SyncResolveRequest(conflict_ids=["c1"], resolution="local")
            resp = await proxy.resolve("test_session", req)
            _assert(resp.resolved == ["c1"], "离线 resolve 返回已解决列表")
            queue_size = await proxy.get_queue_size()
            _assert(queue_size == 3, f"队列大小为 3 (实际: {queue_size})")
        except Exception as e:
            _assert(False, f"离线 resolve 报错: {e}")

        # ---- 1.9 replay 在无 sync_api 时返回空结果 ----
        try:
            result = await proxy.replay()
            _assert(result.success_count == 0, "无 sync_api 时 replay success_count 为 0")
            _assert(result.failed_count == 0, "无 sync_api 时 replay failed_count 为 0")
            _assert(result.skipped_count == 0, "无 sync_api 时 replay skipped_count 为 0")
        except Exception as e:
            _assert(False, f"replay 报错: {e}")

        # ---- 1.10 bind_sync_api 绑定后状态不自动改变（需显式检查） ----
        from unittest.mock import AsyncMock

        try:
            mock_api = AsyncMock()
            proxy.bind_sync_api(mock_api)
            _assert(proxy._sync_api is not None, "bind_sync_api 后 _sync_api 不为 None")
            # 绑定后状态仍然是 OFFLINE，需要显式检查连通性
            _assert(
                proxy.state == ConnectionState.OFFLINE,
                f"bind_sync_api 后状态仍为 OFFLINE (实际: {proxy.state.value})",
            )
        except Exception as e:
            _assert(False, f"bind_sync_api 报错: {e}")

        # stop
        try:
            await proxy.stop()
            _assert(True, "stop() 正常执行")
        except Exception as e:
            _assert(False, f"stop() 报错: {e}")

    print(f"\n测试 1 完成：通过 {_passed - 0} 项（累计）")


# ===========================================================================
# 测试 2：LocalDataManager initialize_db 建表
# ===========================================================================

async def test_local_data_manager_init_db() -> None:
    """测试 LocalDataManager 能否正常 initialize_db 和建表."""
    print("\n" + "=" * 60)
    print("测试 2：LocalDataManager initialize_db 建表")
    print("=" * 60)

    from edge_cloud_kernel.local_data.local_data_manager import LocalDataManager
    import aiosqlite

    # 重置单例
    LocalDataManager.reset_instance()

    with tempfile.TemporaryDirectory() as tmpdir:
        # ---- 2.1 初始化不报错 ----
        try:
            mgr = LocalDataManager(data_dir=tmpdir)
            await mgr.initialize()
            _assert(True, "initialize() 不报错")
        except Exception as e:
            _assert(False, f"initialize() 报错: {e}")
            return

        # ---- 2.2 数据库文件存在 ----
        db_path = Path(mgr.db_path)
        _assert(db_path.exists(), f"数据库文件存在: {db_path}")

        # ---- 2.3 验证所有表都已创建 ----
        expected_tables = [
            "call_logs",
            "sync_items",
            "sessions",
            "audit_trail",
            "config_kv",
            "cache_items",
        ]

        conn = await aiosqlite.connect(str(db_path))
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            rows = await cursor.fetchall()
            actual_tables = [row[0] for row in rows]
            print(f"  实际表: {actual_tables}")

            for table in expected_tables:
                _assert(table in actual_tables, f"表 {table} 存在")
        finally:
            await conn.close()

        # ---- 2.4 验证表结构（抽查列） ----
        conn = await aiosqlite.connect(str(db_path))
        try:
            # call_logs 列
            cursor = await conn.execute("PRAGMA table_info(call_logs)")
            rows = await cursor.fetchall()
            call_logs_cols = [row[1] for row in rows]
            expected_cols = [
                "id", "agent_id", "model", "prompt_tokens",
                "completion_tokens", "total_tokens", "latency_ms",
                "status", "error", "route", "created_at",
            ]
            for col in expected_cols:
                _assert(col in call_logs_cols, f"call_logs 包含列 {col}")

            # sessions 列
            cursor = await conn.execute("PRAGMA table_info(sessions)")
            rows = await cursor.fetchall()
            sessions_cols = [row[1] for row in rows]
            for col in ["session_id", "agent_id", "data", "expires_at", "created_at", "updated_at"]:
                _assert(col in sessions_cols, f"sessions 包含列 {col}")

            # config_kv 列
            cursor = await conn.execute("PRAGMA table_info(config_kv)")
            rows = await cursor.fetchall()
            config_cols = [row[1] for row in rows]
            for col in ["key", "value", "updated_at"]:
                _assert(col in config_cols, f"config_kv 包含列 {col}")

            # cache_items 列
            cursor = await conn.execute("PRAGMA table_info(cache_items)")
            rows = await cursor.fetchall()
            cache_cols = [row[1] for row in rows]
            for col in ["cache_key", "value", "expires_at", "created_at"]:
                _assert(col in cache_cols, f"cache_items 包含列 {col}")

            # sync_items 列
            cursor = await conn.execute("PRAGMA table_info(sync_items)")
            rows = await cursor.fetchall()
            sync_cols = [row[1] for row in rows]
            for col in ["id", "item_type", "item_id", "version", "data_hash", "operation", "status"]:
                _assert(col in sync_cols, f"sync_items 包含列 {col}")

            # audit_trail 列
            cursor = await conn.execute("PRAGMA table_info(audit_trail)")
            rows = await cursor.fetchall()
            audit_cols = [row[1] for row in rows]
            for col in ["id", "agent_id", "action", "resource", "detail", "ip_address", "created_at"]:
                _assert(col in audit_cols, f"audit_trail 包含列 {col}")
        finally:
            await conn.close()

    # 重置单例
    LocalDataManager.reset_instance()


# ===========================================================================
# 测试 3：LocalDataManager CRUD 操作
# ===========================================================================

async def test_local_data_manager_crud() -> None:
    """测试 LocalDataManager 基本 CRUD 操作."""
    print("\n" + "=" * 60)
    print("测试 3：LocalDataManager 基本 CRUD 操作")
    print("=" * 60)

    from edge_cloud_kernel.local_data.local_data_manager import LocalDataManager

    # 重置单例
    LocalDataManager.reset_instance()

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = LocalDataManager(data_dir=tmpdir)
        await mgr.initialize()

        # ---- 3.1 调用日志 CRUD ----
        print("\n  -- 调用日志 --")
        try:
            await mgr.save_call_log({
                "agent_id": "agent_001",
                "model": "gpt-4",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latency_ms": 1200,
                "status": "success",
                "route": "cloud",
            })
            await mgr.save_call_log({
                "agent_id": "agent_001",
                "model": "gpt-3.5",
                "prompt_tokens": 50,
                "completion_tokens": 30,
                "total_tokens": 80,
                "latency_ms": 500,
                "status": "success",
                "route": "local",
            })
            await mgr.save_call_log({
                "agent_id": "agent_002",
                "model": "gpt-4",
                "status": "error",
                "error": "timeout",
            })
            _assert(True, "save_call_log 写入 3 条记录")

            # 查询全部
            logs = await mgr.get_call_logs(limit=10)
            _assert(len(logs) == 3, f"get_call_logs 返回 3 条 (实际: {len(logs)})")

            # 按 agent_id 过滤
            logs_agent1 = await mgr.get_call_logs(agent_id="agent_001", limit=10)
            _assert(
                len(logs_agent1) == 2,
                f"agent_001 有 2 条记录 (实际: {len(logs_agent1)})",
            )

            # 按时间倒序
            _assert(
                logs[0]["created_at"] >= logs[-1]["created_at"],
                "调用日志按时间倒序",
            )
        except Exception as e:
            _assert(False, f"调用日志 CRUD 报错: {e}")

        # ---- 3.2 通用缓存 CRUD ----
        print("\n  -- 通用缓存 --")
        try:
            # 设置缓存
            await mgr.set_cache("test_key", {"foo": "bar", "num": 42}, ttl_seconds=3600)
            _assert(True, "set_cache 设置成功")

            # 获取缓存
            value = await mgr.get_cache("test_key")
            _assert(value is not None, "get_cache 不返回 None")
            _assert(
                value == {"foo": "bar", "num": 42},
                f"get_cache 值正确 (实际: {value})",
            )

            # 不存在的 key
            value_none = await mgr.get_cache("nonexistent")
            _assert(value_none is None, "不存在的 key 返回 None")

            # 过期缓存
            await mgr.set_cache("expired_key", "will_expire", ttl_seconds=-1)  # 已过期
            expired_value = await mgr.get_cache("expired_key")
            _assert(expired_value is None, "过期缓存返回 None")

            # 更新缓存
            await mgr.set_cache("test_key", "new_value", ttl_seconds=3600)
            updated_value = await mgr.get_cache("test_key")
            _assert(
                updated_value == "new_value",
                f"缓存更新成功 (实际: {updated_value})",
            )
        except Exception as e:
            _assert(False, f"通用缓存 CRUD 报错: {e}")

        # ---- 3.3 配置键值 CRUD ----
        print("\n  -- 配置键值 --")
        try:
            # 设置配置
            await mgr.set_config("app.version", "1.0.0")
            await mgr.set_config("app.debug", True)
            await mgr.set_config("app.max_users", 100)
            _assert(True, "set_config 设置 3 条配置")

            # 获取配置
            version = await mgr.get_config("app.version")
            _assert(version == "1.0.0", f"get_config version 正确 (实际: {version})")

            debug = await mgr.get_config("app.debug")
            _assert(debug is True, f"get_config debug 正确 (实际: {debug})")

            max_users = await mgr.get_config("app.max_users")
            _assert(max_users == 100, f"get_config max_users 正确 (实际: {max_users})")

            # 默认值
            missing = await mgr.get_config("nonexistent", default="fallback")
            _assert(missing == "fallback", f"不存在的 key 返回默认值 (实际: {missing})")

            # 更新配置
            await mgr.set_config("app.version", "2.0.0")
            updated = await mgr.get_config("app.version")
            _assert(updated == "2.0.0", f"配置更新成功 (实际: {updated})")
        except Exception as e:
            _assert(False, f"配置键值 CRUD 报错: {e}")

        # ---- 3.4 cleanup 正常执行 ----
        print("\n  -- cleanup --")
        try:
            await mgr.cleanup()
            _assert(True, "cleanup() 正常执行")
        except Exception as e:
            _assert(False, f"cleanup() 报错: {e}")

    # 重置单例
    LocalDataManager.reset_instance()


# ===========================================================================
# 测试 4：server.py 初始化方式验证
# ===========================================================================

async def test_server_init_style() -> None:
    """验证 server.py 中的初始化方式能正常工作."""
    print("\n" + "=" * 60)
    print("测试 4：server.py 初始化方式验证")
    print("=" * 60)

    from edge_cloud_kernel.sync.offline_shadow_proxy import OfflineShadowProxy

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "offline_queue.db")

        # 模拟 server.py 第 179 行的初始化方式（只传 db_path）
        try:
            offline_proxy = OfflineShadowProxy(
                db_path=db_path,
            )
            _assert(True, "server.py 方式（仅 db_path）初始化成功")
            _assert(
                offline_proxy._sync_api is None,
                "_sync_api 为 None（纯离线模式）",
            )
            _assert(
                offline_proxy.is_online is False,
                "is_online 为 False（纯离线模式）",
            )
        except Exception as e:
            _assert(False, f"server.py 方式初始化报错: {e}")
            return

        # start / stop 正常
        try:
            await offline_proxy.start()
            _assert(True, "start() 正常")
            await offline_proxy.stop()
            _assert(True, "stop() 正常")
        except Exception as e:
            _assert(False, f"start/stop 报错: {e}")


# ===========================================================================
# 主入口
# ===========================================================================

async def main() -> None:
    """运行所有验证测试."""
    print("P1 修复验证脚本")
    print("=" * 60)

    await test_offline_shadow_proxy_no_sync_api()
    await test_local_data_manager_init_db()
    await test_local_data_manager_crud()
    await test_server_init_style()

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    print(f"  通过: {_passed}")
    print(f"  失败: {_failed}")
    print(f"  总计: {_passed + _failed}")

    if _failed == 0:
        print("\n  所有测试通过！P1 修复验证成功。")
    else:
        print(f"\n  有 {_failed} 项测试失败，请检查。")


if __name__ == "__main__":
    asyncio.run(main())
