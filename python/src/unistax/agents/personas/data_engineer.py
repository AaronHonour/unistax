"""Data Engineer Agent Persona.

Specialized agent for data engineering tasks including:
- ETL pipeline development
- Data quality monitoring
- Schema management
- Performance optimization
- Infrastructure maintenance
"""

from typing import TYPE_CHECKING, Any, ClassVar

from unistax.agents.base import Agent, AgentState, Skill, Task
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

if TYPE_CHECKING:
    from unistax.agents.connectors.postgres import PostgresDataSource

logger = get_logger(__name__)


class DataEngineerAgent(Agent):
    """Data Engineer agent persona.

    Capabilities:
    - Build and maintain ETL pipelines
    - Monitor data quality
    - Optimize query performance
    - Manage data schemas
    - Proactively detect data issues
    - Collaborate on data architecture

    Examples:
        >>> # Create registry and shared infrastructure
        >>> from unistax.agents import AgentRegistry, Skill
        >>> from unistax.metrics import MetricsManager
        >>>
        >>> registry = AgentRegistry()
        >>>
        >>> # Create data engineer with skills
        >>> engineer = DataEngineerAgent(
        ...     agent_id="eng_001",
        ...     event_bus=registry.event_bus,
        ...     metrics_manager=registry.metrics_manager,
        ...     skills=[
        ...         Skill("sql", 0.95, "database"),
        ...         Skill("python", 0.90, "programming"),
        ...         Skill("etl", 0.90, "data_engineering"),
        ...         Skill("airflow", 0.85, "orchestration"),
        ...     ]
        ... )
        >>> registry.register(engineer)
    """

    #: Task types that inspect a real data source when one is attached.
    DATASOURCE_TASK_TYPES: ClassVar[frozenset[str]] = frozenset({"quality_check"})
    USES_DATASOURCE: ClassVar[bool] = True

    TASK_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "build_pipeline",
            "optimize_query",
            "quality_check",
            "schema_migration",
            "monitor_pipeline",
            "fix_data_issue",
        }
    )

    def __init__(
        self,
        agent_id: str,
        event_bus: EventBus | None = None,
        metrics_manager: MetricsManager | None = None,
        skills: list[Skill] | None = None,
        team_id: str | None = None,
        datasource: "PostgresDataSource | None" = None,
        **kwargs,
    ):
        """Initialize Data Engineer agent.

        Args:
            agent_id: Unique identifier for agent
            event_bus: Shared EventBus for communication
            metrics_manager: Shared MetricsManager for metrics
            skills: Custom skills (uses defaults if None)
            team_id: Team this agent belongs to
            datasource: Read-only PostgreSQL data source. With one, ``quality_check`` runs
                real, bounded checks; without one it returns a simulated result (marked
                ``"simulated"``). Other task types remain simulated.
            **kwargs: Additional Agent constructor arguments
        """
        # Default skills for Data Engineer
        default_skills = [
            Skill("sql", 0.90, "database"),
            Skill("python", 0.85, "programming"),
            Skill("etl", 0.90, "data_engineering"),
            Skill("data_quality", 0.85, "data_engineering"),
            Skill("schema_design", 0.80, "database"),
            Skill("performance_tuning", 0.75, "optimization"),
            Skill("airflow", 0.80, "orchestration"),
            Skill("spark", 0.70, "big_data"),
        ]

        super().__init__(
            agent_id=agent_id,
            persona="data_engineer",
            skills=skills or default_skills,
            event_bus=event_bus,
            metrics_manager=metrics_manager,
            team_id=team_id,
            **kwargs,
        )

        # Data Engineer specific attributes
        self.datasource = datasource
        self.pipelines_maintained: set[str] = set()
        self.monitored_tables: set[str] = set()
        self.quality_checks_run: int = 0

        logger.info(f"Data Engineer {agent_id} initialized")

    async def decide(self) -> str | None:
        """Decide what action to take next.

        Decision priority:
        1. Execute assigned tasks
        2. Proactive monitoring (if idle)
        3. Help requests from team members
        4. Data quality checks

        Returns:
            Action identifier or None
        """
        # Priority 1: Execute pending tasks
        if self.current_tasks:
            # Sort by priority (higher first)
            self.current_tasks.sort(key=lambda t: t.priority, reverse=True)
            next_task = self.current_tasks[0]
            return f"execute_task:{next_task.id}"

        # Priority 2: Proactive monitoring (if idle and enabled)
        if self.state == AgentState.IDLE and self.monitored_tables:
            return "proactive_monitor"

        # Priority 3: Check for collaboration opportunities
        # (handled by event subscriptions in base class)

        # Nothing to do
        return None

    async def execute_task(self, task: Task) -> Any:
        """Execute a data engineering task.

        Supports task types:
        - build_pipeline: Create ETL pipeline
        - optimize_query: Optimize database query
        - quality_check: Run data quality validation
        - schema_migration: Perform schema changes
        - monitor_pipeline: Monitor pipeline health
        - fix_data_issue: Fix data quality issue

        Args:
            task: Task to execute

        Returns:
            Task result

        Raises:
            ValueError: If task type is unknown
        """
        task_type = task.type
        context = task.context

        logger.info(f"{self.agent_id} executing {task_type}: {task.description}")

        if task_type == "build_pipeline":
            return await self._build_pipeline(context)

        elif task_type == "optimize_query":
            return await self._optimize_query(context)

        elif task_type == "quality_check":
            return await self._run_quality_check(context)

        elif task_type == "schema_migration":
            return await self._migrate_schema(context)

        elif task_type == "monitor_pipeline":
            return await self._monitor_pipeline(context)

        elif task_type == "fix_data_issue":
            return await self._fix_data_issue(context)

        else:
            raise ValueError(f"Unknown task type: {task_type}")

    # ========================================================================
    # Task execution methods
    # ========================================================================

    async def _build_pipeline(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build an ETL pipeline.

        Args:
            context: Pipeline specification

        Returns:
            Pipeline build result
        """
        pipeline_name = context.get("name", "unnamed_pipeline")
        source = context.get("source", {})
        target = context.get("target", {})

        logger.info(f"{self.agent_id} building pipeline: {pipeline_name}")

        # Simulate pipeline building
        # In real implementation, this would:
        # 1. Validate source/target connections
        # 2. Generate transformation logic
        # 3. Create DAG in Airflow
        # 4. Set up monitoring

        self.pipelines_maintained.add(pipeline_name)

        return {
            "status": "success",
            "pipeline_name": pipeline_name,
            "source": source,
            "target": target,
            "message": f"Pipeline {pipeline_name} built successfully",
        }

    async def _optimize_query(self, context: dict[str, Any]) -> dict[str, Any]:
        """Optimize a database query.

        Args:
            context: Query and optimization hints

        Returns:
            Optimization result
        """
        table = context.get("table", "")

        logger.info(f"{self.agent_id} optimizing query for table: {table}")

        # Simulate query optimization
        # In real implementation, this would:
        # 1. Analyze query execution plan
        # 2. Identify bottlenecks
        # 3. Suggest/apply indexes
        # 4. Rewrite query if needed

        return {
            "status": "success",
            "table": table,
            "improvements": [
                "Added index on column X",
                "Rewrote subquery as JOIN",
                "Reduced full table scans",
            ],
            "performance_gain": "45% faster execution",
        }

    async def _run_quality_check(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run data quality validation.

        Args:
            context: Quality check specification

        Returns:
            Quality check result
        """
        if self.datasource is not None:
            from unistax.agents.connectors import tasks

            outcome = await tasks.quality_check(self.datasource, context, self.knowledge_graph)
            self.quality_checks_run += 1
            result = dict(outcome.result)
            result["knowledge_graph"] = await self.record_knowledge(outcome.nodes, outcome.edges)
            return result

        table = context.get("table", "")
        checks = context.get("checks", [])

        logger.info(f"{self.agent_id} running quality checks on: {table}")

        self.quality_checks_run += 1

        # Simulate quality checks
        # In real implementation, this would:
        # 1. Check for NULL values
        # 2. Validate data types
        # 3. Check referential integrity
        # 4. Validate business rules

        return {
            "status": "success",
            "data_source": "simulated",
            "table": table,
            "checks_passed": len(checks),
            "checks_failed": 0,
            "issues": [],
        }

    async def _migrate_schema(self, context: dict[str, Any]) -> dict[str, Any]:
        """Perform schema migration.

        Args:
            context: Migration specification

        Returns:
            Migration result
        """
        table = context.get("table", "")
        changes = context.get("changes", [])

        logger.info(f"{self.agent_id} migrating schema for: {table}")

        # Simulate schema migration
        # In real implementation, this would:
        # 1. Generate migration SQL
        # 2. Backup existing data
        # 3. Apply migration
        # 4. Validate migration
        # 5. Update documentation

        return {
            "status": "success",
            "table": table,
            "changes_applied": changes,
            "message": f"Schema migration for {table} completed",
        }

    async def _monitor_pipeline(self, context: dict[str, Any]) -> dict[str, Any]:
        """Monitor pipeline health.

        Args:
            context: Pipeline monitoring spec

        Returns:
            Monitoring result
        """
        pipeline_name = context.get("pipeline", "")

        logger.info(f"{self.agent_id} monitoring pipeline: {pipeline_name}")

        # Simulate pipeline monitoring
        # In real implementation, this would:
        # 1. Check last run status
        # 2. Verify data freshness
        # 3. Check for failures
        # 4. Alert if issues found

        return {
            "status": "healthy",
            "pipeline": pipeline_name,
            "last_run": "2024-01-15 10:30:00",
            "success_rate": 0.98,
            "issues": [],
        }

    async def _fix_data_issue(self, context: dict[str, Any]) -> dict[str, Any]:
        """Fix a data quality issue.

        Args:
            context: Issue details and fix strategy

        Returns:
            Fix result
        """
        issue_type = context.get("issue_type", "")
        affected_records = context.get("affected_records", 0)

        logger.info(
            f"{self.agent_id} fixing data issue: {issue_type} " f"({affected_records} records)"
        )

        # Simulate issue fixing
        # In real implementation, this would:
        # 1. Analyze issue root cause
        # 2. Develop fix strategy
        # 3. Apply fix with rollback capability
        # 4. Verify fix
        # 5. Update monitoring

        return {
            "status": "success",
            "issue_type": issue_type,
            "records_fixed": affected_records,
            "message": f"Fixed {affected_records} records with {issue_type} issue",
        }

    # ========================================================================
    # Proactive behaviors
    # ========================================================================

    async def _proactive_monitor(self):
        """Proactively monitor data pipelines and quality.

        This runs when the agent is idle to detect issues before they're reported.
        """
        logger.info(f"{self.agent_id} performing proactive monitoring")

        # In real implementation, this would:
        # 1. Check pipeline run statuses
        # 2. Scan for data anomalies
        # 3. Verify data freshness
        # 4. Create tasks for issues found

        # For now, just log
        logger.debug(
            f"{self.agent_id} monitored {len(self.monitored_tables)} tables, "
            f"{len(self.pipelines_maintained)} pipelines"
        )

    def add_pipeline(self, pipeline_name: str):
        """Add a pipeline to monitor.

        Args:
            pipeline_name: Pipeline identifier
        """
        self.pipelines_maintained.add(pipeline_name)
        logger.info(f"{self.agent_id} now monitoring pipeline: {pipeline_name}")

    def add_table_monitor(self, table_name: str):
        """Add a table to quality monitoring.

        Args:
            table_name: Table identifier
        """
        self.monitored_tables.add(table_name)
        logger.info(f"{self.agent_id} now monitoring table: {table_name}")

    def get_engineer_stats(self) -> dict[str, Any]:
        """Get data engineer specific statistics.

        Returns:
            Statistics dictionary
        """
        base_metrics = self.get_metrics()

        return {
            **base_metrics,
            "pipelines_maintained": len(self.pipelines_maintained),
            "tables_monitored": len(self.monitored_tables),
            "quality_checks_run": self.quality_checks_run,
        }
