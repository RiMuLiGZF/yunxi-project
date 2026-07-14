"""
Hermes Agent 联邦注册脚本
=========================

将 Hermes Agent 注册到 M1 联邦调度系统，作为外部 Agent 使用。

接入方案：方案一（M1 联邦 + MCP 协议层）
- 位置：M1-agent-hub/federation/（联邦调度层）
- 适配器：federation/adapters/hermes_agent.py
- 工具调用：通过 MCP 协议调用 M2 Skills

使用方法：
    python hermes_register.py --register    # 注册 Hermes Agent
    python hermes_register.py --list        # 列出所有已注册 Agent
    python hermes_register.py --test        # 测试 Hermes Agent 调用
    python hermes_register.py --unregister  # 注销 Hermes Agent
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 确保项目路径在 sys.path 中
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from federation.registry import ExternalAgentRegistry
from federation.adapters.hermes_agent import HermesAgentAdapter
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


# Hermes Agent 默认配置
HERMES_DEFAULT_CONFIG = {
    "ollama_base_url": "http://localhost:11434",
    "model_name": "qwen2.5:7b",
    "mcp_server_url": "http://localhost:8002/mcp/v1",
    "max_iterations": 8,
    "temperature": 0.7,
    "timeout": 120.0,
    "max_retries": 1,
}

HERMES_CAPABILITIES = [
    "代码生成",
    "代码审查",
    "问题解答",
    "信息检索",
    "任务规划",
    "多步推理",
    "工具调用",
    "数据分析",
    "文档处理",
    "自学习",
]

HERMES_DESCRIPTION = """
Hermes Agent — 基于本地 Ollama 大模型的自进化智能代理。
通过 ReAct 模式进行多步推理，支持 MCP 协议调用云汐技能集群。
底层驱动：qwen2.5:7b 本地模型，零 API 成本，数据完全本地处理。
""".strip()


def register_hermes_agent(
    registry: ExternalAgentRegistry,
    config: dict | None = None,
) -> str:
    """注册 Hermes Agent 到联邦调度系统

    Args:
        registry: 外部 Agent 注册表实例
        config: 自定义配置（覆盖默认配置）

    Returns:
        注册后的 agent_id
    """
    merged_config = {**HERMES_DEFAULT_CONFIG, **(config or {})}

    profile = registry.register_agent(
        display_name="Hermes 智能代理",
        provider="Hermes",
        agent_type=ExternalAgentType.CUSTOM,  # Hermes 是完整的 Agent，不属于单纯 LLM/CODE 等分类
        capabilities=HERMES_CAPABILITIES,
        cost_model={
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "per_request": 0.0,
            "currency": "USD",
        },
        privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
        connection_type=ConnectionType.LOCAL,
        config={
            "adapter_type": "hermes_agent",
            "description": HERMES_DESCRIPTION,
            **merged_config,
        },
        api_key="",  # 本地模型无需 API Key
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"✅ Hermes Agent 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   显示名称: {profile.display_name}")
    print(f"   服务商: {profile.provider}")
    print(f"   类型: {profile.agent_type.value}")
    print(f"   模型: {merged_config['model_name']}")
    print(f"   能力标签: {', '.join(profile.capabilities)}")
    print(f"   隐私等级: {profile.privacy_level.value}")
    print(f"   许可证: {profile.license.value}")

    return profile.agent_id


def create_adapter(
    agent_id: str,
    config: dict | None = None,
) -> HermesAgentAdapter:
    """创建 Hermes Agent 适配器实例

    Args:
        agent_id: Agent ID
        config: 自定义配置

    Returns:
        HermesAgentAdapter 实例
    """
    merged_config = {**HERMES_DEFAULT_CONFIG, **(config or {})}

    adapter = HermesAgentAdapter(
        agent_id=agent_id,
        display_name="Hermes 智能代理",
        config=merged_config,
        timeout=merged_config.get("timeout", 120.0),
        max_retries=merged_config.get("max_retries", 1),
    )

    return adapter


async def test_hermes_agent(adapter: HermesAgentAdapter) -> None:
    """测试 Hermes Agent 调用

    Args:
        adapter: Hermes Agent 适配器实例
    """
    print("\n" + "=" * 60)
    print("🧪 Hermes Agent 功能测试")
    print("=" * 60)

    # 健康检查
    print("\n📊 健康检查...")
    health = await adapter.health_check()
    print(f"   状态: {'✅ 健康' if health['healthy'] else '❌ 异常'}")
    print(f"   信息: {health['message']}")
    print(f"   延迟: {health['latency_ms']:.2f}ms")

    if not health["healthy"]:
        print("\n⚠️  健康检查未通过，跳过对话测试")
        return

    # 简单对话测试
    print("\n💬 简单对话测试...")
    test_prompts = [
        "用一句话介绍你自己。",
        "计算 256 * 256 等于多少？",
    ]

    for i, prompt in enumerate(test_prompts, 1):
        print(f"\n   测试 {i}: {prompt}")
        result = await adapter.invoke(
            prompt=prompt,
            system_prompt="请简洁回答，不需要调用工具。",
            temperature=0.7,
            max_tokens=300,
        )

        if result["success"]:
            print(f"   ✅ 成功")
            print(f"   回答: {result['output'][:150]}...")
            print(f"   耗时: {result['latency_ms']:.0f}ms | "
                  f"Tokens: {result['input_tokens']}+{result['output_tokens']}")
        else:
            print(f"   ❌ 失败: {result['error']}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


def list_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有已注册的外部 Agent"""
    agents = registry.list_agents()

    print(f"\n📋 已注册的外部 Agent（共 {len(agents)} 个）:")
    print("-" * 60)

    for agent in agents:
        status_icon = "✅" if agent.status == "active" else "⏸️"
        print(f"\n{status_icon} {agent.display_name}")
        print(f"   ID: {agent.agent_id}")
        print(f"   服务商: {agent.provider}")
        print(f"   类型: {agent.agent_type.value}")
        print(f"   状态: {agent.status}")
        print(f"   能力: {', '.join(agent.capabilities[:5])}{'...' if len(agent.capabilities) > 5 else ''}")
        print(f"   隐私: {agent.privacy_level.value}")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="Hermes Agent 联邦注册工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python hermes_register.py --register     # 注册 Hermes Agent
  python hermes_register.py --list         # 列出所有 Agent
  python hermes_register.py --test         # 测试 Hermes Agent
  python hermes_register.py --register --test  # 注册并测试
        """,
    )

    parser.add_argument("--register", action="store_true", help="注册 Hermes Agent")
    parser.add_argument("--unregister", action="store_true", help="注销 Hermes Agent")
    parser.add_argument("--list", action="store_true", help="列出所有已注册 Agent")
    parser.add_argument("--test", action="store_true", help="测试 Hermes Agent 调用")
    parser.add_argument("--model", type=str, default="qwen2.5:7b", help="使用的模型名称")
    parser.add_argument("--mcp-url", type=str, default="http://localhost:8002/mcp/v1", help="MCP 服务器地址")

    args = parser.parse_args()

    # 如果没有指定任何操作，默认显示帮助
    if not any([args.register, args.unregister, args.list, args.test]):
        parser.print_help()
        return

    registry = ExternalAgentRegistry()
    custom_config = {
        "model_name": args.model,
        "mcp_server_url": args.mcp_url,
    }

    if args.register:
        print("\n🚀 正在注册 Hermes Agent...")
        agent_id = register_hermes_agent(registry, custom_config)

        if args.test:
            adapter = create_adapter(agent_id, custom_config)
            await test_hermes_agent(adapter)
            await adapter.close()

    elif args.unregister:
        # 查找 Hermes Agent
        hermes_agents = [
            a for a in registry.list_agents()
            if a.provider == "Hermes"
        ]
        if hermes_agents:
            for agent in hermes_agents:
                # 注意：实际项目中应该有 unregister_agent 方法
                # 这里仅做演示
                print(f"🗑️  待注销: {agent.agent_id} ({agent.display_name})")
            print("提示：请使用 M1 管理台进行 Agent 注销操作")
        else:
            print("未找到已注册的 Hermes Agent")

    elif args.list:
        list_agents(registry)

    elif args.test:
        # 直接用适配器测试（不依赖注册表）
        adapter = create_adapter("hermes_test_direct", custom_config)
        await test_hermes_agent(adapter)
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
