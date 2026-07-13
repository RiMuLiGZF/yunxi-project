"""
Agent 生命周期管理演示工具
===========================

演示"需要时启动，不需要时休息"的效果。

使用方法：
    # 查看所有 Agent 的生命周期状态
    python lifecycle_demo.py --status

    # 模拟使用一个 Agent（触发唤醒）
    python lifecycle_demo.py --wake tide_agent

    # 模拟使用多个 Agent
    python lifecycle_demo.py --wake hermes codex voice

    # 查看 VRAM 使用情况
    python lifecycle_demo.py --vram

    # 运行完整演示（唤醒 -> 使用 -> 等待空闲 -> 休眠）
    python lifecycle_demo.py --demo
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from federation.lifecycle_integration import FederationLifecycleIntegration
from federation.registry import ExternalAgentRegistry


# 预设的演示 Agent 列表（模拟已注册的 Agent）
DEMO_AGENTS = [
    {"id": "hermes", "name": "Hermes 通用智能体", "model": "qwen2.5:7b", "priority": 9},
    {"id": "codex", "name": "Codex 代码专家", "model": "qwen2.5:7b", "priority": 8},
    {"id": "tide", "name": "潮汐管家", "model": "qwen2.5:3b", "priority": 7},
    {"id": "voice", "name": "情感润色", "model": "qwen2.5:1.5b", "priority": 6},
    {"id": "explore", "name": "研究助理", "model": "qwen2.5:1.5b", "priority": 5},
    {"id": "skill_manager", "name": "技能管家", "model": "qwen2.5:1.5b", "priority": 4},
    {"id": "inference_manager", "name": "推理管家", "model": "qwen2.5:1.5b", "priority": 4},
    {"id": "scene_manager", "name": "场景管家", "model": "qwen2.5:1.5b", "priority": 4},
    {"id": "content_manager", "name": "创意管家", "model": "qwen2.5:1.5b", "priority": 3},
    {"id": "security_manager", "name": "安全管家", "model": "qwen2.5:1.5b", "priority": 3},
]


STATE_ICONS = {
    "warm": "🟢",
    "warming": "🟡",
    "cold": "🔵",
    "cooling": "🟠",
    "dormant": "⚫",
}


def print_status_table(states: list[dict]) -> None:
    """打印状态表格"""
    print(f"\n{'='*70}")
    print(f"{'Agent':<22} {'状态':<8} {'模型':<16} {'优先级':<6} {'空闲时间':<10}")
    print(f"{'-'*70}")

    for s in sorted(states, key=lambda x: -x["priority"]):
        icon = STATE_ICONS.get(s["state"], "❓")
        state_name = {
            "warm": "热",
            "warming": "预热",
            "cold": "冷",
            "cooling": "冷却",
            "dormant": "休眠",
        }.get(s["state"], s["state"])

        idle = s.get("last_used_seconds_ago")
        idle_str = f"{idle:.0f}s" if idle is not None else "从未"

        print(
            f"{icon} {s['display_name']:<20} "
            f"{state_name:<8} "
            f"{s.get('model_name', '-'):<16} "
            f"{s['priority']:<6} "
            f"{idle_str:<10}"
        )

    warm_count = sum(1 for s in states if s["state"] == "warm")
    print(f"{'-'*70}")
    print(f"总计: {len(states)} 个 Agent | 热状态: {warm_count} 个")
    print(f"{'='*70}\n")


async def cmd_status(lifecycle: FederationLifecycleIntegration) -> None:
    """查看状态"""
    states = lifecycle.list_agent_states()
    print_status_table(states)

    # VRAM 状态
    try:
        vram = await lifecycle.get_vram_status()
        if vram.get("loaded_models"):
            print(f"📊 VRAM 已加载模型: {vram['loaded_models']} 个")
            print(f"   模型列表: {', '.join(vram['models'])}")
            print(f"   显存占用: {vram['total_vram_gb']:.2f} GB")
        else:
            print("📊 VRAM: 无模型加载")
    except Exception:
        print("📊 VRAM: 无法获取（Ollama 可能未启动）")


async def cmd_wake(lifecycle: FederationLifecycleIntegration, agent_ids: list[str]) -> None:
    """唤醒指定 Agent"""
    for aid in agent_ids:
        # 找到对应的 agent_id（可能有前缀）
        all_states = lifecycle.list_agent_states()
        matched = [s for s in all_states if aid.lower() in s["agent_id"].lower()]

        if not matched:
            print(f"❌ 未找到 Agent: {aid}")
            continue

        target = matched[0]
        print(f"\n⏰ 正在唤醒: {target['display_name']}...")
        start = time.time()

        success = await lifecycle.ensure_agent_warm(target["agent_id"])
        elapsed = time.time() - start

        if success:
            print(f"✅ 唤醒成功！耗时: {elapsed:.1f}s")
            await lifecycle.mark_agent_used(target["agent_id"])
        else:
            print(f"❌ 唤醒失败")

    # 显示当前状态
    states = lifecycle.list_agent_states()
    print_status_table(states)


async def cmd_vram(lifecycle: FederationLifecycleIntegration) -> None:
    """查看 VRAM 状态"""
    try:
        vram = await lifecycle.get_vram_status()
        print(f"\n📊 Ollama VRAM 状态")
        print(f"{'='*50}")
        print(f"已加载模型: {vram['loaded_models']} 个")
        print(f"总显存占用: {vram['total_vram_gb']:.2f} GB")
        if vram.get("models"):
            print(f"模型列表:")
            for m in vram["models"]:
                print(f"  - {m}")
        print(f"{'='*50}\n")
    except Exception as e:
        print(f"❌ 获取 VRAM 状态失败: {e}")
        print("   （请确保 Ollama 已启动）")


async def cmd_demo(lifecycle: FederationLifecycleIntegration) -> None:
    """完整演示"""
    print("\n" + "="*70)
    print("🚀 Agent 生命周期管理演示")
    print("="*70)

    # 初始状态
    print("\n📋 初始状态（所有 Agent 都是冷的）:")
    states = lifecycle.list_agent_states()
    print_status_table(states)

    # 第一步：唤醒一个 Agent
    print("\n👉 第一步：唤醒「潮汐管家」（模拟用户开始使用记忆功能）")
    tide_state = [s for s in states if "潮汐" in s["display_name"]]
    if tide_state:
        await lifecycle.ensure_agent_warm(tide_state[0]["agent_id"])
        await lifecycle.mark_agent_used(tide_state[0]["agent_id"])

    states = lifecycle.list_agent_states()
    print_status_table(states)

    # 第二步：再唤醒一个
    print("\n👉 第二步：唤醒「情感润色」（用户要聊天了）")
    voice_state = [s for s in states if "润色" in s["display_name"]]
    if voice_state:
        await lifecycle.ensure_agent_warm(voice_state[0]["agent_id"])
        await lifecycle.mark_agent_used(voice_state[0]["agent_id"])

    states = lifecycle.list_agent_states()
    print_status_table(states)

    # 第三步：唤醒一个高优先级大模型
    print("\n👉 第三步：唤醒「Hermes 通用智能体」（用户要处理复杂任务）")
    hermes_state = [s for s in states if "Hermes" in s["display_name"]]
    if hermes_state:
        await lifecycle.ensure_agent_warm(hermes_state[0]["agent_id"])
        await lifecycle.mark_agent_used(hermes_state[0]["agent_id"])

    states = lifecycle.list_agent_states()
    print_status_table(states)

    # 第四步：超过并发限制时的表现
    print("\n👉 第四步：再唤醒「Codex 代码专家」（触发并发限制，低优先级被淘汰）")
    codex_state = [s for s in states if "Codex" in s["display_name"]]
    if codex_state:
        await lifecycle.ensure_agent_warm(codex_state[0]["agent_id"])
        await lifecycle.mark_agent_used(codex_state[0]["agent_id"])

    states = lifecycle.list_agent_states()
    print_status_table(states)

    print("\n✅ 演示完成！")
    print("\n💡 说明：")
    print("   - 🟢 热状态：模型在显存中，立即可用")
    print("   - 🟡 预热中：正在加载模型")
    print("   - 🔵 冷状态：模型未加载，首次调用需预热")
    print("   - 🟠 冷却中：刚过空闲期，模型即将卸载")
    print("   - ⚫ 休眠：长时间未使用，深度休眠")
    print("\n   默认配置：同时最多 3 个热 Agent，空闲 5 分钟自动冷却")


async def main():
    parser = argparse.ArgumentParser(
        description="Agent 生命周期管理演示工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看所有 Agent 状态
  python lifecycle_demo.py --status

  # 唤醒指定 Agent
  python lifecycle_demo.py --wake tide voice

  # 查看 VRAM 使用情况
  python lifecycle_demo.py --vram

  # 完整演示
  python lifecycle_demo.py --demo
        """,
    )

    parser.add_argument("--status", action="store_true", help="查看所有 Agent 状态")
    parser.add_argument("--wake", nargs="+", metavar="AGENT", help="唤醒指定 Agent")
    parser.add_argument("--vram", action="store_true", help="查看 VRAM 使用情况")
    parser.add_argument("--demo", action="store_true", help="运行完整演示")
    parser.add_argument("--max-warm", type=int, default=3, help="最大热 Agent 数（默认3）")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama 地址")

    args = parser.parse_args()

    if not any([args.status, args.wake, args.vram, args.demo]):
        parser.print_help()
        return

    # 初始化生命周期管理器
    lifecycle = FederationLifecycleIntegration(
        ollama_base_url=args.ollama_url,
        max_concurrent_models=args.max_warm,
        max_warm_agents=args.max_warm,
        model_idle_ttl=180.0,
        agent_idle_ttl=300.0,
    )

    await lifecycle.start()

    try:
        # 注册演示 Agent
        for agent in DEMO_AGENTS:
            lifecycle.agent_lifecycle.register_agent(
                agent_id=agent["id"],
                display_name=agent["name"],
                model_name=agent["model"],
                priority=agent["priority"],
            )

        if args.status:
            await cmd_status(lifecycle)
        elif args.wake:
            await cmd_wake(lifecycle, args.wake)
        elif args.vram:
            await cmd_vram(lifecycle)
        elif args.demo:
            await cmd_demo(lifecycle)

    finally:
        await lifecycle.stop()


if __name__ == "__main__":
    asyncio.run(main())
