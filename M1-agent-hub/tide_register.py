"""
潮汐系统 Agent 联邦注册与管理工具
====================================

「潮汐管家」— M5 潮汐记忆系统的智能代理。

使用方法：
    # 注册到联邦系统
    python tide_register.py --register

    # 测试功能
    python tide_register.py --test

    # 查看所有潮汐 Agent
    python tide_register.py --list

    # 指定 M5 服务地址
    python tide_register.py --register --m5-url http://localhost:8005
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from federation.registry import ExternalAgentRegistry
from federation.adapters.tide_agent import TideAgentAdapter
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


TIDE_CAPABILITIES = [
    "记忆检索",
    "记忆归档",
    "记忆巩固",
    "人格偏好管理",
    "记忆统计分析",
    "四层潮汐存储",
    "RBAC权限控制",
    "加密存储",
    "情绪记忆",
    "睡眠巩固",
]

TIDE_DESCRIPTION = """
潮汐管家 — M5 潮汐记忆系统的智能代理。
负责记忆的检索、归档、巩固和人格偏好管理。
四层潮汐存储结构，数据完全本地加密存储。
""".strip()


def register_tide_agent(
    registry: ExternalAgentRegistry,
    m5_base_url: str = "http://localhost:8005",
    model_name: str = "qwen2.5:3b",
    display_name: str = "潮汐管家",
) -> str:
    """注册潮汐系统 Agent"""

    config = {
        "m5_base_url": m5_base_url,
        "ollama_base_url": "http://localhost:11434",
        "model_name": model_name,
        "adapter_type": "tide_agent",
        "description": TIDE_DESCRIPTION,
        "default_domain": "private",
        "default_layers": ["l1_shallow", "l2_deep"],
        "enable_llm_enhance": True,
        "temperature": 0.3,
    }

    profile = registry.register_agent(
        display_name=display_name,
        provider="Tide",
        agent_type=ExternalAgentType.CUSTOM,
        capabilities=TIDE_CAPABILITIES,
        cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
        privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
        connection_type=ConnectionType.LOCAL,
        config=config,
        api_key="",
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"\n✅ 潮汐系统 Agent 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   显示名称: {profile.display_name}")
    print(f"   M5 地址: {m5_base_url}")
    print(f"   推理模型: {model_name}")
    print(f"   隐私等级: {profile.privacy_level.value}")
    print(f"   能力: {', '.join(profile.capabilities[:5])}...")

    return profile.agent_id


def create_tide_adapter(
    agent_id: str = "tide_test_direct",
    m5_base_url: str = "http://localhost:8005",
    model_name: str = "qwen2.5:3b",
    display_name: str = "潮汐管家",
) -> TideAgentAdapter:
    """创建潮汐 Agent 适配器"""
    return TideAgentAdapter(
        agent_id=agent_id,
        display_name=display_name,
        config={
            "m5_base_url": m5_base_url,
            "ollama_base_url": "http://localhost:11434",
            "model_name": model_name,
            "enable_llm_enhance": True,
            "temperature": 0.3,
        },
        timeout=60.0,
        max_retries=1,
    )


async def test_tide_agent(adapter: TideAgentAdapter) -> None:
    """测试潮汐 Agent 功能"""
    print("\n" + "=" * 60)
    print("🌊 潮汐系统 Agent 功能测试")
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

    # 测试用例
    test_cases = [
        ("记忆统计", "我的记忆系统现在有多少条记忆？", "stats"),
        ("偏好查询", "我的人格偏好设置是什么？", "preference"),
        ("记忆归档测试", "记住：用户喜欢简洁的回答和深色主题", "archive"),
    ]

    print("\n🧪 功能测试...")
    for test_name, prompt, expected_type in test_cases:
        print(f"\n   测试 [{test_name}]: {prompt[:40]}...")
        try:
            result = await adapter.invoke(
                prompt=prompt,
                system_prompt="你是潮汐管家，请简洁回答。",
                temperature=0.3,
                max_tokens=400,
            )

            if result["success"]:
                output_preview = result['output'][:100].replace('\n', ' ')
                task_type = result.get('task_type', 'unknown')
                print(f"   ✅ 成功 (类型: {task_type})")
                print(f"   输出预览: {output_preview}...")
                print(f"   耗时: {result['latency_ms']:.0f}ms | "
                      f"Tokens: {result['input_tokens']}+{result['output_tokens']}")
            else:
                print(f"   ❌ 失败: {result['error']}")
        except Exception as exc:
            print(f"   ⚠️  异常: {exc}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


def list_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有潮汐 Agent"""
    agents = [a for a in registry.list_agents() if a.provider == "Tide"]

    print(f"\n📋 已注册的潮汐系统 Agent（共 {len(agents)} 个）:")
    print("-" * 60)

    if not agents:
        print("   （暂无）")
    else:
        for agent in agents:
            model = agent.config.get("model_name", "unknown")
            m5_url = agent.config.get("m5_base_url", "unknown")
            status_icon = "✅" if agent.status == "active" else "⏸️"
            print(f"\n{status_icon} {agent.display_name}")
            print(f"   ID: {agent.agent_id}")
            print(f"   M5 地址: {m5_url}")
            print(f"   模型: {model}")
            print(f"   状态: {agent.status}")
            print(f"   能力: {', '.join(agent.capabilities[:4])}...")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="潮汐系统 Agent 联邦注册与管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 注册潮汐 Agent
  python tide_register.py --register

  # 测试功能
  python tide_register.py --test

  # 查看所有潮汐 Agent
  python tide_register.py --list

  # 自定义 M5 地址
  python tide_register.py --register --m5-url http://localhost:8005

  # 使用不同模型
  python tide_register.py --test --model qwen2.5:3b
        """,
    )

    parser.add_argument("--register", action="store_true", help="注册潮汐 Agent")
    parser.add_argument("--list", action="store_true", help="列出所有潮汐 Agent")
    parser.add_argument("--test", action="store_true", help="测试潮汐 Agent")
    parser.add_argument("--m5-url", default="http://localhost:8005", help="M5 服务地址")
    parser.add_argument("--model", default="qwen2.5:3b", help="推理模型名称")
    parser.add_argument("--name", default="潮汐管家", help="显示名称")

    args = parser.parse_args()

    if not any([args.register, args.list, args.test]):
        parser.print_help()
        return

    registry = ExternalAgentRegistry()

    if args.register:
        print(f"\n🚀 正在注册潮汐系统 Agent（M5: {args.m5_url}）...")
        agent_id = register_tide_agent(registry, args.m5_url, args.model, args.name)

        if args.test:
            adapter = create_tide_adapter(agent_id, args.m5_url, args.model, args.name)
            await test_tide_agent(adapter)
            await adapter.close()
        return

    if args.list:
        list_agents(registry)
        return

    if args.test:
        adapter = create_tide_adapter(
            m5_base_url=args.m5_url,
            model_name=args.model,
            display_name=args.name,
        )
        await test_tide_agent(adapter)
        await adapter.close()
        return


if __name__ == "__main__":
    asyncio.run(main())
