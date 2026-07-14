"""
成长中心 - 后端 API 路由
包含7个子系统：成就、天赋树、赛季旅程、记忆回响、成长纪事、潮汐日历、形象工坊
数据存储：SQLite 数据库（从 JSON 迁移而来）
"""

import sys
import json
import uuid
import random
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from ..models import (
    get_db,
    GrowthAchievement,
    GrowthTalent,
    GrowthTalentMeta,
    GrowthSeason,
    GrowthSeasonTask,
    GrowthMemory,
    GrowthChronicle,
    GrowthCalendar,
)

router = APIRouter()

# 默认用户 ID（单用户模式）
DEFAULT_USER_ID = 1


# ==================== 数据存储路径（用于迁移） ====================

def _get_growth_dir() -> Path:
    """获取成长数据目录 ~/.yunxi/growth/"""
    growth_dir = Path.home() / ".yunxi" / "growth"
    growth_dir.mkdir(parents=True, exist_ok=True)
    return growth_dir


GROWTH_DIR = _get_growth_dir()
ACHIEVEMENTS_FILE = GROWTH_DIR / "achievements.json"
TALENTS_FILE = GROWTH_DIR / "talents.json"
SEASON_FILE = GROWTH_DIR / "season.json"
CHRONICLE_FILE = GROWTH_DIR / "chronicle.json"
CALENDAR_FILE = GROWTH_DIR / "calendar.json"
MEMORIES_FILE = GROWTH_DIR / "memories.json"


# ==================== 通用 JSON 存储工具（迁移用） ====================

