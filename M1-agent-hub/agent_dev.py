"""
【兼容存根】业务Agent已迁移至 agents/ 目录

DevAgent 原实现位于 agents/agent_dev.py
本文件仅保留向后兼容的 re-export，避免破坏既有 import 路径。

⚠️ 模块边界声明：DevAgent 属于模块二（Skills技能集群），
非模块一（多Agent集群调度架构）核心代码。
"""

from __future__ import annotations

from agents.agent_dev import DevAgent

__all__ = ["DevAgent"]
