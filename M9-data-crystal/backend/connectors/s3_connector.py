"""
云汐 M9 数据水晶 - S3 兼容存储连接器

P3 优化：数据采集管道 + 连接器生态
S3 兼容存储连接器，支持对象列表、文件读写、前缀过滤
"""

from __future__ import annotations

import io
import json
import logging
from typing import Iterator, List, Dict, Any, Optional
from pathlib import Path

from .base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
)

logger = logging.getLogger(__name__)


@ConnectorRegistry.register
class S3Connector(BaseConnector):
    """
    S3 兼容存储连接器

    特性：
    - 列出对象（支持前缀过滤）
    - 读取文件
    - 上传文件
    - 批量操作
    - 兼容 AWS S3、MinIO、阿里云 OSS 等

    依赖：boto3
    """

    meta = ConnectorMeta(
        name="s3",
        connector_type=ConnectorType.CLOUD,
        description="S3 兼容存储连接器，支持对象列表、文件读写、前缀过滤",
        version="1.0.0",
        supported_operations=["read", "write", "batch_read", "batch_write", "list_tables", "schema"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._s3_client = None
        self._bucket: str = ""
        self._endpoint_url: str = ""
        self._region: str = ""

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        连接 S3 兼容存储

        config 参数：
        - access_key: Access Key ID
        - secret_key: Secret Access Key
        - bucket: 存储桶名称
        - endpoint_url: S3 端点 URL（可选，用于兼容 MinIO 等）
        - region: 区域（默认 us-east-1）
        - use_ssl: 是否使用 SSL（默认 True）
        """
        if config:
            self._config.update(config)

        self._status = ConnectionStatus.CONNECTING
        try:
            try:
                import boto3
                from botocore.client import Config
            except ImportError:
                self._status = ConnectionStatus.ERROR
                self._last_error = "boto3 未安装，请执行 pip install boto3"
                logger.warning(self._last_error)
                return False

            access_key = self._config.get("access_key", "")
            secret_key = self._config.get("secret_key", "")
            self._bucket = self._config.get("bucket", "")
            self._endpoint_url = self._config.get("endpoint_url", "")
            self._region = self._config.get("region", "us-east-1")
            use_ssl = self._config.get("use_ssl", True)

            if not self._bucket:
                raise ValueError("必须指定 bucket")

            # 构建 S3 客户端
            s3_config = Config(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=30,
            )

            client_kwargs = {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "region_name": self._region,
                "use_ssl": use_ssl,
                "config": s3_config,
            }

            if self._endpoint_url:
                client_kwargs["endpoint_url"] = self._endpoint_url

            self._s3_client = boto3.client("s3", **client_kwargs)

            # 验证连接（检查桶是否存在）
            self._s3_client.head_bucket(Bucket=self._bucket)

            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"S3 连接成功: bucket={self._bucket}")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"S3 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开 S3 连接"""
        try:
            if self._s3_client:
                # boto3 客户端不需要显式关闭
                self._s3_client = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("S3 连接已关闭")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._record_error()
            return False

    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> List[Dict[str, Any]]:
        """
        列出对象

        Args:
            prefix: 前缀过滤
            max_keys: 最大返回数量

        Returns:
            对象列表，每个对象包含 key, size, last_modified 等
        """
        self._ensure_connected()
        try:
            objects = []
            continuation_token = None

            while True:
                list_kwargs = {
                    "Bucket": self._bucket,
                    "Prefix": prefix,
                    "MaxKeys": min(max_keys - len(objects), 1000),
                }
                if continuation_token:
                    list_kwargs["ContinuationToken"] = continuation_token

                response = self._s3_client.list_objects_v2(**list_kwargs)

                for obj in response.get("Contents", []):
                    objects.append({
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                        "etag": obj.get("ETag", "").strip('"'),
                        "storage_class": obj.get("StorageClass", "STANDARD"),
                    })

                if len(objects) >= max_keys:
                    break

                if not response.get("IsTruncated"):
                    break

                continuation_token = response.get("NextContinuationToken")
                if not continuation_token:
                    break

            return objects[:max_keys]

        except Exception as e:
            self._record_error()
            logger.error(f"S3 list_objects 失败: {e}")
            raise

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        读取 S3 对象内容

        query 参数：
        - key: 对象键（文件名）
        - format: 数据格式（json / csv / text / raw，默认根据扩展名判断）
        - prefix: 前缀（批量读取匹配的对象）
        - encoding: 文本编码（默认 utf-8）
        """
        self._ensure_connected()
        query = query or {}

        try:
            key = query.get("key", "")
            prefix = query.get("prefix", "")
            data_format = query.get("format", "auto")
            encoding = query.get("encoding", "utf-8")

            # 确定要读取的对象列表
            if prefix:
                objects = self.list_objects(prefix=prefix, max_keys=100)
                keys = [obj["key"] for obj in objects]
            elif key:
                keys = [key]
            else:
                raise ValueError("query 必须包含 key 或 prefix 参数")

            total_count = 0

            for obj_key in keys:
                # 下载对象
                response = self._s3_client.get_object(Bucket=self._bucket, Key=obj_key)
                body = response["Body"].read()

                # 自动检测格式
                if data_format == "auto":
                    if obj_key.lower().endswith(".json"):
                        fmt = "json"
                    elif obj_key.lower().endswith(".jsonl"):
                        fmt = "jsonl"
                    elif obj_key.lower().endswith(".csv"):
                        fmt = "csv"
                    else:
                        fmt = "text"
                else:
                    fmt = data_format

                # 解析数据
                if fmt == "json":
                    data = json.loads(body.decode(encoding))
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                item["_source_key"] = obj_key
                                yield item
                                total_count += 1
                            else:
                                yield {"value": item, "_source_key": obj_key}
                                total_count += 1
                    elif isinstance(data, dict):
                        data["_source_key"] = obj_key
                        yield data
                        total_count += 1

                elif fmt == "jsonl":
                    for line in body.decode(encoding).splitlines():
                        line = line.strip()
                        if line:
                            record = json.loads(line)
                            if isinstance(record, dict):
                                record["_source_key"] = obj_key
                            else:
                                record = {"value": record, "_source_key": obj_key}
                            yield record
                            total_count += 1

                elif fmt == "csv":
                    import csv
                    reader = csv.DictReader(io.StringIO(body.decode(encoding)))
                    for row in reader:
                        row["_source_key"] = obj_key
                        yield dict(row)
                        total_count += 1

                else:
                    # text / raw
                    yield {
                        "key": obj_key,
                        "content": body.decode(encoding),
                        "size": len(body),
                        "content_type": response.get("ContentType", ""),
                    }
                    total_count += 1

            self._record_read(count=total_count, bytes_read=total_count * 100)

        except Exception as e:
            self._record_error()
            logger.error(f"S3 读取失败: {e}")
            raise

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取"""
        return super().read_batch(batch_size, query)

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        写入数据到 S3

        配置：
        - write_key: 写入的对象键
        - write_format: 写入格式（json / jsonl / csv / text，默认 json）
        - encoding: 编码（默认 utf-8）
        """
        self._ensure_connected()

        if not data:
            return 0

        try:
            write_key = self._config.get("write_key", "")
            if not write_key:
                raise ValueError("未指定 write_key")

            write_format = self._config.get("write_format", "json")
            encoding = self._config.get("encoding", "utf-8")

            # 序列化数据
            if write_format == "json":
                content = json.dumps(data, ensure_ascii=False, indent=2).encode(encoding)
            elif write_format == "jsonl":
                lines = [json.dumps(record, ensure_ascii=False) for record in data]
                content = "\n".join(lines).encode(encoding)
            elif write_format == "csv":
                import csv
                output = io.StringIO()
                if data:
                    writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
                    writer.writeheader()
                    writer.writerows(data)
                content = output.getvalue().encode(encoding)
            else:
                # text：拼接 content 字段
                content = "\n".join(
                    str(record.get("content", "")) for record in data
                ).encode(encoding)

            # 上传到 S3
            self._s3_client.put_object(
                Bucket=self._bucket,
                Key=write_key,
                Body=content,
                ContentType=self._get_content_type(write_format),
            )

            count = len(data)
            self._record_write(count=count, bytes_written=len(content))
            return count

        except Exception as e:
            self._record_error()
            logger.error(f"S3 写入失败: {e}")
            raise

    def _get_content_type(self, fmt: str) -> str:
        """获取内容类型"""
        types = {
            "json": "application/json",
            "jsonl": "application/x-ndjson",
            "csv": "text/csv",
            "text": "text/plain",
        }
        return types.get(fmt, "application/octet-stream")

    def list_tables(self) -> List[str]:
        """列出存储桶中的对象（作为"表"）"""
        try:
            objects = self.list_objects(max_keys=100)
            return [obj["key"] for obj in objects]
        except Exception as e:
            self._record_error()
            raise

    def get_schema(self, table: str) -> Dict[str, Any]:
        """获取对象信息（作为 schema）"""
        self._ensure_connected()
        try:
            response = self._s3_client.head_object(Bucket=self._bucket, Key=table)
            return {
                "table": table,
                "size": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", ""),
                "last_modified": response.get("LastModified", "").isoformat() if response.get("LastModified") else None,
                "etag": response.get("ETag", "").strip('"'),
                "fields": {},
            }
        except Exception as e:
            self._record_error()
            raise

    def upload_file(self, local_path: str, s3_key: str) -> bool:
        """上传本地文件到 S3"""
        self._ensure_connected()
        try:
            self._s3_client.upload_file(local_path, self._bucket, s3_key)
            return True
        except Exception as e:
            self._record_error()
            logger.error(f"S3 上传文件失败: {e}")
            raise

    def download_file(self, s3_key: str, local_path: str) -> bool:
        """从 S3 下载文件到本地"""
        self._ensure_connected()
        try:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            self._s3_client.download_file(self._bucket, s3_key, local_path)
            return True
        except Exception as e:
            self._record_error()
            logger.error(f"S3 下载文件失败: {e}")
            raise

    def _health_probe(self) -> None:
        """健康探针：检查桶是否可访问"""
        if self._s3_client:
            self._s3_client.head_bucket(Bucket=self._bucket)