def _load_json(filepath: Path, default: Any) -> Any:
    """从文件加载 JSON 数据（迁移时使用）"""
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json(filepath: Path, data: Any) -> None:
    """保存 JSON 数据到文件（迁移用）"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_user_id(current_user: dict) -> int:
    """从当前用户获取用户标识（单用户模式默认 1）"""
    return DEFAULT_USER_ID


# ==================== 预置数据 ====================

def _get_default_achievements() -> List[dict]:
    """预置20+个成就"""
    return [
        # 探索类
        {"id": "ach_001", "name": "初次相遇", "description": "第一次登录云汐系统", "category": "exploration", "rarity": "common", "icon": "🌟", "points": 10, "unlocked": False, "unlocked_at": None},
        {"id": "ach_002", "name": "探索先锋", "description": "访问所有功能模块", "category": "exploration", "rarity": "rare", "icon": "🔭", "points": 50, "unlocked": False, "unlocked_at": None},
        {"id": "ach_003", "name": "深度潜水", "description": "使用潮汐记忆系统", "category": "exploration", "rarity": "uncommon", "icon": "🌊", "points": 30, "unlocked": False, "unlocked_at": None},
        {"id": "ach_004", "name": "多面手", "description": "使用5种不同的技能", "category": "exploration", "rarity": "rare", "icon": "🎭", "points": 50, "unlocked": False, "unlocked_at": None},
        {"id": "ach_005", "name": "系统架构师", "description": "部署并运行所有模块", "category": "exploration", "rarity": "epic", "icon": "🏛️", "points": 100, "unlocked": False, "unlocked_at": None},
        # 对话类
        {"id": "ach_006", "name": "初出茅庐", "description": "完成第一次对话", "category": "conversation", "rarity": "common", "icon": "💬", "points": 10, "unlocked": False, "unlocked_at": None},
        {"id": "ach_007", "name": "健谈者", "description": "累计对话100次", "category": "conversation", "rarity": "uncommon", "icon": "🗣️", "points": 30, "unlocked": False, "unlocked_at": None},
        {"id": "ach_008", "name": "深夜交谈", "description": "在凌晨1点后进行对话", "category": "conversation", "rarity": "rare", "icon": "🌙", "points": 40, "unlocked": False, "unlocked_at": None},
        {"id": "ach_009", "name": "长篇大论", "description": "单次对话超过50轮", "category": "conversation", "rarity": "epic", "icon": "📜", "points": 80, "unlocked": False, "unlocked_at": None},
        {"id": "ach_010", "name": "知心好友", "description": "累计对话1000次", "category": "conversation", "rarity": "legendary", "icon": "💝", "points": 200, "unlocked": False, "unlocked_at": None},
        # 成长类
        {"id": "ach_011", "name": "天赋觉醒", "description": "解锁第一个天赋节点", "category": "growth", "rarity": "common", "icon": "✨", "points": 15, "unlocked": False, "unlocked_at": None},
        {"id": "ach_012", "name": "天赋异禀", "description": "解锁10个天赋节点", "category": "growth", "rarity": "rare", "icon": "🌠", "points": 60, "unlocked": False, "unlocked_at": None},
        {"id": "ach_013", "name": "全知全能", "description": "解锁所有天赋节点", "category": "growth", "rarity": "legendary", "icon": "👑", "points": 500, "unlocked": False, "unlocked_at": None},
        {"id": "ach_014", "name": "持之以恒", "description": "连续打卡7天", "category": "growth", "rarity": "uncommon", "icon": "📅", "points": 30, "unlocked": False, "unlocked_at": None},
        {"id": "ach_015", "name": "月度冠军", "description": "连续打卡30天", "category": "growth", "rarity": "epic", "icon": "🏆", "points": 150, "unlocked": False, "unlocked_at": None},
        # 记忆类
        {"id": "ach_016", "name": "记忆萌芽", "description": "保存第一条记忆", "category": "memory", "rarity": "common", "icon": "🌱", "points": 10, "unlocked": False, "unlocked_at": None},
        {"id": "ach_017", "name": "记忆收藏家", "description": "保存100条记忆", "category": "memory", "rarity": "rare", "icon": "📚", "points": 80, "unlocked": False, "unlocked_at": None},
        {"id": "ach_018", "name": "深海宝藏", "description": "一条记忆晋升到深海层", "category": "memory", "rarity": "epic", "icon": "💎", "points": 100, "unlocked": False, "unlocked_at": None},
        {"id": "ach_019", "name": "回响共鸣", "description": "生成第一条记忆回响", "category": "memory", "rarity": "uncommon", "icon": "🎵", "points": 25, "unlocked": False, "unlocked_at": None},
        # 赛季类
        {"id": "ach_020", "name": "赛季启航", "description": "完成第一个赛季任务", "category": "season", "rarity": "common", "icon": "⛵", "points": 20, "unlocked": False, "unlocked_at": None},
        {"id": "ach_021", "name": "赛季达人", "description": "完成本赛季所有任务", "category": "season", "rarity": "epic", "icon": "🏅", "points": 120, "unlocked": False, "unlocked_at": None},
        {"id": "ach_022", "name": "时光旅者", "description": "参与3个赛季", "category": "season", "rarity": "legendary", "icon": "⏳", "points": 300, "unlocked": False, "unlocked_at": None},
        # 特殊类
        {"id": "ach_023", "name": "完美主义者", "description": "获得所有普通成就", "category": "special", "rarity": "rare", "icon": "🎯", "points": 100, "unlocked": False, "unlocked_at": None},
        {"id": "ach_024", "name": "云汐守护者", "description": "使用系统超过100小时", "category": "special", "rarity": "legendary", "icon": "🛡️", "points": 500, "unlocked": False, "unlocked_at": None},
        {"id": "ach_025", "name": "彩蛋猎人", "description": "发现一个隐藏成就", "category": "special", "rarity": "epic", "icon": "🥚", "points": 88, "unlocked": False, "unlocked_at": None},
    ]


def _get_default_talents() -> dict:
    """预置15+个天赋节点"""
    nodes = [
        # 第一层 - 核心
        {"id": "tal_001", "name": "感知强化", "description": "提升信息感知能力，加快响应速度", "branch": "core", "layer": 1, "max_level": 3, "current_level": 0, "cost": [1, 2, 3], "icon": "👁️", "position": {"x": 400, "y": 50}, "prerequisites": [], "effects": ["响应速度+5%/级", "信息提取+3%/级"]},
        # 第二层 - 左分支（认知）
        {"id": "tal_002", "name": "逻辑推演", "description": "增强逻辑推理和分析能力", "branch": "cognition", "layer": 2, "max_level": 3, "current_level": 0, "cost": [2, 3, 4], "icon": "🧠", "position": {"x": 250, "y": 130}, "prerequisites": ["tal_001"], "effects": ["推理精度+5%/级"]},
        {"id": "tal_003", "name": "创意涌现", "description": "激发创意和发散思维", "branch": "cognition", "layer": 2, "max_level": 3, "current_level": 0, "cost": [2, 3, 4], "icon": "💡", "position": {"x": 550, "y": 130}, "prerequisites": ["tal_001"], "effects": ["创意产出+8%/级"]},
        # 第三层 - 中分支
        {"id": "tal_004", "name": "深度理解", "description": "加深对复杂概念的理解", "branch": "cognition", "layer": 3, "max_level": 3, "current_level": 0, "cost": [3, 4, 5], "icon": "📖", "position": {"x": 150, "y": 210}, "prerequisites": ["tal_002"], "effects": ["理解深度+6%/级"]},
        {"id": "tal_005", "name": "记忆宫殿", "description": "提升记忆检索和存储效率", "branch": "memory", "layer": 3, "max_level": 3, "current_level": 0, "cost": [3, 4, 5], "icon": "🏰", "position": {"x": 400, "y": 210}, "prerequisites": ["tal_002", "tal_003"], "effects": ["记忆速度+10%/级", "检索精度+5%/级"]},
        {"id": "tal_006", "name": "语言精通", "description": "提升多语言处理能力", "branch": "cognition", "layer": 3, "max_level": 3, "current_level": 0, "cost": [3, 4, 5], "icon": "🌐", "position": {"x": 650, "y": 210}, "prerequisites": ["tal_003"], "effects": ["翻译质量+8%/级"]},
        # 第四层
        {"id": "tal_007", "name": "知识图谱", "description": "构建关联知识网络", "branch": "memory", "layer": 4, "max_level": 3, "current_level": 0, "cost": [4, 5, 6], "icon": "🕸️", "position": {"x": 250, "y": 290}, "prerequisites": ["tal_004", "tal_005"], "effects": ["关联记忆+12%/级"]},
        {"id": "tal_008", "name": "情感共鸣", "description": "增强情感理解和共情能力", "branch": "emotion", "layer": 4, "max_level": 3, "current_level": 0, "cost": [4, 5, 6], "icon": "💗", "position": {"x": 550, "y": 290}, "prerequisites": ["tal_005", "tal_006"], "effects": ["情感识别+10%/级", "共情能力+8%/级"]},
        # 第五层
        {"id": "tal_009", "name": "创造力爆发", "description": "突破性创意生成", "branch": "cognition", "layer": 5, "max_level": 1, "current_level": 0, "cost": [10], "icon": "🚀", "position": {"x": 150, "y": 370}, "prerequisites": ["tal_007"], "effects": ["突破性创意概率+15%"]},
        {"id": "tal_010", "name": "智慧核心", "description": "整合所有认知能力的核心", "branch": "core", "layer": 5, "max_level": 1, "current_level": 0, "cost": [10], "icon": "💠", "position": {"x": 400, "y": 370}, "prerequisites": ["tal_007", "tal_008"], "effects": ["全属性+5%"]},
        {"id": "tal_011", "name": "心灵相通", "description": "深度情感连接能力", "branch": "emotion", "layer": 5, "max_level": 1, "current_level": 0, "cost": [10], "icon": "💕", "position": {"x": 650, "y": 370}, "prerequisites": ["tal_008"], "effects": ["情感共鸣深度+20%"]},
        # 辅助分支
        {"id": "tal_012", "name": "效率提升", "description": "提升任务执行效率", "branch": "utility", "layer": 2, "max_level": 3, "current_level": 0, "cost": [1, 2, 3], "icon": "⚡", "position": {"x": 100, "y": 130}, "prerequisites": ["tal_001"], "effects": ["任务速度+7%/级"]},
        {"id": "tal_013", "name": "精准输出", "description": "提升输出质量和准确性", "branch": "utility", "layer": 3, "max_level": 3, "current_level": 0, "cost": [2, 3, 4], "icon": "🎯", "position": {"x": 50, "y": 210}, "prerequisites": ["tal_012"], "effects": ["输出精度+6%/级"]},
        {"id": "tal_014", "name": "自适应学习", "description": "根据交互自动优化", "branch": "utility", "layer": 4, "max_level": 2, "current_level": 0, "cost": [5, 7], "icon": "🔄", "position": {"x": 100, "y": 290}, "prerequisites": ["tal_013"], "effects": ["自适应优化+10%/级"]},
        {"id": "tal_015", "name": "完美主义", "description": "所有输出追求极致品质", "branch": "utility", "layer": 5, "max_level": 1, "current_level": 0, "cost": [8], "icon": "✨", "position": {"x": 150, "y": 370}, "prerequisites": ["tal_014"], "effects": ["品质加成+15%"]},
        # 右侧辅助
        {"id": "tal_016", "name": "社交魅力", "description": "提升社交互动体验", "branch": "social", "layer": 2, "max_level": 3, "current_level": 0, "cost": [1, 2, 3], "icon": "🌟", "position": {"x": 700, "y": 130}, "prerequisites": ["tal_001"], "effects": ["互动愉悦度+5%/级"]},
        {"id": "tal_017", "name": "治愈心灵", "description": "提供情绪价值和慰藉", "branch": "social", "layer": 3, "max_level": 3, "current_level": 0, "cost": [2, 3, 4], "icon": "🫂", "position": {"x": 750, "y": 210}, "prerequisites": ["tal_016"], "effects": ["治愈效果+8%/级"]},
    ]
    
    # 生成连线
    connections = []
    node_map = {n["id"]: n for n in nodes}
    for node in nodes:
        for prereq in node["prerequisites"]:
            connections.append({
                "from": prereq,
                "to": node["id"],
            })
    
    return {
        "total_points": 5,
        "used_points": 0,
        "nodes": nodes,
        "connections": connections,
    }


def _get_default_season() -> dict:
    """预置赛季数据"""
    now = datetime.now()
    season_start = datetime(now.year, now.month, 1)
    season_end = (season_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    
    return {
        "current_season": {
            "id": f"season_{now.year}_{now.month:02d}",
            "name": f"{now.year}年{now.month}月潮汐季",
            "theme": "探索成长",
            "description": "本月主题：探索自我，持续成长。完成每日任务获取丰厚奖励！",
            "start_date": season_start.strftime("%Y-%m-%d"),
            "end_date": season_end.strftime("%Y-%m-%d"),
            "status": "active",
            "total_tasks": 8,
            "completed_tasks": 0,
            "claimed_tasks": 0,
            "reward_preview": {
                "points": 500,
                "title": "潮汐探索者",
                "badge": "🏅",
            },
        },
        "tasks": [
            {"id": "st_001", "name": "每日问候", "description": "每天与云汐打个招呼", "type": "daily", "target": 1, "current": 0, "reward_points": 10, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_002", "name": "知识汲取", "description": "进行一次有深度的对话", "type": "daily", "target": 1, "current": 0, "reward_points": 15, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_003", "name": "记忆留存", "description": "保存一条记忆到潮汐记忆", "type": "daily", "target": 1, "current": 0, "reward_points": 20, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_004", "name": "天赋激活", "description": "升级一个天赋节点", "type": "weekly", "target": 1, "current": 0, "reward_points": 50, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_005", "name": "持之以恒", "description": "连续打卡7天", "type": "weekly", "target": 7, "current": 0, "reward_points": 80, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_006", "name": "探索达人", "description": "使用3个不同的功能模块", "type": "weekly", "target": 3, "current": 0, "reward_points": 60, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_007", "name": "月度成就", "description": "解锁5个成就", "type": "monthly", "target": 5, "current": 0, "reward_points": 150, "status": "incomplete", "completed_at": None, "claimed": False},
            {"id": "st_008", "name": "赛季全勤", "description": "完成所有每日和每周任务", "type": "monthly", "target": 30, "current": 0, "reward_points": 300, "status": "incomplete", "completed_at": None, "claimed": False},
        ],
        "history": [
            {
                "id": "season_2026_06",
                "name": "2026年6月初心季",
                "theme": "初心启程",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "status": "completed",
                "completed_tasks": 6,
                "total_tasks": 8,
                "rank": "silver",
            },
            {
                "id": "season_2026_05",
                "name": "2026年5月萌芽季",
                "theme": "春芽初萌",
                "start_date": "2026-05-01",
                "end_date": "2026-05-31",
                "status": "completed",
                "completed_tasks": 8,
                "total_tasks": 8,
                "rank": "gold",
            },
        ],
    }


def _get_default_chronicle() -> dict:
    """预置纪事数据"""
    return {
        "entries": [
            {
                "id": "chr_001",
                "title": "与云汐的第一次相遇",
                "content": "今天第一次打开云汐系统，感觉界面很清新。和AI聊了聊最近的心情，它的回应很温暖。期待接下来的探索之旅。",
                "category": "milestone",
                "tags": ["初次体验", "心情"],
                "mood": "happy",
                "created_at": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
                "important": True,
            },
            {
                "id": "chr_002",
                "title": "发现潮汐记忆",
                "content": "探索了潮汐记忆系统，四层记忆模型很有意思。沙滩层、浅水层、深水层、深渊层，就像真实的记忆一样会逐渐沉淀。",
                "category": "discovery",
                "tags": ["记忆系统", "探索"],
                "mood": "curious",
                "created_at": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
                "important": False,
            },
            {
                "id": "chr_003",
                "title": "第一个成就解锁",
                "content": "解锁了第一个成就「初次相遇」！看着成就列表里亮起的图标，有种游戏的感觉。成长系统的设计很用心。",
                "category": "achievement",
                "tags": ["成就", "成长"],
                "mood": "proud",
                "created_at": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
                "important": True,
            },
        ],
        "total": 3,
    }


def _get_default_calendar() -> dict:
    """预置日历数据"""
    today = date.today()
    checkin_days = []
    # 生成过去7天的打卡记录（模拟）
    for i in range(1, 8):
        d = today - timedelta(days=i)
        if random.random() > 0.3:  # 70% 概率打卡
            checkin_days.append({
                "date": d.strftime("%Y-%m-%d"),
                "checked_in": True,
                "mood": random.choice(["happy", "calm", "energetic", "peaceful"]),
                "note": "",
            })
    
    return {
        "checkin_days": checkin_days,
        "streak": 3,  # 当前连续打卡天数
        "total_checkins": len(checkin_days),
        "monthly_moods": {},
    }


def _get_default_memories() -> dict:
    """预置记忆回响数据（M5不可用时使用）"""
    return {
        "echoes": [
            {
                "id": "echo_001",
                "title": "温暖的午后对话",
                "content_summary": "那天下午聊了很多关于梦想的话题，云汐说要陪我一起实现。",
                "original_memory_id": "mem_demo_001",
                "generated_at": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "emotion_tags": ["温暖", "希望"],
                "echo_type": "reflection",
                "favorite": True,
            },
            {
                "id": "echo_002",
                "title": "困惑时的指引",
                "content_summary": "在工作遇到瓶颈时，云汐帮我梳理了思路，找到了新的方向。",
                "original_memory_id": "mem_demo_002",
                "generated_at": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
                "emotion_tags": ["感激", "成长"],
                "echo_type": "insight",
                "favorite": False,
            },
        ],
        "total": 2,
    }


# ==================== 数据迁移：JSON → 数据库 ====================

def _migrate_from_json(db: Session, user_id: int = DEFAULT_USER_ID) -> None:
    """
    从 JSON 文件迁移数据到 SQLite 数据库。
    仅当对应表为空时执行迁移，保证幂等性。
    """
    # ---- 成就迁移 ----
    if db.query(GrowthAchievement).filter_by(user_id=user_id).count() == 0:
        achievements_data = _load_json(ACHIEVEMENTS_FILE, _get_default_achievements())
        for ach in achievements_data:
            unlocked_at = None
            if ach.get("unlocked_at"):
                try:
                    unlocked_at = datetime.strptime(ach["unlocked_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    unlocked_at = None
            db.add(GrowthAchievement(
                achievement_id=ach["id"],
                name=ach.get("name", ""),
                description=ach.get("description", ""),
                category=ach.get("category", "exploration"),
                rarity=ach.get("rarity", "common"),
                points=ach.get("points", 0),
                icon=ach.get("icon", ""),
                unlocked=ach.get("unlocked", False),
                unlocked_at=unlocked_at,
                user_id=user_id,
            ))
        db.commit()

    # ---- 天赋树迁移 ----
    if db.query(GrowthTalent).filter_by(user_id=user_id).count() == 0:
        talents_data = _load_json(TALENTS_FILE, _get_default_talents())
        nodes = talents_data.get("nodes", [])
        for node in nodes:
            pos = node.get("position", {})
            db.add(GrowthTalent(
                talent_id=node["id"],
                name=node.get("name", ""),
                description=node.get("description", ""),
                branch=node.get("branch", "core"),
                tier=node.get("layer", 1),
                cost=node.get("cost", []),
                unlocked=node.get("current_level", 0) > 0,
                current_level=node.get("current_level", 0),
                max_level=node.get("max_level", 1),
                position_x=pos.get("x", 0),
                position_y=pos.get("y", 0),
                prerequisites=node.get("prerequisites", []),
                effects=node.get("effects", []),
                icon=node.get("icon", ""),
                user_id=user_id,
            ))
        # 天赋点元数据
        db.add(GrowthTalentMeta(
            total_points=talents_data.get("total_points", 5),
            used_points=talents_data.get("used_points", 0),
            user_id=user_id,
        ))
        db.commit()

    # ---- 赛季迁移 ----
    if db.query(GrowthSeason).filter_by(user_id=user_id).count() == 0:
        season_data = _load_json(SEASON_FILE, _get_default_season())
        # 当前赛季
        current = season_data.get("current_season", {})
        if current:
            db.add(GrowthSeason(
                season_id=current["id"],
                name=current.get("name", ""),
                theme=current.get("theme", ""),
                description=current.get("description", ""),
                start_date=current.get("start_date", ""),
                end_date=current.get("end_date", ""),
                current=True,
                status=current.get("status", "active"),
                reward_preview=current.get("reward_preview", {}),
                user_id=user_id,
            ))
            # 当前赛季任务
            for task in season_data.get("tasks", []):
                completed_at = None
                if task.get("completed_at"):
                    try:
                        completed_at = datetime.strptime(task["completed_at"], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        completed_at = None
                db.add(GrowthSeasonTask(
                    season_id=current["id"],
                    task_id=task["id"],
                    name=task.get("name", ""),
                    description=task.get("description", ""),
                    type=task.get("type", "daily"),
                    points=task.get("reward_points", 0),
                    target=task.get("target", 1),
                    current=task.get("current", 0),
                    completed=task.get("status") == "completed",
                    completed_at=completed_at,
                    claimed=task.get("claimed", False),
                    user_id=user_id,
                ))
        # 历史赛季
        for hist in season_data.get("history", []):
            db.add(GrowthSeason(
                season_id=hist["id"],
                name=hist.get("name", ""),
                theme=hist.get("theme", ""),
                start_date=hist.get("start_date", ""),
                end_date=hist.get("end_date", ""),
                current=False,
                status=hist.get("status", "completed"),
                rank=hist.get("rank"),
                user_id=user_id,
            ))
        db.commit()

    # ---- 记忆回响迁移 ----
    if db.query(GrowthMemory).filter_by(user_id=user_id).count() == 0:
        memories_data = _load_json(MEMORIES_FILE, _get_default_memories())
        for echo in memories_data.get("echoes", []):
            generated_at = None
            if echo.get("generated_at"):
                try:
                    generated_at = datetime.strptime(echo["generated_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    generated_at = None
            db.add(GrowthMemory(
                memory_id=echo["id"],
                title=echo.get("title", ""),
                content=echo.get("content_summary", ""),
                content_summary=echo.get("content_summary", ""),
                tags=echo.get("emotion_tags", []),
                emotion_tags=echo.get("emotion_tags", []),
                echo_type=echo.get("echo_type", "reflection"),
                original_memory_id=echo.get("original_memory_id"),
                favorite=echo.get("favorite", False),
                generated_at=generated_at,
                created_at=generated_at or datetime.utcnow(),
                user_id=user_id,
            ))
        db.commit()

    # ---- 成长纪事迁移 ----
    if db.query(GrowthChronicle).filter_by(user_id=user_id).count() == 0:
        chronicle_data = _load_json(CHRONICLE_FILE, _get_default_chronicle())
        for entry in chronicle_data.get("entries", []):
            created_at = None
            updated_at = None
            if entry.get("created_at"):
                try:
                    created_at = datetime.strptime(entry["created_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    created_at = None
            if entry.get("updated_at"):
                try:
                    updated_at = datetime.strptime(entry["updated_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    updated_at = None
            db.add(GrowthChronicle(
                chronicle_id=entry["id"],
                title=entry.get("title", ""),
                content=entry.get("content", ""),
                category=entry.get("category", "daily"),
                tags=entry.get("tags", []),
                mood=entry.get("mood"),
                important=entry.get("important", False),
                created_at=created_at or datetime.utcnow(),
                updated_at=updated_at or datetime.utcnow(),
                user_id=user_id,
            ))
        db.commit()

    # ---- 潮汐日历迁移 ----
    if db.query(GrowthCalendar).filter_by(user_id=user_id).count() == 0:
        calendar_data = _load_json(CALENDAR_FILE, _get_default_calendar())
        streak = calendar_data.get("streak", 0)
        for day in calendar_data.get("checkin_days", []):
            db.add(GrowthCalendar(
                date=day["date"],
                checked_in=day.get("checked_in", True),
                mood=day.get("mood"),
                note=day.get("note", ""),
                streak=streak,
                user_id=user_id,
            ))
        db.commit()


# ==================== 数据初始化 ====================

def _ensure_data_initialized(db: Session, user_id: int = DEFAULT_USER_ID):
    """确保所有数据已初始化（优先从 JSON 迁移，否则使用默认数据）"""
    _migrate_from_json(db, user_id)


# ==================== Pydantic 模型 ====================

class ChronicleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="纪事标题")
    content: str = Field(..., min_length=1, description="纪事内容")
    category: str = Field(default="daily", description="分类：milestone/discovery/achievement/daily/reflection")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    mood: Optional[str] = Field(default=None, description="心情标签")
    important: bool = Field(default=False, description="是否重要")


class ChronicleUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    content: Optional[str] = Field(default=None)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    mood: Optional[str] = None
    important: Optional[bool] = None


class MemoryGenerateRequest(BaseModel):
    query: Optional[str] = Field(default=None, description="生成回响的主题/关键词")
    memory_id: Optional[str] = Field(default=None, description="基于特定记忆生成")
    echo_type: str = Field(default="reflection", description="回响类型：reflection/insight/poem/story")


class CheckinRequest(BaseModel):
    mood: Optional[str] = Field(default="calm", description="今日心情")
    note: Optional[str] = Field(default="", description="打卡备注")


# ==================== 辅助工具：ORM → Dict ====================

def _achievement_to_dict(ach: GrowthAchievement) -> dict:
    """成就 ORM → 字典（兼容原格式）"""
    return {
        "id": ach.achievement_id,
        "name": ach.name,
        "description": ach.description,
        "category": ach.category,
        "rarity": ach.rarity,
        "icon": ach.icon,
        "points": ach.points,
        "unlocked": ach.unlocked,
        "unlocked_at": ach.unlocked_at.strftime("%Y-%m-%d %H:%M:%S") if ach.unlocked_at else None,
    }


def _talent_to_dict(tal: GrowthTalent) -> dict:
    """天赋节点 ORM → 字典（兼容原格式）"""
    return {
        "id": tal.talent_id,
        "name": tal.name,
        "description": tal.description,
        "branch": tal.branch,
        "layer": tal.tier,
        "max_level": tal.max_level,
        "current_level": tal.current_level,
        "cost": tal.cost or [],
        "icon": tal.icon,
        "position": {"x": tal.position_x, "y": tal.position_y},
        "prerequisites": tal.prerequisites or [],
        "effects": tal.effects or [],
    }


def _season_task_to_dict(task: GrowthSeasonTask) -> dict:
    """赛季任务 ORM → 字典（兼容原格式）"""
    return {
        "id": task.task_id,
        "name": task.name,
        "description": task.description,
        "type": task.type,
        "target": task.target,
        "current": task.current,
        "reward_points": task.points,
        "status": "completed" if task.completed else "incomplete",
        "completed_at": task.completed_at.strftime("%Y-%m-%d %H:%M:%S") if task.completed_at else None,
        "claimed": task.claimed,
    }


def _season_to_dict(season: GrowthSeason, tasks: List[GrowthSeasonTask] = None) -> dict:
    """赛季 ORM → 字典（兼容原格式）"""
    result = {
        "id": season.season_id,
        "name": season.name,
        "theme": season.theme,
        "description": season.description,
        "start_date": season.start_date,
        "end_date": season.end_date,
        "status": season.status,
    }
    if season.rank:
        result["rank"] = season.rank
    if season.reward_preview:
        result["reward_preview"] = season.reward_preview
    if tasks is not None:
        completed = sum(1 for t in tasks if t.completed)
        claimed = sum(1 for t in tasks if t.claimed)
        result["total_tasks"] = len(tasks)
        result["completed_tasks"] = completed
        result["claimed_tasks"] = claimed
        result["progress"] = round(completed / len(tasks) * 100, 1) if tasks else 0
    return result


def _memory_to_dict(mem: GrowthMemory) -> dict:
    """记忆回响 ORM → 字典（兼容原格式）"""
    return {
        "id": mem.memory_id,
        "title": mem.title,
        "content_summary": mem.content_summary or mem.content,
        "original_memory_id": mem.original_memory_id,
        "generated_at": mem.generated_at.strftime("%Y-%m-%d %H:%M:%S") if mem.generated_at else None,
        "emotion_tags": mem.emotion_tags or [],
        "echo_type": mem.echo_type,
        "favorite": mem.favorite,
    }


def _chronicle_to_dict(chr_: GrowthChronicle) -> dict:
    """纪事 ORM → 字典（兼容原格式）"""
    return {
        "id": chr_.chronicle_id,
        "title": chr_.title,
        "content": chr_.content,
        "category": chr_.category,
        "tags": chr_.tags or [],
        "mood": chr_.mood,
        "created_at": chr_.created_at.strftime("%Y-%m-%d %H:%M:%S") if chr_.created_at else None,
        "updated_at": chr_.updated_at.strftime("%Y-%m-%d %H:%M:%S") if chr_.updated_at else None,
        "important": chr_.important,
    }


def _calendar_to_dict(cal: GrowthCalendar) -> dict:
    """日历打卡 ORM → 字典（兼容原格式）"""
    return {
        "date": cal.date,
        "checked_in": cal.checked_in,
        "mood": cal.mood,
        "note": cal.note,
    }


# ==================== 成就系统 API ====================

@router.get("/achievements")
async def get_achievements(
    category: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取成就列表（含解锁状态）"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    query = db.query(GrowthAchievement).filter_by(user_id=user_id)
    if category:
        query = query.filter_by(category=category)
    
    achievements = query.all()
    filtered = [_achievement_to_dict(a) for a in achievements]
    
    if status == "unlocked":
        filtered = [a for a in filtered if a.get("unlocked")]
    elif status == "locked":
        filtered = [a for a in filtered if not a.get("unlocked")]
    
    # 按稀有度排序
    rarity_order = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4}
    filtered.sort(key=lambda a: rarity_order.get(a.get("rarity", "common"), 0))
    
    return ApiResponse.success(data={
        "total": len(filtered),
        "items": filtered,
    })


@router.post("/achievements/{achievement_id}/unlock")
async def unlock_achievement(
    achievement_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解锁成就"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    ach = db.query(GrowthAchievement).filter_by(
        achievement_id=achievement_id, user_id=user_id
    ).first()
    
    if not ach:
        return ApiResponse.error(code=404, message="成就不存在")
    
    if ach.unlocked:
        return ApiResponse.error(code=400, message="成就已解锁")
    
    ach.unlocked = True
    ach.unlocked_at = datetime.now()
    db.commit()
    
    return ApiResponse.success(
        message="成就解锁成功",
        data={"achievement": _achievement_to_dict(ach), "points_earned": ach.points}
    )


@router.get("/achievements/stats")
async def get_achievement_stats(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """成就统计"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    achievements = db.query(GrowthAchievement).filter_by(user_id=user_id).all()
    achievement_dicts = [_achievement_to_dict(a) for a in achievements]
    
    total = len(achievement_dicts)
    unlocked = [a for a in achievement_dicts if a.get("unlocked")]
    unlocked_count = len(unlocked)
    
    # 按分类统计
    by_category = {}
    by_rarity = {}
    
    for ach in achievement_dicts:
        cat = ach.get("category", "unknown")
        rar = ach.get("rarity", "common")
        
        if cat not in by_category:
            by_category[cat] = {"total": 0, "unlocked": 0}
        by_category[cat]["total"] += 1
        if ach.get("unlocked"):
            by_category[cat]["unlocked"] += 1
        
        if rar not in by_rarity:
            by_rarity[rar] = {"total": 0, "unlocked": 0}
        by_rarity[rar]["total"] += 1
        if ach.get("unlocked"):
            by_rarity[rar]["unlocked"] += 1
    
    total_points = sum(a.get("points", 0) for a in achievement_dicts)
    earned_points = sum(a.get("points", 0) for a in unlocked)
    
    completion_rate = round(unlocked_count / total * 100, 1) if total > 0 else 0
    
    # 最近解锁的成就
    recent = sorted(
        unlocked,
        key=lambda a: a.get("unlocked_at", ""),
        reverse=True
    )[:5]
    
    return ApiResponse.success(data={
        "total": total,
        "unlocked": unlocked_count,
        "completion_rate": completion_rate,
        "total_points": total_points,
        "earned_points": earned_points,
        "by_category": by_category,
        "by_rarity": by_rarity,
        "recent_unlocked": recent,
    })


