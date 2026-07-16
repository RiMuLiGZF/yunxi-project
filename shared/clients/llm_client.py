"""
云汐系统 - 统一大模型客户端 LLMClient
支持多后端切换：DeepSeek API / OpenAI API / 本地 Ollama
统一接口：chat(messages) -> str

支持三层模型架构路由模式（通过 LLM_USE_ROUTER=true 启用）：
  - Tier 0: 3B 模型（常驻，处理简单任务）
  - Tier 1: 7B 模型（按需，处理中等任务）
  - Tier 2: 云端 API（兜底，处理复杂任务）
"""

import json
import time
from typing import List, Dict, Optional, AsyncIterator
from abc import ABC, abstractmethod

import httpx

from ..core.config import get_config
from ..core.logger import get_logger

logger = get_logger("yunxi.llm")


class BaseLLMProvider(ABC):
    """LLM 提供方抽象基类"""

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """同步对话"""
        pass

    @abstractmethod
    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """流式对话"""
        pass

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """文本嵌入"""
        pass


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek API 提供方"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": False,
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"DeepSeek chat error: {e}")
            raise

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }

        async with self._client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def embed(self, text: str) -> List[float]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "text-embedding-3-small",
            "input": text,
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"DeepSeek embed error: {e}")
            raise


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API 提供方（兼容 OpenAI 格式的 API 都可用）"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI chat error: {e}")
            raise

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }

        async with self._client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def embed(self, text: str) -> List[float]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "text-embedding-3-small",
            "input": text,
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"OpenAI embed error: {e}")
            raise


class OllamaProvider(BaseLLMProvider):
    """本地 Ollama 提供方"""

    def __init__(self, base_url: str, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            },
        }

        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except Exception as e:
            logger.error(f"Ollama chat error: {e}")
            raise

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncIterator[str]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            },
        }

        async with self._client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

    async def embed(self, text: str) -> List[float]:
        url = f"{self.base_url}/api/embeddings"
        payload = {
            "model": self.model,
            "prompt": text,
        }

        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("embedding", [])
        except Exception as e:
            logger.error(f"Ollama embed error: {e}")
            raise


class LLMClient:
    """
    统一大模型客户端
    支持多后端切换，配置驱动
    支持三层模型架构路由模式（可选，通过 LLM_USE_ROUTER 环境变量启用）

    两种模式：
    1. 单模型模式（默认）：所有请求走同一个 provider
    2. 三层路由模式（LLM_USE_ROUTER=true）：根据任务复杂度自动路由到 3B/7B/云端
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._config = get_config()

        # 检查是否启用三层路由模式
        self._use_router = getattr(self._config, "llm_use_router", False)
        self._router = None

        if self._use_router:
            # 三层路由模式：惰性初始化 router（需要 async 初始化）
            logger.info("LLMClient running in three-tier router mode")
        else:
            # 单模型模式
            self._provider = self._create_provider()
            logger.info(f"LLMClient initialized with provider: {self._config.llm_provider}")

        self._initialized = True

    def _create_provider(self) -> BaseLLMProvider:
        """根据配置创建 LLM 提供方"""
        provider = self._config.llm_provider.lower()

        if provider == "deepseek":
            return DeepSeekProvider(
                api_key=self._config.llm_api_key,
                base_url=self._config.llm_base_url,
                model=self._config.llm_model,
                timeout=self._config.llm_timeout,
            )
        elif provider == "openai":
            return OpenAIProvider(
                api_key=self._config.llm_api_key,
                base_url=self._config.llm_base_url,
                model=self._config.llm_model,
                timeout=self._config.llm_timeout,
            )
        elif provider == "ollama":
            return OllamaProvider(
                base_url=self._config.ollama_base_url,
                model=self._config.ollama_model,
                timeout=self._config.ollama_timeout,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def _get_router(self):
        """获取三层路由调度器（惰性初始化）"""
        if self._router is None:
            from ..model_router import get_model_router_async
            self._router = await get_model_router_async()
        return self._router

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        对话接口

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            **kwargs: 其他参数（model, temperature, max_tokens 等）

        Returns:
            模型回复文本
        """
        start_time = time.time()
        try:
            if self._use_router:
                # 三层路由模式
                router = await self._get_router()
                result = await router.chat(messages, **kwargs)
            else:
                # 单模型模式
                result = await self._provider.chat(messages, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"LLM chat completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"LLM chat failed after {elapsed:.2f}s: {e}")
            raise

    async def chat_simple(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        强制使用 3B 轻量模型（仅路由模式下有效）

        适用于简单对话、状态查询等轻量任务。
        非路由模式下回退到普通 chat。
        """
        if self._use_router:
            router = await self._get_router()
            return await router.chat_simple(messages, **kwargs)
        return await self.chat(messages, **kwargs)

    async def chat_heavy(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        强制使用 7B 主力模型（仅路由模式下有效）

        适用于代码生成、分析总结等需要一定推理能力的任务。
        非路由模式下回退到普通 chat。
        """
        if self._use_router:
            router = await self._get_router()
            return await router.chat_heavy(messages, **kwargs)
        return await self.chat(messages, **kwargs)

    async def chat_cloud(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        强制使用云端 API 模型（仅路由模式下有效）

        适用于复杂专业任务、创意写作等。
        非路由模式下回退到普通 chat。
        """
        if self._use_router:
            router = await self._get_router()
            return await router.chat_cloud(messages, **kwargs)
        return await self.chat(messages, **kwargs)

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """
        流式对话接口

        Args:
            messages: 消息列表
            **kwargs: 其他参数

        Yields:
            逐块返回的文本
        """
        async for chunk in self._provider.chat_stream(messages, **kwargs):
            yield chunk

    async def embed(self, text: str) -> List[float]:
        """
        文本嵌入接口

        Args:
            text: 待嵌入的文本

        Returns:
            嵌入向量
        """
        return await self._provider.embed(text)

    def switch_provider(self, provider: str, **kwargs):
        """
        切换 LLM 提供方（运行时切换）

        注意：路由模式下此方法仅影响 fallback 行为，
        实际路由由 ThreeTierModelRouter 控制。

        Args:
            provider: 提供方名称 (deepseek/openai/ollama)
            **kwargs: 额外配置参数
        """
        if self._use_router:
            logger.warning("switch_provider called in router mode, use router config instead")
            return
        self._config.llm_provider = provider
        if "api_key" in kwargs:
            self._config.llm_api_key = kwargs["api_key"]
        if "base_url" in kwargs:
            self._config.llm_base_url = kwargs["base_url"]
        if "model" in kwargs:
            self._config.llm_model = kwargs["model"]
        self._provider = self._create_provider()
        logger.info(f"LLM provider switched to: {provider}")

    def get_router_stats(self) -> dict:
        """获取三层路由调度器的统计信息（仅路由模式下有效）"""
        if not self._use_router or self._router is None:
            return {"router_mode": False}
        return self._router.stats()


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    return LLMClient()
