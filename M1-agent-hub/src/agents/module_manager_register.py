"""
模块管家 Agent 联邦注册与管理工具
====================================

「云汐总管」— M8 模块管理平台的智能代理。
负责云汐八大模块（M1~M8）的统一监控、配置、升级和测试。

使用方法：
    # 注册到联邦系统
    python module_manager_register.py --register

    # 测试功能
    python module_manager_register.py --test

    # 查看所有模块管家 Agent
    python module_manager_register.py --list

    # 指定各模块地址
    python module_manager_register.py --register --m1-url http://localhost:8001
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.federation.registry import ExternalAgentRegistry
from src.federation.adapters.module_manager_agent import ModuleManagerAgentAdapter
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


MODULE_MANAGER_CAPABILITIES = [
    "健康监控",
    "性能指标",
    "配置管理",
    "版本升级",
    "升级回滚",
    "自动化测试",
    "多模块统一管控",
    "M8标准接口",
    "全局运维视图",
    "异常告警",
    "配置同步",
    "批量操作",
]

MODULE_MANAGER_DESCRIPTION = """
云汐总管 — M8 模块管理平台的智能代理。
负责云汐八大模块（M1~M8）的统一监控、配置管理、版本升级和自动化测试。
基于 M8 标准接口，提供全局运维视图和批量操作能力。
""".strip()

# 八大模块默认端口
MODULE_DEFAULT_PORTS = {
    "m1": 8001,
    "m2": 8002,
    "m3": 8003,
    "m4": 8004,
    "m5": 8005,
    "m6": 8006,
    "m7": 8007,
    "m8": 8008,
}

MODULE_NAMES = {
    "m1": "多Agent集群调度",
    "m2": "智能对话与交互",
    "m3": "知识图谱与推理",
    "m4": "代码生成与工程",
    "m5": "潮汐记忆系统",
    "m6": "创意与内容生成",
    "m7": "安全与隐私防护",
    "m8": "总管与运维平台",
}


def _build_module_addresses(
    base_url: str,
    custom_addresses: dict[str, str] | None = None,
) -> dict[str, str]:
    """构建模块地址映射"""
    addresses = {}
    for module_id, port in MODULE_DEFAULT_PORTS.items():
        addresses[module_id] = f"{base_url}:{port}"

    if custom_addresses:
        for module_id, url in custom_addresses.items():
            if module_id in MODULE_DEFAULT_PORTS:
                addresses[module_id] = url

    return addresses


def register_module_manager_agent(
    registry: ExternalAgentRegistry,
    base_url: str = "http://localhost",
    m8_token: str = "",
    display_name: str = "云汐总管",
    custom_addresses: dict[str, str] | None = None,
) -> str:
    """注册模块管家 Agent"""

    module_addresses = _build_module_addresses(base_url, custom_addresses)

    config = {
        "module_addresses": module_addresses,
        "m8_token": m8_token,
        "default_base_url": base_url,
        "adapter_type": "module_manager_agent",
        "description": MODULE_MANAGER_DESCRIPTION,
        "request_timeout": 10.0,
        "parallel_limit": 4,
    }

    profile = registry.register_agent(
        display_name=display_name,
        provider="ModuleManager",
        agent_type=ExternalAgentType.CUSTOM,
        capabilities=MODULE_MANAGER_CAPABILITIES,
        cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "CNY"},
        privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
        connection_type=ConnectionType.LOCAL,
        config=config,
        api_key="",
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"\n✅ 模块管家 Agent 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   显示名称: {profile.display_name}")
    print(f"   管理模块: {len(module_addresses)} 个 (M1~M8)")
    print(f"   基础地址: {base_url}")
    print(f"   隐私等级: {profile.privacy_level.value}")
    print(f"   能力: {', '.join(profile.capabilities[:5])}...")
    print(f"\n📦 各模块地址:")
    for mid in sorted(module_addresses.keys()):
        name = MODULE_NAMES.get(mid, mid)
        print(f"   {mid.upper():>3} - {name:<14} {module_addresses[mid]}")

    return profile.agent_id


def create_module_manager_adapter(
    agent_id: str = "module_manager_test_direct",
    base_url: str = "http://localhost",
    m8_token: str = "",
    display_name: str = "云汐总管",
    custom_addresses: dict[str, str] | None = None,
) -> ModuleManagerAgentAdapter:
    """创建模块管家 Agent 适配器"""
    module_addresses = _build_module_addresses(base_url, custom_addresses)

    return ModuleManagerAgentAdapter(
        agent_id=agent_id,
        display_name=display_name,
        config={
            "module_addresses": module_addresses,
            "m8_token": m8_token,
            "default_base_url": base_url,
            "request_timeout": 10.0,
        },
        timeout=60.0,
        max_retries=1,
    )


async def test_module_manager_agent(adapter: ModuleManagerAgentAdapter) -> None:
    """测试模块管家 Agent 功能"""
    print("\n" + "=" * 60)
    print("🏛️  模块管家 Agent 功能测试")
    print("=" * 60)

    # 健康检查
    print("\n📊 健康检查...")
    health = await adapter.health_check()
    print(f"   状态: {'✅ 健康' if health['healthy'] else '❌ 异常'}")
    print(f"   信息: {health['message']}")
    print(f"   延迟: {health['latency_ms']:.2f}ms")

    # 功能测试用例（仅测试可访问的接口）
    test_cases = [
        ("健康检查命令", "检查所有模块的健康状态", "health_check"),
        ("性能指标命令", "获取所有模块的性能指标", "get_metrics"),
        ("指定模块健康", "检查 M1 模块状态", "health_check"),
    ]

    print("\n🧪 功能测试...")
    for test_name, prompt, expected_type in test_cases:
        print(f"\n   测试 [{test_name}]: {prompt[:40]}...")
        try:
            result = await adapter.invoke(
                prompt=prompt,
                system_prompt="你是云汐总管，请简洁回答。",
                temperature=0.1,
                max_tokens=800,
            )

            if result["success"]:
                output_preview = result["output"][:120].replace("\n", " ")
                command_type = result.get("command_type", "unknown")
                modules = result.get("target_modules", [])
                print(f"   ✅ 成功 (命令: {command_type}, 模块: {len(modules)}个)")
                print(f"   输出预览: {output_preview}...")
                print(f"   耗时: {result['latency_ms']:.0f}ms | "
                      f"Tokens: {result['input_tokens']}+{result['output_tokens']}")
            else:
                print(f"   ❌ 失败: {result['error']}")
        except Exception as exc:
            print(f"   ⚠️  异常: {exc}")

    # 测试带 metadata 的明确命令
    print("\n📋 Metadata 命令测试...")
    metadata_tests = [
        ("通过metadata指定health_check", {"command_type": "health_check", "modules": ["m1", "m5"]}),
    ]
    for test_name, metadata in metadata_tests:
        print(f"\n   测试 [{test_name}]")
        try:
            result = await adapter.invoke(
                prompt="检查指定模块",
                system_prompt="你是云汐总管。",
                temperature=0.1,
                max_tokens=400,
                metadata=metadata,
            )
            if result["success"]:
                print(f"   ✅ 成功")
                print(f"   目标模块: {result.get('target_modules', [])}")
            else:
                print(f"   ❌ 失败: {result['error']}")
        except Exception as exc:
            print(f"   ⚠️  异常: {exc}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


def list_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有模块管家 Agent"""
    agents = [a for a in registry.list_agents() if a.provider == "ModuleManager"]

    print(f"\n📋 已注册的模块管家 Agent（共 {len(agents)} 个）:")
    print("-" * 60)

    if not agents:
        print("   （暂无）")
    else:
        for agent in agents:
            module_count = len(agent.config.get("module_addresses", {}))
            base_url = agent.config.get("default_base_url", "unknown")
            status_icon = "✅" if agent.status == "active" else "⏸️"
            print(f"\n{status_icon} {agent.display_name}")
            print(f"   ID: {agent.agent_id}")
            print(f"   管理模块数: {module_count}")
            print(f"   基础地址: {base_url}")
            print(f"   状态: {agent.status}")
            print(f"   能力: {', '.join(agent.capabilities[:4])}...")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="模块管家 Agent 联邦注册与管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 注册模块管家 Agent（使用默认地址）
  python module_manager_register.py --register

  # 自定义基础地址
  python module_manager_register.py --register --base-url http://192.168.1.100

  # 指定 M8 管理令牌
  python module_manager_register.py --register --m8-token your_token

  # 自定义单个模块地址
  python module_manager_register.py --register --m5-url http://localhost:9005

  # 测试功能
  python module_manager_register.py --test

  # 查看所有模块管家 Agent
  python module_manager_register.py --list

  # 注册并测试
  python module_manager_register.py --register --test
        """,
    )

    parser.add_argument("--register", action="store_true", help="注册模块管家 Agent")
    parser.add_argument("--list", action="store_true", help="列出所有模块管家 Agent")
    parser.add_argument("--test", action="store_true", help="测试模块管家 Agent")
    parser.add_argument("--base-url", default="http://localhost", help="模块服务基础地址前缀")
    parser.add_argument("--m8-token", default="", help="M8 管理令牌")
    parser.add_argument("--name", default="云汐总管", help="显示名称")

    # 各模块自定义地址参数
    for mid in sorted(MODULE_DEFAULT_PORTS.keys()):
        parser.add_argument(
            f"--{mid}-url",
            default=None,
            help=f"自定义 {mid.upper()} 模块地址（{MODULE_NAMES.get(mid, '')}）",
        )

    args = parser.parse_args()

    if not any([args.register, args.list, args.test]):
        parser.print_help()
        return

    # 收集自定义模块地址
    custom_addresses = {}
    for mid in MODULE_DEFAULT_PORTS.keys():
        url = getattr(args, f"{mid}_url", None)
        if url:
            custom_addresses[mid] = url

    registry = ExternalAgentRegistry()

    if args.register:
        print(f"\n🚀 正在注册模块管家 Agent（基础地址: {args.base_url}）...")
        agent_id = register_module_manager_agent(
            registry=registry,
            base_url=args.base_url,
            m8_token=args.m8_token,
            display_name=args.name,
            custom_addresses=custom_addresses or None,
        )

        if args.test:
            adapter = create_module_manager_adapter(
                agent_id=agent_id,
                base_url=args.base_url,
                m8_token=args.m8_token,
                display_name=args.name,
                custom_addresses=custom_addresses or None,
            )
            await test_module_manager_agent(adapter)
            await adapter.close()
        return

    if args.list:
        list_agents(registry)
        return

    if args.test:
        adapter = create_module_manager_adapter(
            base_url=args.base_url,
            m8_token=args.m8_token,
            display_name=args.name,
            custom_addresses=custom_addresses or None,
        )
        await test_module_manager_agent(adapter)
        await adapter.close()
        return


if __name__ == "__main__":
    asyncio.run(main())
