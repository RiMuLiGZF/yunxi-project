"""
认证中间件

JWT Token 认证 + 域权限校验
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple


class AuthMiddleware:
    """
    认证中间件
    
    功能：
    - JWT Token 验证
    - Agent身份识别
    - 域权限预校验
    - 请求速率限制
    - 请求审计记录
    """

    def __init__(self, domain_manager=None, audit_logger=None, secret_key: str = None):
        self._domain = domain_manager
        self._audit = audit_logger
        self._secret_key = secret_key or ""
        self._rate_limits: Dict[str, dict] = {}  # agent_id -> {count, window_start}
        self._default_rate_limit = 1000  # 每小时1000次请求

    def authenticate(self, request: Dict) -> Tuple[bool, Dict]:
        """
        认证请求
        
        Args:
            request: 请求对象
        
        Returns:
            (是否通过, 认证信息)
        """
        # 1. 提取Token
        token = self._extract_token(request)
        if not token:
            return False, {"error": "missing_token", "agent_id": "anonymous"}

        # 2. 验证Token
        agent_info = self._verify_token(token)
        if not agent_info:
            return False, {"error": "invalid_token", "agent_id": "unknown"}

        # 3. 速率限制检查
        agent_id = agent_info.get("agent_id", "unknown")
        if not self._check_rate_limit(agent_id):
            return False, {"error": "rate_limited", "agent_id": agent_id}

        # 4. 审计记录
        if self._audit:
            self._audit.record(
                memory_id="auth",
                operation="login",
                agent_id=agent_id,
                domain=agent_info.get("domain", "private"),
                success=True,
                metadata={"request_id": request.get("request_id", "")},
            )

        return True, agent_info

    def _extract_token(self, request: Dict) -> Optional[str]:
        """从请求中提取Token"""
        # 从headers提取
        headers = request.get("headers", {})
        auth = headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        
        # 从query参数提取
        params = request.get("query_params", {})
        if "token" in params:
            return params["token"]
        
        # 从body提取
        body = request.get("body", {})
        if "token" in body:
            return body["token"]
        
        return None

    def _verify_token(self, token: str) -> Optional[Dict]:
        """
        验证JWT Token
        
        ⚠️ 此处为框架实现，实际使用需替换为真正的JWT验证
        """
        try:
            # 简化实现：解析token结构（实际应使用PyJWT）
            # 格式: base64(header).base64(payload).signature
            parts = token.split(".")
            if len(parts) != 3:
                # 非JWT格式，作为简单token处理
                return {"agent_id": token[:16], "role": "normal", "domain": "private"}

            # 解码payload
            import base64
            import json
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            
            return {
                "agent_id": payload.get("sub", "unknown"),
                "role": payload.get("role", "normal"),
                "domain": payload.get("domain", "private"),
                "exp": payload.get("exp"),
            }
        except Exception:
            return None

    def _check_rate_limit(self, agent_id: str) -> bool:
        """检查速率限制"""
        import time
        now = int(time.time())
        window = 3600  # 1小时窗口

        if agent_id not in self._rate_limits:
            self._rate_limits[agent_id] = {"count": 0, "window_start": now}

        info = self._rate_limits[agent_id]
        
        # 重置窗口
        if now - info["window_start"] > window:
            info["count"] = 0
            info["window_start"] = now

        info["count"] += 1
        return info["count"] <= self._default_rate_limit

    def check_domain_permission(self, agent_id: str, domain: str, action: str) -> bool:
        """检查域权限"""
        if self._domain:
            return self._domain.check_permission(agent_id, domain, action)
        return True  # 无管理器时默认允许

    def get_auth_stats(self) -> Dict:
        """获取认证统计"""
        return {
            "total_agents_tracked": len(self._rate_limits),
            "rate_limit": self._default_rate_limit,
        }
