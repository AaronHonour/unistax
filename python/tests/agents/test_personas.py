"""Tests for agent personas."""

import asyncio

import pytest

from unistax.agents.base import Skill, Task
from unistax.agents.personas.data_analyst import DataAnalystAgent
from unistax.agents.personas.data_engineer import DataEngineerAgent
from unistax.events import EventBus


@pytest.mark.unit
@pytest.mark.agents
class TestDataEngineerAgent:
    """Test DataEngineerAgent persona."""

    def test_engineer_initialization(self):
        """Test Data Engineer agent initialization."""
        engineer = DataEngineerAgent(
            agent_id="eng_001",
            event_bus=EventBus(),
        )

        assert engineer.agent_id == "eng_001"
        assert engineer.persona == "data_engineer"
        assert len(engineer.skills) == 8  # Default skills

        # Check default skills
        assert "sql" in engineer.skills
        assert "python" in engineer.skills
        assert "etl" in engineer.skills
        assert "data_quality" in engineer.skills

    def test_engineer_custom_skills(self):
        """Test Data Engineer with custom skills."""
        custom_skills = [
            Skill("sql", 0.95, "database"),
            Skill("python", 0.90, "programming"),
        ]

        engineer = DataEngineerAgent(
            agent_id="eng_001",
            skills=custom_skills,
        )

        assert len(engineer.skills) == 2
        assert engineer.skills["sql"].proficiency == 0.95

    @pytest.mark.asyncio
    async def test_engineer_decide(self):
        """Test Data Engineer decision making."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        # No tasks - should return None
        decision = await engineer.decide()
        assert decision is None

        # Add task - should decide to execute it
        task = Task(type="build_pipeline", description="Test pipeline")
        engineer.current_tasks.append(task)

        decision = await engineer.decide()
        assert decision is not None
        assert decision.startswith("execute_task:")

    @pytest.mark.asyncio
    async def test_engineer_build_pipeline(self):
        """Test building a pipeline."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="build_pipeline",
            description="Build customer pipeline",
            context={
                "name": "customer_pipeline",
                "source": {"type": "postgres"},
                "target": {"type": "snowflake"},
            },
        )

        result = await engineer.execute_task(task)

        assert result["status"] == "success"
        assert result["pipeline_name"] == "customer_pipeline"
        assert "customer_pipeline" in engineer.pipelines_maintained

    @pytest.mark.asyncio
    async def test_engineer_optimize_query(self):
        """Test query optimization."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="optimize_query",
            description="Optimize slow query",
            context={
                "query": "SELECT * FROM large_table",
                "table": "large_table",
            },
        )

        result = await engineer.execute_task(task)

        assert result["status"] == "success"
        assert result["table"] == "large_table"
        assert "improvements" in result

    @pytest.mark.asyncio
    async def test_engineer_quality_check(self):
        """Test data quality check."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="quality_check",
            description="Check data quality",
            context={
                "table": "customers",
                "checks": ["null_check", "type_check", "integrity_check"],
            },
        )

        result = await engineer.execute_task(task)

        assert result["status"] == "success"
        assert result["table"] == "customers"
        assert engineer.quality_checks_run == 1

    @pytest.mark.asyncio
    async def test_engineer_schema_migration(self):
        """Test schema migration."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="schema_migration",
            description="Migrate schema",
            context={
                "table": "orders",
                "changes": ["add_column", "modify_type"],
            },
        )

        result = await engineer.execute_task(task)

        assert result["status"] == "success"
        assert result["table"] == "orders"
        assert result["changes_applied"] == ["add_column", "modify_type"]

    @pytest.mark.asyncio
    async def test_engineer_monitor_pipeline(self):
        """Test pipeline monitoring."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="monitor_pipeline",
            description="Monitor pipeline health",
            context={"pipeline": "customer_pipeline"},
        )

        result = await engineer.execute_task(task)

        assert result["status"] == "healthy"
        assert result["pipeline"] == "customer_pipeline"

    @pytest.mark.asyncio
    async def test_engineer_fix_data_issue(self):
        """Test fixing data issues."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="fix_data_issue",
            description="Fix null values",
            context={
                "issue_type": "null_values",
                "affected_records": 150,
            },
        )

        result = await engineer.execute_task(task)

        assert result["status"] == "success"
        assert result["records_fixed"] == 150

    @pytest.mark.asyncio
    async def test_engineer_unknown_task_type(self):
        """Test handling unknown task type."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        task = Task(
            type="unknown_task",
            description="Unknown task",
        )

        with pytest.raises(ValueError, match="Unknown task type"):
            await engineer.execute_task(task)

    def test_engineer_add_pipeline(self):
        """Test adding pipeline to monitor."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        engineer.add_pipeline("pipeline_1")
        engineer.add_pipeline("pipeline_2")

        assert len(engineer.pipelines_maintained) == 2
        assert "pipeline_1" in engineer.pipelines_maintained

    def test_engineer_add_table_monitor(self):
        """Test adding table to monitor."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        engineer.add_table_monitor("customers")
        engineer.add_table_monitor("orders")

        assert len(engineer.monitored_tables) == 2
        assert "customers" in engineer.monitored_tables

    def test_engineer_stats(self):
        """Test Data Engineer specific statistics."""
        engineer = DataEngineerAgent(agent_id="eng_001")

        engineer.add_pipeline("pipeline_1")
        engineer.add_table_monitor("table_1")
        engineer.quality_checks_run = 5

        stats = engineer.get_engineer_stats()

        assert stats["pipelines_maintained"] == 1
        assert stats["tables_monitored"] == 1
        assert stats["quality_checks_run"] == 5