# ==================== 天赋树系统 API ====================

@router.get("/talents")
async def get_talents(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取天赋树数据（节点+连线）"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    talents = db.query(GrowthTalent).filter_by(user_id=user_id).all()
    meta = db.query(GrowthTalentMeta).filter_by(user_id=user_id).first()
    
    nodes = [_talent_to_dict(t) for t in talents]
    
    # 生成连线
    connections = []
    node_map = {n["id"]: n for n in nodes}
    for node in nodes:
        for prereq in node["prerequisites"]:
            connections.append({
                "from": prereq,
                "to": node["id"],
            })
    
    return ApiResponse.success(data={
        "total_points": meta.total_points if meta else 5,
        "used_points": meta.used_points if meta else 0,
        "nodes": nodes,
        "connections": connections,
    })


@router.post("/talents/{talent_id}/upgrade")
async def upgrade_talent(
    talent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """升级天赋节点"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    talents = db.query(GrowthTalent).filter_by(user_id=user_id).all()
    node_map = {t.talent_id: t for t in talents}
    
    if talent_id not in node_map:
        return ApiResponse.error(code=404, message="天赋节点不存在")
    
    node = node_map[talent_id]
    
    if node.current_level >= node.max_level:
        return ApiResponse.error(code=400, message="天赋已达到最高等级")
    
    # 检查前置天赋
    for prereq_id in node.prerequisites or []:
        prereq = node_map.get(prereq_id)
        if not prereq or prereq.current_level == 0:
            return ApiResponse.error(code=400, message=f"需要先解锁前置天赋：{prereq.name if prereq else prereq_id}")
    
    # 检查天赋点
    current_level = node.current_level
    cost_list = node.cost or []
    cost = cost_list[current_level] if current_level < len(cost_list) else cost_list[-1]
    
    meta = db.query(GrowthTalentMeta).filter_by(user_id=user_id).first()
    if not meta:
        meta = GrowthTalentMeta(total_points=5, used_points=0, user_id=user_id)
        db.add(meta)
        db.commit()
        db.refresh(meta)
    
    available = meta.total_points - meta.used_points
    if available < cost:
        return ApiResponse.error(code=400, message=f"天赋点不足，需要{cost}点，当前可用{available}点")
    
    # 升级
    node.current_level += 1
    node.unlocked = True
    meta.used_points += cost
    db.commit()
    db.refresh(node)
    db.refresh(meta)
    
    return ApiResponse.success(
        message="天赋升级成功",
        data={
            "node": _talent_to_dict(node),
            "cost": cost,
            "remaining_points": meta.total_points - meta.used_points,
        }
    )


@router.post("/talents/reset")
async def reset_talents(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重置天赋树（返还所有天赋点）"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    talents = db.query(GrowthTalent).filter_by(user_id=user_id).all()
    for node in talents:
        node.current_level = 0
        node.unlocked = False
    
    meta = db.query(GrowthTalentMeta).filter_by(user_id=user_id).first()
    if meta:
        meta.used_points = 0
    
    db.commit()
    
    return ApiResponse.success(
        message="天赋树已重置，所有天赋点已返还",
        data={
            "total_points": meta.total_points if meta else 5,
            "available_points": meta.total_points if meta else 5,
        }
    )


@router.get("/talents/points")
async def get_talent_points(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取可用天赋点"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    meta = db.query(GrowthTalentMeta).filter_by(user_id=user_id).first()
    total = meta.total_points if meta else 5
    used = meta.used_points if meta else 0
    available = total - used
    
    return ApiResponse.success(data={
        "total_points": total,
        "used_points": used,
        "available_points": available,
    })


# ==================== 赛季旅程 API ====================

@router.get("/season/current")
async def get_current_season(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前赛季信息"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    season = db.query(GrowthSeason).filter_by(user_id=user_id, current=True).first()
    if not season:
        return ApiResponse.error(code=404, message="无当前赛季")
    
    tasks = db.query(GrowthSeasonTask).filter_by(
        season_id=season.season_id, user_id=user_id
    ).all()
    
    current_dict = _season_to_dict(season, tasks)
    return ApiResponse.success(data=current_dict)


@router.get("/season/tasks")
async def get_season_tasks(
    type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取赛季任务列表"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    season = db.query(GrowthSeason).filter_by(user_id=user_id, current=True).first()
    if not season:
        return ApiResponse.success(data={"total": 0, "items": []})
    
    query = db.query(GrowthSeasonTask).filter_by(
        season_id=season.season_id, user_id=user_id
    )
    if type:
        query = query.filter_by(type=type)
    
    tasks = query.all()
    items = [_season_task_to_dict(t) for t in tasks]
    
    return ApiResponse.success(data={
        "total": len(items),
        "items": items,
    })


@router.post("/season/tasks/{task_id}/complete")
async def complete_season_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """完成任务"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    season = db.query(GrowthSeason).filter_by(user_id=user_id, current=True).first()
    if not season:
        return ApiResponse.error(code=404, message="无当前赛季")
    
    task = db.query(GrowthSeasonTask).filter_by(
        task_id=task_id, season_id=season.season_id, user_id=user_id
    ).first()
    
    if not task:
        return ApiResponse.error(code=404, message="任务不存在")
    
    if task.completed:
        return ApiResponse.error(code=400, message="任务已完成")
    
    task.current = task.target
    task.completed = True
    task.completed_at = datetime.now()
    db.commit()
    db.refresh(task)
    
    return ApiResponse.success(
        message="任务完成",
        data={"task": _season_task_to_dict(task), "reward_points": task.points}
    )


@router.post("/season/tasks/{task_id}/claim")
async def claim_season_reward(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """领取奖励"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    season = db.query(GrowthSeason).filter_by(user_id=user_id, current=True).first()
    if not season:
        return ApiResponse.error(code=404, message="无当前赛季")
    
    task = db.query(GrowthSeasonTask).filter_by(
        task_id=task_id, season_id=season.season_id, user_id=user_id
    ).first()
    
    if not task:
        return ApiResponse.error(code=404, message="任务不存在")
    
    if not task.completed:
        return ApiResponse.error(code=400, message="任务尚未完成，无法领取奖励")
    if task.claimed:
        return ApiResponse.error(code=400, message="奖励已领取")
    
    task.claimed = True
    
    # 同时给天赋点增加奖励
    reward = task.points
    # 每50奖励点转化为1天赋点
    talent_bonus = reward // 50
    if talent_bonus > 0:
        meta = db.query(GrowthTalentMeta).filter_by(user_id=user_id).first()
        if meta:
            meta.total_points += talent_bonus
        else:
            meta = GrowthTalentMeta(total_points=5 + talent_bonus, used_points=0, user_id=user_id)
            db.add(meta)
    
    db.commit()
    db.refresh(task)
    
    return ApiResponse.success(
        message="奖励领取成功",
        data={
            "task": _season_task_to_dict(task),
            "reward_points": reward,
            "talent_points_bonus": talent_bonus,
        }
    )


@router.get("/season/history")
async def get_season_history(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """历史赛季列表"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    history_seasons = db.query(GrowthSeason).filter_by(
        user_id=user_id, current=False
    ).order_by(GrowthSeason.start_date.desc()).all()
    
    items = []
    for s in history_seasons:
        season_dict = _season_to_dict(s)
        # 历史赛季需要补充 completed_tasks/total_tasks
        tasks = db.query(GrowthSeasonTask).filter_by(
            season_id=s.season_id, user_id=user_id
        ).all()
        if tasks:
            completed = sum(1 for t in tasks if t.completed)
            season_dict["completed_tasks"] = completed
            season_dict["total_tasks"] = len(tasks)
        else:
            # 从 rank 推断或默认值
            season_dict.setdefault("completed_tasks", 0)
            season_dict.setdefault("total_tasks", 8)
        items.append(season_dict)
    
    return ApiResponse.success(data={
        "total": len(items),
        "items": items,
    })


# ==================== 记忆回响 API ====================

@router.get("/memories")
async def get_memories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    echo_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取记忆列表（优先尝试从M5获取，不可用时用本地数据）"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    # 尝试从 M5 获取记忆
    try:
        from shared.module_client import get_module_registry
        registry = get_module_registry()
        m5_client = registry.get_client("m5")
        
        is_healthy = await m5_client.health_check()
        if is_healthy:
            result = await m5_client.post(
                "/api/v1/memory/recall",
                json_data={
                    "query": "",
                    "domain": "private",
                    "agent_id": current_user.get("username", "system"),
                    "top_k": page_size,
                },
                use_auth=True,
            )
            
            m5_memories = result.get("data", {}).get("results", []) if isinstance(result, dict) else []
            
            # 转换格式
            items = []
            for mem in m5_memories:
                items.append({
                    "id": mem.get("memory_id", ""),
                    "title": mem.get("content_hint", "记忆片段")[:50],
                    "content_summary": mem.get("content_hint", ""),
                    "layer": mem.get("layer", ""),
                    "tags": mem.get("tags", []),
                    "created_at": mem.get("created_at", ""),
                    "source": "m5",
                })
            
            return ApiResponse.success(data={
                "total": len(items),
                "page": page,
                "page_size": page_size,
                "items": items,
                "source": "m5",
            })
    except Exception:
        pass
    
    # 回退到本地记忆回响数据（从数据库）
    query = db.query(GrowthMemory).filter_by(user_id=user_id)
    if echo_type:
        query = query.filter_by(echo_type=echo_type)
    
    total = query.count()
    memories = query.order_by(GrowthMemory.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    
    items = [_memory_to_dict(m) for m in memories]
    
    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
        "source": "local",
    })


@router.post("/memories/generate")
async def generate_memory_echo(
    req: MemoryGenerateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 生成回响"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    # 模拟 AI 生成回响
    echo_templates = {
        "reflection": [
            {"title": "时光倒影", "content": "回望这段记忆，仿佛看到了当时的自己。那些情绪和想法，都是成长路上珍贵的印记。"},
            {"title": "心灵回响", "content": "这段记忆在心中回荡，带来新的感悟。每一次回顾，都有新的收获。"},
        ],
        "insight": [
            {"title": "顿悟时刻", "content": "从这段经历中，我看到了更深层的意义。原来当时的困惑，是成长的必经之路。"},
            {"title": "智慧之光", "content": "回顾过去，我发现了之前未曾注意到的模式。这份洞察将指引未来的方向。"},
        ],
        "poem": [
            {"title": "记忆诗篇", "content": "潮汐退去沙滩浅，往事如烟入梦来。拾得贝壳三两枚，藏在心底慢慢开。"},
        ],
        "story": [
            {"title": "成长的故事", "content": "这是一个关于勇气与成长的故事。主角在迷茫中寻找方向，最终找到了属于自己的道路。"},
        ],
    }
    
    templates = echo_templates.get(req.echo_type, echo_templates["reflection"])
    template = random.choice(templates)
    
    now = datetime.now()
    new_echo = GrowthMemory(
        memory_id=f"echo_{uuid.uuid4().hex[:12]}",
        title=template["title"],
        content=template["content"],
        content_summary=template["content"],
        emotion_tags=["感悟", "成长"],
        echo_type=req.echo_type,
        original_memory_id=req.memory_id,
        favorite=False,
        generated_at=now,
        created_at=now,
        user_id=user_id,
    )
    db.add(new_echo)
    db.commit()
    db.refresh(new_echo)
    
    return ApiResponse.success(
        message="回响生成成功",
        data=_memory_to_dict(new_echo),
    )


@router.get("/memories/{memory_id}")
async def get_memory_detail(
    memory_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取记忆详情"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    # 先查本地回响
    mem = db.query(GrowthMemory).filter_by(
        memory_id=memory_id, user_id=user_id
    ).first()
    if mem:
        result = _memory_to_dict(mem)
        result["source"] = "local_echo"
        return ApiResponse.success(data=result)
    
    # 尝试从 M5 获取
    try:
        from shared.module_client import get_module_registry
        registry = get_module_registry()
        m5_client = registry.get_client("m5")
        
        is_healthy = await m5_client.health_check()
        if is_healthy:
            result = await m5_client.get(
                f"/api/v1/memory/{memory_id}",
                use_auth=True,
            )
            return ApiResponse.success(data={**result.get("data", result), "source": "m5"})
    except Exception:
        pass
    
    return ApiResponse.error(code=404, message="记忆不存在")


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除记忆"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    # 从本地回响删除
    mem = db.query(GrowthMemory).filter_by(
        memory_id=memory_id, user_id=user_id
    ).first()
    if mem:
        db.delete(mem)
        db.commit()
        return ApiResponse.success(message="记忆删除成功")
    
    # 尝试从 M5 删除
    try:
        from shared.module_client import get_module_registry
        registry = get_module_registry()
        m5_client = registry.get_client("m5")
        
        is_healthy = await m5_client.health_check()
        if is_healthy:
            result = await m5_client.delete(
                f"/api/v1/memory/{memory_id}",
                use_auth=True,
            )
            return ApiResponse.success(message="记忆删除成功", data={"source": "m5"})
    except Exception:
        pass
    
    return ApiResponse.error(code=404, message="记忆不存在")


# ==================== 成长纪事 API ====================

@router.get("/chronicle")
async def get_chronicle(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取纪事列表（分页）"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    query = db.query(GrowthChronicle).filter_by(user_id=user_id)
    if category:
        query = query.filter_by(category=category)
    
    total = query.count()
    entries = query.order_by(GrowthChronicle.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    
    items = [_chronicle_to_dict(e) for e in entries]
    
    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


@router.post("/chronicle")
async def create_chronicle(
    req: ChronicleCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增纪事"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    now = datetime.now()
    new_entry = GrowthChronicle(
        chronicle_id=f"chr_{uuid.uuid4().hex[:12]}",
        title=req.title,
        content=req.content,
        category=req.category,
        tags=req.tags,
        mood=req.mood,
        important=req.important,
        created_at=now,
        updated_at=now,
        user_id=user_id,
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    
    return ApiResponse.success(
        message="纪事创建成功",
        data=_chronicle_to_dict(new_entry),
    )


@router.get("/chronicle/{entry_id}")
async def get_chronicle_detail(
    entry_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取纪事详情"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    entry = db.query(GrowthChronicle).filter_by(
        chronicle_id=entry_id, user_id=user_id
    ).first()
    
    if not entry:
        return ApiResponse.error(code=404, message="纪事不存在")
    
    return ApiResponse.success(data=_chronicle_to_dict(entry))


@router.put("/chronicle/{entry_id}")
async def update_chronicle(
    entry_id: str,
    req: ChronicleUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新纪事"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    entry = db.query(GrowthChronicle).filter_by(
        chronicle_id=entry_id, user_id=user_id
    ).first()
    
    if not entry:
        return ApiResponse.error(code=404, message="纪事不存在")
    
    if req.title is not None:
        entry.title = req.title
    if req.content is not None:
        entry.content = req.content
    if req.category is not None:
        entry.category = req.category
    if req.tags is not None:
        entry.tags = req.tags
    if req.mood is not None:
        entry.mood = req.mood
    if req.important is not None:
        entry.important = req.important
    
    entry.updated_at = datetime.now()
    db.commit()
    db.refresh(entry)
    
    return ApiResponse.success(
        message="纪事更新成功",
        data=_chronicle_to_dict(entry),
    )


@router.delete("/chronicle/{entry_id}")
async def delete_chronicle(
    entry_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除纪事"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    entry = db.query(GrowthChronicle).filter_by(
        chronicle_id=entry_id, user_id=user_id
    ).first()
    
    if not entry:
        return ApiResponse.error(code=404, message="纪事不存在")
    
    db.delete(entry)
    db.commit()
    
    return ApiResponse.success(message="纪事删除成功")


# ==================== 潮汐日历 API ====================

@router.get("/calendar/{year}/{month}")
async def get_calendar_month(
    year: int,
    month: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取月历数据"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    # 查询本月所有打卡记录
    month_prefix = f"{year}-{month:02d}"
    checkins = db.query(GrowthCalendar).filter(
        GrowthCalendar.user_id == user_id,
        GrowthCalendar.date.like(f"{month_prefix}%"),
        GrowthCalendar.checked_in == True,
    ).all()
    
    checkin_days = [_calendar_to_dict(c) for c in checkins]
    
    # 构建月历数据
    import calendar
    cal = calendar.monthcalendar(year, month)
    
    weeks = []
    for week in cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append(None)
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                checkin_info = next((d for d in checkin_days if d["date"] == date_str), None)
                week_data.append({
                    "date": date_str,
                    "day": day,
                    "checked_in": checkin_info is not None,
                    "mood": checkin_info.get("mood") if checkin_info else None,
                    "note": checkin_info.get("note") if checkin_info else None,
                })
        weeks.append(week_data)
    
    # 本月统计
    month_checkins = [d for d in checkin_days if d["date"].startswith(f"{year}-{month:02d}")]
    
    # 心情分布
    mood_counts = {}
    for d in month_checkins:
        mood = d.get("mood", "unknown")
        if mood:
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
    
    # 当前连续打卡天数
    streak_record = db.query(GrowthCalendar).filter_by(
        user_id=user_id, date=date.today().strftime("%Y-%m-%d")
    ).first()
    current_streak = streak_record.streak if streak_record else 0
    # 如果今天还没打卡，计算到昨天的连续天数
    if not streak_record or not streak_record.checked_in:
        streak = 0
        d = date.today() - timedelta(days=1)
        while True:
            rec = db.query(GrowthCalendar).filter_by(
                user_id=user_id, date=d.strftime("%Y-%m-%d"), checked_in=True
            ).first()
            if rec:
                streak += 1
                d -= timedelta(days=1)
            else:
                break
        current_streak = streak
    
    return ApiResponse.success(data={
        "year": year,
        "month": month,
        "weeks": weeks,
        "monthly_checkins": len(month_checkins),
        "mood_distribution": mood_counts,
        "current_streak": current_streak,
    })


@router.post("/calendar/checkin")
async def calendar_checkin(
    req: CheckinRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """打卡"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    today = date.today().strftime("%Y-%m-%d")
    
    # 检查今日是否已打卡
    existing = db.query(GrowthCalendar).filter_by(
        date=today, user_id=user_id
    ).first()
    if existing and existing.checked_in:
        return ApiResponse.error(code=400, message="今日已打卡")
    
    # 计算连续打卡天数
    streak = 0
    d = date.today() - timedelta(days=1)
    while True:
        rec = db.query(GrowthCalendar).filter_by(
            user_id=user_id, date=d.strftime("%Y-%m-%d"), checked_in=True
        ).first()
        if rec:
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    streak += 1  # 加上今天
    
    # 新增或更新打卡记录
    if existing:
        existing.checked_in = True
        existing.mood = req.mood
        existing.note = req.note
        existing.streak = streak
    else:
        new_checkin = GrowthCalendar(
            date=today,
            checked_in=True,
            mood=req.mood,
            note=req.note,
            streak=streak,
            user_id=user_id,
        )
        db.add(new_checkin)
    
    db.commit()
    
    # 检查是否解锁连续打卡成就
    newly_unlocked = []
    achievements = db.query(GrowthAchievement).filter_by(user_id=user_id).all()
    for ach in achievements:
        if not ach.unlocked:
            if ach.achievement_id == "ach_014" and streak >= 7:
                ach.unlocked = True
                ach.unlocked_at = datetime.now()
                newly_unlocked.append(ach.name)
            if ach.achievement_id == "ach_015" and streak >= 30:
                ach.unlocked = True
                ach.unlocked_at = datetime.now()
                newly_unlocked.append(ach.name)
    if newly_unlocked:
        db.commit()
    
    # 获取总打卡数
    total_checkins = db.query(GrowthCalendar).filter_by(
        user_id=user_id, checked_in=True
    ).count()
    
    return ApiResponse.success(
        message="打卡成功",
        data={
            "checkin": {
                "date": today,
                "checked_in": True,
                "mood": req.mood,
                "note": req.note,
            },
            "streak": streak,
            "total_checkins": total_checkins,
            "newly_unlocked_achievements": newly_unlocked,
        }
    )


@router.get("/calendar/stats")
async def get_calendar_stats(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """日历统计"""
    user_id = _get_user_id(current_user)
    _ensure_data_initialized(db, user_id)
    
    all_checkins = db.query(GrowthCalendar).filter_by(
        user_id=user_id, checked_in=True
    ).all()
    
    # 心情分布
    mood_counts = {}
    for d in all_checkins:
        mood = d.mood
        if mood:
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
    
    # 本月打卡
    today = date.today()
    month_prefix = today.strftime("%Y-%m")
    month_checkins = [d for d in all_checkins if d.date.startswith(month_prefix)]
    
    # 最长连续打卡
    checkin_set = {d.date for d in all_checkins}
    max_streak = 0
    current_streak_calc = 0
    
    sorted_dates = sorted(checkin_set)
    if sorted_dates:
        current_streak_calc = 1
        max_streak = 1
        for i in range(1, len(sorted_dates)):
            d1 = datetime.strptime(sorted_dates[i-1], "%Y-%m-%d").date()
            d2 = datetime.strptime(sorted_dates[i], "%Y-%m-%d").date()
            if (d2 - d1).days == 1:
                current_streak_calc += 1
                max_streak = max(max_streak, current_streak_calc)
            else:
                current_streak_calc = 1
    
    # 当前连续打卡
    today_str = today.strftime("%Y-%m-%d")
    current_streak = 0
    d = today
    while True:
        d_str = d.strftime("%Y-%m-%d")
        rec = db.query(GrowthCalendar).filter_by(
            user_id=user_id, date=d_str, checked_in=True
        ).first()
        if rec:
            current_streak += 1
            d -= timedelta(days=1)
        else:
            break
    
    # 周统计
    week_checkins = 0
    for i in range(7):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in checkin_set:
            week_checkins += 1
    
    return ApiResponse.success(data={
        "total_checkins": len(all_checkins),
        "current_streak": current_streak,
        "max_streak": max_streak,
        "monthly_checkins": len(month_checkins),
        "weekly_checkins": week_checkins,
        "mood_distribution": mood_counts,
    })
