"""
情景感知与主动提醒引擎

功能：
1. 情景感知 - 时间/位置/设备状态/用户行为综合分析
2. 主动提醒 - 基于规则和学习的智能提醒
3. 预判服务 - 根据用户习惯提前准备服务
4. 提醒管理 - 增删改查 +  snooze + 完成标记
"""

import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta


class ReminderType(str, Enum):
    """提醒类型"""
    ONCE = "once"  # 一次性提醒
    DAILY = "daily"  # 每日重复
    WEEKLY = "weekly"  # 每周重复
    MONTHLY = "monthly"  # 每月重复
    CONDITIONAL = "conditional"  # 条件触发


class ReminderPriority(str, Enum):
    """提醒优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReminderStatus(str, Enum):
    """提醒状态"""
    PENDING = "pending"  # 等待触发
    TRIGGERED = "triggered"  # 已触发
    SNOOZED = "snoozed"  # 已延后
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"  # 已取消


class ContextType(str, Enum):
    """情景类型"""
    TIME = "time"  # 时间情景
    LOCATION = "location"  # 位置情景
    DEVICE = "device"  # 设备情景
    ACTIVITY = "activity"  # 活动情景
    WEATHER = "weather"  # 天气情景


@dataclass
class Reminder:
    """提醒项"""
    id: str
    title: str
    description: str = ""
    type: str = ReminderType.ONCE.value
    priority: str = ReminderPriority.NORMAL.value
    status: str = ReminderStatus.PENDING.value
    
    # 时间相关
    trigger_time: Optional[float] = None  # 触发时间戳（一次性提醒用）
    repeat_days: List[int] = field(default_factory=list)  # 每周重复的日期 0-6 (周一到周日)
    repeat_time: Optional[str] = None  # 重复时间 "HH:MM" 格式
    
    # 条件触发相关
    condition_type: Optional[str] = None  # 条件类型
    condition_config: Dict[str, Any] = field(default_factory=dict)
    
    # 提醒方式
    notify_methods: List[str] = field(default_factory=lambda: ["voice", "notification"])
    
    # 元数据
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    triggered_at: Optional[float] = None
    completed_at: Optional[float] = None
    snooze_until: Optional[float] = None
    
    # 关联数据
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def should_trigger(self, now: Optional[float] = None) -> bool:
        """检查是否应该触发"""
        now = now or time.time()
        
        # 已完成或已取消的不触发
        if self.status in (ReminderStatus.COMPLETED.value, ReminderStatus.CANCELLED.value):
            return False
        
        # 延后中的不触发
        if self.snooze_until and now < self.snooze_until:
            return False
        
        if self.type == ReminderType.ONCE.value:
            return self.trigger_time and now >= self.trigger_time
        
        elif self.type in (ReminderType.DAILY.value, ReminderType.WEEKLY.value, ReminderType.MONTHLY.value):
            return self._check_repeat_trigger(now)
        
        elif self.type == ReminderType.CONDITIONAL.value:
            # 条件触发由外部条件检查决定
            return False
        
        return False
    
    def _check_repeat_trigger(self, now: float) -> bool:
        """检查重复提醒是否应该触发"""
        if not self.repeat_time:
            return False
        
        dt = datetime.fromtimestamp(now)
        hour, minute = map(int, self.repeat_time.split(":"))
        
        # 今天的触发时间
        today_trigger = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        trigger_ts = today_trigger.timestamp()
        
        # 检查是否已经触发过（今日）
        if self.triggered_at:
            last_trigger = datetime.fromtimestamp(self.triggered_at)
            if last_trigger.date() == dt.date():
                return False  # 今天已经触发过了
        
        # 检查是否到了触发时间
        if now < trigger_ts:
            return False
        
        # 检查重复规则
        if self.type == ReminderType.DAILY.value:
            return True
        
        elif self.type == ReminderType.WEEKLY.value:
            weekday = dt.weekday()  # 0=周一, 6=周日
            return weekday in self.repeat_days
        
        elif self.type == ReminderType.MONTHLY.value:
            # 简化：每月同一天触发（配置在metadata.day中）
            day = self.metadata.get("day", dt.day)
            return dt.day == day
        
        return False
    
    def get_next_trigger_time(self, now: Optional[float] = None) -> Optional[float]:
        """获取下次触发时间"""
        now = now or time.time()
        
        if self.status in (ReminderStatus.COMPLETED.value, ReminderStatus.CANCELLED.value):
            return None
        
        if self.type == ReminderType.ONCE.value:
            if self.trigger_time and self.trigger_time > now:
                return self.trigger_time
            return None
        
        elif self.type in (ReminderType.DAILY.value, ReminderType.WEEKLY.value, ReminderType.MONTHLY.value):
            return self._get_next_repeat_time(now)
        
        return None
    
    def _get_next_repeat_time(self, now: float) -> Optional[float]:
        """获取下次重复触发时间"""
        if not self.repeat_time:
            return None
        
        dt = datetime.fromtimestamp(now)
        hour, minute = map(int, self.repeat_time.split(":"))
        
        for day_offset in range(7):  # 最多查找7天
            check_date = dt.date() + timedelta(days=day_offset)
            check_dt = datetime.combine(check_date, datetime.min.time())
            check_dt = check_dt.replace(hour=hour, minute=minute, second=0)
            check_ts = check_dt.timestamp()
            
            if check_ts <= now:
                continue
            
            if self.type == ReminderType.DAILY.value:
                return check_ts
            
            elif self.type == ReminderType.WEEKLY.value:
                weekday = check_dt.weekday()
                if weekday in self.repeat_days:
                    return check_ts
            
            elif self.type == ReminderType.MONTHLY.value:
                day = self.metadata.get("day", dt.day)
                if check_dt.day == day:
                    return check_ts
        
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ContextSnapshot:
    """情景快照"""
    timestamp: float = field(default_factory=time.time)
    
    # 时间情景
    hour: int = 0
    weekday: int = 0  # 0-6 周一到周日
    is_weekend: bool = False
    time_of_day: str = "day"  # morning/afternoon/evening/night
    
    # 设备情景
    device_active: bool = True
    battery_level: float = 100.0
    is_charging: bool = False
    
    # 用户状态
    user_active: bool = True
    last_activity: float = 0
    
    # 位置
    location: Optional[str] = None
    
    def update(self):
        """更新情景快照"""
        self.timestamp = time.time()
        dt = datetime.now()
        self.hour = dt.hour
        self.weekday = dt.weekday()
        self.is_weekend = self.weekday >= 5
        
        if 5 <= self.hour < 12:
            self.time_of_day = "morning"
        elif 12 <= self.hour < 18:
            self.time_of_day = "afternoon"
        elif 18 <= self.hour < 22:
            self.time_of_day = "evening"
        else:
            self.time_of_day = "night"


class ContextAwareEngine:
    """情景感知引擎 - 单例模式"""
    
    _instance: Optional["ContextAwareEngine"] = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, data_dir: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True
        
        # 数据目录
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path.home() / ".yunxi" / "context"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 提醒存储
        self._reminders: Dict[str, Reminder] = {}
        self._reminder_file = self._data_dir / "reminders.json"
        
        # 情景快照
        self._context = ContextSnapshot()
        
        # 回调函数
        self._reminder_callbacks: List[Callable[[Reminder], None]] = []
        
        # 线程锁
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._check_thread: Optional[threading.Thread] = None
        
        # 检查间隔（秒）
        self._check_interval = 30  # 每30秒检查一次提醒
        
        # 加载提醒
        self._load_reminders()
        
        # 启动后台检查线程
        self._start_check_loop()
    
    def _load_reminders(self):
        """从文件加载提醒"""
        try:
            if self._reminder_file.exists():
                with open(self._reminder_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    reminder = Reminder(**item)
                    self._reminders[reminder.id] = reminder
        except Exception as e:
            print(f"加载提醒失败: {e}")
    
    def _save_reminders(self):
        """保存提醒到文件"""
        try:
            data = [r.to_dict() for r in self._reminders.values()]
            with open(self._reminder_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存提醒失败: {e}")
    
    def _start_check_loop(self):
        """启动提醒检查循环"""
        self._stop_event.clear()
        self._check_thread = threading.Thread(
            target=self._check_loop,
            name="ContextAwareEngine",
            daemon=True
        )
        self._check_thread.start()
    
    def _check_loop(self):
        """提醒检查主循环"""
        while not self._stop_event.is_set():
            try:
                # 更新情景
                self._context.update()
                
                # 检查提醒
                self._check_reminders()
                
            except Exception as e:
                print(f"提醒检查异常: {e}")
            
            # 等待下一次检查
            self._stop_event.wait(self._check_interval)
    
    def _check_reminders(self):
        """检查所有提醒"""
        now = time.time()
        triggered = []
        
        with self._lock:
            for reminder in self._reminders.values():
                if reminder.should_trigger(now):
                    # 标记为已触发
                    reminder.status = ReminderStatus.TRIGGERED.value
                    reminder.triggered_at = now
                    reminder.updated_at = now
                    triggered.append(reminder)
            
            if triggered:
                self._save_reminders()
        
        # 触发回调（在锁外执行，避免死锁）
        for reminder in triggered:
            self._trigger_reminder(reminder)
    
    def _trigger_reminder(self, reminder: Reminder):
        """触发提醒回调"""
        for callback in self._reminder_callbacks:
            try:
                callback(reminder)
            except Exception as e:
                print(f"提醒回调异常: {e}")
    
    def add_reminder(self, title: str, description: str = "",
                     reminder_type: str = ReminderType.ONCE.value,
                     priority: str = ReminderPriority.NORMAL.value,
                     trigger_time: Optional[float] = None,
                     repeat_time: Optional[str] = None,
                     repeat_days: Optional[List[int]] = None,
                     notify_methods: Optional[List[str]] = None,
                     tags: Optional[List[str]] = None,
                     metadata: Optional[Dict] = None) -> Reminder:
        """添加提醒"""
        import uuid
        
        reminder_id = f"rem_{uuid.uuid4().hex[:12]}"
        
        reminder = Reminder(
            id=reminder_id,
            title=title,
            description=description,
            type=reminder_type,
            priority=priority,
            trigger_time=trigger_time,
            repeat_time=repeat_time,
            repeat_days=repeat_days or [],
            notify_methods=notify_methods or ["voice", "notification"],
            tags=tags or [],
            metadata=metadata or {},
        )
        
        with self._lock:
            self._reminders[reminder_id] = reminder
            self._save_reminders()
        
        return reminder
    
    def get_reminder(self, reminder_id: str) -> Optional[Reminder]:
        """获取单个提醒"""
        with self._lock:
            return self._reminders.get(reminder_id)
    
    def list_reminders(self, status: Optional[str] = None,
                       reminder_type: Optional[str] = None,
                       limit: int = 50, offset: int = 0) -> List[Reminder]:
        """列出提醒（可按状态/类型筛选）"""
        with self._lock:
            reminders = list(self._reminders.values())
            
            if status:
                reminders = [r for r in reminders if r.status == status]
            
            if reminder_type:
                reminders = [r for r in reminders if r.type == reminder_type]
            
            # 按触发时间排序
            reminders.sort(key=lambda r: r.trigger_time or r.created_at, reverse=True)
            
            return reminders[offset:offset + limit]
    
    def update_reminder(self, reminder_id: str, **kwargs) -> Optional[Reminder]:
        """更新提醒"""
        with self._lock:
            reminder = self._reminders.get(reminder_id)
            if not reminder:
                return None
            
            for key, value in kwargs.items():
                if hasattr(reminder, key):
                    setattr(reminder, key, value)
            
            reminder.updated_at = time.time()
            self._save_reminders()
            return reminder
    
    def complete_reminder(self, reminder_id: str) -> bool:
        """标记提醒为已完成"""
        return self.update_reminder(
            reminder_id,
            status=ReminderStatus.COMPLETED.value,
            completed_at=time.time()
        ) is not None
    
    def snooze_reminder(self, reminder_id: str, minutes: int = 10) -> bool:
        """延后提醒"""
        snooze_until = time.time() + minutes * 60
        return self.update_reminder(
            reminder_id,
            status=ReminderStatus.SNOOZED.value,
            snooze_until=snooze_until
        ) is not None
    
    def cancel_reminder(self, reminder_id: str) -> bool:
        """取消提醒"""
        return self.update_reminder(
            reminder_id,
            status=ReminderStatus.CANCELLED.value
        ) is not None
    
    def delete_reminder(self, reminder_id: str) -> bool:
        """删除提醒"""
        with self._lock:
            if reminder_id not in self._reminders:
                del self._reminders[reminder_id]
                self._save_reminders()
                return True
            return False
    
    def get_context(self) -> ContextSnapshot:
        """获取当前情景"""
        self._context.update()
        return self._context
    
    def get_upcoming_reminders(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取即将到来的提醒"""
        now = time.time()
        upcoming = []
        
        with self._lock:
            for reminder in self._reminders.values():
                if reminder.status in (ReminderStatus.COMPLETED.value, ReminderStatus.CANCELLED.value):
                    continue
                
                next_time = reminder.get_next_trigger_time(now)
                if next_time:
                    upcoming.append({
                    "id": reminder.id,
                    "title": reminder.title,
                    "description": reminder.description,
                    "type": reminder.type,
                    "priority": reminder.priority,
                    "next_trigger_time": next_time,
                    "status": reminder.status,
                })
        
        # 按下次触发时间排序
        upcoming.sort(key=lambda x: x["next_trigger_time"])
        return upcoming[:limit]
    
    def get_daily_summary(self) -> Dict[str, Any]:
        """获取今日提醒摘要"""
        today = datetime.now().date()
        start_of_day = datetime.combine(today, datetime.min.time()).timestamp()
        end_of_day = start_of_day + 86400
        
        stats = {
            "total": 0,
            "completed": 0,
            "pending": 0,
            "missed": 0,
            "upcoming": [],
        }
        
        with self._lock:
            for reminder in self._reminders.values():
                trigger_time = reminder.trigger_time or 0
                
                # 是否是今日的提醒
                is_today = start_of_day <= trigger_time < end_of_day
                
                # 重复提醒也算今日
                if not is_today and reminder.type in (
                    ReminderType.DAILY.value,
                    ReminderType.WEEKLY.value,
                    ReminderType.MONTHLY.value,
                ):
                    next_time = reminder.get_next_trigger_time()
                    if next_time and start_of_day <= next_time < end_of_day:
                        is_today = True
                
                if not is_today:
                    continue
                
                stats["total"] += 1
                
                if reminder.status == ReminderStatus.COMPLETED.value:
                    stats["completed"] += 1
                elif reminder.status == ReminderStatus.PENDING.value:
                    stats["pending"] += 1
                elif reminder.status == ReminderStatus.TRIGGERED.value:
                    stats["pending"] += 1  # 已触发但未完成
                
                # 即将到来的
                if reminder.status in (ReminderStatus.PENDING.value, ReminderStatus.SNOOZED.value):
                    next_time = reminder.get_next_trigger_time()
                    if next_time:
                        stats["upcoming"].append({
                            "id": reminder.id,
                            "title": reminder.title,
                            "time": next_time,
                            "priority": reminder.priority,
                        })
        
        # 按时间排序
        stats["upcoming"].sort(key=lambda x: x["time"])
        stats["missed"] = max(0, stats["total"] - stats["completed"] - stats["pending"])
        
        return stats
    
    def register_reminder_callback(self, callback: Callable[[Reminder], None]):
        """注册提醒触发回调"""
        self._reminder_callbacks.append(callback)
    
    def unregister_reminder_callback(self, callback: Callable[[Reminder], None]):
        """注销提醒回调"""
        if callback in self._reminder_callbacks:
            self._reminder_callbacks.remove(callback)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取提醒统计"""
        with self._lock:
            stats = {
                "total": len(self._reminders),
                "by_status": {},
                "by_type": {},
                "by_priority": {},
            }
            
            for reminder in self._reminders.values():
                # 按状态统计
                status = reminder.status
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                
                # 按类型统计
                rtype = reminder.type
                stats["by_type"][rtype] = stats["by_type"].get(rtype, 0) + 1
                
                # 按优先级统计
                priority = reminder.priority
                stats["by_priority"][priority] = stats["by_priority"].get(priority, 0) + 1
            
            return stats
    
    def stop(self):
        """停止引擎"""
        self._stop_event.set()
        if self._check_thread:
            self._check_thread.join(timeout=5)


# 全局单例
_context_engine: Optional[ContextAwareEngine] = None


def get_context_aware_engine() -> ContextAwareEngine:
    """获取情景感知引擎单例"""
    global _context_engine
    if _context_engine is None:
        _context_engine = ContextAwareEngine()
    return _context_engine
