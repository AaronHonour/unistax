"""Request/response schemas for the agent API."""

from unistax.agents.api.schemas.agents import (
    AgentResponse,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from unistax.agents.api.schemas.common import paginate
from unistax.agents.api.schemas.knowledge import (
    AddEdgeRequest,
    AddNodeRequest,
    BestPracticeRequest,
    IssueRequest,
    KnowledgeEdgeResponse,
    KnowledgeNodeResponse,
)
from unistax.agents.api.schemas.metrics import AgentMetricsResponse, SystemMetricsResponse
from unistax.agents.api.schemas.tasks import TaskRequest, TaskResponse
from unistax.agents.api.schemas.teams import CreateTeamRequest, TeamResponse, UpdateTeamRequest
from unistax.agents.api.schemas.workflows import (
    CreateWorkflowRequest,
    WorkflowResponse,
    WorkflowStatusResponse,
    WorkflowStepRequest,
    WorkflowStepResponse,
)

__all__ = [
    "AddEdgeRequest",
    "AddNodeRequest",
    "AgentMetricsResponse",
    "AgentResponse",
    "BestPracticeRequest",
    "CreateAgentRequest",
    "CreateTeamRequest",
    "CreateWorkflowRequest",
    "IssueRequest",
    "KnowledgeEdgeResponse",
    "KnowledgeNodeResponse",
    "SystemMetricsResponse",
    "TaskRequest",
    "TaskResponse",
    "TeamResponse",
    "UpdateAgentRequest",
    "UpdateTeamRequest",
    "WorkflowResponse",
    "WorkflowStatusResponse",
    "WorkflowStepRequest",
    "WorkflowStepResponse",
    "paginate",
]
