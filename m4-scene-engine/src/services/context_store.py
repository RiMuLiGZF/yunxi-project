"""上下文存储服务.

内存存储 + JSON 文件持久化。
每个场景有独立的上下文存储空间。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

try:
    from src.models import SCENE_DEFINITIONS, SceneContext
except ImportError:
    from models import SCENE_DEFINITIONS, SceneContext  # type: ignore


class ContextStore:
    """上下文存储服务.

    支持：
    - 按场景ID存储上下文
    - 内存缓存
    - JSON 文件持久化
    - 自动保存
    """

    def __init__(
        self,
        persist_path: str = "",
        auto_save: bool = True,
    ) -> None:
        """初始化上下文存储.

        Args:
            persist_path: 持久化文件路径，为空则使用默认路径 ~/.yunxi/m4_data.json
            auto_save: 是否自动保存到磁盘
        """
        if not persist_path:
            home = Path.home()
            yunxi_dir = home / ".yunxi"
            yunxi_dir.mkdir(parents=True, exist_ok=True)
            persist_path = str(yunxi_dir / "m4_data.json")

        self._persist_path = persist_path
        self._auto_save = auto_save

        # 上下文数据: {user_id: {scene_id: SceneContext}}
        self._contexts: dict[str, dict[str, SceneContext]] = {}

        # 线程锁
        self._lock = Lock()

        # 从磁盘加载
        self._load_from_disk()

    # -----------------------------------------------------------------------
    # 公开方法
    # -----------------------------------------------------------------------

    def get_context(
        self,
        scene_id: str,
        user_id: str = "default",
    ) -> dict[str, Any]:
        """获取场景上下文.

        Args:
            scene_id: 场景ID
            user_id: 用户ID

        Returns:
            上下文数据字典
        """
        with self._lock:
            user_contexts = self._contexts.get(user_id, {})
            ctx = user_contexts.get(scene_id)

            if ctx is None:
                return {
                    "scene_id": scene_id,
                    "context_data": {},
                    "last_updated": 0,
                    "update_count": 0,
                    "exists": False,
                }

            return {
                "scene_id": ctx.scene_id,
                "context_data": ctx.context_data,
                "last_updated": ctx.last_updated,
                "update_count": ctx.update_count,
                "exists": True,
            }

    def save_context(
        self,
        scene_id: str,
        context_data: dict[str, Any],
        user_id: str = "default",
        merge: bool = True,
    ) -> dict[str, Any]:
        """保存场景上下文.

        Args:
            scene_id: 场景ID
            context_data: 上下文数据
            user_id: 用户ID
            merge: 是否合并（True:合并, False:覆盖）

        Returns:
            保存结果
        """
        with self._lock:
            if user_id not in self._contexts:
                self._contexts[user_id] = {}

            user_contexts = self._contexts[user_id]

            if scene_id in user_contexts and merge:
                # 合并
                existing = user_contexts[scene_id]
                existing.context_data.update(context_data)
                existing.last_updated = time.time()
                existing.update_count += 1
                ctx = existing
            else:
                # 覆盖或新建
                ctx = SceneContext(
                    scene_id=scene_id,
                    context_data=dict(context_data),
                    last_updated=time.time(),
                    update_count=1,
                )
                user_contexts[scene_id] = ctx

        if self._auto_save:
            self._save_to_disk()

        return {
            "scene_id": scene_id,
            "last_updated": ctx.last_updated,
            "update_count": ctx.update_count,
            "merged": merge,
            "success": True,
        }

    def clear_context(
        self,
        scene_id: str,
        user_id: str = "default",
    ) -> dict[str, Any]:
        """清空场景上下文.

        Args:
            scene_id: 场景ID
            user_id: 用户ID

        Returns:
            清空结果
        """
        with self._lock:
            user_contexts = self._contexts.get(user_id, {})
            existed = scene_id in user_contexts
            if existed:
                del user_contexts[scene_id]

        if self._auto_save:
            self._save_to_disk()

        return {
            "scene_id": scene_id,
            "cleared": existed,
            "success": True,
        }

    def get_status(self, user_id: str = "default") -> dict[str, Any]:
        """获取上下文状态概览.

        Args:
            user_id: 用户ID

        Returns:
            状态概览字典
        """
        with self._lock:
            user_contexts = self._contexts.get(user_id, {})
            total_contexts = len(user_contexts)

            scene_stats = []
            for scene_id, ctx in user_contexts.items():
                scene_info = SCENE_DEFINITIONS.get(scene_id, {})
                data_size = len(json.dumps(ctx.context_data, ensure_ascii=False))
                scene_stats.append({
                    "scene_id": scene_id,
                    "scene_name": scene_info.get("name", scene_id),
                    "data_size_bytes": data_size,
                    "update_count": ctx.update_count,
                    "last_updated": ctx.last_updated,
                })

            # 按最后更新时间排序
            scene_stats.sort(key=lambda x: x["last_updated"], reverse=True)

            total_size = sum(s["data_size_bytes"] for s in scene_stats)

            return {
                "user_id": user_id,
                "total_scenes": total_contexts,
                "total_size_bytes": total_size,
                "scene_stats": scene_stats,
                "all_scenes": list(SCENE_DEFINITIONS.keys()),
            }

    def get_all_status(self) -> dict[str, Any]:
        """获取所有用户的上下文状态."""
        with self._lock:
            result = {}
            for user_id in self._contexts:
                user_ctx = self._contexts[user_id]
                result[user_id] = {
                    "scene_count": len(user_ctx),
                    "total_updates": sum(ctx.update_count for ctx in user_ctx.values()),
                }
            return {
                "total_users": len(result),
                "users": result,
            }

    def save_to_disk(self) -> bool:
        """手动保存到磁盘."""
        return self._save_to_disk()

    def load_from_disk(self) -> bool:
        """从磁盘重新加载."""
        return self._load_from_disk()

    # -----------------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------------

    def _save_to_disk(self) -> bool:
        """保存数据到 JSON 文件."""
        try:
            data = {}
            for user_id, contexts in self._contexts.items():
                user_data = {}
                for scene_id, ctx in contexts.items():
                    user_data[scene_id] = {
                        "scene_id": ctx.scene_id,
                        "context_data": ctx.context_data,
                        "last_updated": ctx.last_updated,
                        "update_count": ctx.update_count,
                    }
                data[user_id] = user_data

            persist_path = Path(self._persist_path)
            persist_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            return True
        except Exception:
            return False

    def _load_from_disk(self) -> bool:
        """从 JSON 文件加载数据."""
        try:
            if not os.path.exists(self._persist_path):
                return False

            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            with self._lock:
                self._contexts = {}
                for user_id, user_data in data.items():
                    contexts = {}
                    for scene_id, ctx_data in user_data.items():
                        ctx = SceneContext(
                            scene_id=ctx_data.get("scene_id", scene_id),
                            context_data=ctx_data.get("context_data", {}),
                            last_updated=ctx_data.get("last_updated", time.time()),
                            update_count=ctx_data.get("update_count", 0),
                        )
                        contexts[scene_id] = ctx
                    self._contexts[user_id] = contexts

            return True
        except Exception:
            return False

    @property
    def persist_path(self) -> str:
        """获取持久化文件路径."""
        return self._persist_path
