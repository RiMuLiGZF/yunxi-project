"""场景模板市场服务.

提供场景模板的浏览、搜索、应用、创建、分享、导入导出功能。
内置 8 大类场景模板，支持用户自定义和分享。

使用方式::

    service = SceneTemplateService()
    templates = service.list_templates(category="工作")
    service.apply_template(template_id, user_id)
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Optional


# 内置场景模板定义
BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    # ===== 工作模式 =====
    {
        "id": "tpl_work_focus",
        "name": "专注工作",
        "description": "深度专注模式，屏蔽干扰，提高效率",
        "category": "工作",
        "icon": "💼",
        "tags": ["专注", "效率", "深度工作"],
        "scene_target": "work",
        "difficulty": "easy",
        "settings": {
            "notification_mode": "priority_only",
            "dnd_enabled": True,
            "dnd_start": "09:00",
            "dnd_end": "18:00",
            "focus_mode": True,
            "break_reminder": True,
            "break_interval_minutes": 50,
            "break_duration_minutes": 10,
        },
        "estimated_effectiveness": 0.85,
    },
    {
        "id": "tpl_work_meeting",
        "name": "会议模式",
        "description": "会议场景，自动静音，准备会议资料",
        "category": "工作",
        "icon": "📋",
        "tags": ["会议", "协作"],
        "scene_target": "meeting",
        "difficulty": "easy",
        "settings": {
            "notification_mode": "silent",
            "auto_reply_enabled": True,
            "auto_reply_message": "正在会议中，稍后回复",
            "meeting_reminder_minutes": 5,
        },
        "estimated_effectiveness": 0.75,
    },
    {
        "id": "tpl_work_email",
        "name": "邮件处理",
        "description": "集中处理邮件，批量高效",
        "category": "工作",
        "icon": "📧",
        "tags": ["邮件", "效率"],
        "scene_target": "work",
        "difficulty": "easy",
        "settings": {
            "batch_mode": True,
            "focus_mode": True,
            "pomodoro_enabled": False,
        },
        "estimated_effectiveness": 0.70,
    },
    # ===== 学习模式 =====
    {
        "id": "tpl_learn_reading",
        "name": "深度阅读",
        "description": "沉浸式阅读学习，减少干扰",
        "category": "学习",
        "icon": "📚",
        "tags": ["阅读", "专注", "学习"],
        "scene_target": "learning",
        "difficulty": "easy",
        "settings": {
            "dnd_enabled": True,
            "reading_mode": True,
            "screen_warmth": 0.7,
            "break_interval_minutes": 45,
        },
        "estimated_effectiveness": 0.80,
    },
    {
        "id": "tpl_learn_writing",
        "name": "写作模式",
        "description": "专注写作，沉浸式创作",
        "category": "学习",
        "icon": "✍️",
        "tags": ["写作", "创作"],
        "scene_target": "learning",
        "difficulty": "medium",
        "settings": {
            "dnd_enabled": True,
            "fullscreen_mode": True,
            "typewriter_mode": True,
            "word_goal": 1000,
        },
        "estimated_effectiveness": 0.78,
    },
    {
        "id": "tpl_learn_review",
        "name": "复习模式",
        "description": "高效复习，间隔重复记忆",
        "category": "学习",
        "icon": "📝",
        "tags": ["复习", "记忆", "考试"],
        "scene_target": "learning",
        "difficulty": "medium",
        "settings": {
            "spaced_repetition": True,
            "quiz_mode": True,
            "review_interval": [1, 3, 7, 14, 30],
            "focus_mode": True,
        },
        "estimated_effectiveness": 0.82,
    },
    {
        "id": "tpl_learn_exam",
        "name": "备考模式",
        "description": "考试冲刺，高强度学习",
        "category": "学习",
        "icon": "🎯",
        "tags": ["考试", "冲刺", "高强度"],
        "scene_target": "learning",
        "difficulty": "hard",
        "settings": {
            "dnd_enabled": True,
            "pomodoro_enabled": True,
            "work_minutes": 50,
            "break_minutes": 10,
            "daily_goal_hours": 8,
            "strict_mode": True,
        },
        "estimated_effectiveness": 0.88,
    },
    # ===== 娱乐模式 =====
    {
        "id": "tpl_entertainment_gaming",
        "name": "游戏模式",
        "description": "沉浸游戏体验，性能优化",
        "category": "娱乐",
        "icon": "🎮",
        "tags": ["游戏", "性能"],
        "scene_target": "entertainment",
        "difficulty": "easy",
        "settings": {
            "performance_mode": "high",
            "notification_mode": "game_only",
            "rgb_enabled": True,
        },
        "estimated_effectiveness": 0.75,
    },
    {
        "id": "tpl_entertainment_movie",
        "name": "观影模式",
        "description": "影院级观影体验",
        "category": "娱乐",
        "icon": "🎬",
        "tags": ["电影", "放松"],
        "scene_target": "entertainment",
        "difficulty": "easy",
        "settings": {
            "notification_mode": "silent",
            "screen_warmth": 0.5,
            "theater_mode": True,
        },
        "estimated_effectiveness": 0.70,
    },
    {
        "id": "tpl_entertainment_music",
        "name": "音乐模式",
        "description": "沉浸式音乐体验",
        "category": "娱乐",
        "icon": "🎵",
        "tags": ["音乐", "放松"],
        "scene_target": "entertainment",
        "difficulty": "easy",
        "settings": {
            "audio_enhancer": True,
            "equalizer_preset": "music",
            "lyrics_display": True,
        },
        "estimated_effectiveness": 0.65,
    },
    # ===== 运动模式 =====
    {
        "id": "tpl_fitness_running",
        "name": "跑步模式",
        "description": "跑步记录与激励",
        "category": "运动",
        "icon": "🏃",
        "tags": ["跑步", "有氧"],
        "scene_target": "fitness",
        "difficulty": "easy",
        "settings": {
            "gps_tracking": True,
            "heart_rate_monitor": True,
            "voice_feedback": True,
            "feedback_interval_km": 1,
        },
        "estimated_effectiveness": 0.80,
    },
    {
        "id": "tpl_fitness_workout",
        "name": "健身训练",
        "description": "力量训练指导与记录",
        "category": "运动",
        "icon": "💪",
        "tags": ["健身", "力量训练"],
        "scene_target": "fitness",
        "difficulty": "medium",
        "settings": {
            "workout_plan": True,
            "rest_timer": True,
            "rest_seconds": 90,
            "progressive_overload": True,
        },
        "estimated_effectiveness": 0.82,
    },
    {
        "id": "tpl_fitness_yoga",
        "name": "瑜伽冥想",
        "description": "身心放松，呼吸冥想",
        "category": "运动",
        "icon": "🧘",
        "tags": ["瑜伽", "冥想", "放松"],
        "scene_target": "fitness",
        "difficulty": "easy",
        "settings": {
            "breathing_guide": True,
            "ambient_sound": True,
            "session_duration": 30,
        },
        "estimated_effectiveness": 0.78,
    },
    # ===== 睡眠模式 =====
    {
        "id": "tpl_sleep_relax",
        "name": "助眠放松",
        "description": "睡前放松，帮助入睡",
        "category": "睡眠",
        "icon": "🌙",
        "tags": ["助眠", "放松"],
        "scene_target": "sleep",
        "difficulty": "easy",
        "settings": {
            "wind_down_duration_minutes": 30,
            "screen_warmth": 0.9,
            "blue_light_filter": True,
            "sleep_sounds": True,
            "sleep_reminder": "22:30",
        },
        "estimated_effectiveness": 0.75,
    },
    {
        "id": "tpl_sleep_deep",
        "name": "深度睡眠",
        "description": "深度睡眠优化",
        "category": "睡眠",
        "icon": "😴",
        "tags": ["深睡", "质量"],
        "scene_target": "sleep",
        "difficulty": "medium",
        "settings": {
            "dnd_enabled": True,
            "smart_alarm": True,
            "sleep_tracking": True,
            "ideal_sleep_hours": 8,
            "bedtime": "23:00",
            "waketime": "07:00",
        },
        "estimated_effectiveness": 0.80,
    },
    # ===== 社交模式 =====
    {
        "id": "tpl_social_party",
        "name": "聚会模式",
        "description": "社交聚会场景",
        "category": "社交",
        "icon": "🎉",
        "tags": ["聚会", "社交"],
        "scene_target": "social",
        "difficulty": "easy",
        "settings": {
            "notification_mode": "important_only",
            "photo_mode": True,
            "location_share": True,
        },
        "estimated_effectiveness": 0.65,
    },
    # ===== 出行模式 =====
    {
        "id": "tpl_travel_commute",
        "name": "通勤模式",
        "description": "日常通勤优化",
        "category": "出行",
        "icon": "🚇",
        "tags": ["通勤", "交通"],
        "scene_target": "travel",
        "difficulty": "easy",
        "settings": {
            "traffic_alert": True,
            "route_suggestion": True,
            "podcast_auto_play": True,
            "offline_maps": True,
        },
        "estimated_effectiveness": 0.72,
    },
    # ===== 创作模式 =====
    {
        "id": "tpl_create_coding",
        "name": "编程模式",
        "description": "沉浸式编程开发",
        "category": "创作",
        "icon": "💻",
        "tags": ["编程", "开发", "专注"],
        "scene_target": "creative",
        "difficulty": "medium",
        "settings": {
            "dnd_enabled": True,
            "focus_mode": True,
            "pomodoro_enabled": True,
            "work_minutes": 50,
            "break_minutes": 10,
            "editor_theme": "dark",
        },
        "estimated_effectiveness": 0.85,
    },
    {
        "id": "tpl_create_design",
        "name": "设计创作",
        "description": "设计工作场景",
        "category": "创作",
        "icon": "🎨",
        "tags": ["设计", "创作"],
        "scene_target": "creative",
        "difficulty": "medium",
        "settings": {
            "dnd_enabled": True,
            "color_calibration": True,
            "performance_mode": "high",
        },
        "estimated_effectiveness": 0.78,
    },
]


class SceneTemplateService:
    """场景模板市场服务."""

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self._lock = Lock()
        self._storage_path = Path(storage_path) if storage_path else None
        self._custom_templates: dict[str, dict[str, Any]] = {}
        self._applications: dict[str, list[dict[str, Any]]] = {}  # user_id -> 应用记录
        self._load_custom_templates()

    def _load_custom_templates(self) -> None:
        """加载自定义模板."""
        if self._storage_path:
            try:
                file_path = self._storage_path / "custom_templates.json"
                if file_path.exists():
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    for tpl in data.get("templates", []):
                        self._custom_templates[tpl["id"]] = tpl
            except Exception:
                pass

    def _save_custom_templates(self) -> None:
        """保存自定义模板."""
        if self._storage_path:
            try:
                self._storage_path.mkdir(parents=True, exist_ok=True)
                file_path = self._storage_path / "custom_templates.json"
                data = {"templates": list(self._custom_templates.values())}
                file_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 模板浏览与搜索
    # ------------------------------------------------------------------

    def list_templates(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        sort_by: str = "popular",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """列出模板.

        Args:
            category: 分类过滤
            difficulty: 难度过滤
            sort_by: 排序方式 (popular/new/name/rating)
            page: 页码
            page_size: 每页数量
        """
        all_templates = list(BUILTIN_TEMPLATES) + list(self._custom_templates.values())

        # 过滤
        if category:
            all_templates = [t for t in all_templates if t.get("category") == category]
        if difficulty:
            all_templates = [t for t in all_templates if t.get("difficulty") == difficulty]

        # 排序
        if sort_by == "name":
            all_templates.sort(key=lambda t: t["name"])
        elif sort_by == "rating":
            all_templates.sort(key=lambda t: t.get("rating", 0), reverse=True)
        elif sort_by == "new":
            all_templates.sort(
                key=lambda t: t.get("created_at", ""), reverse=True
            )
        # popular: 默认按效果评分
        else:
            all_templates.sort(
                key=lambda t: t.get("estimated_effectiveness", 0), reverse=True
            )

        total = len(all_templates)
        start = (page - 1) * page_size
        end = start + page_size
        items = all_templates[start:end]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    def search_templates(
        self,
        keyword: str,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """搜索模板."""
        keyword_lower = keyword.lower()
        all_templates = list(BUILTIN_TEMPLATES) + list(self._custom_templates.values())

        scored = []
        for tpl in all_templates:
            if category and tpl.get("category") != category:
                continue
            score = 0
            name = tpl.get("name", "")
            desc = tpl.get("description", "")
            tags = tpl.get("tags", [])

            if keyword_lower in name.lower():
                score += 50
            if keyword_lower in desc.lower():
                score += 20
            for tag in tags:
                if keyword_lower in tag.lower():
                    score += 15
            if keyword_lower in tpl.get("category", "").lower():
                score += 10

            if score > 0:
                scored.append((score, tpl))

        scored.sort(key=lambda x: x[0], reverse=True)
        total = len(scored)
        start = (page - 1) * page_size
        end = start + page_size
        items = [tpl for _, tpl in scored[start:end]]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    def get_template(self, template_id: str) -> Optional[dict[str, Any]]:
        """获取模板详情."""
        for tpl in BUILTIN_TEMPLATES:
            if tpl["id"] == template_id:
                return deepcopy(tpl)
        if template_id in self._custom_templates:
            return deepcopy(self._custom_templates[template_id])
        return None

    def get_categories(self) -> list[dict[str, Any]]:
        """获取模板分类列表."""
        categories = {}
        for tpl in BUILTIN_TEMPLATES:
            cat = tpl.get("category", "其他")
            if cat not in categories:
                categories[cat] = {"name": cat, "count": 0, "icon": ""}
            categories[cat]["count"] += 1

        for tpl in self._custom_templates.values():
            cat = tpl.get("category", "其他")
            if cat not in categories:
                categories[cat] = {"name": cat, "count": 0, "icon": ""}
            categories[cat]["count"] += 1

        return list(categories.values())

    # ------------------------------------------------------------------
    # 模板应用
    # ------------------------------------------------------------------

    def apply_template(
        self,
        template_id: str,
        user_id: str,
        override_settings: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """应用模板.

        Args:
            template_id: 模板 ID
            user_id: 用户 ID
            override_settings: 覆盖的设置

        Returns:
            应用结果
        """
        template = self.get_template(template_id)
        if not template:
            return {"success": False, "error": "模板不存在"}

        settings = deepcopy(template.get("settings", {}))
        if override_settings:
            settings.update(override_settings)

        # 记录应用
        with self._lock:
            if user_id not in self._applications:
                self._applications[user_id] = []
            self._applications[user_id].append({
                "template_id": template_id,
                "template_name": template.get("name", ""),
                "applied_at": datetime.now().isoformat(),
                "settings": settings,
            })

        return {
            "success": True,
            "template": template,
            "settings": settings,
            "scene_target": template.get("scene_target"),
            "message": f"已应用模板「{template.get('name', '')}」",
        }

    def get_applied_templates(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取用户已应用的模板历史."""
        with self._lock:
            apps = self._applications.get(user_id, [])
        return list(reversed(apps[-limit:]))

    # ------------------------------------------------------------------
    # 自定义模板
    # ------------------------------------------------------------------

    def create_custom_template(
        self,
        name: str,
        description: str,
        category: str,
        settings: dict[str, Any],
        user_id: str,
        icon: str = "📄",
        tags: Optional[list[str]] = None,
        scene_target: str = "custom",
    ) -> dict[str, Any]:
        """创建自定义模板."""
        template_id = f"tpl_custom_{uuid.uuid4().hex[:8]}"
        template = {
            "id": template_id,
            "name": name,
            "description": description,
            "category": category,
            "icon": icon,
            "tags": tags or [],
            "scene_target": scene_target,
            "is_custom": True,
            "is_builtin": False,
            "owner_id": user_id,
            "settings": deepcopy(settings),
            "difficulty": "custom",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "usage_count": 0,
            "rating": 0.0,
        }

        with self._lock:
            self._custom_templates[template_id] = template
            self._save_custom_templates()

        return template

    def update_custom_template(
        self,
        template_id: str,
        user_id: str,
        data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新自定义模板."""
        with self._lock:
            tpl = self._custom_templates.get(template_id)
            if not tpl:
                return None
            if tpl.get("owner_id") != user_id:
                return None  # 无权限
            for key in ["name", "description", "category", "icon", "tags", "settings"]:
                if key in data:
                    tpl[key] = data[key]
            tpl["updated_at"] = datetime.now().isoformat()
            self._save_custom_templates()
            return deepcopy(tpl)

    def delete_custom_template(self, template_id: str, user_id: str) -> bool:
        """删除自定义模板."""
        with self._lock:
            tpl = self._custom_templates.get(template_id)
            if not tpl:
                return False
            if tpl.get("owner_id") != user_id:
                return False
            del self._custom_templates[template_id]
            self._save_custom_templates()
            return True

    def list_my_templates(self, user_id: str) -> list[dict[str, Any]]:
        """列出用户的自定义模板."""
        return [
            deepcopy(tpl)
            for tpl in self._custom_templates.values()
            if tpl.get("owner_id") == user_id
        ]

    # ------------------------------------------------------------------
    # 导入导出
    # ------------------------------------------------------------------

    def export_template(self, template_id: str) -> Optional[dict[str, Any]]:
        """导出模板."""
        template = self.get_template(template_id)
        if not template:
            return None
        # 移除运行时字段
        template.pop("usage_count", None)
        template.pop("rating", None)
        template["export_version"] = "1.0"
        template["exported_at"] = datetime.now().isoformat()
        return template

    def import_template(
        self,
        template_data: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        """导入模板."""
        # 基本校验
        required_fields = ["name", "description", "settings"]
        for field in required_fields:
            if field not in template_data:
                return {"success": False, "error": f"缺少必填字段: {field}"}

        new_id = f"tpl_imported_{uuid.uuid4().hex[:8]}"
        template = deepcopy(template_data)
        template["id"] = new_id
        template["is_custom"] = True
        template["is_builtin"] = False
        template["owner_id"] = user_id
        template["imported_at"] = datetime.now().isoformat()

        with self._lock:
            self._custom_templates[new_id] = template
            self._save_custom_templates()

        return {"success": True, "template": template}

    # ------------------------------------------------------------------
    # 场景组合（嵌套/叠加）
    # ------------------------------------------------------------------

    def combine_scenes(
        self,
        primary_scene: str,
        secondary_scenes: list[str],
        user_id: str,
    ) -> dict[str, Any]:
        """场景组合（主场景 + 辅助场景叠加）.

        Args:
            primary_scene: 主场景 ID
            secondary_scenes: 辅助场景列表
            user_id: 用户 ID

        Returns:
            组合后的场景配置
        """
        # 简单实现：主场景设置为主，辅助场景的设置叠加
        primary = self.get_template(f"tpl_{primary_scene}")
        if not primary:
            # 尝试从内置中找
            for tpl in BUILTIN_TEMPLATES:
                if tpl.get("scene_target") == primary_scene:
                    primary = tpl
                    break

        base_settings = deepcopy(primary.get("settings", {})) if primary else {}
        combined_settings = dict(base_settings)

        for sec in secondary_scenes:
            sec_tpl = None
            for tpl in BUILTIN_TEMPLATES:
                if tpl.get("scene_target") == sec:
                    sec_tpl = tpl
                    break
            if sec_tpl:
                # 叠加：辅助场景的非冲突设置合并进来
                for key, value in sec_tpl.get("settings", {}).items():
                    if key not in combined_settings:
                        combined_settings[key] = value

        return {
            "success": True,
            "primary": primary_scene,
            "secondary": secondary_scenes,
            "combined_settings": combined_settings,
            "total_settings": len(combined_settings),
        }

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取模板市场统计."""
        builtin_count = len(BUILTIN_TEMPLATES)
        custom_count = len(self._custom_templates)
        categories = self.get_categories()

        return {
            "total_templates": builtin_count + custom_count,
            "builtin_templates": builtin_count,
            "custom_templates": custom_count,
            "categories": len(categories),
            "category_list": categories,
        }
