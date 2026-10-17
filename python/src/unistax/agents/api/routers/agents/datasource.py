"""Inspect the configured data source (never exposes the connection string)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from unistax.agents.api.auth import require_operator
from unistax.agents.api.deps import Runtime
from unistax.agents.connectors.errors import DataSourceError, DataSourceUnsafe
from unistax.api import APIResponse

router = APIRouter(
    prefix="/datasource", tags=["Data Source"], dependencies=[Depends(require_operator)]
)


@router.get(
    "",
    response_model=APIResponse[dict[str, Any]],
    summary="Data source configuration and health",
    description="Connects (if needed) and reports whether the configured role is safe to use. "
    "The connection string is never returned.",
)
async def get_datasource(runtime: Runtime) -> APIResponse[dict[str, Any]]:
    ds = runtime.datasource
    if ds is None:
        return APIResponse(
            data={
                "configured": False,
                "detail": (
                    "No data source is configured; data-aware tasks return simulated results."
                ),
            }
        )

    config = ds.config
    info: dict[str, Any] = {
        "configured": True,
        "kind": ds.kind,
        "name": config.name,
        "label": ds.label,
        "schemas": list(config.schemas),
        "table_patterns": list(config.table_patterns),
        "limits": {
            "catalog_timeout_ms": config.catalog_timeout_ms,
            "scan_timeout_ms": config.scan_timeout_ms,
            "sample_rows": config.sample_rows,
            "max_scan_rows": config.max_scan_rows,
            "max_tables": config.max_tables,
        },
    }
    try:
        report = await ds.verify()
    except DataSourceUnsafe as exc:
        info.update(status="unsafe", detail=str(exc))
    except DataSourceError as exc:
        info.update(status="unavailable", detail=str(exc))
    else:
        info.update(
            status="ok",
            role=report.role,
            server_version=report.server_version,
            warnings=list(report.warnings),
        )
    return APIResponse(data=info)
