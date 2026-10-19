"""Status of the language-model backend (never exposes prompts, outputs or credentials)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from unistax.agents.api.auth import require_operator
from unistax.agents.api.deps import Runtime
from unistax.api import APIResponse

router = APIRouter(prefix="/llm", tags=["Language Model"], dependencies=[Depends(require_operator)])


@router.get(
    "",
    response_model=APIResponse[dict[str, Any]],
    summary="Model backend status, usage and limits",
)
async def llm_status(runtime: Runtime) -> APIResponse[dict[str, Any]]:
    gateway = runtime.llm
    if gateway is None:
        return APIResponse(
            data={
                "configured": False,
                "detail": "No language-model backend is configured; swarms are unavailable.",
            }
        )
    settings = runtime.settings
    report = runtime.llm_report
    return APIResponse(
        data={
            "configured": True,
            "backend": gateway.backend.name,
            "cli_version": report.version if report else None,
            "paused": gateway.paused_for > 0,
            "gateway": gateway.stats(),
            "swarms": {
                "active": runtime.swarms.running_count if runtime.swarms else 0,
                "max_active": settings.swarm_max_active,
                "max_subtasks": settings.swarm_max_subtasks,
                "max_calls_per_swarm": settings.swarm_max_calls,
            },
            "notice": (
                "Calls use the signed-in Claude plan of whoever runs this service. Plan usage "
                "limits are shared with that person's interactive use."
            ),
        }
    )
