from __future__ import annotations

"""数据分析技能."""

from typing import Any

import pandas as pd
import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()

MAX_ROWS = 100_000


class DataAnalysisSkill(ISkill):
    """数据分析技能，支持 CSV/JSON 解析、统计描述、相关性、过滤."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.data_analysis",
            name="数据分析",
            version="1.0.0",
            description="解析 CSV/JSON、统计描述、相关性分析、数据过滤",
            author="yunxi",
            tags=["data", "analysis"],
            capabilities=["parse_csv", "parse_json", "describe", "correlation", "filter"],
            permissions=["read_file"],
            entrypoint="DataAnalysisSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "parse_csv":
                data = self._parse_csv(params)
            elif action == "parse_json":
                data = self._parse_json(params)
            elif action == "describe":
                data = self._describe(params)
            elif action == "correlation":
                data = self._correlation(params)
            elif action == "filter":
                data = self._filter(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)
            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    def _parse_csv(self, params: dict[str, Any]) -> dict[str, Any]:
        content = params.get("content")
        file_path = params.get("file_path")
        if content is not None:
            from io import StringIO
            df = pd.read_csv(StringIO(content))
        elif file_path is not None:
            df = pd.read_csv(file_path)
        else:
            raise ValueError("Either content or file_path must be provided")
        if len(df) > MAX_ROWS:
            raise ValueError(f"Data exceeds {MAX_ROWS} rows, please process in batches")
        return {
            "columns": df.columns.tolist(),
            "shape": df.shape,
            "preview": df.head(10).to_dict(orient="records"),
        }

    def _parse_json(self, params: dict[str, Any]) -> dict[str, Any]:
        import json

        content = params.get("content", "")
        data = json.loads(content)
        return {"data": data}

    def _describe(self, params: dict[str, Any]) -> dict[str, Any]:
        data = params.get("data", [])
        column = params.get("column", "")
        df = pd.DataFrame(data)
        if column not in df.columns:
            raise ValueError(f"Column {column} not found")
        desc = df[column].describe()
        return {
            "count": int(desc.get("count", 0)),
            "mean": float(desc.get("mean", 0)),
            "std": float(desc.get("std", 0)),
            "min": float(desc.get("min", 0)),
            "25%": float(desc.get("25%", 0)),
            "50%": float(desc.get("50%", 0)),
            "75%": float(desc.get("75%", 0)),
            "max": float(desc.get("max", 0)),
        }

    def _correlation(self, params: dict[str, Any]) -> dict[str, Any]:
        data = params.get("data", [])
        columns = params.get("columns", [])
        df = pd.DataFrame(data)
        corr = df[columns].corr()
        return {"correlation": corr.to_dict()}

    def _filter(self, params: dict[str, Any]) -> dict[str, Any]:
        data = params.get("data", [])
        condition = params.get("condition", {})
        df = pd.DataFrame(data)
        for col, val in condition.items():
            if col in df.columns:
                df = df[df[col] == val]
        return {"filtered": df.to_dict(orient="records"), "count": len(df)}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("data_analysis_error", action=request.action, error=error, trace_id=request.trace_id)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict[str, Any]) -> None:
        self._config.update(config)