@pytest.mark.unit
@pytest.mark.agents
class TestDataAnalystAgent:
    """Test DataAnalystAgent persona."""

    def test_analyst_initialization(self):
        """Test Data Analyst agent initialization."""
        analyst = DataAnalystAgent(
            agent_id="analyst_001",
            event_bus=EventBus(),
        )

        assert analyst.agent_id == "analyst_001"
        assert analyst.persona == "data_analyst"
        assert len(analyst.skills) == 8  # Default skills

        # Check default skills
        assert "sql" in analyst.skills
        assert "python" in analyst.skills
        assert "statistics" in analyst.skills
        assert "data_analysis" in analyst.skills

    def test_analyst_custom_skills(self):
        """Test Data Analyst with custom skills."""
        custom_skills = [
            Skill("sql", 0.95, "database"),
            Skill("statistics", 0.90, "analytics"),
        ]

        analyst = DataAnalystAgent(
            agent_id="analyst_001",
            skills=custom_skills,
        )

        assert len(analyst.skills) == 2
        assert analyst.skills["sql"].proficiency == 0.95

    @pytest.mark.asyncio
    async def test_analyst_decide(self):
        """Test Data Analyst decision making."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        # No tasks - should return None
        decision = await analyst.decide()
        assert decision is None

        # Add task - should decide to execute it
        task = Task(type="analyze_data", description="Test analysis")
        analyst.current_tasks.append(task)

        decision = await analyst.decide()
        assert decision is not None
        assert decision.startswith("execute_task:")

    @pytest.mark.asyncio
    async def test_analyst_analyze_data(self):
        """Test data analysis."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="analyze_data",
            description="Analyze customer data",
            context={
                "dataset": "customers",
                "analysis_type": "descriptive",
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert result["dataset"] == "customers"
        assert "key_findings" in result
        assert analyst.queries_executed == 1

    @pytest.mark.asyncio
    async def test_analyst_create_dashboard(self):
        """Test dashboard creation."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="create_dashboard",
            description="Create sales dashboard",
            context={
                "name": "sales_dashboard",
                "metrics": ["revenue", "conversion"],
                "data_sources": ["sales_db"],
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert result["dashboard_name"] == "sales_dashboard"
        assert "sales_dashboard" in analyst.dashboards_created

    @pytest.mark.asyncio
    async def test_analyst_generate_report(self):
        """Test report generation."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="generate_report",
            description="Generate monthly report",
            context={
                "name": "monthly_sales",
                "type": "summary",
                "period": "monthly",
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert result["report_name"] == "monthly_sales"
        assert analyst.reports_generated == 1

    @pytest.mark.asyncio
    async def test_analyst_execute_query(self):
        """Test SQL query execution."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="execute_query",
            description="Run customer query",
            context={
                "query": "SELECT * FROM customers",
                "database": "main_db",
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert result["database"] == "main_db"
        assert "rows_returned" in result
        assert analyst.queries_executed == 1

    @pytest.mark.asyncio
    async def test_analyst_identify_trends(self):
        """Test trend identification."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="identify_trends",
            description="Identify sales trends",
            context={
                "metric": "sales",
                "time_period": "30d",
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert result["metric"] == "sales"
        assert "trend" in result
        assert "forecast" in result
        assert analyst.insights_provided == 1

    @pytest.mark.asyncio
    async def test_analyst_calculate_metrics(self):
        """Test metrics calculation."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="calculate_metrics",
            description="Calculate KPIs",
            context={
                "metrics": ["revenue", "conversion_rate"],
                "data_source": "analytics_db",
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert "metrics" in result
        assert "revenue" in result["metrics"]

    @pytest.mark.asyncio
    async def test_analyst_provide_insights(self):
        """Test insight generation."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="provide_insights",
            description="Generate insights",
            context={
                "topic": "customer_retention",
                "data_sources": ["crm", "analytics"],
            },
        )

        result = await analyst.execute_task(task)

        assert result["status"] == "success"
        assert result["topic"] == "customer_retention"
        assert "insights" in result
        assert analyst.insights_provided == 1

    @pytest.mark.asyncio
    async def test_analyst_unknown_task_type(self):
        """Test handling unknown task type."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        task = Task(
            type="unknown_task",
            description="Unknown task",
        )

        with pytest.raises(ValueError, match="Unknown task type"):
            await analyst.execute_task(task)

    def test_analyst_add_dashboard(self):
        """Test adding dashboard to monitor."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        analyst.add_dashboard("dashboard_1")
        analyst.add_dashboard("dashboard_2")

        assert len(analyst.dashboards_created) == 2
        assert "dashboard_1" in analyst.dashboards_created

    def test_analyst_stats(self):
        """Test Data Analyst specific statistics."""
        analyst = DataAnalystAgent(agent_id="analyst_001")

        analyst.add_dashboard("dashboard_1")
        analyst.reports_generated = 3
        analyst.queries_executed = 10
        analyst.insights_provided = 5

        stats = analyst.get_analyst_stats()

        assert stats["dashboards_created"] == 1
        assert stats["reports_generated"] == 3
        assert stats["queries_executed"] == 10
        assert stats["insights_provided"] == 5


@pytest.mark.integration
@pytest.mark.agents
class TestPersonaCollaboration:
    """Test collaboration between personas."""

    @pytest.mark.asyncio
    async def test_engineer_analyst_collaboration(self):
        """Test Data Engineer and Data Analyst collaboration."""
        event_bus = EventBus()

        engineer = DataEngineerAgent("eng_001", event_bus=event_bus)
        analyst = DataAnalystAgent("analyst_001", event_bus=event_bus)

        # Analyst sends request to engineer
        await analyst.send_message(
            to_agent="eng_001",
            msg_type="request",
            content={"action": "quality_check", "table": "customers"},
        )

        # Wait for message processing
        await asyncio.sleep(0.01)

        # Check engineer received message
        assert engineer.inbox.qsize() == 1

    def test_skill_overlap(self):
        """Test skill overlap between personas."""
        engineer = DataEngineerAgent("eng_001")
        analyst = DataAnalystAgent("analyst_001")

        # Both should have SQL and Python
        assert "sql" in engineer.skills
        assert "sql" in analyst.skills
        assert "python" in engineer.skills
        assert "python" in analyst.skills

        # Engineer should have ETL, analyst should not
        assert "etl" in engineer.skills
        assert "etl" not in analyst.skills

        # Analyst should have statistics, engineer should not
        assert "statistics" in analyst.skills
        assert "statistics" not in engineer.skills
