"""Data Analyst Agent Persona.

Specialized agent for data analysis tasks including:
- Ad-hoc data analysis
- SQL queries and reporting
- Data visualization
- Metric tracking and dashboards
- Business intelligence
"""

from typing import Any, ClassVar

from unistax.agents.base import Agent, AgentState, Skill, Task
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

logger = get_logger(__name__)


class DataAnalystAgent(Agent):
    """Data Analyst agent persona.

    Capabilities:
    - Execute SQL queries and analysis
    - Create reports and dashboards
    - Analyze trends and patterns
    - Generate business insights
    - Monitor key metrics
    - Collaborate with Data Engineers for data needs

    Examples:
        >>> # Create registry and shared infrastructure
        >>> from unistax.agents import AgentRegistry, Skill
        >>> from unistax.metrics import MetricsManager
        >>>
        >>> registry = AgentRegistry()
        >>>
        >>> # Create data analyst with skills
        >>> analyst = DataAnalystAgent(
        ...     agent_id="analyst_001",
        ...     event_bus=registry.event_bus,
        ...     metrics_manager=registry.metrics_manager,
        ...     skills=[
        ...         Skill("sql", 0.90, "database"),
        ...         Skill("python", 0.75, "programming"),
        ...         Skill("statistics", 0.85, "analytics"),
        ...         Skill("visualization", 0.80, "analytics"),
        ...     ]
        ... )
        >>> registry.register(analyst)
    """

    TASK_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "analyze_data",
            "create_dashboard",
            "generate_report",
            "execute_query",
            "identify_trends",
            "calculate_metrics",
            "provide_insights",
        }
    )

    def __init__(
        self,
        agent_id: str,
        event_bus: EventBus | None = None,
        metrics_manager: MetricsManager | None = None,
        skills: list[Skill] | None = None,
        team_id: str | None = None,
        **kwargs,
    ):
        """Initialize Data Analyst agent.

        Args:
            agent_id: Unique identifier for agent
            event_bus: Shared EventBus for communication
            metrics_manager: Shared MetricsManager for metrics
            skills: Custom skills (uses defaults if None)
            team_id: Team this agent belongs to
            **kwargs: Additional Agent constructor arguments
        """
        # Default skills for Data Analyst
        default_skills = [
            Skill("sql", 0.90, "database"),
            Skill("python", 0.75, "programming"),
            Skill("statistics", 0.85, "analytics"),
            Skill("data_analysis", 0.90, "analytics"),
            Skill("visualization", 0.80, "analytics"),
            Skill("business_intelligence", 0.85, "analytics"),
            Skill("excel", 0.80, "tools"),
            Skill("reporting", 0.85, "analytics"),
        ]

        super().__init__(
            agent_id=agent_id,
            persona="data_analyst",
            skills=skills or default_skills,
            event_bus=event_bus,
            metrics_manager=metrics_manager,
            team_id=team_id,
            **kwargs,
        )

        # Data Analyst specific attributes
        self.dashboards_created: set[str] = set()
        self.reports_generated: int = 0
        self.queries_executed: int = 0
        self.insights_provided: int = 0

        logger.info(f"Data Analyst {agent_id} initialized")

    async def decide(self) -> str | None:
        """Decide what action to take next.

        Decision priority:
        1. Execute assigned tasks
        2. Proactive metric monitoring (if idle)
        3. Generate scheduled reports
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
        if self.state == AgentState.IDLE and self.dashboards_created:
            return "proactive_monitor"

        # Nothing to do
        return None

    async def execute_task(self, task: Task) -> Any:
        """Execute a data analysis task.

        Supports task types:
        - analyze_data: Perform ad-hoc analysis
        - create_dashboard: Build visualization dashboard
        - generate_report: Create business report
        - execute_query: Run SQL query
        - identify_trends: Analyze trends and patterns
        - calculate_metrics: Compute business metrics
        - provide_insights: Generate business insights

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

        if task_type == "analyze_data":
            return await self._analyze_data(context)

        elif task_type == "create_dashboard":
            return await self._create_dashboard(context)

        elif task_type == "generate_report":
            return await self._generate_report(context)

        elif task_type == "execute_query":
            return await self._execute_query(context)

        elif task_type == "identify_trends":
            return await self._identify_trends(context)

        elif task_type == "calculate_metrics":
            return await self._calculate_metrics(context)

        elif task_type == "provide_insights":
            return await self._provide_insights(context)

        else:
            raise ValueError(f"Unknown task type: {task_type}")

    # ========================================================================
    # Task execution methods
    # ========================================================================

    async def _analyze_data(self, context: dict[str, Any]) -> dict[str, Any]:
        """Perform ad-hoc data analysis.

        Args:
            context: Analysis specification

        Returns:
            Analysis result
        """
        dataset = context.get("dataset", "")
        analysis_type = context.get("analysis_type", "descriptive")

        logger.info(f"{self.agent_id} analyzing dataset: {dataset}")

        # Simulate data analysis
        # In real implementation, this would:
        # 1. Load dataset from source
        # 2. Perform statistical analysis
        # 3. Generate visualizations
        # 4. Summarize findings

        self.queries_executed += 1

        return {
            "status": "success",
            "dataset": dataset,
            "analysis_type": analysis_type,
            "summary": {
                "row_count": 10000,
                "column_count": 15,
                "null_percentage": 2.5,
                "data_quality_score": 0.95,
            },
            "key_findings": [
                "Revenue increased 15% month-over-month",
                "Customer retention rate improved to 87%",
                "Top 3 products account for 45% of sales",
            ],
        }

    async def _create_dashboard(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build visualization dashboard.

        Args:
            context: Dashboard specification

        Returns:
            Dashboard creation result
        """
        dashboard_name = context.get("name", "unnamed_dashboard")
        metrics = context.get("metrics", [])
        data_sources = context.get("data_sources", [])

        logger.info(f"{self.agent_id} creating dashboard: {dashboard_name}")

        # Simulate dashboard creation
        # In real implementation, this would:
        # 1. Connect to data sources
        # 2. Design layout and visualizations
        # 3. Configure refresh schedule
        # 4. Set up alerts and thresholds
        # 5. Share with stakeholders

        self.dashboards_created.add(dashboard_name)

        return {
            "status": "success",
            "dashboard_name": dashboard_name,
            "metrics": metrics,
            "data_sources": data_sources,
            "url": f"/dashboards/{dashboard_name}",
            "refresh_schedule": "hourly",
        }

    async def _generate_report(self, context: dict[str, Any]) -> dict[str, Any]:
        """Create business report.

        Args:
            context: Report specification

        Returns:
            Report generation result
        """
        report_name = context.get("name", "unnamed_report")
        report_type = context.get("type", "summary")
        period = context.get("period", "monthly")

        logger.info(f"{self.agent_id} generating report: {report_name}")

        # Simulate report generation
        # In real implementation, this would:
        # 1. Gather data from sources
        # 2. Perform calculations and aggregations
        # 3. Generate charts and visualizations
        # 4. Format report (PDF/HTML/Excel)
        # 5. Distribute to recipients

        self.reports_generated += 1

        return {
            "status": "success",
            "report_name": report_name,
            "report_type": report_type,
            "period": period,
            "file_path": f"/reports/{report_name}.pdf",
            "page_count": 12,
            "generated_at": "2024-01-15 10:30:00",
        }

    async def _execute_query(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run SQL query.

        Args:
            context: Query specification

        Returns:
            Query execution result
        """
        database = context.get("database", "default")

        logger.info(f"{self.agent_id} executing query on: {database}")

        # Simulate query execution
        # In real implementation, this would:
        # 1. Validate SQL syntax
        # 2. Execute query on database
        # 3. Fetch results
        # 4. Format output

        self.queries_executed += 1

        return {
            "status": "success",
            "database": database,
            "rows_returned": 1523,
            "execution_time_ms": 245,
            "columns": ["customer_id", "order_date", "total_amount", "status"],
            "sample_data": [
                {
                    "customer_id": 1001,
                    "order_date": "2024-01-10",
                    "total_amount": 299.99,
                    "status": "completed",
                },
                {
                    "customer_id": 1002,
                    "order_date": "2024-01-11",
                    "total_amount": 149.50,
                    "status": "pending",
                },
            ],
        }

    async def _identify_trends(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze trends and patterns.

        Args:
            context: Trend analysis specification

        Returns:
            Trend analysis result
        """
        metric_name = context.get("metric", "")
        time_period = context.get("time_period", "30d")

        logger.info(f"{self.agent_id} identifying trends for: {metric_name}")

        # Simulate trend analysis
        # In real implementation, this would:
        # 1. Fetch historical data
        # 2. Apply statistical methods (moving averages, regression)
        # 3. Detect anomalies
        # 4. Forecast future values
        # 5. Identify seasonal patterns

        self.insights_provided += 1

        return {
            "status": "success",
            "metric": metric_name,
            "time_period": time_period,
            "trend": "increasing",
            "growth_rate": 0.12,  # 12% growth
            "seasonality": "weekly pattern detected",
            "anomalies": [
                {"date": "2024-01-08", "value": 1250, "expected": 980, "deviation": "+27%"}
            ],
            "forecast": {
                "next_7_days": [1050, 1075, 1100, 1090, 1120, 1080, 1110],
                "confidence": 0.85,
            },
        }

    async def _calculate_metrics(self, context: dict[str, Any]) -> dict[str, Any]:
        """Compute business metrics.

        Args:
            context: Metrics calculation specification

        Returns:
            Metrics calculation result
        """
        data_source = context.get("data_source", "")

        logger.info(f"{self.agent_id} calculating metrics from: {data_source}")

        # Simulate metrics calculation
        # In real implementation, this would:
        # 1. Query data source
        # 2. Calculate KPIs
        # 3. Compare to targets
        # 4. Generate alerts if thresholds exceeded

        return {
            "status": "success",
            "data_source": data_source,
            "metrics": {
                "revenue": {"value": 125000, "change": "+15%", "vs_target": "+5%"},
                "customers": {"value": 1450, "change": "+8%", "vs_target": "+2%"},
                "conversion_rate": {"value": 0.034, "change": "-2%", "vs_target": "-5%"},
                "avg_order_value": {"value": 86.21, "change": "+6%", "vs_target": "+3%"},
            },
            "alerts": [
                {
                    "metric": "conversion_rate",
                    "message": "Below target by 5%",
                    "severity": "warning",
                }
            ],
        }

    async def _provide_insights(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate business insights.

        Args:
            context: Insights specification

        Returns:
            Business insights
        """
        topic = context.get("topic", "")

        logger.info(f"{self.agent_id} providing insights on: {topic}")

        # Simulate insight generation
        # In real implementation, this would:
        # 1. Analyze multiple data sources
        # 2. Apply domain knowledge
        # 3. Identify patterns and correlations
        # 4. Generate actionable recommendations

        self.insights_provided += 1

        return {
            "status": "success",
            "topic": topic,
            "insights": [
                {
                    "title": "Customer Retention Opportunity",
                    "description": (
                        "Customers who purchase within first 7 days "
                        "have 3x higher lifetime value"
                    ),
                    "recommendation": "Implement onboarding campaign for new customers",
                    "priority": "high",
                    "impact": "Potential 15% increase in CLV",
                },
                {
                    "title": "Seasonal Sales Pattern",
                    "description": "Sales peak on Tuesdays and Thursdays, 20% above average",
                    "recommendation": "Optimize inventory and staffing for peak days",
                    "priority": "medium",
                    "impact": "Reduce stockouts by 30%",
                },
            ],
            "confidence": 0.87,
            "data_quality": "high",
        }

    # ========================================================================
    # Proactive behaviors
    # ========================================================================

    async def _proactive_monitor(self):
        """Proactively monitor dashboards and metrics.

        This runs when the agent is idle to detect anomalies and insights.
        """
        logger.info(f"{self.agent_id} performing proactive monitoring")

        # In real implementation, this would:
        # 1. Check dashboard metrics
        # 2. Detect anomalies
        # 3. Identify interesting trends
        # 4. Create tasks for investigation

        logger.debug(f"{self.agent_id} monitored {len(self.dashboards_created)} dashboards")

    def add_dashboard(self, dashboard_name: str):
        """Add a dashboard to monitor.

        Args:
            dashboard_name: Dashboard identifier
        """
        self.dashboards_created.add(dashboard_name)
        logger.info(f"{self.agent_id} now monitoring dashboard: {dashboard_name}")

    def get_analyst_stats(self) -> dict[str, Any]:
        """Get data analyst specific statistics.

        Returns:
            Statistics dictionary
        """
        base_metrics = self.get_metrics()

        return {
            **base_metrics,
            "dashboards_created": len(self.dashboards_created),
            "reports_generated": self.reports_generated,
            "queries_executed": self.queries_executed,
            "insights_provided": self.insights_provided,
        }
