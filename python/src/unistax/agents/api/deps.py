"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request

from unistax.agents.api.runtime import AgentRuntime


def get_runtime(request: Request) -> AgentRuntime:
    runtime: AgentRuntime = request.app.state.runtime
    return runtime


Runtime = Annotated[AgentRuntime, Depends(get_runtime)]


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


Paging = Annotated[Pagination, Depends(Pagination)]
