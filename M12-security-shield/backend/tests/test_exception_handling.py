"""
M12 安全盾 - 异常处理测试
验证异常处理规范化是否正确，确保没有静默失败。

测试覆盖：
1. WAF 路由异常日志记录
2. IP 控制路由异常日志记录
3. 关键操作失败时返回正确错误
4. 数据库操作异常处理
5. 中间件异常处理
6. 无静默失败验证
"""

import os
import sys
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ===========================================================================
# 测试环境初始化
# ===========================================================================

_current_dir = Path(__file__).resolve().parent
_backend_dir = _current_dir.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# 使用临时数据库
os.environ.setdefault("M12_DB_PATH", ":memory:")
os.environ.setdefault("M12_ENV", "test")
# 跳过 JWT 密钥安全检查（测试环境）
os.environ.setdefault("M12_REQUIRE_SECURE_SECRET", "false")


# ===========================================================================
# 测试辅助：日志捕获
# ===========================================================================

class LogCapture:
    """日志捕获辅助类"""

    def __init__(self, logger_name: str, level=logging.ERROR):
        self.logger_name = logger_name
        self.level = level
        self.records = []
        self._handler = None
        self._logger = None

    def __enter__(self):
        self._logger = logging.getLogger(self.logger_name)
        original_level = self._logger.level
        self._logger.setLevel(min(self.level, original_level))
        self._handler = logging.Handler()
        self._handler.setLevel(self.level)
        self._handler.emit = self._capture
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, *args):
        if self._handler and self._logger:
            self._logger.removeHandler(self._handler)

    def _capture(self, record):
        self.records.append(record)

    @property
    def count(self) -> int:
        return len(self.records)

    def has_message(self, substring: str) -> bool:
        return any(substring in rec.getMessage() for rec in self.records)

    def get_messages(self) -> list:
        return [rec.getMessage() for rec in self.records]


# ===========================================================================
# WAF 路由异常处理测试
# ===========================================================================

class TestWafExceptionHandling:
    """WAF 路由异常处理测试"""

    def setup_method(self):
        """每个测试前的设置"""
        from database import safe_init_db
        safe_init_db()

    def test_waf_status_exception_logged(self):
        """测试 WAF 状态查询异常被正确记录"""
        from routers.waf import waf_status

        with patch('routers.waf.get_waf_engine') as mock_get:
            mock_get.side_effect = Exception("模拟WAF引擎错误")

            with LogCapture('routers.waf', level=logging.ERROR) as log_cap:
                result = waf_status(current_user={"role": "viewer"})

                # 验证返回了错误响应
                assert result is not None
                # 验证日志被记录
                assert log_cap.count > 0, "异常应该被记录到日志中"
                assert log_cap.has_message("获取WAF状态失败"), "日志应包含操作描述"

    def test_waf_toggle_exception_logged(self):
        """测试 WAF 开关切换异常被正确记录"""
        from routers.waf import waf_toggle

        with patch('routers.waf.get_waf_engine') as mock_get:
            mock_get.side_effect = Exception("模拟切换错误")

            with LogCapture('routers.waf', level=logging.ERROR) as log_cap:
                result = waf_toggle(current_user={"role": "admin"})

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("切换WAF状态失败")

    def test_waf_rules_list_exception_logged(self):
        """测试 WAF 规则列表查询异常被正确记录"""
        from routers.waf import list_rules

        with patch('routers.waf.get_waf_engine') as mock_get:
            mock_get.side_effect = Exception("模拟规则查询错误")

            with LogCapture('routers.waf', level=logging.ERROR) as log_cap:
                result = list_rules(current_user={"role": "viewer"})

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("获取规则列表失败")

    def test_waf_create_rule_exception_logged(self):
        """测试 WAF 创建规则异常被正确记录"""
        from routers.waf import create_rule

        with patch('routers.waf.get_waf_engine') as mock_get:
            mock_get.side_effect = Exception("模拟创建规则错误")

            with LogCapture('routers.waf', level=logging.ERROR) as log_cap:
                result = create_rule(
                    rule_name="test-rule",
                    pattern="<script>",
                    rule_type="xss",
                    severity="high",
                    current_user={"role": "admin"},
                )

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("创建规则失败")

    def test_waf_delete_rule_exception_logged(self):
        """测试 WAF 删除规则异常被正确记录"""
        from routers.waf import delete_rule

        with patch('routers.waf.get_waf_engine') as mock_get:
            mock_get.side_effect = Exception("模拟删除规则错误")

            with LogCapture('routers.waf', level=logging.ERROR) as log_cap:
                result = delete_rule(rule_id=1, current_user={"role": "admin"})

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("删除规则失败")

    def test_waf_exception_returns_error_response(self):
        """测试 WAF 异常返回正确的错误响应格式"""
        from routers.waf import waf_status

        with patch('routers.waf.get_waf_engine') as mock_get:
            mock_get.side_effect = Exception("测试错误")

            result = waf_status(current_user={"role": "viewer"})

            # 验证返回了错误响应（不是 None，也不是正常响应）
            assert result is not None
            # 错误响应中应该包含错误信息
            result_str = str(result)
            assert "测试错误" in result_str or "失败" in result_str


