"""
LLM 客户端（Mock 版本）
用于阶段一开发的模拟 LLM 客户端
"""

from typing import Optional, List, Dict, Any


class LLMClient:
    """LLM 客户端（模拟版本）

    阶段一开发使用，返回模拟响应。
    后续接入真实 LLM API 时替换实现。
    """

    def __init__(self, model: str = "mock-model", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self._mock_responses = {
            "default": "这是一个模拟响应。在真实环境中，这里会返回 LLM 的实际输出。",
        }

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """聊天补全

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            **kwargs: 其他参数

        Returns:
            响应文本
        """
        return self._mock_responses["default"]

    async def achat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """异步聊天补全"""
        return self.chat(messages, **kwargs)

    def generate(self, prompt: str, **kwargs) -> str:
        """文本生成"""
        return self._mock_responses["default"]

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "model": self.model,
            "provider": "mock",
            "status": "available",
        }
