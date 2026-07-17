"""
E2E 测试 - 统一 API 客户端

封装 httpx.AsyncClient / requests，提供：
- 自动处理认证（JWT / API Key）
- 统一的请求/响应处理
- 重试机制
- 超时控制
- 请求记录与统计
- Mock 模式支持（不依赖真实服务）
"""

import time
import json
import uuid
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from unittest.mock import MagicMock, AsyncMock


@dataclass
class RequestRecord:
    """请求记录"""
    method: str
    url: str
    status_code: int
    duration_ms: float
    request_body: Optional[Dict] = None
    response_body: Optional[Dict] = None
    error: Optional[str] = None


@dataclass
class E2EApiClientStats:
    """API 客户端统计"""
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    requests: List[RequestRecord] = field(default_factory=list)

    @property
    def avg_response_time_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_ms / self.total_requests

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.success_count / self.total_requests


class E2EApiClient:
    """
    E2E 测试统一 API 客户端

    支持两种模式：
    1. Mock 模式：不依赖真实服务，返回模拟响应
    2. 真实模式：连接真实后端服务

    使用示例：
        client = E2EApiClient(base_url="http://localhost:8080", use_mock=True)
        client.login("admin", "admin123456")
        result = client.get("/api/v1/users")
        assert result["code"] == 0
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        use_mock: bool = True,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_interval: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.use_mock = use_mock
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_interval = retry_interval

        # 认证状态
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.api_key: Optional[str] = None
        self.current_user: Optional[Dict[str, Any]] = None

        # 统计
        self.stats = E2EApiClientStats()

        # Mock 数据存储
        self._mock_data_store: Dict[str, Any] = {}
        self._mock_users: Dict[str, Dict[str, Any]] = {}
        self._mock_sessions: Dict[str, Dict[str, Any]] = {}
        self._mock_modules: Dict[str, Dict[str, Any]] = {}
        self._mock_memories: List[Dict[str, Any]] = []
        self._mock_workflows: Dict[str, Dict[str, Any]] = {}
        self._mock_tasks: Dict[str, Dict[str, Any]] = {}
        self._mock_skills: Dict[str, Dict[str, Any]] = {}
        self._mock_scenes: Dict[str, Dict[str, Any]] = {}
        self._init_default_mock_data()

    # ============================================================
    # Mock 数据初始化
    # ============================================================

    def _init_default_mock_data(self):
        """初始化默认 Mock 数据"""
        # 默认管理员用户
        self._mock_users["admin"] = {
            "id": 1,
            "username": "admin",
            "email": "admin@yunxi.local",
            "password_hash": "mock_hash_admin123",
            "role": "admin",
            "is_active": True,
            "first_login": False,
            "created_at": "2024-01-01T00:00:00Z",
        }

        # 默认模块状态
        modules = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"]
        module_names = {
            "m1": "M1 多Agent调度中心",
            "m2": "M2 技能集群",
            "m3": "M3 端云协同内核",
            "m4": "M4 场景引擎",
            "m5": "M5 潮汐记忆系统",
            "m6": "M6 硬件外设模拟",
            "m7": "M7 积木平台",
            "m8": "M8 管理控制塔",
            "m9": "M9 开发者工坊",
            "m10": "M10 系统卫士",
            "m11": "M11 MCP总线",
            "m12": "M12 安全盾",
        }
        for m in modules:
            self._mock_modules[m] = {
                "key": m,
                "name": module_names.get(m, m),
                "status": "running",
                "version": "1.0.0",
                "health": "healthy",
            }

        # 默认技能
        default_skills = [
            {"id": "skill-time", "name": "时间查询", "category": "utility", "enabled": True},
            {"id": "skill-weather", "name": "天气查询", "category": "utility", "enabled": True},
            {"id": "skill-calc", "name": "计算器", "category": "utility", "enabled": True},
            {"id": "skill-translate", "name": "翻译", "category": "language", "enabled": True},
            {"id": "skill-code", "name": "代码生成", "category": "development", "enabled": True},
        ]
        for s in default_skills:
            self._mock_skills[s["id"]] = s

        # 默认场景
        default_scenes = [
            {"id": "scene-work", "name": "工作模式", "description": "专注工作场景", "active": True},
            {"id": "scene-study", "name": "学习模式", "description": "学习辅助场景", "active": False},
            {"id": "scene-life", "name": "生活助手", "description": "日常生活场景", "active": False},
        ]
        for s in default_scenes:
            self._mock_scenes[s["id"]] = s

        # 默认工作流
        default_workflows = [
            {
                "id": "wf-daily-report",
                "name": "每日报告生成",
                "description": "自动生成每日工作报告",
                "status": "active",
                "steps": 5,
            },
            {
                "id": "wf-code-review",
                "name": "代码审查流程",
                "description": "自动化代码审查工作流",
                "status": "active",
                "steps": 3,
            },
        ]
        for w in default_workflows:
            self._mock_workflows[w["id"]] = w

    # ============================================================
    # 认证方法
    # ============================================================

    def login(self, username: str = "admin", password: str = "admin123456") -> Dict[str, Any]:
        """
        登录并保存 Token

        Returns:
            登录响应 {code, message, data: {access_token, refresh_token, user}}
        """
        if self.use_mock:
            return self._mock_login(username, password)

        # 真实模式
        return self.post("/api/auth/login", {"username": username, "password": password})

    def _mock_login(self, username: str, password: str) -> Dict[str, Any]:
        """Mock 登录"""
        user = self._mock_users.get(username)
        if not user or not user["is_active"]:
            return {
                "code": 401,
                "message": "用户名或密码错误",
                "data": None,
            }

        # 密码验证（mock 模式下使用存储的明文密码或默认密码）
        expected_password = user.get("_plain_password", "")
        # admin 默认密码
        if username == "admin" and not expected_password:
            expected_password = "admin123456"

        if expected_password and password != expected_password:
            return {
                "code": 401,
                "message": "用户名或密码错误",
                "data": None,
            }

        # 生成 Mock Token
        access_token = f"mock_access_{uuid.uuid4().hex}"
        refresh_token = f"mock_refresh_{uuid.uuid4().hex}"

        self.access_token = access_token
        self.refresh_token = refresh_token
        self.current_user = {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
        }

        # 记录会话
        self._mock_sessions[access_token] = {
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
        }

        return {
            "code": 0,
            "message": "登录成功",
            "data": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": 3600,
                "user": self.current_user,
                "first_login": user.get("first_login", False),
            },
        }

    def logout(self) -> Dict[str, Any]:
        """登出"""
        if self.use_mock:
            if self.access_token and self.access_token in self._mock_sessions:
                del self._mock_sessions[self.access_token]
            self.access_token = None
            self.refresh_token = None
            self.current_user = None
            return {"code": 0, "message": "登出成功", "data": None}

        return self.post("/api/auth/logout", {})

    def refresh_token_flow(self) -> Dict[str, Any]:
        """刷新 Token"""
        if self.use_mock:
            if not self.refresh_token:
                return {"code": 401, "message": "无 refresh token", "data": None}

            new_access_token = f"mock_access_{uuid.uuid4().hex}"
            self.access_token = new_access_token

            # 更新会话
            if self.current_user:
                self._mock_sessions[new_access_token] = {
                    "user_id": self.current_user["id"],
                    "username": self.current_user["username"],
                    "role": self.current_user["role"],
                    "created_at": time.time(),
                    "expires_at": time.time() + 3600,
                }

            return {
                "code": 0,
                "message": "Token 刷新成功",
                "data": {
                    "access_token": new_access_token,
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            }

        return self.post("/api/auth/refresh", {"refresh_token": self.refresh_token or ""})

    def set_token(self, token: str):
        """手动设置 Access Token"""
        self.access_token = token

    def set_api_key(self, api_key: str):
        """设置 API Key"""
        self.api_key = api_key

    # ============================================================
    # 通用 HTTP 方法
    # ============================================================

    def get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """发送 GET 请求"""
        return self._request("GET", path, params=params)

    def post(self, path: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """发送 POST 请求"""
        return self._request("POST", path, body=data)

    def put(self, path: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """发送 PUT 请求"""
        return self._request("PUT", path, body=data)

    def delete(self, path: str) -> Dict[str, Any]:
        """发送 DELETE 请求"""
        return self._request("DELETE", path)

    def patch(self, path: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """发送 PATCH 请求"""
        return self._request("PATCH", path, body=data)

    # ============================================================
    # 核心请求方法
    # ============================================================

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求（带重试）
        """
        url = self._build_url(path, params)
        start_time = time.time()

        last_error = None
        for attempt in range(self.max_retries):
            try:
                if self.use_mock:
                    result = self._mock_request(method, path, params, body)
                else:
                    result = self._real_request(method, url, body)

                # 记录请求
                duration = (time.time() - start_time) * 1000
                self._record_request(method, url, 200, duration, body, result)

                return result

            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_interval)
                else:
                    duration = (time.time() - start_time) * 1000
                    self._record_request(method, url, 0, duration, body, None, last_error)
                    return {
                        "code": -1,
                        "message": f"请求失败: {last_error}",
                        "data": None,
                        "error": last_error,
                    }

        return {
            "code": -1,
            "message": f"请求失败（重试 {self.max_retries} 次）: {last_error}",
            "data": None,
        }

    def _real_request(self, method: str, url: str, body: Optional[Dict]) -> Dict[str, Any]:
        """真实 HTTP 请求（使用 urllib）"""
        import urllib.request
        import urllib.error

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
                try:
                    return json.loads(response_body)
                except json.JSONDecodeError:
                    return {
                        "code": -1,
                        "message": "响应解析失败",
                        "data": response_body,
                        "status_code": response.status,
                    }
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                return json.loads(error_body)
            except Exception:
                return {
                    "code": e.code,
                    "message": str(e.reason),
                    "data": None,
                }

    def _mock_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict],
        body: Optional[Dict],
    ) -> Dict[str, Any]:
        """
        Mock 请求处理

        根据路径和方法返回模拟响应。
        这是 E2E 测试的核心 Mock 逻辑，模拟各模块 API 的行为。
        """
        # 认证检查（需要认证的路径）
        public_path_prefixes = (
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/refresh",
            "/health",
            "/gateway/health",
            "/gateway/routes",
            "/gateway/status",
            "/gateway/metrics",
            "/gateway/circuit-breakers",
            "/m8/health",
            "/m8/metrics",
            "/routes",
            "/api/v1/public",
            "/api/v1/status",
            "/api/v1/auth/login",
            "/api/v1/auth/register",
        )
        path_lower = path.lower()
        auth_required = not any(
            path_lower.startswith(p) for p in public_path_prefixes
        )
        if auth_required and not self._is_authenticated():
            return {
                "code": 401,
                "message": "未授权",
                "data": None,
            }

        # 路由到对应的 Mock 处理器
        path_lower = path.lower()

        # 健康检查
        if path_lower in ("/health", "/gateway/health", "/m8/health"):
            return self._mock_health_check()

        # 认证相关
        if "/api/auth/me" in path_lower or "/api/user/info" in path_lower:
            return self._mock_get_user_info()
        if "/api/auth/password" in path_lower and method == "PUT":
            return self._mock_change_password(body)
        if "/api/auth/register" in path_lower and method == "POST":
            return self._mock_register(body)

        # 用户管理
        if "/api/users" in path_lower:
            return self._mock_users_api(method, path, body)

        # 模块管理
        if "/api/modules" in path_lower or "/api/v1/modules" in path_lower:
            return self._mock_modules_api(method, path, body)

        # 系统信息
        if "/api/system/info" in path_lower or "/api/system/stats" in path_lower:
            return self._mock_system_stats()

        # 配置管理
        if "/api/config" in path_lower:
            return self._mock_config_api(method, path, body)

        # 记忆系统
        if "/api/memory" in path_lower or "/api/v1/memory" in path_lower:
            return self._mock_memory_api(method, path, body)

        # 技能系统
        if "/api/skills" in path_lower or "/api/v1/skills" in path_lower:
            return self._mock_skills_api(method, path, body)

        # 场景引擎
        if "/api/scenes" in path_lower or "/api/v1/scenes" in path_lower:
            return self._mock_scenes_api(method, path, body)

        # 工作流
        if "/api/workflows" in path_lower or "/api/v1/workflows" in path_lower:
            return self._mock_workflows_api(method, path, body)

        # 任务管理
        if "/api/tasks" in path_lower or "/api/v1/tasks" in path_lower:
            return self._mock_tasks_api(method, path, body)

        # 对话 / Agent
        if "/api/chat" in path_lower or "/api/v1/chat" in path_lower or "/api/agents" in path_lower:
            return self._mock_chat_api(method, path, body)

        # 网关管理
        if "/gateway/routes" in path_lower:
            return self._mock_gateway_routes(method, path, body)
        if "/gateway/status" in path_lower:
            return self._mock_gateway_status()
        if "/gateway/metrics" in path_lower:
            return self._mock_gateway_metrics()

        # 审计日志
        if "/api/audit" in path_lower:
            return self._mock_audit_api(method, path, body)

        # 备份管理
        if "/api/backup" in path_lower:
            return self._mock_backup_api(method, path, body)

        # 默认成功响应
        return {
            "code": 0,
            "message": "success",
            "data": {
                "path": path,
                "method": method,
                "mock": True,
            },
        }

    # ============================================================
    # Mock API 处理器
    # ============================================================

    def _is_authenticated(self) -> bool:
        """检查是否已认证"""
        if not self.access_token:
            return False
        if self.use_mock:
            # 在 mock 模式下，token 在会话中或以 mock_access_ 开头都视为有效
            # （set_token 手动设置的 token 也应该有效）
            if self.access_token in self._mock_sessions:
                return True
            if self.access_token.startswith("mock_access_"):
                return True
            return False
        return True

    def _mock_health_check(self) -> Dict[str, Any]:
        """Mock 健康检查"""
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "service": "yunxi-api-gateway",
                "version": "2.0.0",
                "routes_count": len(self._mock_modules),
                "timestamp": int(time.time()),
            },
        }

    def _mock_get_user_info(self) -> Dict[str, Any]:
        """Mock 获取用户信息"""
        if not self.access_token:
            return {"code": 401, "message": "未登录", "data": None}

        # 优先从 current_user 获取
        if self.current_user:
            return {
                "code": 0,
                "message": "success",
                "data": self.current_user,
            }

        # 从会话中获取
        session = self._mock_sessions.get(self.access_token)
        if session:
            user_info = {
                "id": session.get("user_id"),
                "username": session.get("username"),
                "role": session.get("role"),
            }
            return {
                "code": 0,
                "message": "success",
                "data": user_info,
            }

        # token 以 mock_access_ 开头但不在会话中（手动 set_token 的情况）
        if self.access_token.startswith("mock_access_"):
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "id": 1,
                    "username": "admin",
                    "email": "admin@yunxi.local",
                    "role": "admin",
                },
            }

        return {"code": 401, "message": "未登录", "data": None}

    def _mock_change_password(self, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 修改密码"""
        if not body:
            return {"code": 400, "message": "参数错误", "data": None}

        old_password = body.get("old_password", "")
        new_password = body.get("new_password", "")

        if not old_password or not new_password:
            return {"code": 400, "message": "密码不能为空", "data": None}

        if len(new_password) < 8:
            return {"code": 400, "message": "新密码长度不足", "data": None}

        # 验证旧密码
        if self.current_user:
            username = self.current_user["username"]
            user = self._mock_users.get(username)
            if user:
                expected_password = user.get("_plain_password", "")
                if username == "admin" and not expected_password:
                    expected_password = "admin123456"
                if expected_password and old_password != expected_password:
                    return {"code": 401, "message": "旧密码错误", "data": None}
                # 更新密码
                user["_plain_password"] = new_password

        # 密码修改成功后，旧 token 失效
        old_token = self.access_token
        if old_token and old_token in self._mock_sessions:
            del self._mock_sessions[old_token]

        # 生成新 token
        if self.current_user:
            new_token = f"mock_access_{uuid.uuid4().hex}"
            self.access_token = new_token
            self._mock_sessions[new_token] = {
                "user_id": self.current_user["id"],
                "username": self.current_user["username"],
                "role": self.current_user["role"],
                "created_at": time.time(),
                "expires_at": time.time() + 3600,
            }

        return {
            "code": 0,
            "message": "密码修改成功",
            "data": {"token_invalidated": True},
        }

    def _mock_register(self, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 用户注册"""
        if not body:
            return {"code": 400, "message": "参数错误", "data": None}

        username = body.get("username", "")
        password = body.get("password", "")
        email = body.get("email", "")

        if not username or not password:
            return {"code": 400, "message": "用户名和密码不能为空", "data": None}

        if username in self._mock_users:
            return {"code": 409, "message": "用户名已存在", "data": None}

        user_id = len(self._mock_users) + 1
        self._mock_users[username] = {
            "id": user_id,
            "username": username,
            "email": email,
            "password_hash": f"mock_hash_{uuid.uuid4().hex[:8]}",
            "_plain_password": password,
            "role": "user",
            "is_active": True,
            "first_login": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        return {
            "code": 0,
            "message": "注册成功",
            "data": {
                "id": user_id,
                "username": username,
                "email": email,
            },
        }

    def _mock_users_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 用户管理 API"""
        if method == "GET":
            # 用户列表
            users_list = [
                {k: v for k, v in u.items() if k != "password_hash"}
                for u in self._mock_users.values()
            ]
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": users_list,
                    "total": len(users_list),
                    "page": 1,
                    "page_size": 20,
                },
            }
        elif method == "POST":
            # 创建用户
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            username = body.get("username", "")
            if username in self._mock_users:
                return {"code": 409, "message": "用户名已存在", "data": None}
            user_id = len(self._mock_users) + 1
            self._mock_users[username] = {
                "id": user_id,
                "username": username,
                "email": body.get("email", ""),
                "password_hash": f"mock_hash_{uuid.uuid4().hex[:8]}",
                "_plain_password": body.get("password", ""),
                "role": body.get("role", "user"),
                "is_active": body.get("is_active", True),
                "first_login": True,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            return {
                "code": 0,
                "message": "用户创建成功",
                "data": {"id": user_id, "username": username},
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_modules_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 模块管理 API"""
        if method == "GET":
            modules_list = list(self._mock_modules.values())
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": modules_list,
                    "total": len(modules_list),
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_system_stats(self) -> Dict[str, Any]:
        """Mock 系统统计"""
        running_count = sum(
            1 for m in self._mock_modules.values() if m["status"] == "running"
        )
        return {
            "code": 0,
            "message": "success",
            "data": {
                "total_modules": len(self._mock_modules),
                "running_modules": running_count,
                "total_users": len(self._mock_users),
                "active_users": sum(
                    1 for u in self._mock_users.values() if u["is_active"]
                ),
                "health_score": 95,
                "uptime_seconds": 86400,
                "timestamp": int(time.time()),
            },
        }

    def _mock_config_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 配置管理 API"""
        if method == "GET":
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "system_name": "云汐系统",
                    "version": "1.0.0",
                    "language": "zh-CN",
                    "theme": "dark",
                    "notifications_enabled": True,
                },
            }
        elif method in ("PUT", "PATCH"):
            if body:
                for key, value in body.items():
                    self._mock_data_store[f"config:{key}"] = value
            return {"code": 0, "message": "配置更新成功", "data": body}
        return {"code": 0, "message": "success", "data": None}

    def _mock_memory_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 记忆系统 API"""
        if method == "POST" and "search" in path:
            # 记忆搜索
            query = body.get("query", "") if body else ""
            results = [
                m for m in self._mock_memories
                if query.lower() in m.get("content", "").lower()
            ]
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "results": results[:10],
                    "total": len(results),
                    "query": query,
                },
            }
        elif method == "POST":
            # 写入记忆
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            memory_id = f"mem_{uuid.uuid4().hex[:12]}"
            memory = {
                "id": memory_id,
                "content": body.get("content", ""),
                "type": body.get("type", "general"),
                "tags": body.get("tags", []),
                "importance": body.get("importance", 0.5),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._mock_memories.append(memory)
            return {
                "code": 0,
                "message": "记忆存储成功",
                "data": memory,
            }
        elif method == "GET":
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": self._mock_memories[:20],
                    "total": len(self._mock_memories),
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_skills_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 技能系统 API"""
        if method == "GET":
            skills_list = list(self._mock_skills.values())
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": skills_list,
                    "total": len(skills_list),
                },
            }
        elif method == "POST" and "execute" in path:
            # 执行技能
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            skill_id = body.get("skill_id", "")
            return {
                "code": 0,
                "message": "技能执行成功",
                "data": {
                    "skill_id": skill_id,
                    "result": f"执行结果: {skill_id}",
                    "duration_ms": 150,
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_scenes_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 场景引擎 API"""
        if method == "GET":
            scenes_list = list(self._mock_scenes.values())
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": scenes_list,
                    "total": len(scenes_list),
                },
            }
        elif method == "POST" and "switch" in path:
            # 切换场景
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            scene_id = body.get("scene_id", "")
            if scene_id not in self._mock_scenes:
                return {"code": 404, "message": "场景不存在", "data": None}
            # 停用其他场景
            for sid in self._mock_scenes:
                self._mock_scenes[sid]["active"] = (sid == scene_id)
            return {
                "code": 0,
                "message": "场景切换成功",
                "data": {"active_scene": scene_id},
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_workflows_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 工作流 API"""
        if method == "GET":
            wf_list = list(self._mock_workflows.values())
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": wf_list,
                    "total": len(wf_list),
                },
            }
        elif method == "POST" and "execute" in path:
            # 执行工作流
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            wf_id = body.get("workflow_id", "")
            if wf_id not in self._mock_workflows:
                return {"code": 404, "message": "工作流不存在", "data": None}
            execution_id = f"exec_{uuid.uuid4().hex[:12]}"
            return {
                "code": 0,
                "message": "工作流执行成功",
                "data": {
                    "execution_id": execution_id,
                    "workflow_id": wf_id,
                    "status": "completed",
                    "duration_ms": 1200,
                    "steps_completed": self._mock_workflows[wf_id].get("steps", 0),
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_tasks_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 任务管理 API"""
        if method == "POST":
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            task_id = f"task_{uuid.uuid4().hex[:12]}"
            task = {
                "id": task_id,
                "type": body.get("type", "general"),
                "title": body.get("title", ""),
                "status": "queued",
                "priority": body.get("priority", "normal"),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._mock_tasks[task_id] = task
            return {
                "code": 0,
                "message": "任务创建成功",
                "data": task,
            }
        elif method == "GET":
            tasks_list = list(self._mock_tasks.values())
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": tasks_list,
                    "total": len(tasks_list),
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_chat_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 对话 API"""
        if method == "POST":
            if not body:
                return {"code": 400, "message": "参数错误", "data": None}
            message = body.get("message", "")
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "reply": f"收到消息：{message}。这是 E2E 测试的模拟回复。",
                    "conversation_id": f"conv_{uuid.uuid4().hex[:12]}",
                    "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                    "agent": "principal",
                    "timestamp": int(time.time()),
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_gateway_routes(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 网关路由 API"""
        import re

        # 检查是否是单个路由详情
        single_route_match = re.match(r'^/gateway/routes/([^/]+)$', path)
        if single_route_match and method == "GET":
            route_key = single_route_match.group(1)
            route_info = self._get_route_detail(route_key)
            if route_info is None:
                return {"code": 404, "message": f"Route '{route_key}' not found", "data": None}
            return {"code": 0, "message": "success", "data": route_info}

        # 检查是否是 reload 单个路由
        reload_match = re.match(r'^/gateway/routes/([^/]+)/reload$', path)
        if reload_match and method == "POST":
            route_key = reload_match.group(1)
            route_info = self._get_route_detail(route_key)
            if route_info is None:
                return {"code": 404, "message": f"Route '{route_key}' not found", "data": None}
            return {
                "code": 0,
                "message": f"Route '{route_key}' reloaded successfully",
                "data": {"route_key": route_key, "reloaded": True},
            }

        # 检查是否是 reload 所有路由
        if path == "/gateway/routes/reload" and method == "POST":
            return {
                "code": 0,
                "message": f"All {len(self._mock_modules)} routes reloaded successfully",
                "data": {"reloaded_count": len(self._mock_modules)},
            }

        # 默认：路由列表
        routes = []
        for key, module in self._mock_modules.items():
            routes.append(self._get_route_detail(key))

        return {
            "code": 0,
            "message": "success",
            "data": {
                "total": len(routes),
                "enabled_count": len(routes),
                "routes": routes,
            },
        }

    def _get_route_detail(self, key: str) -> Optional[Dict[str, Any]]:
        """获取单个路由详情"""
        module = self._mock_modules.get(key)
        if not module:
            return None

        # 不同模块有不同的限流级别和熔断阈值
        tier_map = {
            "m8": "admin",
            "m10": "admin",
            "m11": "mcp",
        }
        tier = tier_map.get(key, "public")

        rate_limit_map = {
            "m1": 120, "m5": 120, "m8": 120, "m10": 120, "m11": 120,
        }
        rate_limit = rate_limit_map.get(key, 60)

        cb_threshold_map = {
            "m3": 3, "m8": 10, "m12": 10,
        }
        cb_threshold = cb_threshold_map.get(key, 5)

        cb_recovery_map = {
            "m3": 60, "m8": 15, "m12": 15,
        }
        cb_recovery = cb_recovery_map.get(key, 30)

        public_paths = ["/health"]
        if key == "m8":
            public_paths.extend(["/metrics", "/api/v1/auth/login", "/api/v1/status", "/api/v1/public"])
        if key == "m12":
            public_paths.extend([
                "/api/v1/auth/login", "/api/v1/auth/register",
                "/api/v1/auth/password/forgot", "/api/v1/auth/password/reset",
                "/api/v1/status", "/api/v1/public-key",
            ])
        if key == "m2":
            public_paths.extend(["/api/v1/skills/public", "/api/v1/categories"])
        if key == "m4":
            public_paths.extend(["/api/v1/scenes/public", "/api/v1/templates"])
        if key == "m11":
            public_paths.extend(["/api/v1/tools/public", "/sse"])

        supports_sse = key in ["m1", "m3", "m4", "m6", "m7", "m9", "m10", "m11"]
        supports_ws = key in ["m1", "m3", "m6", "m7", "m9", "m10", "m11"]

        return {
            "key": key,
            "name": module["name"],
            "description": f"{module['name']} 服务",
            "prefix": f"/{key}",
            "target_url": f"http://localhost:80{key[1:].zfill(2)}",
            "enabled": module["status"] == "running",
            "timeout": 60.0 if key in ["m1", "m3", "m4", "m7", "m9"] else 30.0,
            "health_path": "/health",
            "health_timeout": 5.0,
            "auth_required": True,
            "public_paths": public_paths,
            "rate_limit_per_minute": rate_limit,
            "rate_limit_per_ip": rate_limit // 2,
            "rate_limit_tier": tier,
            "supports_websocket": supports_ws,
            "supports_sse": supports_sse,
            "cb_failure_threshold": cb_threshold,
            "cb_recovery_time": cb_recovery,
        }

    def _mock_gateway_status(self) -> Dict[str, Any]:
        """Mock 网关状态"""
        running_count = sum(
            1 for m in self._mock_modules.values() if m["status"] == "running"
        )

        # 模块详情
        module_details = {}
        for key, module in self._mock_modules.items():
            module_details[key] = {
                "status": "healthy" if module["status"] == "running" else "unhealthy",
                "version": module.get("version", "1.0.0"),
                "last_check": int(time.time()),
            }

        # 熔断器详情
        cb_details = {}
        for key in self._mock_modules:
            cb_details[key] = {
                "state": "closed",
                "failure_count": 0,
                "success_count": 100,
            }

        return {
            "code": 0,
            "message": "success",
            "data": {
                "gateway": {
                    "status": "healthy",
                    "version": "2.0.0",
                    "uptime": 86400,
                    "timestamp": int(time.time()),
                },
                "modules": {
                    "total": len(self._mock_modules),
                    "healthy": running_count,
                    "unhealthy": len(self._mock_modules) - running_count,
                    "disabled": 0,
                    "details": module_details,
                },
                "circuit_breakers": {
                    "total": len(self._mock_modules),
                    "open": 0,
                    "half_open": 0,
                    "closed": len(self._mock_modules),
                    "details": cb_details,
                },
            },
        }

    def _mock_gateway_metrics(self) -> Dict[str, Any]:
        """Mock 网关指标"""
        return {
            "code": 0,
            "message": "success",
            "data": {
                "proxy": {
                    "total_requests": 1000,
                    "success_count": 980,
                    "error_count": 20,
                    "avg_response_time_ms": 150,
                    "uptime_seconds": 86400,
                },
                "rate_limit": {
                    "total_limited": 5,
                    "per_ip_limited": 3,
                },
                "circuit_breakers": {
                    "total": len(self._mock_modules),
                    "open": 0,
                    "details": {
                        key: {"state": "closed"}
                        for key in self._mock_modules
                    },
                },
                "routes_count": len(self._mock_modules),
            },
        }

    def _mock_audit_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 审计日志 API"""
        if method == "GET":
            logs = [
                {
                    "id": i + 1,
                    "action": f"action_{i}",
                    "operator": "admin",
                    "module": "system",
                    "ip": "127.0.0.1",
                    "success": True,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                for i in range(10)
            ]
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": logs,
                    "total": 10,
                    "page": 1,
                    "page_size": 20,
                },
            }
        return {"code": 0, "message": "success", "data": None}

    def _mock_backup_api(self, method: str, path: str, body: Optional[Dict]) -> Dict[str, Any]:
        """Mock 备份管理 API"""
        if method == "POST" and "create" in path:
            backup_id = f"backup_{uuid.uuid4().hex[:12]}"
            return {
                "code": 0,
                "message": "备份创建成功",
                "data": {
                    "backup_id": backup_id,
                    "size_bytes": 1024000,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }
        elif method == "POST" and "restore" in path:
            return {
                "code": 0,
                "message": "恢复成功",
                "data": {"restored": True},
            }
        elif method == "GET":
            backups = [
                {
                    "id": f"backup_{i}",
                    "size_bytes": 1024000 * (i + 1),
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                for i in range(5)
            ]
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "items": backups,
                    "total": len(backups),
                },
            }
        return {"code": 0, "message": "success", "data": None}

    # ============================================================
    # 辅助方法
    # ============================================================

    def _build_url(self, path: str, params: Optional[Dict] = None) -> str:
        """构建完整 URL"""
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self.base_url + path

        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url += "?" + query

        return url

    def _record_request(
        self,
        method: str,
        url: str,
        status_code: int,
        duration_ms: float,
        request_body: Optional[Dict] = None,
        response_body: Optional[Dict] = None,
        error: Optional[str] = None,
    ):
        """记录请求"""
        record = RequestRecord(
            method=method,
            url=url,
            status_code=status_code,
            duration_ms=duration_ms,
            request_body=request_body,
            response_body=response_body,
            error=error,
        )
        self.stats.requests.append(record)
        self.stats.total_requests += 1
        self.stats.total_duration_ms += duration_ms
        if status_code == 200 and response_body and response_body.get("code", -1) == 0:
            self.stats.success_count += 1
        else:
            self.stats.failure_count += 1

    def create_test_user(self, username: Optional[str] = None) -> Dict[str, Any]:
        """
        创建测试用户（Mock 模式下直接创建）

        Returns:
            用户信息字典
        """
        if not username:
            username = f"e2e_test_{uuid.uuid4().hex[:8]}"

        password = "Test@123456"
        user_id = len(self._mock_users) + 1
        self._mock_users[username] = {
            "id": user_id,
            "username": username,
            "email": f"{username}@test.local",
            "password_hash": f"mock_hash_{uuid.uuid4().hex[:8]}",
            "_plain_password": password,
            "role": "user",
            "is_active": True,
            "first_login": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        return {
            "id": user_id,
            "username": username,
            "email": f"{username}@test.local",
            "role": "user",
            "password": password,
        }

    def cleanup_test_data(self, prefix: str = "e2e_test_") -> int:
        """
        清理测试数据

        Args:
            prefix: 测试数据前缀

        Returns:
            清理的数据条数
        """
        count = 0

        # 清理测试用户
        to_delete = [
            username for username in self._mock_users
            if username.startswith(prefix)
        ]
        for username in to_delete:
            del self._mock_users[username]
            count += 1

        # 清理测试会话
        to_delete_sessions = [
            token for token, session in self._mock_sessions.items()
            if session.get("username", "").startswith(prefix)
        ]
        for token in to_delete_sessions:
            del self._mock_sessions[token]

        # 清理测试记忆
        self._mock_memories = [
            m for m in self._mock_memories
            if not m.get("content", "").startswith("E2E_TEST_")
        ]

        return count

    def close(self):
        """关闭客户端"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
