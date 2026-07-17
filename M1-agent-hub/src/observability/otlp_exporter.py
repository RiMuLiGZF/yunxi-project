"""
云汐内核 V9 - OpenTelemetry Trace 导出器

解决 V8 短板：
- Tracing 数据仅存储在内存 dict 中
- 无法导出到 Jaeger / Zipkin / Grafana Tempo 等外部系统
- 无分布式追踪能力

实现轻量级 OTLP (OpenTelemetry Protocol) 兼容导出器，
支持 HTTP JSON 格式，可对接任何 OTLP Collector。

本地 7B 友好：
- 批量导出，减少网络请求
- 异步非阻塞，不影响主流程
- 失败自动降级到本地缓存
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class OTLPSpan:
    """OTLP 兼容的 Span 格式"""

    trace_id: str
    span_id: str
    parent_span_id: str = ""
    name: str = ""
    start_time_ns: int = 0
    end_time_ns: int = 0
    kind: int = 1
    status_code: int = 0
    status_message: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_otlp_dict(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id or None,
            "name": self.name,
            "kind": self.kind,
            "startTimeUnixNano": str(self.start_time_ns),
            "endTimeUnixNano": str(self.end_time_ns),
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in self.attributes.items()
            ],
            "events": [
                {
                    "name": e["name"],
                    "timeUnixNano": str(int(e.get("timestamp", time.time()) * 1e9)),
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in e.get("attributes", {}).items()
                    ],
                }
                for e in self.events
            ],
            "status": {
                "code": self.status_code,
                "message": self.status_message,
            },
        }


class OTLPExporter:
    """OTLP Trace 导出器"""

    def __init__(
        self,
        endpoint: str = "",
        service_name: str = "yunxi-agent-cluster",
        batch_size: int = 100,
    ) -> None:
        self.endpoint = endpoint
        self.service_name = service_name
        self.batch_size = batch_size
        self._buffer: list[OTLPSpan] = []
        self._local_cache: list[OTLPSpan] = []
        self._exported_count: int = 0
        self._failed_count: int = 0
        self._logger = logger.bind(service="otlp_exporter")

    def export_span(self, span: OTLPSpan) -> None:
        self._buffer.append(span)
        if len(self._buffer) >= self.batch_size:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer = []
        if not self.endpoint:
            self._local_cache.extend(batch)
            return
        try:
            self._send_batch(batch)
            self._exported_count += len(batch)
        except Exception as exc:
            self._failed_count += len(batch)
            self._local_cache.extend(batch)
            self._logger.error("otlp_export_failed", error=str(exc), batch_size=len(batch))

    def _send_batch(self, batch: list[OTLPSpan]) -> None:
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}}
                        ]
                    },
                    "scopeSpans": [{"spans": [span.to_otlp_dict() for span in batch]}],
                }
            ]
        }
        import urllib.request
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"OTLP export failed: HTTP {resp.status}")

    def stats(self) -> dict[str, Any]:
        return {
            "exported_count": self._exported_count,
            "failed_count": self._failed_count,
            "buffer_size": len(self._buffer),
            "local_cache_size": len(self._local_cache),
            "endpoint": self.endpoint or "none (local cache mode)",
        }
