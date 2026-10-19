"""Knowledge graph endpoints."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status

from unistax.agents.api.auth import Principal, require_operator, require_viewer
from unistax.agents.api.deps import Paging, Runtime
from unistax.agents.api.presenters import edge_response, node_response
from unistax.agents.api.schemas import (
    AddEdgeRequest,
    AddNodeRequest,
    BestPracticeRequest,
    IssueRequest,
    KnowledgeEdgeResponse,
    KnowledgeNodeResponse,
    paginate,
)
from unistax.agents.intelligence.knowledge_graph import (
    KnowledgeNode,
    NodeType,
    RelationType,
)
from unistax.api import APIResponse, PaginatedResponse

router = APIRouter(prefix="/knowledge", tags=["Knowledge Graph"])

E = TypeVar("E", bound=Enum)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def _parse_enum(enum_cls: type[E], value: str, label: str) -> E:
    try:
        return enum_cls(value.lower())
    except ValueError:
        raise _unprocessable(
            f"Unknown {label} '{value}'; use one of {[e.value for e in enum_cls]}"
        ) from None


def _require_nodes(runtime: Runtime, ids: list[str]) -> None:
    missing = [i for i in ids if i not in runtime.knowledge_graph.nodes]
    if missing:
        raise _unprocessable(f"Unknown node(s): {missing}")


def _get_node(runtime: Runtime, node_id: str) -> KnowledgeNode:
    node = runtime.knowledge_graph.get_node(node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Node '{node_id}' not found")
    return node


@router.post(
    "/nodes",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[KnowledgeNodeResponse],
    summary="Add or update a node",
)
async def add_node(
    body: AddNodeRequest, runtime: Runtime, principal: Principal = Depends(require_operator)
) -> APIResponse[KnowledgeNodeResponse]:
    node_type = _parse_enum(NodeType, body.node_type, "node type")
    existing = runtime.knowledge_graph.get_node(body.node_id)
    if existing and existing.node_type != node_type:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Node '{body.node_id}' already exists with type '{existing.node_type.value}'",
        )
    node = runtime.knowledge_graph.add_node(
        body.node_id, node_type, body.properties, agent_id=principal.subject
    )
    await runtime.persist_knowledge([node], [])
    return APIResponse(data=node_response(node), message="Node saved")


@router.get(
    "/nodes",
    response_model=PaginatedResponse[KnowledgeNodeResponse],
    summary="List nodes",
    dependencies=[Depends(require_viewer)],
)
async def list_nodes(
    runtime: Runtime, paging: Paging, node_type: str | None = Query(None)
) -> PaginatedResponse[Any]:
    kg = runtime.knowledge_graph
    nodes = (
        kg.query_by_type(_parse_enum(NodeType, node_type, "node type"))
        if node_type
        else list(kg.nodes.values())
    )
    nodes.sort(key=lambda n: n.id)
    page = nodes[paging.offset : paging.offset + paging.page_size]
    return paginate(
        KnowledgeNodeResponse,
        [node_response(n) for n in page],
        paging.page,
        paging.page_size,
        len(nodes),
    )


@router.get(
    "/nodes/{node_id}",
    response_model=APIResponse[KnowledgeNodeResponse],
    summary="Get node",
    dependencies=[Depends(require_viewer)],
)
async def get_node(node_id: str, runtime: Runtime) -> APIResponse[KnowledgeNodeResponse]:
    return APIResponse(data=node_response(_get_node(runtime, node_id)))


@router.get(
    "/nodes/{node_id}/edges",
    response_model=APIResponse[list[KnowledgeEdgeResponse]],
    summary="Edges touching a node",
    dependencies=[Depends(require_viewer)],
)
async def node_edges(node_id: str, runtime: Runtime) -> APIResponse[list[KnowledgeEdgeResponse]]:
    _get_node(runtime, node_id)
    kg = runtime.knowledge_graph
    edges = [*kg.get_outgoing_edges(node_id), *kg.get_incoming_edges(node_id)]
    return APIResponse(data=[edge_response(e) for e in edges])


@router.get(
    "/nodes/{node_id}/dependencies",
    response_model=APIResponse[list[str]],
    summary="Transitive dependencies",
    dependencies=[Depends(require_viewer)],
)
async def dependencies(
    node_id: str, runtime: Runtime, max_depth: int = Query(3, ge=1, le=10)
) -> APIResponse[list[str]]:
    _get_node(runtime, node_id)
    return APIResponse(data=sorted(runtime.knowledge_graph.get_dependencies(node_id, max_depth)))


@router.get(
    "/nodes/{node_id}/consumers",
    response_model=APIResponse[list[str]],
    summary="Nodes consuming this node",
    dependencies=[Depends(require_viewer)],
)
async def consumers(node_id: str, runtime: Runtime) -> APIResponse[list[str]]:
    _get_node(runtime, node_id)
    return APIResponse(data=sorted(runtime.knowledge_graph.get_consumers(node_id)))


@router.get(
    "/nodes/{node_id}/producers",
    response_model=APIResponse[list[str]],
    summary="Nodes producing this node",
    dependencies=[Depends(require_viewer)],
)
async def producers(node_id: str, runtime: Runtime) -> APIResponse[list[str]]:
    _get_node(runtime, node_id)
    return APIResponse(data=sorted(runtime.knowledge_graph.get_producers(node_id)))


@router.post(
    "/edges",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[KnowledgeEdgeResponse],
    summary="Add an edge between two existing nodes",
)
async def add_edge(
    body: AddEdgeRequest, runtime: Runtime, principal: Principal = Depends(require_operator)
) -> APIResponse[KnowledgeEdgeResponse]:
    relation = _parse_enum(RelationType, body.relation_type, "relation type")
    _require_nodes(runtime, [body.source_id, body.target_id])
    edge = runtime.knowledge_graph.add_edge(
        body.source_id,
        body.target_id,
        relation,
        properties=body.properties,
        weight=body.weight,
        agent_id=principal.subject,
    )
    await runtime.persist_knowledge([], [edge])
    return APIResponse(data=edge_response(edge), message="Edge added")


@router.post(
    "/best-practices",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[KnowledgeNodeResponse],
    summary="Share a best practice",
)
async def add_best_practice(
    body: BestPracticeRequest, runtime: Runtime, principal: Principal = Depends(require_operator)
) -> APIResponse[KnowledgeNodeResponse]:
    _require_nodes(runtime, body.related_nodes)
    kg = runtime.knowledge_graph
    before = len(kg.edges)
    node = kg.add_best_practice(
        body.practice_id, body.topic, body.description, principal.subject, body.related_nodes
    )
    await runtime.persist_knowledge([node], [])
    await runtime.persist_knowledge([], kg.edges[before:])
    return APIResponse(data=node_response(node), message="Best practice saved")


@router.get(
    "/best-practices",
    response_model=APIResponse[list[KnowledgeNodeResponse]],
    summary="List best practices",
    dependencies=[Depends(require_viewer)],
)
async def best_practices(
    runtime: Runtime, topic: str | None = Query(None)
) -> APIResponse[list[KnowledgeNodeResponse]]:
    practices = runtime.knowledge_graph.get_best_practices(topic=topic)
    return APIResponse(data=[node_response(p) for p in sorted(practices, key=lambda n: n.id)])


@router.post(
    "/issues",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[KnowledgeNodeResponse],
    summary="Record an issue",
)
async def record_issue(
    body: IssueRequest, runtime: Runtime, principal: Principal = Depends(require_operator)
) -> APIResponse[KnowledgeNodeResponse]:
    _require_nodes(runtime, body.affected_nodes)
    kg = runtime.knowledge_graph
    before = len(kg.edges)
    node = kg.record_issue(
        body.issue_id, body.description, body.severity, body.affected_nodes, principal.subject
    )
    await runtime.persist_knowledge([node], [])
    await runtime.persist_knowledge([], kg.edges[before:])
    return APIResponse(data=node_response(node), message="Issue recorded")


@router.get(
    "/statistics",
    response_model=APIResponse[dict[str, Any]],
    summary="Graph statistics",
    dependencies=[Depends(require_viewer)],
)
async def statistics(runtime: Runtime) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=runtime.knowledge_graph.get_graph_statistics())
