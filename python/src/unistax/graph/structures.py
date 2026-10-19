"""Core graph data structures for service dependency analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class DependencyType(str, Enum):
    """Types of service dependencies."""

    API_CALL = "api_call"
    DATABASE = "database"
    MESSAGE_QUEUE = "message_queue"
    CACHE = "cache"
    STORAGE = "storage"
    EXTERNAL_SERVICE = "external_service"


class ServiceType(str, Enum):
    """Types of services in the dependency graph."""

    API = "api"
    DATABASE = "database"
    CACHE = "cache"
    QUEUE = "queue"
    STORAGE = "storage"
    EXTERNAL = "external"
    GATEWAY = "gateway"
    WORKER = "worker"


@dataclass
class ServiceNode:
    """Represents a service in the dependency graph."""

    __slots__ = (
        "id",
        "name",
        "service_type",
        "endpoints",
        "metadata",
        "health_score",
        "created_at",
        "updated_at",
    )

    id: UUID
    name: str
    service_type: ServiceType
    endpoints: list[str] = field(default_factory=list[Any])
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    health_score: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        name: str,
        service_type: ServiceType,
        endpoints: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ServiceNode:
        """Create a new service node."""
        return cls(
            id=uuid4(),
            name=name,
            service_type=service_type,
            endpoints=endpoints or [],
            metadata=metadata or {},
        )

    def update_health(self, score: float) -> None:
        """Update the health score of the service."""
        if not 0.0 <= score <= 1.0:
            raise ValueError("Health score must be between 0.0 and 1.0")
        self.health_score = score
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class WeightedEdge:
    """Represents a weighted edge in a graph."""

    __slots__ = ("source", "target", "weight")

    source: str
    target: str
    weight: float = 1.0

    def __hash__(self) -> int:
        """Make edge hashable."""
        return hash((self.source, self.target))


@dataclass
class DependencyEdge:
    """Represents a dependency between two services."""

    __slots__ = (
        "id",
        "source",
        "target",
        "dependency_type",
        "weight",
        "latency_p99",
        "error_rate",
        "request_rate",
        "metadata",
        "created_at",
        "updated_at",
    )

    id: UUID
    source: str  # Service name
    target: str  # Service name
    dependency_type: DependencyType
    weight: float = 1.0  # Normalized importance/frequency
    latency_p99: float | None = None  # Milliseconds
    error_rate: float = 0.0  # 0.0 to 1.0
    request_rate: float = 0.0  # Requests per second
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        source: str,
        target: str,
        dependency_type: DependencyType,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> DependencyEdge:
        """Create a new dependency edge."""
        return cls(
            id=uuid4(),
            source=source,
            target=target,
            dependency_type=dependency_type,
            weight=weight,
            metadata=metadata or {},
        )

    def update_metrics(
        self,
        latency_p99: float | None = None,
        error_rate: float | None = None,
        request_rate: float | None = None,
    ) -> None:
        """Update edge metrics."""
        if latency_p99 is not None:
            self.latency_p99 = latency_p99
        if error_rate is not None:
            if not 0.0 <= error_rate <= 1.0:
                raise ValueError("Error rate must be between 0.0 and 1.0")
            self.error_rate = error_rate
        if request_rate is not None:
            self.request_rate = request_rate
        self.updated_at = datetime.now(timezone.utc)


class DirectedGraph:
    """Efficient directed graph implementation using adjacency lists."""

    __slots__ = ("_adj_list", "_reverse_adj_list", "_nodes", "_edges")

    def __init__(self) -> None:
        """Initialize an empty directed graph."""
        self._adj_list: dict[str, set[str]] = {}
        self._reverse_adj_list: dict[str, set[str]] = {}
        self._nodes: set[str] = set()
        self._edges: set[WeightedEdge] = set()

    def add_node(self, node: str) -> None:
        """Add a node to the graph."""
        if node not in self._nodes:
            self._nodes.add(node)
            self._adj_list[node] = set()
            self._reverse_adj_list[node] = set()

    def add_edge(self, source: str, target: str, weight: float = 1.0) -> None:
        """Add a directed edge from source to target."""
        # Ensure nodes exist
        self.add_node(source)
        self.add_node(target)

        # Add edge
        self._adj_list[source].add(target)
        self._reverse_adj_list[target].add(source)
        self._edges.add(WeightedEdge(source, target, weight))

    def remove_edge(self, source: str, target: str) -> None:
        """Remove an edge from the graph."""
        if source in self._adj_list:
            self._adj_list[source].discard(target)
        if target in self._reverse_adj_list:
            self._reverse_adj_list[target].discard(source)
        self._edges.discard(WeightedEdge(source, target, 0.0))

    def has_edge(self, source: str, target: str) -> bool:
        """Check if an edge exists."""
        return source in self._adj_list and target in self._adj_list[source]

    def get_successors(self, node: str) -> set[str]:
        """Get all nodes that this node points to (outgoing edges)."""
        return self._adj_list.get(node, set()).copy()

    def get_predecessors(self, node: str) -> set[str]:
        """Get all nodes that point to this node (incoming edges)."""
        return self._reverse_adj_list.get(node, set()).copy()

    def get_nodes(self) -> set[str]:
        """Get all nodes in the graph."""
        return self._nodes.copy()

    def get_edges(self) -> set[WeightedEdge]:
        """Get all edges in the graph."""
        return self._edges.copy()

    def node_count(self) -> int:
        """Get the number of nodes."""
        return len(self._nodes)

    def edge_count(self) -> int:
        """Get the number of edges."""
        return len(self._edges)

    def in_degree(self, node: str) -> int:
        """Get the in-degree of a node (number of incoming edges)."""
        return len(self._reverse_adj_list.get(node, set()))

    def out_degree(self, node: str) -> int:
        """Get the out-degree of a node (number of outgoing edges)."""
        return len(self._adj_list.get(node, set()))

    def subgraph(self, nodes: set[str]) -> DirectedGraph:
        """Create a subgraph containing only the specified nodes."""
        sub = DirectedGraph()
        for node in nodes:
            if node in self._nodes:
                sub.add_node(node)

        for edge in self._edges:
            if edge.source in nodes and edge.target in nodes:
                sub.add_edge(edge.source, edge.target, edge.weight)

        return sub


class ServiceDependencyGraph:
    """Domain-specific graph for service dependency analysis."""

    __slots__ = ("_graph", "_services", "_dependencies", "_metadata")

    def __init__(self) -> None:
        """Initialize an empty service dependency graph."""
        self._graph = DirectedGraph()
        self._services: dict[str, ServiceNode] = {}
        self._dependencies: dict[tuple[str, str], DependencyEdge] = {}
        self._metadata: dict[str, Any] = {}

    def add_service(self, service: ServiceNode) -> None:
        """Add a service to the graph."""
        self._services[service.name] = service
        self._graph.add_node(service.name)

    def add_dependency(self, dependency: DependencyEdge) -> None:
        """Add a dependency between services."""
        # Ensure services exist
        if dependency.source not in self._services:
            self.add_service(
                ServiceNode.create(
                    dependency.source,
                    ServiceType.API,  # Default type
                )
            )
        if dependency.target not in self._services:
            self.add_service(
                ServiceNode.create(
                    dependency.target,
                    ServiceType.API,  # Default type
                )
            )

        # Add dependency
        key = (dependency.source, dependency.target)
        self._dependencies[key] = dependency
        self._graph.add_edge(
            dependency.source,
            dependency.target,
            dependency.weight,
        )

    def get_service(self, name: str) -> ServiceNode | None:
        """Get a service by name."""
        return self._services.get(name)

    def get_dependency(self, source: str, target: str) -> DependencyEdge | None:
        """Get a dependency edge."""
        return self._dependencies.get((source, target))

    def get_all_services(self) -> list[ServiceNode]:
        """Get all services."""
        return list(self._services.values())

    def get_all_dependencies(self) -> list[DependencyEdge]:
        """Get all dependencies."""
        return list(self._dependencies.values())

    def get_downstream_services(self, service_name: str) -> set[str]:
        """Get all services that depend on this service (downstream)."""
        return self._graph.get_successors(service_name)

    def get_upstream_services(self, service_name: str) -> set[str]:
        """Get all services this service depends on (upstream)."""
        return self._graph.get_predecessors(service_name)

    def get_service_count(self) -> int:
        """Get the number of services."""
        return len(self._services)

    def get_dependency_count(self) -> int:
        """Get the number of dependencies."""
        return len(self._dependencies)

    def get_underlying_graph(self) -> DirectedGraph:
        """Get the underlying directed graph."""
        return self._graph

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata for the graph."""
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata from the graph."""
        return self._metadata.get(key, default)
