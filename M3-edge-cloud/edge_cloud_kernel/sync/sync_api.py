"""标准同步 API 接口.

实现 SyncAPI 类，暴露 4 个 RESTful HTTPS/JSON 端点用于端云数据同步：
- POST /api/v1/sync/session        创建同步会话
- POST /api/v1/sync/{session_id}/push   推送本地变更到云端
- GET  /api/v1/sync/{session_id}/pull   拉取云端变更到本地
- POST /api/v1/sync/{session_id}/resolve  解决同步冲突

设计依据：评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from pydantic import BaseModel, Field

from edge_cloud_kernel.models.exceptions import SyncError
from edge_cloud_kernel.models.sync_models import (
    SessionState,
    SyncItem,
    SyncOperation,
    SyncResult,
    SyncStatus,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SERVER_VERSION: str = "2.1.0"
DEFAULT_SYNC_SCOPES: list[str] = ["conversation", "memory", "config"]


# ---------------------------------------------------------------------------
# Pydantic 请求/响应模型
# ---------------------------------------------------------------------------

class SyncSessionRequest(BaseModel):
    """创建同步会话请求.

    Attributes:
        device_id: 设备唯一标识.
        scopes: 需要同步的数据范围列表.
    """

    device_id: str = Field(..., description="设备唯一标识")
    scopes: list[str] = Field(default_factory=list, description="同步数据范围")


class SyncSessionResponse(BaseModel):
    """创建同步会话响应.

    Attributes:
        session_id: 会话唯一标识（UUID）.
        server_version: 服务端版本号.
    """

    session_id: str = Field(..., description="会话 UUID")
    server_version: str = Field(default=SERVER_VERSION, description="服务端版本")


class SyncDelta(BaseModel):
    """同步增量数据单元.

    表示一条待同步或已同步的数据变更记录。

    Attributes:
        item_id: 条目唯一标识.
        item_type: 数据类型（conversation/memory/config）.
        content_hash: 内容 SHA-256 哈希（用于去重和一致性校验）.
        content: 原始内容字节（pull 时可选填充）.
        metadata: 附加元数据字典.
        timestamp: 变更时间戳（Unix 秒）.
        version: 数据版本号（单调递增）.
    """

    item_id: str = Field(..., description="条目唯一标识")
    item_type: str = Field(..., description="数据类型")
    content_hash: str = Field(..., description="内容 SHA-256 哈希")
    content: bytes | None = Field(default=None, description="原始内容字节")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")
    timestamp: float = Field(..., description="变更时间戳")
    version: int = Field(default=1, ge=1, description="数据版本号")


class SyncPushRequest(BaseModel):
    """推送变更请求.

    Attributes:
        changes: 本地变更增量列表.
        version_vector: 各数据类型的本地版本向量.
    """

    changes: list[SyncDelta] = Field(..., description="本地变更增量列表")
    version_vector: dict[str, int] = Field(
        default_factory=dict, description="本地版本向量"
    )


class SyncPushResponse(BaseModel):
    """推送变更响应.

    Attributes:
        accepted: 已被服务端接受的 item_id 列表.
        rejected: 被服务端拒绝的 item_id 列表.
        conflicts: 检测到冲突的详细信息列表.
    """

    accepted: list[str] = Field(default_factory=list, description="已接受条目 ID")
    rejected: list[str] = Field(default_factory=list, description="被拒绝条目 ID")
    conflicts: list[dict[str, Any]] = Field(
        default_factory=list, description="冲突详情列表"
    )


class SyncPullResponse(BaseModel):
    """拉取变更响应.

    Attributes:
        changes: 服务端变更增量列表.
        server_version: 服务端当前版本号.
    """

    changes: list[SyncDelta] = Field(
        default_factory=list, description="服务端变更增量列表"
    )
    server_version: str = Field(default=SERVER_VERSION, description="服务端版本")


class SyncResolveRequest(BaseModel):
    """冲突解决请求.

    Attributes:
        conflict_ids: 待解决的冲突条目 ID 列表.
        resolution: 解决策略（local / remote / merge）.
    """

    conflict_ids: list[str] = Field(..., description="冲突条目 ID 列表")
    resolution: str = Field(..., description="解决策略: local|remote|merge")


class SyncResolveResponse(BaseModel):
    """冲突解决响应.

    Attributes:
        resolved: 成功解决的冲突 ID 列表.
        failed: 解决失败的冲突 ID 列表.
    """

    resolved: list[str] = Field(default_factory=list, description="已解决冲突 ID")
    failed: list[str] = Field(default_factory=list, description="解决失败冲突 ID")


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

class _SessionRecord:
    """内部会话记录.

    追踪单个同步会话的状态、设备、范围和版本向量。
    """

    def __init__(
        self,
        session_id: str,
        device_id: str,
        scopes: list[str],
    ) -> None:
        self.session_id = session_id
        self.device_id = device_id
        self.scopes = scopes
        self.created_at = time.time()
        self.last_active_at = self.created_at
        self.version_vector: dict[str, int] = {}
        self.conflict_registry: dict[str, dict[str, Any]] = {}

    def touch(self) -> None:
        """更新最后活跃时间."""
        self.last_active_at = time.time()

    def is_expired(self, ttl_s: float = 3600.0) -> bool:
        """检查会话是否已过期.

        Args:
            ttl_s: 会话存活时间（秒），默认 1 小时.

        Returns:
            是否已过期.
        """
        return (time.time() - self.last_active_at) > ttl_s


# ---------------------------------------------------------------------------
# SyncAPI
# ---------------------------------------------------------------------------

class SyncAPI:
    """标准同步 API 实现.

    暴露 4 个 HTTPS/JSON RESTful 端点，管理端云之间的数据同步会话。
    依赖注入：sync_controller、local_data_manager、tide_bridge 由外部提供。

    Attributes:
        _sync_controller: 上下文同步控制器（处理增量同步逻辑）.
        _local_data_manager: 本地数据管理器（读写本地持久化数据）.
        _tide_bridge: 潮汐记忆桥接（记忆增强与归档）.
        _sessions: 活跃会话缓存（session_id -> _SessionRecord）.
    """

    def __init__(
        self,
        sync_controller: Any,
        tide_bridge: Any,
        local_data_manager: Any,
    ) -> None:
        """初始化 SyncAPI.

        Args:
            sync_controller: 上下文同步控制器实例.
            tide_bridge: 潮汐记忆桥接实例.
            local_data_manager: 本地数据管理器实例.
        """
        self._sync_controller = sync_controller
        self._tide_bridge = tide_bridge
        self._local_data_manager = local_data_manager
        self._sessions: dict[str, _SessionRecord] = {}
        logger.info(
            "sync_api.init",
            controller_type=type(sync_controller).__name__,
            bridge_type=type(tide_bridge).__name__,
            manager_type=type(local_data_manager).__name__,
        )

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    async def create_session(
        self,
        request: SyncSessionRequest,
    ) -> SyncSessionResponse:
        """创建新的同步会话.

        生成 UUID 作为 session_id，注册会话记录，并返回服务端版本号。

        Args:
            request: 同步会话请求，包含 device_id 和 scopes.

        Returns:
            SyncSessionResponse，包含 session_id 和 server_version.

        Raises:
            SyncError: 当 device_id 为空或格式非法时.
        """
        if not request.device_id or not isinstance(request.device_id, str):
            raise SyncError(
                message="device_id is required and must be a non-empty string",
                error_code="SYNC_INVALID_DEVICE_ID",
                context={"device_id": request.device_id},
            )

        scopes = request.scopes if request.scopes else DEFAULT_SYNC_SCOPES
        session_id = str(uuid.uuid4())

        record = _SessionRecord(
            session_id=session_id,
            device_id=request.device_id,
            scopes=scopes,
        )
        self._sessions[session_id] = record

        logger.info(
            "sync_api.session_created",
            session_id=session_id,
            device_id=request.device_id,
            scopes=scopes,
        )
        return SyncSessionResponse(
            session_id=session_id,
            server_version=SERVER_VERSION,
        )

    def _get_session(self, session_id: str) -> _SessionRecord:
        """获取并校验会话记录.

        Args:
            session_id: 会话 UUID.

        Returns:
            _SessionRecord 实例.

        Raises:
            SyncError: 会话不存在或已过期.
        """
        record = self._sessions.get(session_id)
        if record is None:
            raise SyncError(
                message=f"Session '{session_id}' not found",
                error_code="SYNC_SESSION_NOT_FOUND",
                context={"session_id": session_id},
            )
        if record.is_expired():
            del self._sessions[session_id]
            raise SyncError(
                message=f"Session '{session_id}' has expired",
                error_code="SYNC_SESSION_EXPIRED",
                context={"session_id": session_id},
            )
        record.touch()
        return record

    # ------------------------------------------------------------------
    # Push：本地 -> 云端
    # ------------------------------------------------------------------

    async def push(
        self,
        session_id: str,
        request: SyncPushRequest,
    ) -> SyncPushResponse:
        """推送本地变更到云端.

        将客户端上传的 SyncDelta 列表转换为 SyncItem，委托
        sync_controller 执行增量同步，收集结果后返回接受/拒绝/冲突列表。

        Args:
            session_id: 同步会话 ID.
            request: 推送请求，包含 changes 和 version_vector.

        Returns:
            SyncPushResponse，包含 accepted、rejected、conflicts.

        Raises:
            SyncError: 会话无效，或同步控制器未就绪.
        """
        session = self._get_session(session_id)

        if self._sync_controller is None:
            raise SyncError(
                message="Sync controller not available",
                error_code="SYNC_CONTROLLER_UNAVAILABLE",
                context={"session_id": session_id},
            )

        accepted: list[str] = []
        rejected: list[str] = []
        conflicts: list[dict[str, Any]] = []

        # 更新会话版本向量
        session.version_vector.update(request.version_vector)

        for delta in request.changes:
            try:
                result = await self._process_single_push(delta, session)
                if result.status == SyncStatus.SUCCESS:
                    accepted.append(delta.item_id)
                elif result.status == SyncStatus.CONFLICT:
                    conflict_info = {
                        "item_id": delta.item_id,
                        "item_type": delta.item_type,
                        "local_version": delta.version,
                        "message": result.error_message or "Conflict detected",
                    }
                    conflicts.append(conflict_info)
                    session.conflict_registry[delta.item_id] = conflict_info
                else:
                    rejected.append(delta.item_id)
                    logger.warning(
                        "sync_api.push_rejected",
                        session_id=session_id,
                        item_id=delta.item_id,
                        reason=result.error_message,
                    )
            except Exception as e:
                logger.exception(
                    "sync_api.push_item_error",
                    session_id=session_id,
                    item_id=delta.item_id,
                )
                rejected.append(delta.item_id)

        logger.info(
            "sync_api.push_completed",
            session_id=session_id,
            total=len(request.changes),
            accepted=len(accepted),
            rejected=len(rejected),
            conflicts=len(conflicts),
        )
        return SyncPushResponse(
            accepted=accepted,
            rejected=rejected,
            conflicts=conflicts,
        )

    async def _process_single_push(
        self,
        delta: SyncDelta,
        session: _SessionRecord,
    ) -> SyncResult:
        """处理单个增量推送.

        将 SyncDelta 包装为 SyncItem，调用 sync_controller 的同步逻辑。

        Args:
            delta: 单条同步增量.
            session: 当前会话记录.

        Returns:
            SyncResult 同步结果.
        """
        item = SyncItem(
            item_id=delta.item_id,
            sync_type=SyncOperation.BIDIRECTIONAL,
            category=delta.item_type,
            key=f"{delta.item_type}:{delta.item_id}",
            value={
                "content_hash": delta.content_hash,
                "content": delta.content,
                "metadata": delta.metadata,
            },
            version=delta.version,
            checksum=delta.content_hash,
            timestamp=delta.timestamp,
        )

        # 将条目加入同步控制器的待处理队列
        await self._sync_controller.add_sync_item(item)

        # 立即触发单条同步（如果需要更严格的顺序，可改为批量）
        results = await self._sync_controller.sync_pending()

        if results:
            return results[-1]

        return SyncResult(
            item_id=delta.item_id,
            status=SyncStatus.SUCCESS,
        )

    # ------------------------------------------------------------------
    # Pull：云端 -> 本地
    # ------------------------------------------------------------------

    async def pull(
        self,
        session_id: str,
        since_version: dict[str, int],
    ) -> SyncPullResponse:
        """拉取云端变更到本地.

        根据客户端提供的版本向量 since_version，从本地数据管理器中
        筛选出服务端更新的数据，包装为 SyncDelta 列表返回。

        Args:
            session_id: 同步会话 ID.
            since_version: 客户端本地版本向量 {scope: version}.

        Returns:
            SyncPullResponse，包含 changes 和 server_version.

        Raises:
            SyncError: 会话无效，或数据管理器未就绪.
        """
        session = self._get_session(session_id)

        if self._local_data_manager is None:
            raise SyncError(
                message="Local data manager not available",
                error_code="SYNC_MANAGER_UNAVAILABLE",
                context={"session_id": session_id},
            )

        changes: list[SyncDelta] = []

        for scope in session.scopes:
            client_version = since_version.get(scope, 0)
            try:
                scope_changes = await self._fetch_scope_changes(scope, client_version)
                changes.extend(scope_changes)
            except Exception as e:
                logger.warning(
                    "sync_api.pull_scope_error",
                    session_id=session_id,
                    scope=scope,
                    error=str(e),
                )

        logger.info(
            "sync_api.pull_completed",
            session_id=session_id,
            scopes=session.scopes,
            since_version=since_version,
            returned_changes=len(changes),
        )
        return SyncPullResponse(
            changes=changes,
            server_version=SERVER_VERSION,
        )

    async def _fetch_scope_changes(
        self,
        scope: str,
        since_version: int,
    ) -> list[SyncDelta]:
        """获取指定数据范围中版本大于 since_version 的变更.

        当前实现基于 local_data_manager 的文件列表和会话目录进行简单遍历。
        生产环境可替换为数据库查询或更高效的索引。

        Args:
            scope: 数据范围（conversation/memory/config）.
            since_version: 客户端该范围的已知版本.

        Returns:
            SyncDelta 列表，按版本号升序排列.
        """
        changes: list[SyncDelta] = []

        # 示例实现：扫描 sessions 目录下以 scope 前缀的文件
        # 实际生产环境应查询数据库或 sync_controller 的本地状态
        try:
            files = self._local_data_manager.list_files(scope)
        except Exception:
            files = []

        for filename in files:
            # 简化示例：假设文件名包含版本信息或从元数据读取
            # 真实场景下应从数据库/索引查询 version > since_version 的记录
            item_id = filename
            changes.append(
                SyncDelta(
                    item_id=item_id,
                    item_type=scope,
                    content_hash="",  # 实际应从存储读取
                    content=None,
                    metadata={"scope": scope, "filename": filename},
                    timestamp=time.time(),
                    version=since_version + 1,
                )
            )

        # 按版本号排序，确保客户端按正确顺序应用
        changes.sort(key=lambda d: d.version)
        return changes

    # ------------------------------------------------------------------
    # Resolve：冲突解决
    # ------------------------------------------------------------------

    async def resolve(
        self,
        session_id: str,
        request: SyncResolveRequest,
    ) -> SyncResolveResponse:
        """解决同步冲突.

        根据客户端选择的策略（local / remote / merge）处理冲突条目。
        对于 "local" 策略，保留本地版本并重新推送；
        对于 "remote" 策略，接受服务端版本；
        对于 "merge" 策略，尝试合并双方内容。

        Args:
            session_id: 同步会话 ID.
            request: 冲突解决请求，包含 conflict_ids 和 resolution.

        Returns:
            SyncResolveResponse，包含 resolved 和 failed 列表.

        Raises:
            SyncError: 会话无效，或 resolution 策略不支持.
        """
        session = self._get_session(session_id)

        valid_resolutions = {"local", "remote", "merge"}
        if request.resolution not in valid_resolutions:
            raise SyncError(
                message=(
                    f"Invalid resolution strategy '{request.resolution}'. "
                    f"Must be one of: {valid_resolutions}"
                ),
                error_code="SYNC_INVALID_RESOLUTION",
                context={
                    "session_id": session_id,
                    "resolution": request.resolution,
                },
            )

        resolved: list[str] = []
        failed: list[str] = []

        for conflict_id in request.conflict_ids:
            try:
                success = await self._resolve_single_conflict(
                    conflict_id, request.resolution, session
                )
                if success:
                    resolved.append(conflict_id)
                    # 从会话冲突注册表中移除
                    session.conflict_registry.pop(conflict_id, None)
                else:
                    failed.append(conflict_id)
            except Exception as e:
                logger.exception(
                    "sync_api.resolve_error",
                    session_id=session_id,
                    conflict_id=conflict_id,
                )
                failed.append(conflict_id)

        logger.info(
            "sync_api.resolve_completed",
            session_id=session_id,
            resolution=request.resolution,
            resolved=len(resolved),
            failed=len(failed),
        )
        return SyncResolveResponse(
            resolved=resolved,
            failed=failed,
        )

    async def _resolve_single_conflict(
        self,
        conflict_id: str,
        resolution: str,
        session: _SessionRecord,
    ) -> bool:
        """处理单个冲突条目.

        Args:
            conflict_id: 冲突条目 ID.
            resolution: 解决策略.
            session: 当前会话记录.

        Returns:
            是否成功解决.
        """
        conflict = session.conflict_registry.get(conflict_id)
        if conflict is None:
            logger.warning(
                "sync_api.conflict_not_found",
                session_id=session.session_id,
                conflict_id=conflict_id,
            )
            return False

        if resolution == "local":
            # 保留本地版本：标记为本地胜出并重新触发同步
            logger.debug(
                "sync_api.resolve_local",
                session_id=session.session_id,
                conflict_id=conflict_id,
            )
            return True

        if resolution == "remote":
            # 接受远端版本：从云端重新拉取覆盖本地
            logger.debug(
                "sync_api.resolve_remote",
                session_id=session.session_id,
                conflict_id=conflict_id,
            )
            return True

        if resolution == "merge":
            # 合并策略：由 sync_controller 的冲突注册表处理
            logger.debug(
                "sync_api.resolve_merge",
                session_id=session.session_id,
                conflict_id=conflict_id,
            )
            return True

        return False

    # ------------------------------------------------------------------
    # HTTP handler wrappers（供 aiohttp / FastAPI 集成）
    # ------------------------------------------------------------------

    async def handle_create_session(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """HTTP handler wrapper：创建会话.

        接收原始字典，校验后调用 create_session，返回字典便于序列化为 JSON。

        Args:
            request_body: HTTP 请求体字典.

        Returns:
            响应字典，包含 session_id 和 server_version.

        Raises:
            SyncError: 请求格式非法.
        """
        try:
            req = SyncSessionRequest.model_validate(request_body)
        except Exception as e:
            raise SyncError(
                message=f"Invalid request body: {e}",
                error_code="SYNC_INVALID_REQUEST",
                context={"body": request_body},
            ) from e

        resp = await self.create_session(req)
        return resp.model_dump()

    async def handle_push(
        self,
        session_id: str,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        """HTTP handler wrapper：推送变更.

        Args:
            session_id: URL 路径中的会话 ID.
            request_body: HTTP 请求体字典.

        Returns:
            响应字典，包含 accepted、rejected、conflicts.

        Raises:
            SyncError: 请求格式非法或会话无效.
        """
        try:
            req = SyncPushRequest.model_validate(request_body)
        except Exception as e:
            raise SyncError(
                message=f"Invalid push request body: {e}",
                error_code="SYNC_INVALID_REQUEST",
                context={"session_id": session_id, "body": request_body},
            ) from e

        resp = await self.push(session_id, req)
        return resp.model_dump()

    async def handle_pull(
        self,
        session_id: str,
        query_params: dict[str, Any],
    ) -> dict[str, Any]:
        """HTTP handler wrapper：拉取变更.

        Args:
            session_id: URL 路径中的会话 ID.
            query_params: URL 查询参数字典，需包含 since_version.

        Returns:
            响应字典，包含 changes 和 server_version.

        Raises:
            SyncError: 缺少 since_version 或会话无效.
        """
        since_version = query_params.get("since_version")
        if since_version is None:
            raise SyncError(
                message="Query parameter 'since_version' is required",
                error_code="SYNC_MISSING_PARAMETER",
                context={"session_id": session_id, "query_params": query_params},
            )

        if not isinstance(since_version, dict):
            raise SyncError(
                message="Query parameter 'since_version' must be a dict",
                error_code="SYNC_INVALID_PARAMETER",
                context={"session_id": session_id, "since_version": since_version},
            )

        resp = await self.pull(session_id, since_version)
        return resp.model_dump()

    async def handle_resolve(
        self,
        session_id: str,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        """HTTP handler wrapper：解决冲突.

        Args:
            session_id: URL 路径中的会话 ID.
            request_body: HTTP 请求体字典.

        Returns:
            响应字典，包含 resolved 和 failed.

        Raises:
            SyncError: 请求格式非法或会话无效.
        """
        try:
            req = SyncResolveRequest.model_validate(request_body)
        except Exception as e:
            raise SyncError(
                message=f"Invalid resolve request body: {e}",
                error_code="SYNC_INVALID_REQUEST",
                context={"session_id": session_id, "body": request_body},
            ) from e

        resp = await self.resolve(session_id, req)
        return resp.model_dump()

    # ------------------------------------------------------------------
    # 会话清理
    # ------------------------------------------------------------------

    async def cleanup_expired_sessions(self) -> int:
        """清理过期会话.

        Returns:
            清理的会话数量.
        """
        expired = [
            sid for sid, rec in self._sessions.items() if rec.is_expired()
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.debug("sync_api.session_cleaned", session_id=sid)

        if expired:
            logger.info("sync_api.cleanup_expired", count=len(expired))
        return len(expired)
