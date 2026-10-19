"""Knowledge Graph for agent knowledge sharing.

Provides knowledge graph capabilities for agents:
- Share knowledge about data assets
- Track dependencies and relationships
- Query for best practices
- Collaborative learning
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from unistax.logging import get_logger

logger = get_logger(__name__)


class NodeType(Enum):
    """Types of nodes in knowledge graph."""

    DATASET = "dataset"
    PIPELINE = "pipeline"
    MODEL = "model"
    AGENT = "agent"
    TASK = "task"
    INSIGHT = "insight"
    BEST_PRACTICE = "best_practice"
    ISSUE = "issue"


class RelationType(Enum):
    """Types of relationships in knowledge graph."""

    DEPENDS_ON = "depends_on"
    PRODUCES = "produces"
    CONSUMES = "consumes"
    TRAINED_BY = "trained_by"
    EXECUTED_BY = "executed_by"
    RELATED_TO = "related_to"
    SIMILAR_TO = "similar_to"
    LEARNED_FROM = "learned_from"


@dataclass
class KnowledgeNode:
    """Node in the knowledge graph."""

    id: str
    node_type: NodeType
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    created_by: str | None = None  # Agent ID


@dataclass
class KnowledgeEdge:
    """Edge in the knowledge graph."""

    source_id: str
    target_id: str
    relation_type: RelationType
    properties: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str | None = None  # Agent ID


class AgentKnowledgeGraph:
    """Knowledge graph for multi-agent knowledge sharing.

    Enables agents to:
    - Share knowledge about data assets
    - Discover relationships and dependencies
    - Learn from each other's experiences
    - Query for relevant information

    Examples:
        >>> kg = AgentKnowledgeGraph()
        >>>
        >>> # Add knowledge about a dataset
        >>> dataset_node = kg.add_node(
        ...     node_id="customers",
        ...     node_type=NodeType.DATASET,
        ...     properties={"table": "dim_customers", "size_mb": 450},
        ...     agent_id="steward_001",
        ... )
        >>>
        >>> # Add relationship
        >>> kg.add_edge(
        ...     source_id="pipeline_etl",
        ...     target_id="customers",
        ...     relation_type=RelationType.PRODUCES,
        ...     agent_id="eng_001",
        ... )
        >>>
        >>> # Query for dependencies
        >>> deps = kg.get_dependencies("customers")
    """

    def __init__(self) -> None:
        """Initialize knowledge graph."""
        self.nodes: dict[str, KnowledgeNode] = {}
        self.edges: list[KnowledgeEdge] = []

        # Indices for fast lookup
        self._edges_by_source: dict[str, list[KnowledgeEdge]] = {}
        self._edges_by_target: dict[str, list[KnowledgeEdge]] = {}

        logger.info("Initialized agent knowledge graph")

    def add_node(
        self,
        node_id: str,
        node_type: NodeType,
        properties: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> KnowledgeNode:
        """Add node to knowledge graph.

        Args:
            node_id: Unique node identifier
            node_type: Type of node
            properties: Node properties
            agent_id: Agent adding the node

        Returns:
            Created node
        """
        if node_id in self.nodes:
            # Update existing node
            node = self.nodes[node_id]
            if properties:
                node.properties.update(properties)
            node.updated_at = datetime.now()
            logger.debug(f"Updated knowledge node: {node_id}")
        else:
            # Create new node
            node = KnowledgeNode(
                id=node_id,
                node_type=node_type,
                properties=properties or {},
                created_by=agent_id,
            )
            self.nodes[node_id] = node
            logger.info(
                f"Added knowledge node: {node_id} (type={node_type.value}, " f"agent={agent_id})"
            )

        return node

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        """Get node by ID.

        Args:
            node_id: Node identifier

        Returns:
            Node or None if not found
        """
        return self.nodes.get(node_id)

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        properties: dict[str, Any] | None = None,
        weight: float = 1.0,
        agent_id: str | None = None,
    ) -> KnowledgeEdge:
        """Add edge to knowledge graph.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            relation_type: Type of relationship
            properties: Edge properties
            weight: Edge weight
            agent_id: Agent adding the edge

        Returns:
            Created edge
        """
        edge = KnowledgeEdge(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=properties or {},
            weight=weight,
            created_by=agent_id,
        )

        self.edges.append(edge)

        # Update indices
        if source_id not in self._edges_by_source:
            self._edges_by_source[source_id] = []
        self._edges_by_source[source_id].append(edge)

        if target_id not in self._edges_by_target:
            self._edges_by_target[target_id] = []
        self._edges_by_target[target_id].append(edge)

        logger.info(
            f"Added knowledge edge: {source_id} --[{relation_type.value}]--> {target_id} "
            f"(agent={agent_id})"
        )

        return edge

    def get_outgoing_edges(
        self,
        node_id: str,
        relation_type: RelationType | None = None,
    ) -> list[KnowledgeEdge]:
        """Get edges going out from node.

        Args:
            node_id: Source node ID
            relation_type: Optional filter by relation type

        Returns:
            List of outgoing edges
        """
        edges = self._edges_by_source.get(node_id, [])

        if relation_type:
            edges = [e for e in edges if e.relation_type == relation_type]

        return edges

    def get_incoming_edges(
        self,
        node_id: str,
        relation_type: RelationType | None = None,
    ) -> list[KnowledgeEdge]:
        """Get edges coming into node.

        Args:
            node_id: Target node ID
            relation_type: Optional filter by relation type

        Returns:
            List of incoming edges
        """
        edges = self._edges_by_target.get(node_id, [])

        if relation_type:
            edges = [e for e in edges if e.relation_type == relation_type]

        return edges

    def get_dependencies(self, node_id: str, max_depth: int = 3) -> list[str]:
        """Get all dependencies of a node (transitive).

        Args:
            node_id: Node to find dependencies for
            max_depth: Maximum depth to traverse

        Returns:
            List of node IDs this node depends on
        """
        dependencies = set()
        visited = set()

        def traverse(current_id: str, depth: int):
            if depth > max_depth or current_id in visited:
                return

            visited.add(current_id)

            # Find DEPENDS_ON edges
            edges = self.get_outgoing_edges(current_id, RelationType.DEPENDS_ON)

            for edge in edges:
                dependencies.add(edge.target_id)
                traverse(edge.target_id, depth + 1)

        traverse(node_id, 0)
        return list(dependencies)

    def get_consumers(self, node_id: str) -> list[str]:
        """Get all nodes that consume this node.

        Args:
            node_id: Node to find consumers for

        Returns:
            List of consumer node IDs
        """
        edges = self.get_incoming_edges(node_id, RelationType.CONSUMES)
        return [e.source_id for e in edges]

    def get_producers(self, node_id: str) -> list[str]:
        """Get all nodes that produce this node.

        Args:
            node_id: Node to find producers for

        Returns:
            List of producer node IDs
        """
        edges = self.get_incoming_edges(node_id, RelationType.PRODUCES)
        return [e.source_id for e in edges]

    def find_similar_nodes(
        self,
        node_id: str,
        node_type: NodeType | None = None,
    ) -> list[str]:
        """Find nodes similar to given node.

        Args:
            node_id: Reference node ID
            node_type: Optional filter by node type

        Returns:
            List of similar node IDs
        """
        # Find explicit SIMILAR_TO relationships
        edges = self.get_outgoing_edges(node_id, RelationType.SIMILAR_TO)
        similar = [e.target_id for e in edges]

        # Filter by type if specified
        if node_type:
            similar = [
                nid
                for nid in similar
                if self.nodes.get(nid) and self.nodes[nid].node_type == node_type
            ]

        return similar

    def query_by_type(self, node_type: NodeType) -> list[KnowledgeNode]:
        """Get all nodes of a specific type.

        Args:
            node_type: Node type to filter by

        Returns:
            List of nodes
        """
        return [node for node in self.nodes.values() if node.node_type == node_type]

    def query_by_properties(
        self,
        property_filters: dict[str, Any],
        node_type: NodeType | None = None,
    ) -> list[KnowledgeNode]:
        """Query nodes by properties.

        Args:
            property_filters: Dictionary of property conditions
            node_type: Optional filter by node type

        Returns:
            List of matching nodes
        """
        results = []

        for node in self.nodes.values():
            # Type filter
            if node_type and node.node_type != node_type:
                continue

            # Property filters
            match = True
            for key, value in property_filters.items():
                if key not in node.properties or node.properties[key] != value:
                    match = False
                    break

            if match:
                results.append(node)

        return results

    def get_best_practices(
        self,
        topic: str | None = None,
    ) -> list[KnowledgeNode]:
        """Get best practices from knowledge graph.

        Args:
            topic: Optional topic filter

        Returns:
            List of best practice nodes
        """
        practices = self.query_by_type(NodeType.BEST_PRACTICE)

        if topic:
            practices = [p for p in practices if p.properties.get("topic") == topic]

        return practices

    def add_best_practice(
        self,
        practice_id: str,
        topic: str,
        description: str,
        agent_id: str,
        related_nodes: list[str] | None = None,
    ) -> KnowledgeNode:
        """Add a best practice to knowledge graph.

        Args:
            practice_id: Unique identifier
            topic: Practice topic
            description: Practice description
            agent_id: Agent sharing the practice
            related_nodes: Related node IDs

        Returns:
            Created best practice node
        """
        node = self.add_node(
            node_id=practice_id,
            node_type=NodeType.BEST_PRACTICE,
            properties={
                "topic": topic,
                "description": description,
            },
            agent_id=agent_id,
        )

        # Link to related nodes
        if related_nodes:
            for related_id in related_nodes:
                self.add_edge(
                    source_id=practice_id,
                    target_id=related_id,
                    relation_type=RelationType.RELATED_TO,
                    agent_id=agent_id,
                )

        return node

    def record_issue(
        self,
        issue_id: str,
        description: str,
        severity: str,
        affected_nodes: list[str],
        agent_id: str,
    ) -> KnowledgeNode:
        """Record an issue in knowledge graph.

        Args:
            issue_id: Unique identifier
            description: Issue description
            severity: Issue severity (low, medium, high, critical)
            affected_nodes: Node IDs affected by issue
            agent_id: Agent reporting the issue

        Returns:
            Created issue node
        """
        node = self.add_node(
            node_id=issue_id,
            node_type=NodeType.ISSUE,
            properties={
                "description": description,
                "severity": severity,
                "status": "open",
            },
            agent_id=agent_id,
        )

        # Link to affected nodes
        for affected_id in affected_nodes:
            self.add_edge(
                source_id=issue_id,
                target_id=affected_id,
                relation_type=RelationType.RELATED_TO,
                agent_id=agent_id,
            )

        logger.warning(
            f"Issue recorded: {description} (severity={severity}, "
            f"affected={len(affected_nodes)})"
        )

        return node

    def get_graph_statistics(self) -> dict[str, Any]:
        """Get knowledge graph statistics.

        Returns:
            Statistics dictionary
        """
        node_counts = {}
        for node_type in NodeType:
            count = len(self.query_by_type(node_type))
            if count > 0:
                node_counts[node_type.value] = count

        edge_counts = {}
        for relation_type in RelationType:
            count = len([e for e in self.edges if e.relation_type == relation_type])
            if count > 0:
                edge_counts[relation_type.value] = count

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "nodes_by_type": node_counts,
            "edges_by_type": edge_counts,
        }