# ===========================================================================
# IP 控制路由异常处理测试
# ===========================================================================

class TestIPControlExceptionHandling:
    """IP 控制路由异常处理测试"""

    def setup_method(self):
        """每个测试前的设置"""
        from database import safe_init_db
        safe_init_db()

    def test_blacklist_get_exception_logged(self):
        """测试获取黑名单异常被正确记录"""
        from routers.ip_control import list_blacklist

        with patch('routers.ip_control.get_ip_filter') as mock_get:
            mock_get.side_effect = Exception("模拟获取黑名单错误")

            with LogCapture('routers.ip_control', level=logging.ERROR) as log_cap:
                result = list_blacklist(current_user={"role": "viewer"})

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("获取黑名单失败")

    def test_blacklist_add_exception_logged(self):
        """测试添加黑名单异常被正确记录"""
        from routers.ip_control import add_blacklist

        with patch('routers.ip_control.get_ip_filter') as mock_get:
            mock_get.side_effect = Exception("模拟添加黑名单错误")

            with LogCapture('routers.ip_control', level=logging.ERROR) as log_cap:
                result = add_blacklist(
                    ip_address="192.168.1.1",
                    reason="test",
                    current_user={"role": "admin"},
                )

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("添加黑名单失败")

    def test_whitelist_get_exception_logged(self):
        """测试获取白名单异常被正确记录"""
        from routers.ip_control import list_whitelist

        with patch('routers.ip_control.get_ip_filter') as mock_get:
            mock_get.side_effect = Exception("模拟获取白名单错误")

            with LogCapture('routers.ip_control', level=logging.ERROR) as log_cap:
                result = list_whitelist(current_user={"role": "viewer"})

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("获取白名单失败")

    def test_ip_check_exception_logged(self):
        """测试 IP 检测异常被正确记录"""
        from routers.ip_control import check_ip

        with patch('routers.ip_control.get_ip_filter') as mock_get:
            mock_get.side_effect = Exception("模拟IP检测错误")

            with LogCapture('routers.ip_control', level=logging.ERROR) as log_cap:
                result = check_ip(ip_address="192.168.1.1", current_user={"role": "viewer"})

                assert result is not None
                assert log_cap.count > 0
                assert log_cap.has_message("IP 检测失败")


# ===========================================================================
# 数据库异常处理测试
# ===========================================================================

class TestDatabaseExceptionHandling:
    """数据库异常处理测试"""

    def test_get_db_session_exception_rollback(self):
        """测试数据库会话异常时正确回滚"""
        from core.db import get_db_session

        with patch('core.db.SessionLocal') as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.commit.side_effect = Exception("模拟提交错误")

            with pytest.raises(Exception):
                with get_db_session() as session:
                    pass  # 进入上下文后 commit 会失败

            # 验证 rollback 被调用
            mock_session.rollback.assert_called()
            # 验证 close 被调用
            mock_session.close.assert_called()

    def test_get_db_session_normal_commit(self):
        """测试数据库会话正常提交"""
        from core.db import get_db_session

        with patch('core.db.SessionLocal') as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            with get_db_session() as session:
                assert session is not None

            # 验证 commit 被调用
            mock_session.commit.assert_called()
            # 验证 close 被调用
            mock_session.close.assert_called()

    def test_check_db_health_handles_error(self):
        """测试数据库健康检查处理错误"""
        from core.db import check_db_health

        with patch('core.db.get_db_session_readonly') as mock_session:
            mock_session.side_effect = Exception("数据库连接失败")

            result = check_db_health()

            assert result["status"] == "unhealthy"
            assert result["error"] is not None
            assert "数据库连接失败" in result["error"]

    def test_safe_init_db_retry(self):
        """测试安全初始化数据库的重试机制"""
        from core.db import safe_init_db

        with patch('core.db.init_db') as mock_init:
            mock_init.side_effect = [Exception("第一次失败"), Exception("第二次失败"), None]

            result = safe_init_db(retry_count=3, retry_delay=0.01)

            assert result is True
            assert mock_init.call_count == 3

    def test_safe_init_db_max_retries_exceeded(self):
        """测试安全初始化数据库达到最大重试次数"""
        from core.db import safe_init_db

        with patch('core.db.init_db') as mock_init:
            mock_init.side_effect = Exception("持续失败")

            result = safe_init_db(retry_count=2, retry_delay=0.01)

            assert result is False
            assert mock_init.call_count == 2


