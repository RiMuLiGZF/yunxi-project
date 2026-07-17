"""
Codex Agent 联邦注册与密钥管理工具
====================================

将 Codex 代码专家 Agent 注册到 M1 联邦调度系统，支持双模式：
  - 本地模式：Ollama qwen2.5:7b 驱动（零成本）
  - API 模式：OpenAI/Anthropic 等 API（更强能力）

API 密钥安全存储：
  - 使用 M1 联邦层的 CryptoManager（Fernet 对称加密）
  - 主密钥从环境变量 FEDERATION_MASTER_KEY 读取
  - 加密后的密钥存储在 ~/.yunxi/codex_keys.enc 中
  - 内存中不保留明文

使用方法：
    # 本地模式（默认）
    python codex_register.py --register --mode local

    # API 模式（交互式输入密钥）
    python codex_register.py --register --mode api --provider openai

    # API 模式（从环境变量读取）
    set OPENAI_API_KEY=sk-xxx
    python codex_register.py --register --mode api --provider openai --env-key OPENAI_API_KEY

    # 测试
    python codex_register.py --test --mode local

    # 列出所有 Codex Agent
    python codex_register.py --list

    # 管理密钥
    python codex_register.py --keys list
    python codex_register.py --keys add --provider openai
    python codex_register.py --keys remove --provider openai
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# 确保项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.federation.registry import ExternalAgentRegistry
from src.federation.adapters.codex_agent import CodexAgentAdapter
from src.federation.crypto_utils import get_crypto_manager, mask_api_key
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


# ── 密钥存储路径 ────────────────────────────────────────────────────────

KEYS_FILE = Path.home() / ".yunxi" / "codex_keys.enc"


# ── Codex Agent 能力标签 ───────────────────────────────────────────────

CODEX_CAPABILITIES_CODE = [
    "代码生成",
    "代码审查",
    "Bug修复",
    "代码解释",
    "重构建议",
    "测试生成",
    "架构设计",
    "性能优化",
    "多语言支持",
    "MCP工具调用",
]

CODEX_DESCRIPTION_LOCAL = """
Codex 代码助手 — 基于本地 qwen2.5:7b 模型驱动的代码专家。
支持代码生成、审查、Bug 修复、重构建议等。
零 API 成本，数据完全本地处理，隐私安全。
""".strip()

CODEX_DESCRIPTION_API = """
Codex 代码专家 — 基于云端 API 的高级代码智能体。
支持复杂架构设计、深度代码审查、多语言高级生成。
需配置 API 密钥，按调用量计费。
""".strip()


# ── 密钥管理 ────────────────────────────────────────────────────────────

def _ensure_keys_dir() -> None:
    """确保密钥存储目录存在"""
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_keys() -> dict[str, str]:
    """加载加密存储的 API 密钥

    Returns:
        {provider: encrypted_key} 字典
    """
    if not KEYS_FILE.exists():
        return {}

    try:
        encrypted_data = KEYS_FILE.read_text(encoding="utf-8")
        crypto = get_crypto_manager()
        decrypted = crypto.decrypt(encrypted_data, caller_id="codex_key_manager")
        return json.loads(decrypted)
    except Exception as exc:
        print(f"⚠️  加载密钥文件失败: {exc}")
        return {}


def save_keys(keys: dict[str, str]) -> None:
    """保存加密后的 API 密钥

    Args:
        keys: {provider: plaintext_key} 字典（明文，将被加密存储）
    """
    _ensure_keys_dir()
    crypto = get_crypto_manager()
    data_str = json.dumps(keys, ensure_ascii=False)
    encrypted = crypto.encrypt(data_str)
    KEYS_FILE.write_text(encrypted, encoding="utf-8")
    print(f"✅ 密钥已加密保存到: {KEYS_FILE}")


def add_key(provider: str, api_key: str) -> None:
    """添加/更新一个 API 密钥"""
    keys = load_keys()
    keys[provider] = api_key
    save_keys(keys)
    print(f"✅ {provider} API 密钥已保存")
    print(f"   密钥预览: {mask_api_key(api_key)}")


def remove_key(provider: str) -> None:
    """移除一个 API 密钥"""
    keys = load_keys()
    if provider in keys:
        del keys[provider]
        save_keys(keys)
        print(f"✅ {provider} API 密钥已移除")
    else:
        print(f"⚠️  未找到 {provider} 的密钥")


def list_keys() -> None:
    """列出所有已存储的密钥（仅显示服务商和掩码）"""
    keys = load_keys()
    crypto = get_crypto_manager()

    if not keys:
        print("\n📭 没有存储的 API 密钥")
        return

    print(f"\n🔐 已存储的 API 密钥（共 {len(keys)} 个）:")
    print("-" * 50)
    for provider, key in sorted(keys.items()):
        # 解密后掩码显示
        try:
            decrypted = crypto.decrypt(key, caller_id="codex_key_manager")
            masked = mask_api_key(decrypted)
        except Exception:
            masked = "（解密失败）"
        print(f"  • {provider:<15} {masked}")
    print()


def get_key(provider: str) -> str:
    """获取指定服务商的明文密钥

    Args:
        provider: 服务商名称

    Returns:
        明文字符串，未找到返回空字符串
    """
    keys = load_keys()
    if provider not in keys:
        return ""

    crypto = get_crypto_manager()
    try:
        return crypto.decrypt(keys[provider], caller_id="codex_agent_init")
    except Exception as exc:
        print(f"⚠️  解密 {provider} 密钥失败: {exc}")
        return ""


# ── 联邦注册 ────────────────────────────────────────────────────────────

def register_codex_agent(
    registry: ExternalAgentRegistry,
    mode: str = "local",
    provider: str = "openai",
    api_base_url: str = "",
    model_name: str = "",
) -> str:
    """注册 Codex Agent 到联邦调度系统

    Args:
        registry: 外部 Agent 注册表
        mode: 运行模式 "local" 或 "api"
        provider: API 服务商（api 模式）
        api_base_url: API 基础 URL（api 模式，可选）
        model_name: 模型名称（可选，不填用默认）

    Returns:
        注册后的 agent_id
    """
    if mode == "local":
        config = {
            "mode": "local",
            "ollama_base_url": "http://localhost:11434",
            "model_name": model_name or "qwen2.5:7b",
            "adapter_type": "codex_agent",
            "description": CODEX_DESCRIPTION_LOCAL,
        }
        display_name = "Codex 代码助手"
        privacy = AgentPrivacyLevel.LOCAL_ONLY
        connection = ConnectionType.LOCAL
        cost_model = {"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"}
    else:
        # API 模式：从密钥存储读取
        api_key = get_key(provider)
        if not api_key:
            print(f"⚠️  未找到 {provider} 的 API 密钥，请先运行:")
            print(f"   python codex_register.py --keys add --provider {provider}")
            raise ValueError(f"缺少 {provider} API 密钥")

        # 默认 URL 映射
        default_urls = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "deepseek": "https://api.deepseek.com/v1",
            "moonshot": "https://api.moonshot.cn/v1",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "custom": "https://api.example.com/v1",
        }
        default_models = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20240620",
            "deepseek": "deepseek-coder",
            "moonshot": "moonshot-v1-8k",
            "qwen": "qwen-plus",
            "custom": "gpt-4o",
        }

        config = {
            "mode": "api",
            "api_provider": provider,
            "api_base_url": api_base_url or default_urls.get(provider, default_urls["custom"]),
            "model_name": model_name or default_models.get(provider, "gpt-4o"),
            "adapter_type": "codex_agent",
            "description": CODEX_DESCRIPTION_API,
            # 注意：api_key 不在 config 中明文存储，运行时从密钥管理读取
        }
        display_name = f"Codex 代码专家 ({provider})"
        privacy = AgentPrivacyLevel.ENHANCED
        connection = ConnectionType.API_KEY
        cost_model = {
            "input_per_1k": 0.005,
            "output_per_1k": 0.015,
            "currency": "USD",
        }

    profile = registry.register_agent(
        display_name=display_name,
        provider="Codex",
        agent_type=ExternalAgentType.CODE,
        capabilities=CODEX_CAPABILITIES_CODE,
        cost_model=cost_model,
        privacy_level=privacy,
        connection_type=connection,
        config=config,
        api_key="",  # 密钥通过密钥管理独立存储
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"\n✅ Codex Agent 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   显示名称: {profile.display_name}")
    print(f"   运行模式: {mode}")
    print(f"   模型: {config.get('model_name', 'N/A')}")
    print(f"   隐私等级: {profile.privacy_level.value}")
    print(f"   能力标签: {', '.join(profile.capabilities[:5])}...")

    return profile.agent_id


def create_codex_adapter(
    agent_id: str,
    mode: str = "local",
    provider: str = "openai",
    model_name: str = "",
    api_base_url: str = "",
) -> CodexAgentAdapter:
    """创建 Codex Agent 适配器实例

    Args:
        agent_id: Agent ID
        mode: 运行模式
        provider: API 服务商
        model_name: 模型名称
        api_base_url: API 基础 URL

    Returns:
        CodexAgentAdapter 实例
    """
    config: dict = {
        "mode": mode,
        "enable_tools": True,
    }

    if mode == "local":
        config["ollama_base_url"] = "http://localhost:11434"
        config["model_name"] = model_name or "qwen2.5:7b"
        display_name = "Codex 代码助手"
    else:
        config["api_provider"] = provider
        config["model_name"] = model_name or "gpt-4o"
        config["api_base_url"] = api_base_url or "https://api.openai.com/v1"
        # 运行时从密钥存储读取
        api_key = get_key(provider)
        config["api_key"] = api_key
        display_name = f"Codex 代码专家 ({provider})"

    adapter = CodexAgentAdapter(
        agent_id=agent_id,
        display_name=display_name,
        config=config,
        timeout=120.0,
        max_retries=1,
    )

    return adapter


async def test_codex_agent(adapter: CodexAgentAdapter) -> None:
    """测试 Codex Agent 功能"""
    print("\n" + "=" * 60)
    print("🧪 Codex Agent 功能测试")
    print("=" * 60)

    # 健康检查
    print("\n📊 健康检查...")
    health = await adapter.health_check()
    print(f"   状态: {'✅ 健康' if health['healthy'] else '❌ 异常'}")
    print(f"   信息: {health['message']}")
    print(f"   延迟: {health['latency_ms']:.2f}ms")

    if not health["healthy"]:
        print("\n⚠️  健康检查未通过，跳过功能测试")
        return

    # 代码生成测试
    print("\n💻 代码生成测试...")
    test_cases = [
        ("用 Python 写一个快速排序函数，带类型注解和 docstring", "代码生成"),
        ("解释这段代码的作用：\n```python\ndef fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n```", "代码解释"),
    ]

    for prompt, test_name in test_cases:
        print(f"\n   测试 [{test_name}]: {prompt[:50]}...")
        result = await adapter.invoke(
            prompt=prompt,
            system_prompt="你是专业的代码专家，请简洁准确地回答问题。不需要调用工具。",
            temperature=0.2,
            max_tokens=500,
        )

        if result["success"]:
            print(f"   ✅ 成功")
            print(f"   输出预览: {result['output'][:120]}...")
            print(f"   耗时: {result['latency_ms']:.0f}ms | "
                  f"Tokens: {result['input_tokens']}+{result['output_tokens']}")
        else:
            print(f"   ❌ 失败: {result['error']}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


def list_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有 Codex Agent"""
    agents = [a for a in registry.list_agents() if a.provider == "Codex"]

    print(f"\n📋 已注册的 Codex Agent（共 {len(agents)} 个）:")
    print("-" * 60)

    if not agents:
        print("   （暂无）")
    else:
        for agent in agents:
            mode = agent.config.get("mode", "unknown")
            model = agent.config.get("model_name", "unknown")
            status_icon = "✅" if agent.status == "active" else "⏸️"
            print(f"\n{status_icon} {agent.display_name}")
            print(f"   ID: {agent.agent_id}")
            print(f"   模式: {mode}")
            print(f"   模型: {model}")
            print(f"   状态: {agent.status}")
            print(f"   能力: {', '.join(agent.capabilities[:4])}...")

    print()


