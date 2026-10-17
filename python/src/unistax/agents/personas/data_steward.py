"""Data Steward Agent Persona.

Specialized agent for data governance and stewardship tasks including:
- Data catalog and metadata management
- Data quality and lineage tracking
- Compliance and regulatory oversight
- Data access control and policies
- Documentation and standards
"""

from typing import TYPE_CHECKING, Any, ClassVar

from unistax.agents.base import Agent, AgentState, Skill, Task
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

if TYPE_CHECKING:
    from unistax.agents.connectors.postgres import PostgresDataSource

logger = get_logger(__name__)


class DataStewardAgent(Agent):
    """Data Steward agent persona.

    Capabilities:
    - Manage data catalog and metadata
    - Track data lineage
    - Ensure regulatory compliance (GDPR, HIPAA, etc.)
    - Define and enforce data policies
    - Document data assets
    - Monitor data access patterns

    Examples:
        >>> # Create registry and shared infrastructure
        >>> from unistax.agents import AgentRegistry, Skill
        >>> from unistax.metrics import MetricsManager
        >>>
        >>> registry = AgentRegistry()
        >>>
        >>> # Create data steward with skills
        >>> steward = DataStewardAgent(
        ...     agent_id="steward_001",
        ...     event_bus=registry.event_bus,
        ...     metrics_manager=registry.metrics_manager,
        ...     skills=[
        ...         Skill("data_governance", 0.90, "governance"),
        ...         Skill("compliance", 0.85, "governance"),
        ...         Skill("metadata_management", 0.90, "governance"),
        ...         Skill("data_quality", 0.85, "governance"),
        ...     ]
        ... )
        >>> registry.register(steward)
    """

    #: Task types that inspect a real data source when one is attached.
    DATASOURCE_TASK_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"catalog_dataset", "document_schema", "classify_data"}
    )
    USES_DATASOURCE: ClassVar[bool] = True

    TASK_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "catalog_dataset",
            "track_lineage",
            "check_compliance",
            "enforce_policy",
            "document_schema",
            "audit_access",
            "classify_data",
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
        """Initialize Data Steward agent.

        Args:
            agent_id: Unique identifier for agent
            event_bus: Shared EventBus for communication
            metrics_manager: Shared MetricsManager for metrics
            skills: Custom skills (uses defaults if None)
            team_id: Team this agent belongs to
            datasource: Read-only PostgreSQL data source. With one, ``catalog_dataset``,
                ``document_schema`` and ``classify_data`` inspect the real database;
                without one they return simulated results (marked ``"simulated"``).
            **kwargs: Additional Agent constructor arguments
        """
        # Default skills for Data Steward
        default_skills = [
            Skill("data_governance", 0.90, "governance"),
            Skill("compliance", 0.85, "governance"),
            Skill("metadata_management", 0.90, "governance"),
            Skill("data_quality", 0.85, "governance"),
            Skill("data_lineage", 0.80, "governance"),
            Skill("policy_management", 0.85, "governance"),
            Skill("documentation", 0.90, "communication"),
            Skill("sql", 0.70, "database"),
        ]

        super().__init__(
            agent_id=agent_id,
            persona="data_steward",
            skills=skills or default_skills,
            event_bus=event_bus,
            metrics_manager=metrics_manager,
            team_id=team_id,
            **kwargs,
        )

        # Data Steward specific attributes
        self.datasource = datasource
        self.datasets_cataloged: set[str] = set()
        self.policies_enforced: int = 0
        self.compliance_checks: int = 0
        self.lineage_documented: int = 0

        logger.info(f"Data Steward {agent_id} initialized")

    async def decide(self) -> str | None:
        """Decide what action to take next.

        Decision priority:
        1. Execute assigned tasks
        2. Proactive compliance monitoring (if idle)
        3. Regular policy audits
        4. Help requests from team members

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
        if self.state == AgentState.IDLE and self.datasets_cataloged:
            return "proactive_monitor"

        # Nothing to do
        return None

    async def execute_task(self, task: Task) -> Any:
        """Execute a data stewardship task.

        Supports task types:
        - catalog_dataset: Add dataset to catalog
        - track_lineage: Document data lineage
        - check_compliance: Verify regulatory compliance
        - enforce_policy: Apply data policy
        - document_schema: Document table schema
        - audit_access: Review data access patterns
        - classify_data: Classify data sensitivity

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

        if task_type == "catalog_dataset":
            return await self._catalog_dataset(context)

        elif task_type == "track_lineage":
            return await self._track_lineage(context)

        elif task_type == "check_compliance":
            return await self._check_compliance(context)

        elif task_type == "enforce_policy":
            return await self._enforce_policy(context)

        elif task_type == "document_schema":
            return await self._document_schema(context)

        elif task_type == "audit_access":
            return await self._audit_access(context)

        elif task_type == "classify_data":
            return await self._classify_data(context)

        else:
            raise ValueError(f"Unknown task type: {task_type}")

    # ========================================================================
    # Task execution methods
    # ========================================================================

    async def _finish_real(self, outcome: Any) -> dict[str, Any]:
        """Record what a real task learned in the knowledge graph and return its result."""
        result = dict(outcome.result)
        result["knowledge_graph"] = await self.record_knowledge(outcome.nodes, outcome.edges)
        return result

    async def _catalog_dataset(self, context: dict[str, Any]) -> dict[str, Any]:
        """Add dataset to data catalog.

        With a data source this reads table metadata from PostgreSQL (one table, or every
        in-scope table when no ``name`` is given); otherwise the result is simulated.

        Args:
            context: Dataset cataloging specification (``name``, optional ``schema``)

        Returns:
            Cataloging result
        """
        if self.datasource is not None:
            from unistax.agents.connectors import tasks

            result = await self._finish_real(await tasks.catalog_dataset(self.datasource, context))
            for entry in result.get("tables", [result]):
                if entry.get("dataset_name"):
                    self.datasets_cataloged.add(entry["dataset_name"])
            return result

        dataset_name = context.get("name", "")
        source = context.get("source", "")

        logger.info(f"{self.agent_id} cataloging dataset: {dataset_name}")

        # Simulate dataset cataloging
        # In real implementation, this would:
        # 1. Extract schema information
        # 2. Profile data (types, nulls, distributions)
        # 3. Add to catalog (DataHub, Amundsen, etc.)
        # 4. Tag with business terms
        # 5. Link to owners

        self.datasets_cataloged.add(dataset_name)

        return {
            "status": "success",
            "data_source": "simulated",
            "dataset_name": dataset_name,
            "source": source,
            "schema": {
                "columns": 25,
                "rows": 1500000,
                "size_mb": 450,
            },
            "metadata": {
                "owner": "data_platform_team",
                "update_frequency": "daily",
                "retention_days": 365,
            },
            "tags": ["customer_data", "pii", "production"],
            "catalog_url": f"/catalog/datasets/{dataset_name}",
        }

    async def _track_lineage(self, context: dict[str, Any]) -> dict[str, Any]:
        """Document data lineage.

        Args:
            context: Lineage tracking specification

        Returns:
            Lineage result
        """
        dataset = context.get("dataset", "")
        upstream_sources = context.get("sources", [])

        logger.info(f"{self.agent_id} tracking lineage for: {dataset}")

        # Simulate lineage tracking
        # In real implementation, this would:
        # 1. Parse SQL/pipeline code
        # 2. Extract dependencies
        # 3. Build lineage graph
        # 4. Store in lineage tool
        # 5. Enable impact analysis

        self.lineage_documented += 1

        return {
            "status": "success",
            "dataset": dataset,
            "upstream_sources": upstream_sources,
            "downstream_consumers": [
                "analytics_dashboard",
                "ml_model_customer_churn",
                "daily_report",
            ],
            "transformation_steps": 5,
            "lineage_depth": 3,
            "lineage_url": f"/lineage/{dataset}",
        }

    async def _check_compliance(self, context: dict[str, Any]) -> dict[str, Any]:
        """Verify regulatory compliance.

        Args:
            context: Compliance check specification

        Returns:
            Compliance result
        """
        dataset = context.get("dataset", "")
        regulations = context.get("regulations", ["GDPR"])

        logger.info(f"{self.agent_id} checking compliance for: {dataset}")

        # Simulate compliance checking
        # In real implementation, this would:
        # 1. Scan for PII/sensitive data
        # 2. Verify encryption at rest
        # 3. Check access controls
        # 4. Validate retention policies
        # 5. Generate compliance report

        self.compliance_checks += 1

        return {
            "status": "compliant",
            "dataset": dataset,
            "regulations": regulations,
            "checks_passed": [
                "PII properly encrypted",
                "Access controls in place",
                "Retention policy defined",
                "Audit logging enabled",
            ],
            "issues": [],
            "risk_score": 2,  # 1-10, lower is better
            "last_audit": "2024-01-15",
        }

    async def _enforce_policy(self, context: dict[str, Any]) -> dict[str, Any]:
        """Apply data policy.

        Args:
            context: Policy enforcement specification

        Returns:
            Enforcement result
        """
        policy_name = context.get("policy", "")
        scope = context.get("scope", "all_datasets")

        logger.info(f"{self.agent_id} enforcing policy: {policy_name}")

        # Simulate policy enforcement
        # In real implementation, this would:
        # 1. Load policy rules
        # 2. Apply to target datasets
        # 3. Update access controls
        # 4. Configure monitoring
        # 5. Notify affected users

        self.policies_enforced += 1

        return {
            "status": "success",
            "policy_name": policy_name,
            "scope": scope,
            "rules_applied": [
                "PII masking for non-admin users",
                "Data access logging",
                "Retention: 90 days",
            ],
            "datasets_affected": 12,
            "users_notified": 45,
        }

    async def _document_schema(self, context: dict[str, Any]) -> dict[str, Any]:
        """Document table schema.

        Args:
            context: Schema documentation specification

        Returns:
            Documentation result
        """
        if self.datasource is not None:
            from unistax.agents.connectors import tasks

            return await self._finish_real(await tasks.document_schema(self.datasource, context))

        table = context.get("table", "")

        logger.info(f"{self.agent_id} documenting schema for: {table}")

        # Simulate schema documentation
        # In real implementation, this would:
        # 1. Extract column metadata
        # 2. Add business descriptions
        # 3. Document relationships
        # 4. Tag columns (PII, sensitive, etc.)
        # 5. Publish to catalog

        return {
            "status": "success",
            "data_source": "simulated",
            "table": table,
            "columns_documented": 18,
            "documentation": {
                "customer_id": {
                    "type": "bigint",
                    "description": "Unique customer identifier",
                    "tags": ["primary_key", "pii"],
                },
                "email": {
                    "type": "varchar",
                    "description": "Customer email address",
                    "tags": ["pii", "contact_info"],
                },
                "created_at": {
                    "type": "timestamp",
                    "description": "Account creation timestamp",
                    "tags": ["audit"],
                },
            },
            "relationships": [{"table": "orders", "type": "one_to_many", "key": "customer_id"}],
        }

    async def _audit_access(self, context: dict[str, Any]) -> dict[str, Any]:
        """Review data access patterns.

        Args:
            context: Access audit specification

        Returns:
            Audit result
        """
        dataset = context.get("dataset", "")
        period = context.get("period", "30d")

        logger.info(f"{self.agent_id} auditing access for: {dataset}")

        # Simulate access auditing
        # In real implementation, this would:
        # 1. Query access logs
        # 2. Analyze user patterns
        # 3. Detect anomalies
        # 4. Identify unused permissions
        # 5. Generate recommendations

        return {
            "status": "success",
            "dataset": dataset,
            "period": period,
            "total_accesses": 1234,
            "unique_users": 45,
            "most_active_users": [
                {"user": "analyst_team", "accesses": 567},
                {"user": "ml_pipeline", "accesses": 345},
                {"user": "dashboard_service", "accesses": 234},
            ],
            "anomalies": [
                {
                    "type": "unusual_access_time",
                    "user": "contractor_123",
                    "time": "2024-01-15 03:00:00",
                }
            ],
            "recommendations": [
                "Revoke access for 3 inactive users",
                "Review permissions for contractor_123",
            ],
        }

    async def _classify_data(self, context: dict[str, Any]) -> dict[str, Any]:
        """Classify data sensitivity.

        Args:
            context: Data classification specification

        Returns:
            Classification result
        """
        if self.datasource is not None:
            from unistax.agents.connectors import tasks

            return await self._finish_real(await tasks.classify_data(self.datasource, context))

        dataset = context.get("dataset", "")

        logger.info(f"{self.agent_id} classifying data: {dataset}")

        # Simulate data classification
        # In real implementation, this would:
        # 1. Scan column content
        # 2. Detect PII patterns (email, SSN, etc.)
        # 3. Apply classification rules
        # 4. Tag columns appropriately
        # 5. Update catalog

        return {
            "status": "success",
            "data_source": "simulated",
            "dataset": dataset,
            "classification": {
                "sensitivity_level": "high",
                "contains_pii": True,
                "regulated_data": ["GDPR", "CCPA"],
            },
            "column_classifications": {
                "email": "PII",
                "phone": "PII",
                "ssn": "SENSITIVE_PII",
                "address": "PII",
                "purchase_amount": "BUSINESS_CONFIDENTIAL",
                "product_id": "PUBLIC",
            },
            "required_controls": [
                "Encryption at rest",
                "Access logging",
                "Data masking for non-admin",
            ],
        }

    # ========================================================================
    # Proactive behaviors
    # ========================================================================

    async def _proactive_monitor(self):
        """Proactively monitor governance compliance.

        This runs when the agent is idle to detect compliance issues.
        """
        logger.info(f"{self.agent_id} performing proactive governance monitoring")

        # In real implementation, this would:
        # 1. Check policy compliance
        # 2. Review access patterns
        # 3. Validate data classifications
        # 4. Audit lineage accuracy
        # 5. Create alerts for issues

        logger.debug(f"{self.agent_id} monitored {len(self.datasets_cataloged)} datasets")

    def add_dataset(self, dataset_name: str):
        """Add a dataset to monitor.

        Args:
            dataset_name: Dataset identifier
        """
        self.datasets_cataloged.add(dataset_name)
        logger.info(f"{self.agent_id} now monitoring dataset: {dataset_name}")

    def get_steward_stats(self) -> dict[str, Any]:
        """Get data steward specific statistics.

        Returns:
            Statistics dictionary
        """
        base_metrics = self.get_metrics()

        return {
            **base_metrics,
            "datasets_cataloged": len(self.datasets_cataloged),
            "policies_enforced": self.policies_enforced,
            "compliance_checks": self.compliance_checks,
            "lineage_documented": self.lineage_documented,
        }
