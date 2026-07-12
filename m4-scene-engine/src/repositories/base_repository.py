"""仓储基类模块.

定义数据访问层的基类 BaseRepository，提供统一的 CRUD 接口规范。
后续迁移 M8 业务数据时，各业务模式的仓储类应继承此基类。
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

# 泛型类型变量，用于仓储的实体类型
T = TypeVar("T")
ID = TypeVar("ID")


class BaseRepository(Generic[T, ID]):
    """仓储基类.

    所有数据访问层（Repository）都应继承此类，
    提供统一的 CRUD 操作接口。

    泛型参数:
        T: 实体类型
        ID: 主键类型

    子类需要实现以下抽象方法:
        - get_by_id
        - list_all
        - create
        - update
        - delete
    """

    # -----------------------------------------------------------------------
    # 基础查询方法
    # -----------------------------------------------------------------------

    async def get_by_id(self, entity_id: ID) -> Optional[T]:
        """根据 ID 获取实体.

        Args:
            entity_id: 实体 ID

        Returns:
            实体对象，不存在返回 None
        """
        raise NotImplementedError("子类必须实现 get_by_id 方法")

    async def list_all(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = False,
    ) -> dict[str, Any]:
        """获取实体列表（分页）.

        Args:
            page: 页码（从 1 开始）
            page_size: 每页条数
            filters: 过滤条件字典
            order_by: 排序字段
            descending: 是否降序

        Returns:
            分页结果字典，包含:
            - items: 实体列表
            - total: 总条数
            - page: 当前页码
            - page_size: 每页条数
            - total_pages: 总页数
        """
        raise NotImplementedError("子类必须实现 list_all 方法")

    # -----------------------------------------------------------------------
    # 基础写入方法
    # -----------------------------------------------------------------------

    async def create(self, entity: T) -> T:
        """创建新实体.

        Args:
            entity: 实体对象

        Returns:
            创建后的实体对象（包含生成的 ID）
        """
        raise NotImplementedError("子类必须实现 create 方法")

    async def update(self, entity_id: ID, data: dict[str, Any]) -> Optional[T]:
        """更新实体.

        Args:
            entity_id: 实体 ID
            data: 更新数据字典

        Returns:
            更新后的实体对象，不存在返回 None
        """
        raise NotImplementedError("子类必须实现 update 方法")

    async def delete(self, entity_id: ID) -> bool:
        """删除实体.

        Args:
            entity_id: 实体 ID

        Returns:
            True 表示删除成功，False 表示实体不存在
        """
        raise NotImplementedError("子类必须实现 delete 方法")

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    async def exists(self, entity_id: ID) -> bool:
        """检查实体是否存在.

        Args:
            entity_id: 实体 ID

        Returns:
            True 表示存在，False 表示不存在
        """
        entity = await self.get_by_id(entity_id)
        return entity is not None

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        """统计实体数量.

        Args:
            filters: 过滤条件字典

        Returns:
            实体总数
        """
        result = await self.list_all(page=1, page_size=1, filters=filters)
        return result.get("total", 0)

    def _calc_total_pages(self, total: int, page_size: int) -> int:
        """计算总页数.

        Args:
            total: 总条数
            page_size: 每页条数

        Returns:
            总页数
        """
        if page_size <= 0:
            return 0
        return (total + page_size - 1) // page_size