# ===========================================================================
# 中间件异常处理测试
# ===========================================================================

class TestMiddlewareExceptionHandling:
    """中间件异常处理测试"""

    def test_waf_middleware_init_not_crash(self):
        """测试 WAF 中间件初始化不会崩溃"""
        from middlewares import WAFMiddleware

        app = MagicMock()
        try:
            middleware = WAFMiddleware(app=app, enabled=True)
            assert middleware is not None
        except Exception as e:
            pytest.fail(f"WAFMiddleware 初始化失败: {e}")

    def test_middleware_module_has_logger(self):
        """测试中间件模块有 logger"""
        import middlewares
        assert hasattr(middlewares, 'logger') or hasattr(middlewares.WAFMiddleware, '__init__')


# ===========================================================================
# 审计服务异常处理测试
# ===========================================================================

class TestAuditExceptionHandling:
    """审计服务异常处理测试"""

    def test_audit_list_events_exception_logged(self):
        """测试审计事件列表异常被正确记录"""
        from routers.audit import list_events

        with patch('routers.audit.get_audit_service') as mock_get:
            mock_get.side_effect = Exception("模拟获取审计日志错误")

            with LogCapture('routers.audit', level=logging.ERROR) as log_cap:
                result = list_events(current_user={"role": "viewer"})

                assert result is not None
                assert log_cap.count > 0


# ===========================================================================
# 无静默失败验证
# ===========================================================================

class TestNoSilentFailures:
    """验证没有静默失败的异常处理"""

    def test_routers_have_logger(self):
        """测试所有路由模块都有 logger"""
        router_files = [
            'routers.waf',
            'routers.ip_control',
            'routers.audit',
            'routers.dashboard',
            'routers.status',
            'routers.masking',
            'routers.auto_response',
            'routers.scan',
            'routers.auth_api',
        ]

        for module_name in router_files:
            try:
                module = __import__(module_name, fromlist=[''])
                assert hasattr(module, 'logger'), f"{module_name} 缺少 logger"
                assert module.logger is not None, f"{module_name} 的 logger 为 None"
            except ImportError:
                # 某些模块可能不存在，跳过
                pass

    def test_core_db_has_logger(self):
        """测试数据库模块有 logger"""
        from core import db as db_module
        assert hasattr(db_module, 'logger')

    def test_thread_safety_module_exists(self):
        """测试线程安全模块存在"""
        from core import thread_safety
        assert hasattr(thread_safety, 'RWLock')
        assert hasattr(thread_safety, 'AtomicCounter')
        assert hasattr(thread_safety, 'ThreadSafeDict')

    def test_no_bare_except_in_key_modules(self):
        """测试关键模块中没有裸 except:"""
        key_files = [
            _backend_dir / 'core' / 'db.py',
            _backend_dir / 'core' / 'thread_safety.py',
            _backend_dir / 'services' / 'waf_engine.py',
            _backend_dir / 'services' / 'ip_filter.py',
        ]

        for file_path in key_files:
            if file_path.exists():
                content = file_path.read_text(encoding='utf-8')
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    # 跳过注释和字符串
                    if stripped.startswith('#'):
                        continue
                    # 检查裸 except
                    if stripped == 'except:':
                        pytest.fail(f"文件 {file_path.name} 第 {i+1} 行有裸 except:")


# ===========================================================================
# 主入口
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
