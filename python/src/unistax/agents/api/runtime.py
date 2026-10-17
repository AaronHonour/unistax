"""Application runtime: owns the agent system and its persistence."""

from __future__ import annotations

import time

from unistax.agents.api import migrate
from unistax.agents.api.auth import Authenticator
from unistax.agents.api.db import Database, Store
from unistax.agents.api.limits import RateLimits
from unistax.agents.api.services.agents import build_agent
from unistax.agents.api.services.events import EventHub
from unistax.agents.api.services.executor import TaskExecutor
from unistax.agents.api.services.workflows import WorkflowRunner
from unistax.agents.api.settings import AgentAPISettings
from unistax.agents.base import Agent
from unistax.agents.intelligence.knowledge_graph import (
    AgentKnowledgeGraph,
    KnowledgeNode,
    NodeType,
    RelationType,
)
from unistax.agents.orchestrator import AgentOrchestrator
from unistax.agents.registry import AgentRegistry
from unistax.agents.team import Team, TeamType
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

logger = get_logger(__name__)

RESTART_REASON = "Interrupted by server restart"


class AgentRuntime:
    """Everything the API needs, created once per application."""

    def __init__(
        self,
        settings: AgentAPISettings,
        *,
        event_bus: EventBus | None = None,
        metrics_manager: MetricsManager | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.authenticator = Authenticator(settings) if settings.auth_enabled else None
        self.limits = RateLimits(settings)

        self.event_bus = event_bus or EventBus()
        self.metrics_manager = metrics_manager or MetricsManager()
        self.registry = AgentRegistry(
            event_bus=self.event_bus, metrics_manager=self.metrics_manager
        )
        self.knowledge_graph = AgentKnowledgeGraph()
        self.orchestrator = AgentOrchestrator(self.registry)

        self.db = Database(settings.database_url)
        self.store = Store(self.db)
        self.executor = TaskExecutor(self.registry, self.store, settings)
        self.workflows = WorkflowRunner(self.registry, self.orchestrator, self.store)
        self.hub = EventHub(self.event_bus, settings.ws_max_connections, settings.ws_queue_size)

        self.started_at = time.time()
        self.ready = False

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self.settings.auto_migrate:
            await migrate.upgrade(self.db)
        await migrate.ensure_current(self.db)

        if self.settings.restore_on_start:
            await self._restore_teams()
            await self._restore_agents()
            await self._restore_knowledge()

        failed_tasks = await self.store.fail_interrupted_tasks(RESTART_REASON)
        failed_workflows = await self.store.fail_interrupted_workflows(RESTART_REASON)
        if failed_tasks or failed_workflows:
            logger.warning(
                "Marked %d task(s) and %d workflow(s) as failed after restart",
                failed_tasks,
                failed_workflows,
            )

        self.hub.attach()
        self.ready = True
        logger.info(
            "Agent runtime started: %d agents, %d teams",
            len(self.registry.agents),
            len(self.registry.team_hierarchy.teams),
        )

    async def stop(self) -> None:
        self.ready = False
        timeout = self.settings.shutdown_timeout
        await self.workflows.shutdown(timeout)
        await self.executor.shutdown(timeout)
        self.hub.detach()
        for agent in list(self.registry.agents.values()):
            agent.unsubscribe_from_events()
        await self.db.dispose()
        logger.info("Agent runtime stopped")

    # -- persistence helpers -------------------------------------------------
    async def save_agent(self, agent: Agent) -> None:
        await self.store.save_agent(
            agent_id=agent.agent_id,
            persona=agent.persona,
            team_id=agent.team_id,
            skills={name: skill.proficiency for name, skill in agent.skills.items()},
            max_concurrent_tasks=agent.max_concurrent_tasks,
        )

    async def save_team(self, team: Team) -> None:
        await self.store.save_team(
            id=team.id,
            name=team.name,
            team_type=team.team_type.value,
            parent_team_id=team.parent_team_id,
            leader_id=team.leader_id,
        )

    # -- restore ---------------------------------------------------------------
    async def _restore_teams(self) -> None:
        pending = {r.id: r for r in await self.store.load_teams()}
        while pending:
            progressed = False
            for team_id, record in list(pending.items()):
                if record.parent_team_id and record.parent_team_id in pending:
                    continue  # parent not restored yet
                team = Team(
                    id=record.id,
                    name=record.name,
                    team_type=TeamType(record.team_type),
                    leader_id=record.leader_id,
                    parent_team_id=(
                        record.parent_team_id
                        if record.parent_team_id in self.registry.team_hierarchy.teams
                        else None
                    ),
                    created_at=record.created_at,
                )
                self.registry.add_team(team)
                del pending[team_id]
                progressed = True
            if not progressed:
                logger.error("Skipping teams with unresolvable parents: %s", sorted(pending))
                break

    async def _restore_agents(self) -> None:
        hierarchy = self.registry.team_hierarchy
        for record in await self.store.load_agents():
            team_id = record.team_id if record.team_id in hierarchy.teams else None
            if record.team_id and team_id is None:
                logger.warning(
                    "Agent %s references missing team %s", record.agent_id, record.team_id
                )
            try:
                agent = build_agent(
                    agent_id=record.agent_id,
                    persona=record.persona,
                    event_bus=self.event_bus,
                    metrics_manager=self.metrics_manager,
                    team_id=team_id,
                    skills=record.skills or None,
                    max_concurrent_tasks=record.max_concurrent_tasks,
                )
            except Exception:
                logger.error("Could not restore agent %s", record.agent_id, exc_info=True)
                continue
            self.registry.register(agent)

    async def _restore_knowledge(self) -> None:
        nodes, edges = await self.store.load_knowledge()
        kg = self.knowledge_graph
        for node_record in nodes:
            kg.nodes[node_record.id] = KnowledgeNode(
                id=node_record.id,
                node_type=NodeType(node_record.node_type),
                properties=dict(node_record.properties or {}),
                created_by=node_record.created_by,
                created_at=node_record.created_at,
                updated_at=node_record.updated_at,
            )
        for edge_record in edges:
            edge = kg.add_edge(
                source_id=edge_record.source_id,
                target_id=edge_record.target_id,
                relation_type=RelationType(edge_record.relation_type),
                properties=dict(edge_record.properties or {}),
                weight=edge_record.weight,
                agent_id=edge_record.created_by,
            )
            edge.created_at = edge_record.created_at
