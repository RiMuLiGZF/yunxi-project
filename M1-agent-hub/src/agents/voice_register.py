"""
情感润色 Agent 联邦注册与管理工具
====================================

「云汐」人格润色 Agent — 将结构化内容转化为有温度的自然语言。

人格配置文件: config/yunxi_personality.yaml
（可以直接修改此文件来调整云汐的性格）

使用方法：
    # 注册到联邦系统
    python voice_register.py --register

    # 测试润色功能
    python voice_register.py --test

    # 查看所有 Voice Agent
    python voice_register.py --list

    # 用特定场景测试
    python voice_register.py --test --scene emotion_companion
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.federation.registry import ExternalAgentRegistry
from src.federation.adapters.voice_agent import VoiceAgentAdapter
from shared_models import (
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    LicenseType,
)


VOICE_CAPABILITIES = [
    "人格润色",
    "语气调节",
    "场景适配",
    "情感表达",
    "质量自检",
    "红线检测",
    "用户偏好管理",
    "多场景切换",
    "本地推理",
    "零API成本",
]

VOICE_DESCRIPTION = """
云汐人格润色 Agent — 负责输出层的语气化妆。
将上游结构化内容转化为有云汐人格温度的自然语言。
五维人格参数可调，支持6种模式+6种场景语气切换。
人格配置文件可直接修改，实时生效。
""".strip()


def register_voice_agent(
    registry: ExternalAgentRegistry,
    model_name: str = "qwen2.5:1.5b",
    display_name: str = "云汐 人格润色",
    personality_config: str = "",
) -> str:
    """注册情感润色 Agent"""

    config_path = personality_config or str(
        PROJECT_ROOT / "config" / "yunxi_personality.yaml"
    )

    config = {
        "ollama_base_url": "http://localhost:11434",
        "model_name": model_name,
        "personality_config_path": config_path,
        "adapter_type": "voice_agent",
        "description": VOICE_DESCRIPTION,
        "default_scene": "work_dev",
        "default_tone": "default",
        "enable_m5_persistence": False,
        "temperature": 0.7,
    }

    profile = registry.register_agent(
        display_name=display_name,
        provider="Voice",
        agent_type=ExternalAgentType.CUSTOM,
        capabilities=VOICE_CAPABILITIES,
        cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
        privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
        connection_type=ConnectionType.LOCAL,
        config=config,
        api_key="",
        license=LicenseType.MIT,
        confirm_license_risk=False,
    )

    print(f"\n✅ 情感润色 Agent 注册成功！")
    print(f"   Agent ID: {profile.agent_id}")
    print(f"   显示名称: {profile.display_name}")
    print(f"   模型: {model_name}")
    print(f"   人格配置: {config_path}")
    print(f"   隐私等级: {profile.privacy_level.value}")
    print(f"   能力: {', '.join(profile.capabilities[:5])}...")
    print()
    print(f"   💡 提示：修改 config/yunxi_personality.yaml 可以调整云汐的性格")

    return profile.agent_id


def create_voice_adapter(
    agent_id: str = "voice_test_direct",
    model_name: str = "qwen2.5:1.5b",
    display_name: str = "云汐 人格润色",
    personality_config: str = "",
) -> VoiceAgentAdapter:
    """创建情感润色 Agent 适配器"""
    config_path = personality_config or str(
        PROJECT_ROOT / "config" / "yunxi_personality.yaml"
    )

    return VoiceAgentAdapter(
        agent_id=agent_id,
        display_name=display_name,
        config={
            "ollama_base_url": "http://localhost:11434",
            "model_name": model_name,
            "personality_config_path": config_path,
            "temperature": 0.7,
        },
        timeout=60.0,
        max_retries=1,
    )


async def test_voice_agent(adapter: VoiceAgentAdapter, scene: str = "work_dev") -> None:
    """测试情感润色功能"""
    print("\n" + "=" * 60)
    print("🎭 情感润色 Agent 功能测试")
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
        ("工作开发模式", "任务已完成，共修复了3个bug，新增了2个功能模块。", "work_dev"),
        ("情感陪伴模式", "用户今天心情不太好，说工作压力很大。", "emotion_companion"),
        ("生活管理模式", "提醒用户明天下午3点有个会议，需要准备PPT。", "life_management"),
    ]

    print(f"\n🧪 润色测试（场景: {scene}）...")

    for test_name, content, test_scene in test_cases:
        print(f"\n   测试 [{test_name}]:")
        print(f"   原始内容: {content[:50]}...")

        try:
            result = await adapter.invoke(
                prompt=content,
                system_prompt="请把这段内容用云汐的方式说出来，保持简洁。",
                temperature=0.7,
                max_tokens=300,
                metadata={"scene": test_scene, "mode": "polish"},
            )

            if result["success"]:
                output_preview = result['output'][:80].replace('\n', ' ')
                red_line_ok = result.get('red_line_check', {}).get('passed', True)
                print(f"   ✅ 润色成功")
                print(f"   润色后: {output_preview}...")
                print(f"   红线检测: {'✅ 通过' if red_line_ok else '⚠️ 有违规'}")
                print(f"   耗时: {result['latency_ms']:.0f}ms | "
                      f"Tokens: {result['input_tokens']}+{result['output_tokens']}")
            else:
                print(f"   ❌ 失败: {result['error']}")
        except Exception as exc:
            print(f"   ⚠️  异常: {exc}")

    # 直接对话测试
    print(f"\n💬 直接对话测试...")
    try:
        result = await adapter.invoke(
            prompt="你好呀，介绍一下你自己吧～",
            system_prompt="用云汐的方式回答，简洁友好。",
            temperature=0.8,
            max_tokens=200,
            metadata={"scene": scene, "mode": "direct_reply"},
        )
        if result["success"]:
            print(f"   云汐: {result['output'][:100]}...")
            print(f"   耗时: {result['latency_ms']:.0f}ms")
    except Exception as exc:
        print(f"   ⚠️  异常: {exc}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


def list_agents(registry: ExternalAgentRegistry) -> None:
    """列出所有 Voice Agent"""
    agents = [a for a in registry.list_agents() if a.provider == "Voice"]

    print(f"\n📋 已注册的情感润色 Agent（共 {len(agents)} 个）:")
    print("-" * 60)

    if not agents:
        print("   （暂无）")
    else:
        for agent in agents:
            model = agent.config.get("model_name", "unknown")
            config_path = agent.config.get("personality_config_path", "unknown")
            status_icon = "✅" if agent.status == "active" else "⏸️"
            print(f"\n{status_icon} {agent.display_name}")
            print(f"   ID: {agent.agent_id}")
            print(f"   模型: {model}")
            print(f"   人格配置: {Path(config_path).name if config_path else '默认'}")
            print(f"   状态: {agent.status}")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="情感润色 Agent 联邦注册与管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 注册 Voice Agent
  python voice_register.py --register

  # 测试功能
  python voice_register.py --test

  # 用特定场景测试
  python voice_register.py --test --scene emotion_companion

  # 列出所有 Voice Agent
  python voice_register.py --list

  # 使用自定义人格配置
  python voice_register.py --test --config ./my_personality.yaml

  # 场景列表: work_dev / study_plan / review_summary /
  #            relationship / emotion_companion / life_management
        """,
    )

    parser.add_argument("--register", action="store_true", help="注册 Voice Agent")
    parser.add_argument("--list", action="store_true", help="列出所有 Voice Agent")
    parser.add_argument("--test", action="store_true", help="测试 Voice Agent")
    parser.add_argument("--model", default="qwen2.5:1.5b", help="模型名称")
    parser.add_argument("--name", default="云汐 人格润色", help="显示名称")
    parser.add_argument("--scene", default="work_dev", help="测试场景")
    parser.add_argument("--config", default="", help="自定义人格配置文件路径")

    args = parser.parse_args()

    if not any([args.register, args.list, args.test]):
        parser.print_help()
        return

    registry = ExternalAgentRegistry()

    if args.register:
        print(f"\n🚀 正在注册情感润色 Agent（模型: {args.model}）...")
        agent_id = register_voice_agent(registry, args.model, args.name, args.config)

        if args.test:
            adapter = create_voice_adapter(agent_id, args.model, args.name, args.config)
            await test_voice_agent(adapter, args.scene)
            await adapter.close()
        return

    if args.list:
        list_agents(registry)
        return

    if args.test:
        adapter = create_voice_adapter(
            model_name=args.model,
            display_name=args.name,
            personality_config=args.config,
        )
        await test_voice_agent(adapter, args.scene)
        await adapter.close()
        return


if __name__ == "__main__":
    asyncio.run(main())
