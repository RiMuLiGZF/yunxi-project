"""
八大模块管家 Agent 统一注册工具
================================

一键注册云汐八大模块的管家 Agent 到 M1 联邦调度系统。

使用方法：
    # 注册所有板块管家
    python modules_register.py --all

    # 注册指定模块
    python modules_register.py --register m2 m3 m4

    # 列出所有板块管家
    python modules_register.py --list

    # 测试所有板块管家
    python modules_register.py --test

    # 测试指定模块
    python modules_register.py --test m2 m5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from federation.registry import ExternalAgentRegistry
from federation.adapters.skill_manager_agent import SkillManagerAgentAdapter
from federation.adapters.inference_manager_agent import InferenceManagerAgentAdapter
from federation.adapters.scene_manager_agent import SceneManagerAgentAdapter
from federation.adapters.content_manager_agent import ContentManagerAgentAdapter
from federation.adapters.security_manager_agent import SecurityManagerAgentAdapter
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


# ── 八大模块定义
MODULES = {
    "m2": {
        "name": "技能管家",
        "full_name": "M2 - 智能对话与交互",
        "port": 8002,
        "provider": "SkillManager",
        "capabilities": [
            "技能检索", "技能推荐", "技能注册",
            "版本管理", "沙箱管理", "技能发现",
            "技能评测", "流水线管理",
        ],
        "description": "技能管家 — M2 技能集群的管理专家。熟悉所有技能的用法、参数和适用场景，帮你找到最合适的工具。",
        "adapter_class": SkillManagerAgentAdapter,
    },
    "m3": {
        "name": "推理管家",
        "full_name": "M3 - 端云协同推理",
        "port": 8003,
        "provider": "InferenceManager",
        "capabilities": [
            "模型管理", "VRAM监控", "端云调度",
            "推理路由", "负载均衡", "缓存管理",
            "性能优化", "离线缓存",
        ],
        "description": "推理管家 — M3 端云协同推理的调度专家。负责模型加载、显存管理、端云协同，让推理又快又省。",
        "adapter_class": InferenceManagerAgentAdapter,
    },
    "m4": {
        "name": "场景管家",
        "full_name": "M4 - 代码生成与工程",
        "port": 8004,
        "provider": "SceneManager",
        "capabilities": [
            "场景识别", "场景切换", "上下文管理",
            "场景配置", "模式切换", "状态管理",
            "工作模式", "生活模式",
        ],
        "description": "场景管家 — M4 场景引擎的调度师。擅长识别用户当前场景，智能切换对应的工作模式和语气风格。",
        "adapter_class": SceneManagerAgentAdapter,
    },
    "m5": {
        "name": "潮汐管家",
        "full_name": "M5 - 潮汐记忆系统",
        "port": 8005,
        "provider": "Tide",
        "capabilities": [
            "记忆检索", "记忆归档", "记忆巩固",
            "人格管理", "四层存储", "RBAC权限",
            "加密存储", "睡眠巩固",
        ],
        "description": "潮汐管家 — M5 潮汐记忆系统的守护者。负责记忆的存取、整理和守护，像一位细致的图书管理员。",
        "adapter_class": None,  # 已有独立注册脚本
    },
    "m6": {
        "name": "创意管家",
        "full_name": "M6 - 创意与内容生成",
        "port": 8006,
        "provider": "ContentManager",
        "capabilities": [
            "文案生成", "创意构思", "内容排版",
            "图片描述", "多媒体处理", "硬件感知",
            "灵感推荐", "风格调整",
        ],
        "description": "创意管家 — M6 创意内容的设计师。灵感丰富、审美在线，帮你把想法变成精彩的内容。",
        "adapter_class": ContentManagerAgentAdapter,
    },
    "m7": {
        "name": "安全管家",
        "full_name": "M7 - 安全与隐私防护",
        "port": 8007,
        "provider": "SecurityManager",
        "capabilities": [
            "安全审计", "隐私保护", "权限管理",
            "威胁检测", "数据脱敏", "积木沙箱",
            "访问控制", "安全扫描",
        ],
        "description": "安全管家 — M7 安全防护的守护官。严谨、警惕、可靠，时刻守护你的数据和隐私安全。",
        "adapter_class": SecurityManagerAgentAdapter,
    },
    "m8": {
        "name": "云汐总管",
        "full_name": "M8 - 总管与运维平台",
        "port": 8008,
        "provider": "ModuleManager",
        "capabilities": [
            "健康监控", "性能指标", "配置管理",
            "升级管理", "测试管理", "全局调度",
            "故障排查", "运维自动化",
        ],
        "description": "云汐总管 — M8 运维管控中心的总负责人。全局视野、严谨高效，负责整个系统的稳定运行。",
        "adapter_class": None,  # 已有独立注册脚本
    },
}


def register_module_agent(
    registry: ExternalAgentRegistry,
    module_key: str,
    base_url: str = "http://localhost",
) -> str | None:
    """注册单个模块管家 Agent"""
    module = MODULES.get(module_key)
    if not module:
        print(f"❌ 未知模块: {module_key}")
        return None

    if not module["adapter_class"]:
        print(f"⏭️  {module['name']} 已有独立注册脚本，跳过")
        return None

    port = module["port"]
    module_url = f"{base_url}:{port}"

    config = {
        "m2_base_url" if module_key == "m2" else "m3_base_url" if module_key == "m3"
        else "m4_base_url" if module_key == "m4" else "m6_base_url" if module_key == "m6"
        else "m7_base_url": module_url,
        "ollama_base_url": "http://localhost:11434",
        "model_name": "qwen2.5:1.5b",
        "adapter_type": f"{module['provider'].lower()}_agent",
        "description": module["description"],
        "enable_llm": True,
        "temperature": 0.7,
    }

    profile = registry.register_agent(
        display_name=module["name"],
        provider=module["provider"],
        agent_type=ExternalAgentType.CUSTOM,
        capabilities=module["capabilities"],
        cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
        privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
        connection_type=ConnectionType.LOCAL,
        config=config,
        api_key="",
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"✅ {module['name']} 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   模块: {module['full_name']}")
    print(f"   地址: {module_url}")

    return profile.agent_id


def list_module_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有模块管家 Agent"""
    all_agents = registry.list_agents()

    # 找出属于模块管家的 Agent
    module_providers = {m["provider"] for m in MODULES.values()}
    module_agents = [a for a in all_agents if a.provider in module_providers]

    print(f"\n📋 已注册的模块管家 Agent（共 {len(module_agents)} / {len(MODULES)} 个）:")
    print("-" * 60)

    for key, module in sorted(MODULES.items()):
        registered = [a for a in module_agents if a.provider == module["provider"]]
        if registered:
            agent = registered[0]
            status_icon = "✅" if agent.status == "active" else "⏸️"
            print(f"\n{status_icon} {key.upper()} {module['name']}")
            print(f"   {module['full_name']}")
            print(f"   ID: {agent.agent_id}")
            print(f"   状态: {agent.status}")
        else:
            print(f"\n⬜ {key.upper()} {module['name']}（未注册）")
            print(f"   {module['full_name']}")

    print()


