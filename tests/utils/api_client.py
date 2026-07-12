"""
云汐系统 - 统一 API 测试客户端

封装 HTTP 请求，提供便捷的 API 调用接口，
自动处理认证、响应解析、错误处理等。
"""

import time
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple


class YunxiApiClient:
    """
    云汐系统 API 测试客户端
    
    使用示例:
        client = YunxiApiClient(base_url="http://localhost:8080")
        client.login("admin", "admin123456")
        result = client.get("/api/system/stats")
        assert result["code"] == 0
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: Optional[str] = None
        self.request_count = 0
        self.response_times = []

    # ============================================================
    # 认证方法
    # ============================================================

    def login(self, username: str = "admin", password: str = "admin123456") -> Dict[str, Any]:
        """登录并保存 Token"""
        result = self.post("/api/auth/login", {
            "username": username,
            "password": password
        })
        if result.get("code") == 0:
            self.token = result.get("data", {}).get("access_token", "")
        return result

    def logout(self) -> Dict[str, Any]:
        """登出"""
        result = self.post("/api/auth/logout", {})
        self.token = None
        return result

    def set_token(self, token: str):
        """手动设置 Token"""
        self.token = token

    # ============================================================
    # HTTP 方法
    # ============================================================

    def get(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送 GET 请求"""
        return self._request("GET", path, params=params)

    def post(self, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送 POST 请求"""
        return self._request("POST", path, body=data)

    def put(self, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送 PUT 请求"""
        return self._request("PUT", path, body=data)

    def delete(self, path: str) -> Dict[str, Any]:
        """发送 DELETE 请求"""
        return self._request("DELETE", path)

    # ============================================================
    # 核心请求方法
    # ============================================================

    def _request(self, method: str, path: str, params: Dict = None, body: Dict = None) -> Dict[str, Any]:
        """
        发送 HTTP 请求
        
        Args:
            method: HTTP 方法
            path: API 路径（相对路径或绝对路径）
            params: URL 查询参数
            body: 请求体数据
            
        Returns:
            解析后的响应字典 {code, message, data, ...}
        """
        url = self._build_url(path, params)
        self.request_count += 1

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        start_time = time.time()
        try:
            data_bytes = None
            if body is not None:
                data_bytes = json.dumps(body).encode("utf-8")

            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
                elapsed = (time.time() - start_time) * 1000
                self.response_times.append(elapsed)
                
                try:
                    return json.loads(response_body)
                except json.JSONDecodeError:
                    return {
                        "code": -1,
                        "message": "响应解析失败",
                        "data": response_body,
                        "status_code": response.status
                    }

        except urllib.error.HTTPError as e:
            elapsed = (time.time() - start_time) * 1000
            self.response_times.append(elapsed)
            try:
                error_body = e.read().decode("utf-8")
                return json.loads(error_body)
            except Exception:
                return {
                    "code": e.code,
                    "message": str(e.reason),
                    "data": None,
                    "status_code": e.code
                }

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            self.response_times.append(elapsed)
            return {
                "code": -1,
                "message": f"请求异常: {str(e)}",
                "data": None,
                "error_type": type(e).__name__
            }

    def _build_url(self, path: str, params: Dict = None) -> str:
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

    # ============================================================
    # 统计信息
    # ============================================================

    @property
    def avg_response_time(self) -> float:
        """平均响应时间（ms）"""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)

    def close(self):
        """关闭客户端（清理资源）"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
