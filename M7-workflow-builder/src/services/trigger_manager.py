"""M7 积木平台 - 触发器管理器.

P2 级优化：完整的触发器系统，支持三种触发方式：
1. Schedule 触发器 - 定时调度（Cron / Interval / One-time）
2. Webhook 触发器 - HTTP 回调触发
3. Event 触发器 - 内部事件总线驱动

核心组件：
- TriggerRepository: 触发器 CRUD
- TriggerScheduler: 定时调度器
- WebhookManager: Webhook 端点管理与签名验证
- EventBus: 简单的内部事件总线
- TriggerManager: 统一管理器
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy import and_, desc, or_

from ..db import get_session
from ..models_db import TriggerDefinition, TriggerHistory

logger = logging.getLogger("m7.triggers")


# ============================================================
# 常量定义
# ============================================================

class TriggerType:
    """触发器类型."""
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    EVENT = "event"
    MANUAL = "manual"

    ALL = {SCHEDULE, WEBHOOK, EVENT, MANUAL}


class TriggerStatus:
    """触发状态."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================
# Cron 表达式解析器（简化版）
# ============================================================

class SimpleCronParser:
    """简化版 Cron 表达式解析器.

    支持 5 字段标准 Cron：分 时 日 月 周
    支持: * */n a-b a,b,c 等基本语法

    注意：这是一个简化实现，用于内部调度。生产环境建议使用 APScheduler。
    """

    @staticmethod
    def parse_field(field: str, min_val: int, max_val: int) -> Set[int]:
        """解析单个 cron 字段.

        Args:
            field: 字段字符串
            min_val: 最小值
            max_val: 最大值

        Returns:
            匹配的值集合
        """
        result = set()

        for part in field.split(","):
            part = part.strip()
            if not part:
                continue

            # 步长 */n
            if part.startswith("*/"):
                step = int(part[2:])
                for v in range(min_val, max_val + 1, step):
                    result.add(v)
                continue

            # 范围 a-b
            if "-" in part and not part.startswith("-"):
                start_str, end_str = part.split("-", 1)
                start = int(start_str)
                end = int(end_str)
                for v in range(start, end + 1):
                    if min_val <= v <= max_val:
                        result.add(v)
                continue

            # 通配符
            if part == "*":
                for v in range(min_val, max_val + 1):
                    result.add(v)
                continue

            # 单个值
            val = int(part)
            if min_val <= val <= max_val:
                result.add(val)

        return result

    @staticmethod
    def next_run_time(cron_expr: str, from_time: Optional[datetime] = None) -> Optional[datetime]:
        """计算下一次运行时间.

        Args:
            cron_expr: Cron 表达式（5 字段：分 时 日 月 周）
            from_time: 起始时间，默认当前

        Returns:
            下一次运行时间，无效表达式返回 None
        """
        from_time = from_time or datetime.now()

        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return None

            minute_field, hour_field, day_field, month_field, weekday_field = parts

            minutes = SimpleCronParser.parse_field(minute_field, 0, 59)
            hours = SimpleCronParser.parse_field(hour_field, 0, 23)
            days = SimpleCronParser.parse_field(day_field, 1, 31)
            months = SimpleCronParser.parse_field(month_field, 1, 12)
            weekdays = SimpleCronParser.parse_field(weekday_field, 0, 6)  # 0=周一? 这里用 0=周日

            if not all([minutes, hours, days, months]):
                return None

            # 从下一分钟开始找
            current = from_time + timedelta(minutes=1)
            current = current.replace(second=0, microsecond=0)

            # 最多搜索 366 天
            for _ in range(366 * 24 * 60):
                if current.month in months:
                    if current.day in days:
                        # 简化：周几不参与复杂判断
                        if current.hour in hours and current.minute in minutes:
                            # 检查周几（Python weekday: 0=周一, cron: 0=周日）
                            cron_weekday = (current.weekday() + 1) % 7
                            if not weekdays or cron_weekday in weekdays:
                                return current
                current += timedelta(minutes=1)

            return None
        except (ValueError, IndexError):
            return None

    @staticmethod
    def is_valid(cron_expr: str) -> bool:
        """验证 Cron 表达式是否有效."""
        return SimpleCronParser.next_run_time(cron_expr) is not None


# ============================================================
# 触发器仓库
# ============================================================

