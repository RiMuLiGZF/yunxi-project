"""
Explore Agent 联邦注册与管理工具
================================

「小探」研究助理 — 基于 qwen2.5:1.5b 本地模型的信息检索专家。

使用方法：
    # 注册到联邦系统
    python explore_register.py --register

    # 测试功能
    python explore_register.py --test

    # 列出所有 Explore Agent
    python explore_register.py --list

    # 使用自定义模型
    python explore_register.py --register --model qwen2.5:1.5b
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 确保项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.federation.registry import ExternalAgentRegistry
from src.federation.adapters.explore_agent import ExploreAgentAdapter
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


# ── Explore Agent 能力标签 ────────────────────────────────────────────

EXPLORE_CAPABILITIES = [
    "网页检索",
    "文档搜索",
    "信息摘要",
    "多源整合",
    "翻译辅助",
    "资料分类",
    "要点提取",
    "文献整理",
    "MCP工具调用",
    "快速响应",
]

EXPLORE_DESCRIPTION = """
「小探」研究助理 — 基于本地轻量大模型的信息检索专家。
擅长网页检索、文档搜索、信息摘要、多源整合。
轻量快速，零成本，数据完全本地处理。
""".strip()


# ── 联邦注册 ──────────────────────────────────────────────────────────

def register_explore_agent(
    registry: ExternalAgentRegistry,
    model_name: str = "qwen2.5:1.5b",
    display_name: str = "小探 研究助理",
) -> str:
    """注册 Explore Agent 到联邦调度系统

    Args:
        registry: 外部 Agent 注册表
        model_name: 模型名称
        display_name: 显示名称

    Returns:
        注册后的 agent_id
    """
    config = {
        "ollama_base_url": "http://localhost:11434",
        "model_name": model_name,
        "adapter_type": "explore_agent",
        "description": EXPLORE_DESCRIPTION,
        "personality": "小探",
        "enable_tools": True,
        "max_iterations": 5,
        "temperature": 0.5,
    }

    profile = registry.register_agent(
        display_name=display_name,
        provider="Explore",
        agent_type=ExternalAgentType.CUSTOM,  # 检索型，自定义分类
        capabilities=EXPLORE_CAPABILITIES,
        cost_model={
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "USD",
        },
        privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
        connection_type=ConnectionType.LOCAL,
        config=config,
        api_key="",  # 本地模型不需要
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"\n✅ Explore Agent 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   显示名称: {profile.display_name}")
    print(f"   模型: {model_name}")
    print(f"   人格: 小探")
    print(f"   隐私等级: {profile.privacy_level.value}")
    print(f"   能力标签: {', '.join(profile.capabilities[:5])}...")

    return profile.agent_id


def create_explore_adapter(
    agent_id: str = "explore_test_direct",
    model_name: str = "qwen2.5:1.5b",
    display_name: str = "小探 研究助理",
    enable_tools: bool = True,
) -> ExploreAgentAdapter:
    """创建 Explore Agent 适配器实例

    Args:
        agent_id: Agent ID
        model_name: 模型名称
        display_name: 显示名称
        enable_tools: 是否启用 MCP 工具

    Returns:
        ExploreAgentAdapter 实例
    """
    adapter = ExploreAgentAdapter(
        agent_id=agent_id,
        display_name=display_name,
        config={
            "ollama_base_url": "http://localhost:11434",
            "model_name": model_name,
            "enable_tools": enable_tools,
            "temperature": 0.5,
            "max_iterations": 5,
        },
        timeout=60.0,
        max_retries=1,
    )

    return adapter


async def test_explore_agent(adapter: ExploreAgentAdapter) -> None:
    """测试 Explore Agent 功能"""
    print("\n" + "=" * 60)
    print("🔍 Explore Agent 功能测试")
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

    # 测试用例（不使用工具，纯模型能力）
    test_cases = [
        ("请用 3 个要点总结一下什么是 RESTful API。", "信息摘要"),
        ("帮我列出学习 Python 的 5 个关键步骤。", "要点提取"),
        ("什么是大语言模型？请用通俗的语言解释。", "概念解释"),
    ]

    print("\n🧪 功能测试（纯推理，不使用工具）...")

    for i, (prompt, test_name) in enumerate(test_cases, 1):
        print(f"\n   测试 {i} [{test_name}]: {prompt[:40]}...")
        result = await adapter.invoke(
            prompt=prompt,
            system_prompt="请简洁回答，不需要调用工具。",
            temperature=0.5,
            max_tokens=400,
        )

        if result["success"]:
            output_preview = result['output'][:100].replace('\n', ' ')
            print(f"   ✅ 成功")
            print(f"   输出预览: {output_preview}...")
            print(f"   耗时: {result['latency_ms']:.0f}ms | "
                  f"Tokens: {result['input_tokens']}+{result['output_tokens']}")
        else:
            print(f"   ❌ 失败: {result['error']}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


def list_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有 Explore Agent"""
    agents = [a for a in registry.list_agents() if a.provider == "Explore"]

    print(f"\n📋 已注册的 Explore Agent（共 {len(agents)} 个）:")
    print("-" * 60)

    if not agents:
        print("   （暂无）")
    else:
        for agent in agents:
            model = agent.config.get("model_name", "unknown")
            personality = agent.config.get("personality", "未知")
            status_icon = "✅" if agent.status == "active" else "⏸️"
            print(f"\n{status_icon} {agent.display_name}")
            print(f"   ID: {agent.agent_id}")
            print(f"   模型: {model}")
            print(f"   人格: {personality}")
            print(f"   状态: {agent.status}")
            print(f"   能力: {', '.join(agent.capabilities[:4])}...")

    print()


# ── 主入口 ────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Explore Agent 联邦注册与管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 注册 Explore Agent
  python explore_register.py --register

  # 测试功能
  python explore_register.py --test

  # 列出所有 Explore Agent
  python explore_register.py --list

  # 使用自定义模型
  python explore_register.py --register --model qwen2.5:1.5b
  python explore_register.py --test --model qwen2.5:1.5b
        """,
    )

    parser.add_argument("--register", action="store_true", help="注册 Explore Agent")
    parser.add_argument("--list", action="store_true", help="列出所有 Explore Agent")
    parser.add_argument("--test", action="store_true", help="测试 Explore Agent")
    parser.add_argument("--model", default="qwen2.5:1.5b", help="使用的模型名称")
    parser.add_argument("--name", default="小探 研究助理", help="显示名称")

    args = parser.parse_args()

    # 如果没有指定任何操作，显示帮助
    if not any([args.register, args.list, args.test]):
        parser.print_help()
        return

    registry = ExternalAgentRegistry()

    if args.register:
        print(f"\n🚀 正在注册 Explore Agent（模型: {args.model}）...")
        agent_id = register_explore_agent(registry, args.model, args.name)

        if args.test:
            adapter = create_explore_adapter(agent_id, args.model, args.name)
            await test_explore_agent(adapter)
            await adapter.close()

        return

    if args.list:
        list_agents(registry)
        return

    if args.test:
        adapter = create_explore_adapter(
            model_name=args.model,
            display_name=args.name,
            enable_tools=True,
        )
        await test_explore_agent(adapter)
        await adapter.close()
        return


if __name__ == "__main__":
    asyncio.run(main())