async def test_module_agent(module_key: str, base_url: str = "http://localhost") -> None:
    """测试单个模块管家"""
    module = MODULES.get(module_key)
    if not module or not module["adapter_class"]:
        print(f"⏭️  {module_key.upper()} {module['name'] if module else '未知'}: 跳过（无适配器或已有独立测试")
        return

    port = module["port"]
    module_url = f"{base_url}:{port}"
    adapter_class = module["adapter_class"]

    adapter = adapter_class(
        agent_id=f"test_{module_key}_agent",
        display_name=module["name"],
        config={
            f"{module_key}_base_url": module_url,
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:1.5b",
            "enable_llm": True,
        },
        timeout=30.0,
        max_retries=1,
    )

    try:
        print(f"\n🧪 {module_key.upper()} {module['name']} 测试...")

        health = await adapter.health_check()
        print(f"   健康: {'✅' if health['healthy'] else '❌'} {health['message'][:60]}...")
        print(f"   延迟: {health['latency_ms']:.0f}ms")

    finally:
        await adapter.close()


async def main():
    parser = argparse.ArgumentParser(
        description="八大模块管家 Agent 统一注册工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 注册所有板块管家
  python modules_register.py --all

  # 注册指定模块
  python modules_register.py --register m2 m3 m4

  # 列出所有板块管家
  python modules_register.py --list

  # 测试所有板块管家
  python modules_register.py --test

  # 测试指定模块
  python modules_register.py --test m2 m6

可用模块: m2, m3, m4, m5, m6, m7, m8
  (m1 为内置调度中心，m5/m8 有独立注册脚本)
        """,
    )

    parser.add_argument("--all", action="store_true", help="注册所有模块管家")
    parser.add_argument("--register", nargs="+", metavar="MODULE", help="注册指定模块")
    parser.add_argument("--list", action="store_true", help="列出所有模块管家")
    parser.add_argument("--test", nargs="*", metavar="MODULE", help="测试模块（不带参数则测试全部）")
    parser.add_argument("--base-url", default="http://localhost", help="基础地址前缀")

    args = parser.parse_args()

    if not any([args.all, args.register, args.list, args.test is not None]):
        parser.print_help()
        return

    registry = ExternalAgentRegistry()

    # 注册
    if args.all or args.register:
        modules_to_register = args.register if args.register else list(MODULES.keys())
        print(f"\n🚀 正在注册模块管家 Agent...\n")

        count = 0
        for key in modules_to_register:
            if key == "m1":
                print("⏭️  M1: 内置调度中心，不需要独立 Agent")
                continue
            result = register_module_agent(registry, key, args.base_url)
            if result:
                count += 1
            print()

        print(f"✅ 共注册 {count} 个模块管家 Agent")

    # 列表
    if args.list:
        list_module_agents(registry)

    # 测试
    if args.test is not None:
        modules_to_test = args.test if args.test else list(MODULES.keys())
        print(f"\n🧪 模块管家 Agent 功能测试\n")

        for key in modules_to_test:
            if key == "m1":
                print("⏭️  M1: 内置调度中心")
                continue
            await test_module_agent(key, args.base_url)

        print(f"\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