# ── 主入口 ──────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Codex Agent 联邦注册与密钥管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 本地模式注册
  python codex_register.py --register --mode local

  # API 模式注册（先添加密钥）
  python codex_register.py --keys add --provider openai
  python codex_register.py --register --mode api --provider openai

  # 测试本地模式
  python codex_register.py --test --mode local

  # 列出所有 Codex Agent
  python codex_register.py --list

  # 密钥管理
  python codex_register.py --keys list
  python codex_register.py --keys add --provider anthropic
  python codex_register.py --keys remove --provider openai
        """,
    )

    # 注册/注销/列表
    parser.add_argument("--register", action="store_true", help="注册 Codex Agent")
    parser.add_argument("--list", action="store_true", help="列出所有 Codex Agent")

    # 模式与配置
    parser.add_argument("--mode", choices=["local", "api"], default="local", help="运行模式")
    parser.add_argument("--provider", default="openai", help="API 服务商 (openai/anthropic/deepseek/moonshot/qwen/custom)")
    parser.add_argument("--model", default="", help="模型名称（可选，使用默认）")
    parser.add_argument("--api-base-url", default="", help="自定义 API 基础 URL")

    # 测试
    parser.add_argument("--test", action="store_true", help="测试 Codex Agent")

    # 密钥管理子命令
    parser.add_argument("--keys", choices=["list", "add", "remove"], help="API 密钥管理")
    parser.add_argument("--env-key", default="", help="从指定环境变量读取 API Key（--keys add 时使用）")

    args = parser.parse_args()

    # 如果没有指定任何操作，显示帮助
    if not any([args.register, args.list, args.test, args.keys]):
        parser.print_help()
        return

    registry = ExternalAgentRegistry()

    # ── 密钥管理 ──
    if args.keys == "list":
        list_keys()
        return

    if args.keys == "add":
        # 从环境变量读取或交互式输入
        api_key = ""
        if args.env_key:
            api_key = os.environ.get(args.env_key, "")
            if not api_key:
                print(f"⚠️  环境变量 {args.env_key} 未设置")
                return
        else:
            import getpass
            api_key = getpass.getpass(f"请输入 {args.provider} API Key: ").strip()

        if not api_key:
            print("⚠️  API Key 不能为空")
            return

        add_key(args.provider, api_key)
        return

    if args.keys == "remove":
        remove_key(args.provider)
        return

    # ── 注册 ──
    if args.register:
        print(f"\n🚀 正在注册 Codex Agent（模式: {args.mode}）...")
        agent_id = register_codex_agent(
            registry,
            mode=args.mode,
            provider=args.provider,
            api_base_url=args.api_base_url,
            model_name=args.model,
        )

        if args.test:
            adapter = create_codex_adapter(
                agent_id=agent_id,
                mode=args.mode,
                provider=args.provider,
                model_name=args.model,
                api_base_url=args.api_base_url,
            )
            await test_codex_agent(adapter)
            await adapter.close()

        return

    # ── 列表 ──
    if args.list:
        list_agents(registry)
        return

    # ── 测试（直接测试，不走注册表）──
    if args.test:
        adapter = create_codex_adapter(
            agent_id="codex_test_direct",
            mode=args.mode,
            provider=args.provider,
            model_name=args.model,
            api_base_url=args.api_base_url,
        )
        await test_codex_agent(adapter)
        await adapter.close()
        return


if __name__ == "__main__":
    asyncio.run(main())