class TriggerRepository:
    """触发器数据仓库.

    提供触发器的 CRUD 操作和历史记录管理。
    """

    def __init__(self, session=None):
        self._external_session = session

    def _get_session(self):
        if self._external_session:
            return self._external_session
        return get_session()

    def _close_if_needed(self, session):
        if self._external_session is None:
            session.close()

    def create_trigger(
        self,
        name: str,
        workflow_id: str,
        trigger_type: str,
        description: str = "",
        config: Optional[Dict[str, Any]] = None,
        input_mapping: Optional[Dict[str, Any]] = None,
        filter_config: Optional[Dict[str, Any]] = None,
        enabled: bool = False,
        timezone: str = "Asia/Shanghai",
        created_by: str = "",
    ) -> Dict[str, Any]:
        """创建触发器.

        Args:
            name: 触发器名称
            workflow_id: 关联工作流 ID
            trigger_type: 触发器类型
            description: 描述
            config: 配置
            input_mapping: 输入映射
            filter_config: 过滤配置
            enabled: 是否启用
            timezone: 时区
            created_by: 创建者

        Returns:
            触发器字典
        """
        session = self._get_session()
        try:
            trigger_id = f"trig_{uuid.uuid4().hex[:12]}"
            now = datetime.utcnow()

            webhook_path = ""
            webhook_secret = ""
            if trigger_type == TriggerType.WEBHOOK:
                webhook_path = f"/webhook/{trigger_id}"
                webhook_secret = uuid.uuid4().hex

            trigger = TriggerDefinition(
                id=trigger_id,
                name=name,
                description=description,
                workflow_id=workflow_id,
                trigger_type=trigger_type,
                enabled=1 if enabled else 0,
                config=config or {},
                input_mapping=input_mapping or {},
                filter_config=filter_config or {},
                webhook_secret=webhook_secret,
                webhook_path=webhook_path,
                timezone=timezone,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            session.add(trigger)
            session.commit()
            result = trigger.to_dict()
            logger.info(f"[Triggers] 创建触发器: {trigger_id} ({name}, type={trigger_type})")
            return result
        except Exception as e:
            session.rollback()
            logger.error(f"[Triggers] 创建触发器失败: {e}")
            raise
        finally:
            self._close_if_needed(session)

    def get_trigger(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        """获取触发器详情."""
        session = self._get_session()
        try:
            trigger = session.query(TriggerDefinition).filter(
                TriggerDefinition.id == trigger_id
            ).first()
            return trigger.to_dict() if trigger else None
        finally:
            self._close_if_needed(session)

    def update_trigger(
        self,
        trigger_id: str,
        **kwargs,
    ) -> bool:
        """更新触发器.

        Args:
            trigger_id: 触发器 ID
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        session = self._get_session()
        try:
            trigger = session.query(TriggerDefinition).filter(
                TriggerDefinition.id == trigger_id
            ).first()
            if not trigger:
                return False

            for key, value in kwargs.items():
                if hasattr(trigger, key) and key not in ("id", "created_at"):
                    if key == "enabled":
                        setattr(trigger, key, 1 if value else 0)
                    else:
                        setattr(trigger, key, value)

            trigger.updated_at = datetime.utcnow()
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[Triggers] 更新触发器失败 {trigger_id}: {e}")
            return False
        finally:
            self._close_if_needed(session)

    def delete_trigger(self, trigger_id: str) -> bool:
        """删除触发器."""
        session = self._get_session()
        try:
            trigger = session.query(TriggerDefinition).filter(
                TriggerDefinition.id == trigger_id
            ).first()
            if not trigger:
                return False
            session.delete(trigger)
            session.commit()
            logger.info(f"[Triggers] 删除触发器: {trigger_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[Triggers] 删除触发器失败 {trigger_id}: {e}")
            return False
        finally:
            self._close_if_needed(session)

    def list_triggers(
        self,
        workflow_id: Optional[str] = None,
        trigger_type: Optional[str] = None,
        enabled: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页列出触发器.

        Args:
            workflow_id: 工作流过滤
            trigger_type: 类型过滤
            enabled: 启用状态过滤
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果
        """
        session = self._get_session()
        try:
            query = session.query(TriggerDefinition)

            if workflow_id:
                query = query.filter(TriggerDefinition.workflow_id == workflow_id)
            if trigger_type:
                query = query.filter(TriggerDefinition.trigger_type == trigger_type)
            if enabled is not None:
                query = query.filter(TriggerDefinition.enabled == (1 if enabled else 0))

            total = query.count()
            items = (
                query.order_by(desc(TriggerDefinition.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "total": total,
                "items": [item.to_dict() for item in items],
                "page": page,
                "page_size": page_size,
            }
        finally:
            self._close_if_needed(session)

    def list_enabled_triggers(self, trigger_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出所有启用的触发器.

        Args:
            trigger_type: 类型过滤

        Returns:
            触发器列表
        """
        result = self.list_triggers(
            trigger_type=trigger_type,
            enabled=True,
            page=1,
            page_size=1000,
        )
        return result["items"]

    def enable_trigger(self, trigger_id: str) -> bool:
        """启用触发器."""
        return self.update_trigger(trigger_id, enabled=True)

    def disable_trigger(self, trigger_id: str) -> bool:
        """禁用触发器."""
        return self.update_trigger(trigger_id, enabled=False)

    def get_by_webhook_path(self, path: str) -> Optional[Dict[str, Any]]:
        """根据 Webhook 路径查找触发器."""
        session = self._get_session()
        try:
            trigger = session.query(TriggerDefinition).filter(
                and_(
                    TriggerDefinition.webhook_path == path,
                    TriggerDefinition.enabled == 1,
                )
            ).first()
            return trigger.to_dict() if trigger else None
        finally:
            self._close_if_needed(session)

    # ---- 历史记录 ----

    def add_history(
        self,
        trigger_id: str,
        workflow_id: str,
        run_id: str = "",
        status: str = TriggerStatus.SUCCESS,
        payload: Optional[Dict[str, Any]] = None,
        input_data: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
        error_message: str = "",
        duration_ms: int = 0,
        source_info: Optional[Dict[str, Any]] = None,
    ) -> int:
        """添加触发历史记录.

        Returns:
            历史记录 ID
        """
        session = self._get_session()
        try:
            # 获取触发器类型
            trigger_type = "schedule"
            trigger = session.query(TriggerDefinition).filter(
                TriggerDefinition.id == trigger_id
            ).first()
            if trigger:
                trigger_type = trigger.trigger_type

            history = TriggerHistory(
                trigger_id=trigger_id,
                workflow_id=workflow_id,
                run_id=run_id,
                trigger_type=trigger_type,
                status=status,
                payload=payload or {},
                input_data=input_data or {},
                result_data=result_data or {},
                error_message=error_message,
                triggered_at=datetime.utcnow(),
                duration_ms=duration_ms,
                source_info=source_info or {},
            )
            session.add(history)

            # 更新触发器统计
            if trigger:
                trigger.trigger_count += 1
                if status == TriggerStatus.SUCCESS:
                    trigger.success_count += 1
                elif status == TriggerStatus.FAILED:
                    trigger.failed_count += 1
                trigger.last_triggered_at = datetime.utcnow()
                trigger.updated_at = datetime.utcnow()

            session.commit()
            return history.id
        except Exception as e:
            session.rollback()
            logger.error(f"[Triggers] 添加历史记录失败 {trigger_id}: {e}")
            return -1
        finally:
            self._close_if_needed(session)

    def list_history(
        self,
        trigger_id: str,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出触发历史.

        Args:
            trigger_id: 触发器 ID
            status: 状态过滤
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果
        """
        session = self._get_session()
        try:
            query = session.query(TriggerHistory).filter(
                TriggerHistory.trigger_id == trigger_id
            )

            if status:
                query = query.filter(TriggerHistory.status == status)

            total = query.count()
            items = (
                query.order_by(desc(TriggerHistory.triggered_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "total": total,
                "items": [item.to_dict() for item in items],
                "page": page,
                "page_size": page_size,
            }
        finally:
            self._close_if_needed(session)


# ============================================================
# 简单事件总线
# ============================================================

class EventBus:
    """简单的内部事件总线.

    支持事件发布/订阅，用于 Event 触发器。
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_types: Set[str] = set()

    def subscribe(self, event_type: str, handler: Callable) -> str:
        """订阅事件.

        Args:
            event_type: 事件类型
            handler: 处理函数

        Returns:
            订阅 ID
        """
        subscription_id = f"sub_{uuid.uuid4().hex[:12]}"

        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
            self._event_types.add(event_type)

        self._subscribers[event_type].append({
            "id": subscription_id,
            "handler": handler,
        })

        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """取消订阅."""
        for event_type, subscribers in self._subscribers.items():
            for sub in subscribers:
                if sub["id"] == subscription_id:
                    subscribers.remove(sub)
                    return True
        return False

    def publish(self, event_type: str, event_data: Dict[str, Any], source: str = "system") -> int:
        """发布事件.

        Args:
            event_type: 事件类型
            event_data: 事件数据
            source: 事件来源

        Returns:
            通知的订阅者数量
        """
        if event_type not in self._subscribers:
            return 0

        event = {
            "event_type": event_type,
            "data": event_data,
            "source": source,
            "timestamp": time.time(),
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        }

        count = 0
        for sub in self._subscribers[event_type]:
            try:
                handler = sub["handler"]
                if asyncio.iscoroutinefunction(handler):
                    # 对于异步 handler，创建任务（不等待）
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
                count += 1
            except Exception as e:
                logger.error(f"[EventBus] 事件处理失败 {event_type}: {e}")

        return count

    def list_event_types(self) -> List[str]:
        """列出所有事件类型."""
        return sorted(list(self._event_types))


# 全局事件总线单例
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取事件总线单例."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# ============================================================
# Webhook 管理器
# ============================================================

class WebhookManager:
    """Webhook 触发器管理器.

    负责 Webhook 签名验证和请求处理。
    """

    @staticmethod
    def verify_signature(
        body: bytes,
        signature: str,
        secret: str,
        algorithm: str = "sha256",
    ) -> bool:
        """验证 Webhook 签名.

        Args:
            body: 请求体原始字节
            signature: 签名头的值（格式: sha256=xxx 或直接 xxx）
            secret: 密钥
            algorithm: 哈希算法

        Returns:
            签名是否有效
        """
        if not secret or not signature:
            return False

        # 处理签名格式
        if "=" in signature:
            algo, sig_value = signature.split("=", 1)
            if algo.lower() != algorithm.lower():
                return False
        else:
            sig_value = signature

        try:
            # 计算 HMAC
            if algorithm.lower() == "sha256":
                mac = hmac.new(secret.encode(), body, hashlib.sha256)
            elif algorithm.lower() == "sha1":
                mac = hmac.new(secret.encode(), body, hashlib.sha1)
            else:
                return False

            expected = mac.hexdigest()

            # 安全比较（防止时序攻击）
            return hmac.compare_digest(expected.lower(), sig_value.lower().strip())
        except Exception:
            return False

    @staticmethod
    def generate_signature(body: bytes, secret: str, algorithm: str = "sha256") -> str:
        """生成签名（用于测试）."""
        if algorithm.lower() == "sha256":
            mac = hmac.new(secret.encode(), body, hashlib.sha256)
        else:
            mac = hmac.new(secret.encode(), body, hashlib.sha1)
        return f"{algorithm}={mac.hexdigest()}"

    @staticmethod
    def map_input(
        payload: Dict[str, Any],
        input_mapping: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将 Webhook 请求体映射到工作流输入.

        支持:
        - 简单键名映射: {"input_key": "payload_key"}
        - 点路径映射: {"input_key": "nested.field.value"}
        - 静态值: {"input_key": {"static": "value"}}
        - 完整 payload: {"raw_body": {"$raw": true}}

        Args:
            payload: 请求体数据
            input_mapping: 映射配置

        Returns:
            映射后的输入数据
        """
        result: Dict[str, Any] = {}

        if not input_mapping:
            return {"payload": payload}

        for target_key, mapping in input_mapping.items():
            if isinstance(mapping, dict):
                if "static" in mapping:
                    result[target_key] = mapping["static"]
                elif "$raw" in mapping and mapping["$raw"]:
                    result[target_key] = payload
                elif "$path" in mapping:
                    result[target_key] = WebhookManager._get_nested_value(
                        payload, mapping["$path"]
                    )
            elif isinstance(mapping, str):
                # 简单的键名或点路径
                result[target_key] = WebhookManager._get_nested_value(payload, mapping)
            else:
                result[target_key] = mapping

        return result

    @staticmethod
    def _get_nested_value(data: Any, path: str) -> Any:
        """获取嵌套值（点路径）."""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                current = current[idx] if 0 <= idx < len(current) else None
            else:
                return None
            if current is None:
                return None
        return current


# ============================================================
# 触发器调度器
# ============================================================

class TriggerScheduler:
    """触发器调度器.

    后台线程驱动的调度器，负责：
    1. Schedule 触发器：基于 Cron/Interval 的定时触发
    2. 触发工作流执行（提交到持久化队列）
    """

    def __init__(
        self,
        trigger_repo: Optional[TriggerRepository] = None,
        check_interval: float = 1.0,
    ):
        """初始化调度器.

        Args:
            trigger_repo: 触发器仓库
            check_interval: 检查间隔（秒）
        """
        self._repo = trigger_repo or TriggerRepository()
        self._check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._next_run_cache: Dict[str, datetime] = {}  # trigger_id -> next_run_time
        self._on_trigger_callbacks: List[Callable] = []

    @property
    def running(self) -> bool:
        return self._running

    def on_trigger(self, callback: Callable):
        """注册触发回调.

        当触发器触发时调用回调函数。
        callback 接收参数: (trigger_dict, input_data)
        """
        self._on_trigger_callbacks.append(callback)

    def start(self):
        """启动调度器（异步任务）."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._schedule_loop())
        logger.info("[Triggers] 调度器已启动")

    def stop(self):
        """停止调度器."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[Triggers] 调度器已停止")

    async def _schedule_loop(self):
        """调度主循环."""
        while self._running:
            try:
                await self._check_and_trigger()
            except Exception as e:
                logger.error(f"[Triggers] 调度循环异常: {e}")

            await asyncio.sleep(self._check_interval)

    async def _check_and_trigger(self):
        """检查并触发到期的 Schedule 触发器."""
        now = datetime.now()

        # 获取所有启用的 schedule 触发器
        triggers = self._repo.list_enabled_triggers(trigger_type=TriggerType.SCHEDULE)

        for trigger in triggers:
            trigger_id = trigger["id"]
            config = trigger.get("config", {})
            schedule_type = config.get("schedule_type", "cron")

            # 计算下次运行时间
            next_run = self._next_run_cache.get(trigger_id)

            if next_run is None:
                # 首次计算
                next_run = self._compute_next_run(trigger, from_time=now)
                if next_run:
                    self._next_run_cache[trigger_id] = next_run
                continue

            # 检查是否到期
            if now >= next_run:
                # 触发
                await self._fire_trigger(trigger)

                # 计算下一次
                next_run = self._compute_next_run(trigger, from_time=now)
                self._next_run_cache[trigger_id] = next_run

    def _compute_next_run(
        self,
        trigger: Dict[str, Any],
        from_time: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """计算触发器的下次运行时间.

        Args:
            trigger: 触发器配置
            from_time: 起始时间

        Returns:
            下次运行时间
        """
        config = trigger.get("config", {})
        schedule_type = config.get("schedule_type", "cron")

        if schedule_type == "cron":
            cron_expr = config.get("cron_expression", "")
            if not cron_expr:
                return None
            return SimpleCronParser.next_run_time(cron_expr, from_time)

        elif schedule_type == "interval":
            interval_seconds = int(config.get("interval_seconds", 60))
            if interval_seconds <= 0:
                return None
            base_time = from_time or datetime.now()
            return base_time + timedelta(seconds=interval_seconds)

        elif schedule_type == "one_time":
            run_at_str = config.get("run_at", "")
            if not run_at_str:
                return None
            try:
                # 支持 ISO 格式时间字符串
                from dateutil import parser as date_parser  # type: ignore
                return date_parser.parse(run_at_str)
            except ImportError:
                # 没有 dateutil 时尝试简单解析
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                    try:
                        return datetime.strptime(run_at_str, fmt)
                    except ValueError:
                        continue
                return None

        return None

    async def _fire_trigger(self, trigger: Dict[str, Any]):
        """触发一个 Schedule 触发器.

        Args:
            trigger: 触发器配置
        """
        trigger_id = trigger["id"]
        workflow_id = trigger["workflow_id"]

        # 构建输入数据
        input_data = trigger.get("input_mapping", {})
        # 对于 schedule 类型，添加时间信息
        input_data.setdefault("_trigger_type", "schedule")
        input_data.setdefault("_trigger_id", trigger_id)
        input_data.setdefault("_trigger_time", datetime.now().isoformat())

        logger.info(f"[Triggers] 定时触发器触发: {trigger_id} (workflow={workflow_id})")

        # 调用回调
        for callback in self._on_trigger_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(trigger, input_data)
                else:
                    callback(trigger, input_data)
            except Exception as e:
                logger.error(f"[Triggers] 触发回调失败 {trigger_id}: {e}")

        # 记录历史
        self._repo.add_history(
            trigger_id=trigger_id,
            workflow_id=workflow_id,
            status=TriggerStatus.SUCCESS,
            payload={"schedule_type": trigger.get("config", {}).get("schedule_type")},
            input_data=input_data,
            source_info={"source": "scheduler"},
        )

    def refresh_trigger_cache(self, trigger_id: str):
        """刷新触发器的调度缓存（触发器更新后调用）."""
        if trigger_id in self._next_run_cache:
            del self._next_run_cache[trigger_id]

    def get_schedule_info(self, trigger_id: str) -> Dict[str, Any]:
        """获取触发器的调度信息."""
        trigger = self._repo.get_trigger(trigger_id)
        if not trigger:
            return {}

        next_run = self._next_run_cache.get(trigger_id)
        if next_run is None:
            next_run = self._compute_next_run(trigger)

        return {
            "trigger_id": trigger_id,
            "name": trigger.get("name"),
            "type": trigger.get("trigger_type"),
            "enabled": trigger.get("enabled"),
            "next_run_time": next_run.isoformat() if next_run else None,
            "config": trigger.get("config", {}),
        }


# ============================================================
# 触发器事件处理（Event 类型）
# ============================================================

class EventTriggerHandler:
    """Event 触发器处理器.

    管理 Event 类型触发器的事件订阅和处理。
    """

    def __init__(
        self,
        trigger_repo: Optional[TriggerRepository] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self._repo = trigger_repo or TriggerRepository()
        self._event_bus = event_bus or get_event_bus()
        self._subscriptions: Dict[str, str] = {}  # trigger_id -> subscription_id
        self._on_trigger_callbacks: List[Callable] = []

    def on_trigger(self, callback: Callable):
        """注册触发回调."""
        self._on_trigger_callbacks.append(callback)

    def register_event_triggers(self):
        """注册所有启用的 Event 触发器到事件总线."""
        triggers = self._repo.list_enabled_triggers(trigger_type=TriggerType.EVENT)
        for trigger in triggers:
            self._subscribe_trigger(trigger)
        logger.info(f"[Triggers] 注册了 {len(triggers)} 个 Event 触发器")

    def _subscribe_trigger(self, trigger: Dict[str, Any]):
        """订阅单个触发器的事件."""
        trigger_id = trigger["id"]
        config = trigger.get("config", {})
        event_type = config.get("event_type", "")

        if not event_type:
            return

        # 如果已订阅，先取消
        if trigger_id in self._subscriptions:
            self._event_bus.unsubscribe(self._subscriptions[trigger_id])
            del self._subscriptions[trigger_id]

        # 创建处理函数
        async def handler(event: Dict[str, Any]):
            await self._handle_event(trigger, event)

        sub_id = self._event_bus.subscribe(event_type, handler)
        self._subscriptions[trigger_id] = sub_id
        logger.debug(f"[Triggers] Event触发器订阅: {trigger_id} -> {event_type}")

    def unsubscribe_trigger(self, trigger_id: str):
        """取消触发器的事件订阅."""
        if trigger_id in self._subscriptions:
            self._event_bus.unsubscribe(self._subscriptions[trigger_id])
            del self._subscriptions[trigger_id]

    async def _handle_event(self, trigger: Dict[str, Any], event: Dict[str, Any]):
        """处理事件，检查过滤条件并触发工作流.

        Args:
            trigger: 触发器配置
            event: 事件数据
        """
        trigger_id = trigger["id"]
        filter_config = trigger.get("filter_config", {})

        # 事件过滤
        if not self._check_event_filter(event, filter_config):
            return  # 不匹配过滤条件，跳过

        # 输入映射
        input_mapping = trigger.get("input_mapping", {})
        input_data = self._map_event_input(event, input_mapping)
        input_data.setdefault("_event_type", event.get("event_type"))
        input_data.setdefault("_event_source", event.get("source"))
        input_data.setdefault("_trigger_id", trigger_id)

        logger.info(f"[Triggers] 事件触发器触发: {trigger_id} (event={event.get('event_type')})")

        # 调用回调
        for callback in self._on_trigger_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(trigger, input_data)
                else:
                    callback(trigger, input_data)
            except Exception as e:
                logger.error(f"[Triggers] 事件触发回调失败 {trigger_id}: {e}")

        # 记录历史
        self._repo.add_history(
            trigger_id=trigger_id,
            workflow_id=trigger["workflow_id"],
            status=TriggerStatus.SUCCESS,
            payload=event,
            input_data=input_data,
            source_info={"event_id": event.get("event_id"), "source": event.get("source")},
        )

    def _check_event_filter(
        self,
        event: Dict[str, Any],
        filter_config: Dict[str, Any],
    ) -> bool:
        """检查事件是否匹配过滤条件.

        支持:
        - event_type: 事件类型匹配
        - source: 来源匹配
        - conditions: 属性条件列表 [{field, operator, value}]

        Returns:
            是否匹配
        """
        if not filter_config:
            return True

        event_data = event.get("data", {})

        # 来源过滤
        source_filter = filter_config.get("source")
        if source_filter and event.get("source") != source_filter:
            return False

        # 属性条件过滤
        conditions = filter_config.get("conditions", [])
        for condition in conditions:
            field = condition.get("field", "")
            operator = condition.get("operator", "eq")
            expected = condition.get("value")

            # 获取事件中的值
            actual = WebhookManager._get_nested_value(event_data, field)

            if not self._check_condition(actual, operator, expected):
                return False

        return True

    def _check_condition(self, actual: Any, operator: str, expected: Any) -> bool:
        """检查单个条件."""
        if operator == "eq":
            return actual == expected
        elif operator == "neq":
            return actual != expected
        elif operator == "gt":
            return actual is not None and actual > expected
        elif operator == "gte":
            return actual is not None and actual >= expected
        elif operator == "lt":
            return actual is not None and actual < expected
        elif operator == "lte":
            return actual is not None and actual <= expected
        elif operator == "contains":
            return isinstance(actual, str) and expected in actual
        elif operator == "in":
            return actual in (expected if isinstance(expected, list) else [expected])
        elif operator == "exists":
            return actual is not None
        else:
            return True  # 未知操作符默认通过

    def _map_event_input(
        self,
        event: Dict[str, Any],
        input_mapping: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将事件数据映射到工作流输入."""
        if not input_mapping:
            return {"event": event}

        event_data = event.get("data", {})
        result = {}
        for target_key, mapping in input_mapping.items():
            if isinstance(mapping, str):
                result[target_key] = WebhookManager._get_nested_value(event_data, mapping)
            elif isinstance(mapping, dict) and "static" in mapping:
                result[target_key] = mapping["static"]
            else:
                result[target_key] = mapping
        return result

    def refresh(self, trigger_id: str):
        """刷新触发器订阅（更新后调用）."""
        trigger = self._repo.get_trigger(trigger_id)
        if not trigger:
            self.unsubscribe_trigger(trigger_id)
            return

        if trigger.get("enabled") and trigger.get("trigger_type") == TriggerType.EVENT:
            self._subscribe_trigger(trigger)
        else:
            self.unsubscribe_trigger(trigger_id)


# ============================================================
# 统一触发器管理器
# ============================================================

class TriggerManager:
    """统一触发器管理器.

    整合所有触发器类型，提供统一的管理接口。
    同时负责将触发的工作流提交到持久化执行引擎。
    """

    def __init__(
        self,
        trigger_repo: Optional[TriggerRepository] = None,
        scheduler: Optional[TriggerScheduler] = None,
        event_handler: Optional[EventTriggerHandler] = None,
        webhook_mgr: Optional[WebhookManager] = None,
    ):
        self._repo = trigger_repo or TriggerRepository()
        self._scheduler = scheduler or TriggerScheduler(self._repo)
        self._event_handler = event_handler or EventTriggerHandler(self._repo)
        self._webhook_mgr = webhook_mgr or WebhookManager()
        self._started = False

        # 注册触发回调：提交到持久化执行队列
        self._scheduler.on_trigger(self._on_trigger_fired)
        self._event_handler.on_trigger(self._on_trigger_fired)

    @property
    def repo(self) -> TriggerRepository:
        return self._repo

    @property
    def scheduler(self) -> TriggerScheduler:
        return self._scheduler

    @property
    def event_handler(self) -> EventTriggerHandler:
        return self._event_handler

    @property
    def webhook_mgr(self) -> WebhookManager:
        return self._webhook_mgr

    def start(self):
        """启动触发器系统."""
        if self._started:
            return

        # 启动定时调度器
        self._scheduler.start()

        # 注册 Event 触发器
        self._event_handler.register_event_triggers()

        self._started = True
        logger.info("[Triggers] 触发器系统已启动")

    def stop(self):
        """停止触发器系统."""
        if not self._started:
            return

        self._scheduler.stop()
        self._started = False
        logger.info("[Triggers] 触发器系统已停止")

    def _on_trigger_fired(self, trigger: Dict[str, Any], input_data: Dict[str, Any]):
        """触发器触发时的回调 - 提交工作流到持久化队列.

        尝试获取工作流定义并提交执行。
        """
        try:
            workflow_id = trigger["workflow_id"]

            # 尝试从存储获取工作流
            try:
                from .storage import get_storage
                storage = get_storage()
                workflow = storage.get_workflow(workflow_id)
                if not workflow:
                    logger.warning(f"[Triggers] 工作流不存在: {workflow_id}")
                    return
            except Exception:
                # 存储不可用时构造最小工作流
                workflow = {"id": workflow_id, "name": trigger.get("workflow_id"), "blocks": []}

            # 提交到持久化执行队列
            try:
                from .persistence import get_persistent_executor
                executor = get_persistent_executor()
                asyncio.create_task(
                    executor.submit_workflow(
                        workflow=workflow,
                        input_data=input_data,
                        created_by=f"trigger:{trigger['id']}",
                        priority=trigger.get("config", {}).get("priority", 5),
                        trigger_type=trigger.get("trigger_type", "schedule"),
                        trigger_id=trigger["id"],
                    )
                )
            except Exception as e:
                logger.error(f"[Triggers] 提交工作流失败: {e}")

        except Exception as e:
            logger.error(f"[Triggers] 触发处理失败: {e}")

    # ---- 便捷方法 ----

    def create_trigger(self, **kwargs) -> Dict[str, Any]:
        """创建触发器."""
        trigger = self._repo.create_trigger(**kwargs)
        # 如果是 Event 类型且启用，注册订阅
        if trigger.get("enabled") and trigger.get("trigger_type") == TriggerType.EVENT:
            self._event_handler.refresh(trigger["id"])
        # 刷新调度缓存
        if trigger.get("trigger_type") == TriggerType.SCHEDULE:
            self._scheduler.refresh_trigger_cache(trigger["id"])
        return trigger

    def update_trigger(self, trigger_id: str, **kwargs) -> bool:
        """更新触发器."""
        result = self._repo.update_trigger(trigger_id, **kwargs)
        if result:
            self._event_handler.refresh(trigger_id)
            self._scheduler.refresh_trigger_cache(trigger_id)
        return result

    def delete_trigger(self, trigger_id: str) -> bool:
        """删除触发器."""
        self._event_handler.unsubscribe_trigger(trigger_id)
        self._scheduler.refresh_trigger_cache(trigger_id)
        return self._repo.delete_trigger(trigger_id)

    def enable_trigger(self, trigger_id: str) -> bool:
        """启用触发器."""
        result = self._repo.enable_trigger(trigger_id)
        if result:
            self._event_handler.refresh(trigger_id)
            self._scheduler.refresh_trigger_cache(trigger_id)
        return result

    def disable_trigger(self, trigger_id: str) -> bool:
        """禁用触发器."""
        result = self._repo.disable_trigger(trigger_id)
        if result:
            self._event_handler.refresh(trigger_id)
            self._scheduler.refresh_trigger_cache(trigger_id)
        return result

    def handle_webhook(
        self,
        path: str,
        body: bytes,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """处理 Webhook 请求.

        Args:
            path: Webhook 路径
            body: 请求体
            headers: 请求头

        Returns:
            处理结果 {success, run_id, trigger_id}
        """
        # 查找触发器
        trigger = self._repo.get_by_webhook_path(path)
        if not trigger:
            return {"success": False, "error": "Webhook 路径不存在或未启用"}

        # 验证签名（如果配置了密钥）
        secret = trigger.get("webhook_secret", "")
        if secret:
            signature = headers.get("X-Signature", headers.get("X-Hub-Signature-256", ""))
            if not self._webhook_mgr.verify_signature(body, signature, secret):
                self._repo.add_history(
                    trigger_id=trigger["id"],
                    workflow_id=trigger["workflow_id"],
                    status=TriggerStatus.FAILED,
                    error_message="签名验证失败",
                    source_info={"headers": dict(headers)},
                )
                return {"success": False, "error": "签名验证失败"}

        # 解析请求体
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw_body": body.decode("utf-8", errors="replace")}

        # 输入映射
        input_data = self._webhook_mgr.map_input(
            payload, trigger.get("input_mapping", {})
        )
        input_data["_trigger_type"] = "webhook"
        input_data["_trigger_id"] = trigger["id"]
        input_data["_webhook_path"] = path

        # 触发工作流
        self._on_trigger_fired(trigger, input_data)

        # 记录历史
        self._repo.add_history(
            trigger_id=trigger["id"],
            workflow_id=trigger["workflow_id"],
            status=TriggerStatus.SUCCESS,
            payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
            input_data=input_data,
            source_info={
                "headers": {k: v for k, v in headers.items() if k.lower() not in ("authorization", "x-signature")},
                "ip": headers.get("X-Forwarded-For", ""),
            },
        )

        return {
            "success": True,
            "trigger_id": trigger["id"],
            "workflow_id": trigger["workflow_id"],
            "message": "Webhook 已接收，工作流已触发",
        }


# ============================================================
# 全局单例
# ============================================================

_trigger_manager: Optional[TriggerManager] = None


def get_trigger_manager() -> TriggerManager:
    """获取触发器管理器单例."""
    global _trigger_manager
    if _trigger_manager is None:
        _trigger_manager = TriggerManager()
    return _trigger_manager
