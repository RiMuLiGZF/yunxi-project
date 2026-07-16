"""数据库事务管理.

提供同步的事务上下文管理器和装饰器，替代直接使用 session 的方式，
确保事务的正确提交/回滚和资源释放。

本模块提供两种使用模式：

1. **独立会话模式** (transactional / transactional_decorator)
   - 自动创建、提交、回滚、关闭会话
   - 适用于 Service 层或独立的业务操作

2. **共享会话模式** (transactional_scope / transactional_method)
   - 使用已有的 Session 对象，只管理 commit/rollback
   - 适用于 Repository 层（session 由调用方注入）
   - 不会关闭传入的 session，生命周期由调用方管理
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# 1. 独立会话模式：自动创建和关闭 session
# ---------------------------------------------------------------------------

@contextmanager
def transactional():
    """事务上下文管理器（独立会话模式）.

    自动管理数据库会话的生命周期：创建、提交、回滚、关闭。
    适用于没有外部 session 的场景，会创建一个新的 session。

    使用方式:
        with transactional() as session:
            session.add(...)
            # 无需手动 commit，with 块正常结束时自动提交
            # 发生异常时自动回滚

    Yields:
        SQLAlchemy Session 对象
    """
    from src.models.db import get_session

    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def transactional_decorator(func: Callable[..., Any]) -> Callable[..., Any]:
    """事务装饰器（独立会话模式）.

    为函数自动包裹事务管理，函数正常返回则提交，抛出异常则回滚。
    被装饰的函数可以通过 session 关键字参数接收数据库会话。

    使用方式:
        @transactional_decorator
        def do_something(session=None, other_arg=None):
            session.add(...)
            # 函数正常返回时自动 commit
            # 抛出异常时自动 rollback

    Args:
        func: 要装饰的函数

    Returns:
        包装后的函数
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from src.models.db import get_session

        session = get_session()
        try:
            # 将 session 注入到 kwargs 中
            kwargs["session"] = session
            result = func(*args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return wrapper


# ---------------------------------------------------------------------------
# 2. 共享会话模式：使用已有 session，只管理 commit/rollback
# ---------------------------------------------------------------------------

@contextmanager
def transactional_scope(session: Session, *, nested: bool = False):
    """事务上下文管理器（共享会话模式）.

    使用已有的 SQLAlchemy Session 对象，只管理 commit/rollback，
    不会关闭 session（session 的生命周期由调用方负责）。

    适用于 Repository 层：session 从外部注入，方法内的写操作
    需要保证原子性（多个写操作要么全部成功要么全部回滚）。

    使用方式:
        class MyRepository:
            def __init__(self, db: Session):
                self.db = db

            def create_something(self, data):
                with transactional_scope(self.db):
                    obj1 = Model1(**data)
                    self.db.add(obj1)
                    obj2 = Model2(**related_data)
                    self.db.add(obj2)
                    # 两个 add 在同一个事务中，要么都提交要么都回滚
                # 退出 with 块后 session 仍然可用
                return obj1

    Args:
        session: 已有的 SQLAlchemy Session 对象
        nested: 是否为嵌套事务（使用 savepoint）。默认 False，
                嵌套调用时如果外层已有事务，内层将不单独提交。

    Yields:
        传入的 Session 对象（方便链式调用）
    """
    if nested:
        # 使用 savepoint 实现嵌套事务
        session.begin_nested()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
    else:
        # 非嵌套模式：直接管理顶层事务
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def transactional_method(func: Callable[..., Any]) -> Callable[..., Any]:
    """方法级事务装饰器（共享会话模式）.

    用于类的实例方法，自动从 self.db 获取 session，
    整个方法作为一个事务：正常返回则 commit，抛出异常则 rollback。
    不会关闭 session（session 的生命周期由调用方负责）。

    使用方式:
        class MyRepository:
            def __init__(self, db: Session):
                self.db = db

            @transactional_method
            def create_something(self, data):
                obj1 = Model1(**data)
                self.db.add(obj1)
                obj2 = Model2(**related_data)
                self.db.add(obj2)
                # 整个方法在一个事务中
                return obj1

    注意:
        被装饰的类必须有 self.db 属性，且为 SQLAlchemy Session 对象。

    Args:
        func: 要装饰的实例方法

    Returns:
        包装后的方法
    """
    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        session: Session = self.db
        try:
            result = func(self, *args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise

    return wrapper


# ---------------------------------------------------------------------------
# 3. 批量操作辅助函数
# ---------------------------------------------------------------------------

def bulk_commit(
    session: Session,
    instances: list[Any],
    *,
    batch_size: int = 100,
) -> int:
    """批量提交实体对象.

    将大量对象分批提交，避免一次性提交过多导致性能问题。
    每批使用独立的事务，一批失败不影响其他批。

    Args:
        session: 数据库会话
        instances: 要添加的实体对象列表
        batch_size: 每批提交的数量，默认 100

    Returns:
        成功提交的总数量

    Example:
        users = [User(name=f"user_{i}") for i in range(1000)]
        count = bulk_commit(session, users, batch_size=200)
    """
    total = 0
    for i in range(0, len(instances), batch_size):
        batch = instances[i:i + batch_size]
        try:
            with transactional_scope(session, nested=True):
                for obj in batch:
                    session.add(obj)
            total += len(batch)
        except Exception:
            # 单批失败，继续下一批
            continue
    return total


def bulk_update(
    session: Session,
    instances: list[Any],
    update_fields: list[str],
    *,
    batch_size: int = 100,
) -> int:
    """批量更新实体对象的指定字段.

    Args:
        session: 数据库会话
        instances: 要更新的实体对象列表（必须是已查询出的托管对象）
        update_fields: 要更新的字段名列表
        batch_size: 每批提交的数量，默认 100

    Returns:
        成功更新的总数量

    Example:
        users = session.query(User).filter(User.status == "active").all()
        for u in users:
            u.status = "inactive"
        count = bulk_update(session, users, ["status"])
    """
    total = 0
    for i in range(0, len(instances), batch_size):
        batch = instances[i:i + batch_size]
        try:
            with transactional_scope(session, nested=True):
                for obj in batch:
                    # 触发脏检查，确保字段被标记为更新
                    for field in update_fields:
                        val = getattr(obj, field)
                        setattr(obj, field, val)
            total += len(batch)
        except Exception:
            continue
    return total


# ---------------------------------------------------------------------------
# 4. 事务辅助工具
# ---------------------------------------------------------------------------

def safe_commit(session: Session) -> bool:
    """安全提交，发生异常时自动回滚并返回 False.

    用于不想通过异常处理来判断提交结果的场景。

    Args:
        session: 数据库会话

    Returns:
        True 表示提交成功，False 表示提交失败（已回滚）

    Example:
        session.add(some_obj)
        if not safe_commit(session):
            print("提交失败，已回滚")
    """
    try:
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False


def with_retry(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """带重试机制的事务执行.

    在事务中执行函数，如果发生异常则回滚并重试，
    最多重试 max_retries 次。适用于可能出现临时冲突的操作。

    Args:
        func: 要执行的函数，接收 session 作为第一个参数
        *args: 传递给 func 的额外位置参数
        max_retries: 最大重试次数，默认 3
        **kwargs: 传递给 func 的关键字参数

    Returns:
        函数执行结果

    Raises:
        最后一次重试仍然失败时抛出原始异常

    Example:
        def create_user(session, name):
            user = User(name=name)
            session.add(user)
            return user

        user = with_retry(create_user, "alice", max_retries=3)
    """
    from src.models.db import get_session

    last_exception: Optional[Exception] = None
    for attempt in range(max_retries):
        session = get_session()
        try:
            result = func(session, *args, **kwargs)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            last_exception = e
            if attempt < max_retries - 1:
                continue
            raise
        finally:
            session.close()

    # 理论上不会执行到这里
    if last_exception:
        raise last_exception
    return None
