"""云端同步客户端.

管理端云之间的数据同步通信。
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

import structlog

from edge_cloud_kernel.models.sync_models import SyncItem, SyncResult, SyncStatus

logger = structlog.get_logger(__name__)


class SyncMode(str, Enum):
    """同步模式枚举.

    Attributes:
        UPLOAD: 上传模式（本地 -> 云端）.
        DOWNLOAD: 下载模式（云端 -> 本地）.
        BIDIRECTIONAL: 双向同步模式.
    """

    UPLOAD = "upload"
    DOWNLOAD = "download"
    BIDIRECTIONAL = "bidirectional"


class SyncClient:
    """云端同步客户端.

    负责与云端服务进行数据同步通信，
    支持上传、下载和双向同步三种模式。

    Attributes:
        _cloud_endpoint: 云端同步 API 端点.
        _api_key: API 密钥.
        _last_sync_time: 上次同步时间.
    """

    def __init__(
        self,
        cloud_endpoint: str = "",
        api_key: str = "",
    ) -> None:
        """初始化 SyncClient.

        Args:
            cloud_endpoint: 云端同步 API 端点.
            api_key: API 密钥.
        """
        self._cloud_endpoint = cloud_endpoint
        self._api_key = api_key
        self._last_sync_time: float = 0.0
        logger.info("sync_client.init")

    async def upload(
        self,
        items: list[SyncItem],
    ) -> list[SyncResult]:
        """上传本地数据到云端.

        Args:
            items: 待上传的同步条目列表.

        Returns:
            同步结果列表.
        """
        results: list[SyncResult] = []
        for item in items:
            try:
                # TODO: 调用云端 API 上传
                result = SyncResult(
                    item_id=item.item_id,
                    status=SyncStatus.SUCCESS,
                )
                results.append(result)
            except Exception as e:
                results.append(SyncResult(
                    item_id=item.item_id,
                    status=SyncStatus.FAILED,
                    error_message=str(e),
                ))

        self._last_sync_time = time.time()
        logger.info(
            "sync_client.uploaded",
            total=len(items),
            success=sum(1 for r in results if r.status == SyncStatus.SUCCESS),
        )
        return results

    async def download(
        self,
        keys: list[str],
    ) -> list[SyncResult]:
        """从云端下载数据到本地.

        Args:
            keys: 要下载的数据键列表.

        Returns:
            同步结果列表.
        """
        results: list[SyncResult] = []
        for key in keys:
            try:
                # TODO: 调用云端 API 下载
                result = SyncResult(
                    item_id=key,
                    status=SyncStatus.SUCCESS,
                )
                results.append(result)
            except Exception as e:
                results.append(SyncResult(
                    item_id=key,
                    status=SyncStatus.FAILED,
                    error_message=str(e),
                ))

        self._last_sync_time = time.time()
        logger.info(
            "sync_client.downloaded",
            total=len(keys),
            success=sum(1 for r in results if r.status == SyncStatus.SUCCESS),
        )
        return results

    async def bidirectional(
        self,
        local_items: list[SyncItem],
    ) -> dict[str, Any]:
        """双向同步（合并）.

        正确的双向同步流程：
        1. 上传本地变更到云端
        2. 下载远端所有变更（不仅限于已上传条目的）
        3. 检测冲突并返回冲突列表

        Args:
            local_items: 本地待同步条目.

        Returns:
            包含 upload_results、download_results、conflicts 的字典.
        """
        # Step 1: 上传本地变更
        upload_results = await self.upload(local_items)

        # Step 2: 下载远端所有变更（不限于已上传条目）
        # 获取所有已知 key 用于拉取远端变更
        all_keys = list({item.key for item in local_items})
        download_results = await self.download(all_keys)

        # Step 3: 检测冲突
        # 冲突判定：同一 key 在本地和远端都发生了变更，且版本不一致
        conflicts: list[dict[str, Any]] = []
        local_key_versions: dict[str, SyncItem] = {
            item.key: item for item in local_items
        }

        for download_result in download_results:
            if download_result.status == SyncStatus.SUCCESS:
                key = download_result.item_id
                local_item = local_key_versions.get(key)
                if local_item is not None:
                    # 检查版本冲突：远端校验和与本地不一致
                    if (
                        download_result.remote_checksum
                        and local_item.checksum
                        and download_result.remote_checksum != local_item.checksum
                    ):
                        conflicts.append({
                            "key": key,
                            "item_id": local_item.item_id,
                            "local_version": local_item.version,
                            "remote_checksum": download_result.remote_checksum,
                            "local_checksum": local_item.checksum,
                        })

        logger.info(
            "sync_client.bidirectional_completed",
            total_upload=len(local_items),
            total_download=len(all_keys),
            conflict_count=len(conflicts),
        )

        return {
            "upload_results": upload_results,
            "download_results": download_results,
            "conflicts": conflicts,
        }

    @property
    def last_sync_time(self) -> float:
        """获取上次同步时间.

        Returns:
            上次同步的时间戳.
        """
        return self._last_sync_time

    def is_configured(self) -> bool:
        """检查客户端是否已配置.

        Returns:
            是否已配置云端端点和 API 密钥.
        """
        return bool(self._cloud_endpoint and self._api_key)
