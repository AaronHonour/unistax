# Agent Swarm Framework

Autonomous agent system for building intelligent data teams that collaborate to manage data platform operations.

## Overview

The Agent Swarm Framework provides a complete system for creating, managing, and orchestrating autonomous agents that work together to handle data engineering, analysis, and platform operations. Agents have specialized skills, collaborate through an event-driven architecture, and organize into hierarchical teams.

## Key Features

- **🤖 Autonomous Agents** - Self-directed agents with cognitive cycle (Sense → Think → Act)
- **👥 Hierarchical Teams** - Multi-level organizational structures with leaders and members
- **🎯 Skill-Based Matching** - Automatic task assignment based on agent capabilities
- **📡 Event-Driven Communication** - Inter-agent messaging via EventBus
- **📊 Performance Tracking** - Built-in metrics and monitoring
- **🔄 Proactive & Reactive** - Agents can both respond to tasks and take initiative
- **🧩 Multiple Personas** - Pre-configured agent types for different roles
- **🧠 Intelligence Features** - RL learning, knowledge graphs, HTN planning, swarm optimization
- **🔀 Multi-Agent Workflows** - DAG-based orchestration with dependency resolution
- **🔐 Enterprise Security** - JWT auth, rate limiting, secrets management

## Architecture

### Agent Cognitive Cycle

Each agent operates on a continuous cognitive cycle:

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  SENSE   │────▶│  THINK   │────▶│   ACT    │
└──────────┘     └──────────┘     └──────────┘
      ▲                                  │
      └──────────────────────────────────┘
```

1. **Sense**: Process incoming messages and observe environment
2. **Think**: Decide what action to take based on state and goals
3. **Act**: Execute the decided action (task, message, etc.)

### Component Hierarchy

```
AgentRegistry
├── EventBus (shared communication)
├── MetricsManager (performance tracking)
└── TeamHierarchy
    ├── Team (Division)
    │   ├── Team (Functional)
    │   │   ├── Agent (Leader)
    │   │   ├── Agent (Member)
    │   │   └── Agent (Specialist)
    │   └── Team (Cross-Functional)
    └── Team (Task Force)
```

## Quick Start

### Basic Setup

```python
from unistax.agents import (
    AgentRegistry,
    DataEngineerAgent,
    DataAnalystAgent,
    Skill,
    Task,
    TeamType,
)

# 1. Create registry with shared infrastructure
registry = AgentRegistry()

# 2. Create a team
data_team = registry.create_team(
    name="Data Platform",
    team_type=TeamType.DIVISION,
)

# 3. Create agents
engineer = DataEngineerAgent(
    agent_id="eng_001",
    event_bus=registry.event_bus,
    metrics_manager=registry.metrics_manager,
    team_id=data_team.id,
)

analyst = DataAnalystAgent(
    agent_id="analyst_001",
    event_bus=registry.event_bus,
    metrics_manager=registry.metrics_manager,
    team_id=data_team.id,
)

# 4. Register agents
registry.register(engineer)
registry.register(analyst)

# 5. Create and assign tasks
task = Task(
    type="build_pipeline",
    description="Create customer analytics pipeline",
    priority=8,
    required_skills={"sql": 0.7, "etl": 0.8},
    context={
        "name": "customer_pipeline",
        "source": {"type": "postgres", "table": "raw_customers"},
        "target": {"type": "snowflake", "table": "dim_customers"},
    },
)

# Check if agent can do task
can_do, confidence = engineer.can_do(task)
if can_do:
    await engineer.accept_task(task)
    result = await engineer.execute_task(task)
```

### Running the Demo

```bash
cd python
PYTHONPATH=src:$PYTHONPATH python examples/agent_collaboration_demo.py
```

## Agent Personas

### Data Engineer

**Focus**: Infrastructure, pipelines, data quality

**Skills** (default):
- SQL: 0.90
- Python: 0.85
- ETL: 0.90
- Data Quality: 0.85
- Schema Design: 0.80
- Performance Tuning: 0.75
- Airflow: 0.80
- Spark: 0.70

**Supported Tasks**:
- `build_pipeline` - Create ETL pipelines
- `optimize_query` - Optimize database queries
- `quality_check` - Run data quality validations
- `schema_migration` - Perform schema changes
- `monitor_pipeline` - Monitor pipeline health
- `fix_data_issue` - Fix data quality issues

**Example**:
```python
task = Task(
    type="build_pipeline",
    context={
        "name": "orders_pipeline",
        "source": {"type": "kafka", "topic": "orders"},
        "target": {"type": "redshift", "table": "fact_orders"},
        "transformations": ["dedupe", "validate", "enrich"],
    },
)

result = await engineer.execute_task(task)
# Returns: {"status": "success", "pipeline_name": "orders_pipeline", ...}
```

### Data Analyst

**Focus**: Analysis, insights, reporting

**Skills** (default):
- SQL: 0.90
- Python: 0.75
- Statistics: 0.85
- Data Analysis: 0.90
- Visualization: 0.80
- Business Intelligence: 0.85
- Excel: 0.80
- Reporting: 0.85

**Supported Tasks**:
- `analyze_data` - Perform ad-hoc analysis
- `create_dashboard` - Build visualization dashboards
- `generate_report` - Create business reports
- `execute_query` - Run SQL queries
- `identify_trends` - Analyze patterns and trends
- `calculate_metrics` - Compute business metrics
- `provide_insights` - Generate recommendations

**Example**:
```python
task = Task(
    type="analyze_data",
    context={
        "dataset": "customer_churn",
        "analysis_type": "predictive",
        "metrics": ["churn_rate", "customer_lifetime_value"],
    },
)

result = await analyst.execute_task(task)
# Returns: {"status": "success", "key_findings": [...], ...}
```

## Team Management

### Creating Teams

```python
# Create division (top-level)
platform = registry.create_team(
    name="Data Platform",
    team_type=TeamType.DIVISION,
)

# Create functional teams under division
engineering = registry.create_team(
    name="Data Engineering",
    team_type=TeamType.FUNCTIONAL,
    parent_id=platform.id,
    leader_id="eng_lead_001",
)

analytics = registry.create_team(
    name="Data Analytics",
    team_type=TeamType.FUNCTIONAL,
    parent_id=platform.id,
    leader_id="analyst_lead_001",
)

# Create cross-functional team
product_team = registry.create_team(
    name="Product Analytics",
    team_type=TeamType.CROSS_FUNCTIONAL,
    parent_id=platform.id,
)
```

### Team Types

- **FUNCTIONAL**: Agents with similar skills (e.g., all engineers)
- **CROSS_FUNCTIONAL**: Mixed roles working on a project
- **TASK_FORCE**: Temporary team for specific goal
- **DIVISION**: High-level organizational unit

### Team Operations

```python
# Get team
team = registry.get_team(team_id)

# Get all team members (including leader)
members = team.all_members(include_leader=True)

# Get organizational path
path = registry.team_hierarchy.get_organizational_path(team_id)
print(" > ".join(t.name for t in path))
# Output: Data Platform > Data Engineering > Backend Team

# Get team metrics
metrics = registry.team_hierarchy.get_metrics(team_id, recursive=True)
```

## Agent Discovery

### Find by Persona

```python
# Find all data engineers
engineers = registry.find_by_persona("data_engineer")

# Find all data analysts
analysts = registry.find_by_persona("data_analyst")
```

### Find by Skill

```python
# Find agents with SQL >= 0.8
sql_experts = registry.find_by_skill("sql", min_proficiency=0.8)

# Find agents with multiple skills
ml_agents = registry.find_by_skill("machine_learning", min_proficiency=0.7)
```

### Find by Team

```python
# Find all agents in a team
team_agents = registry.find_by_team(team_id)
```

### Find Available Agents

```python
# Find any available agent
available = registry.find_available()

# Find available engineers
available_engineers = registry.find_available(persona="data_engineer")

# Find agents with < 2 tasks
lightly_loaded = registry.find_available(max_tasks=2)
```

## Inter-Agent Communication

### Sending Messages

```python
# Send request to specific agent
await analyst.send_message(
    to_agent="eng_001",
    msg_type="request",
    content={
        "action": "quality_check",
        "table": "customer_analytics",
        "urgency": "high",
    },
    requires_response=True,
)

# Broadcast to team
await engineer.broadcast_to_team(
    msg_type="notification",
    content={
        "event": "pipeline_deployed",
        "pipeline": "customer_pipeline",
    },
)

# Broadcast to multiple agents
await analyst.send_message(
    to_agent=["eng_001", "eng_002", "analyst_002"],
    msg_type="broadcast",
    content={"announcement": "New dashboard available"},
)
```

### Message Types

- `request` - Request action from another agent
- `response` - Response to a previous request
- `broadcast` - Announce to multiple agents
- `notification` - Inform of an event
- `task_assignment` - Assign a task
- `help_request` - Request assistance
- `peer_review` - Request code/work review

### Event Subscriptions

Agents automatically subscribe to relevant events:

```python
# These events are automatically handled:
- AgentMessageEvent: Messages sent via EventBus
- TaskAssignedEvent: Task assignments
- TaskCompletedEvent: Task completions
- TaskFailedEvent: Task failures
- AgentStateChangeEvent: State transitions
- CollaborationRequestEvent: Collaboration requests
```

## Task Management

### Creating Tasks

```python
task = Task(
    type="analyze_data",
    description="Analyze customer churn patterns",
    priority=7,  # 1-10, higher = more urgent
    required_skills={
        "sql": 0.7,
        "statistics": 0.8,
        "data_analysis": 0.85,
    },
    context={
        "dataset": "customer_events",
        "time_period": "90d",
        "target_metric": "churn_rate",
    },
    dependencies=["task_123"],  # Must complete first
    deadline=datetime.now() + timedelta(hours=4),
)
```

### Task Assignment

```python
# Check if agent can do task
can_do, confidence = agent.can_do(task)
print(f"Can do: {can_do}, Confidence: {confidence:.2%}")

# Accept task
if can_do:
    success = await agent.accept_task(task)

    # Task is now in agent's queue
    assert task in agent.current_tasks
    assert task.status == TaskStatus.ASSIGNED
```

### Task Execution

```python
# Execute task (happens in agent's run loop)
result = await agent.execute_task(task)

# Task moves to history
assert task in agent.task_history
assert task.status == TaskStatus.COMPLETED
assert task.result == result
```

### Task Status Lifecycle

```
PENDING → ASSIGNED → IN_PROGRESS → WAITING_REVIEW → COMPLETED
                                   ↓
                                 FAILED
                                   ↓
                               CANCELLED
```

## Metrics and Monitoring

### Agent Metrics

```python
metrics = agent.get_metrics()

# Returns:
{
    "tasks_completed": 15,
    "tasks_failed": 2,
    "tasks_helped_with": 5,
    "messages_sent": 42,
    "messages_received": 38,
    "collaborations": 8,
    "uptime_seconds": 3600.0,
    "success_rate": 0.88,
    "current_tasks": 2,
    "state": "working",
    "reputation": 1.0,
}
```

### Persona-Specific Metrics

```python
# Data Engineer
eng_stats = engineer.get_engineer_stats()
# Additional metrics:
# - pipelines_maintained
# - tables_monitored
# - quality_checks_run

# Data Analyst
analyst_stats = analyst.get_analyst_stats()
# Additional metrics:
# - dashboards_created
# - reports_generated
# - queries_executed
# - insights_provided
```

### Registry Statistics

```python
stats = registry.get_registry_stats()

# Returns:
{
    "total_agents": 5,
    "active_agents": 4,
    "total_teams": 3,
    "personas": ["data_engineer", "data_analyst"],
    "total_current_tasks": 8,
    "avg_tasks_per_agent": 1.6,
}
```

## Advanced Usage

### Custom Agent Personas

```python
from unistax.agents.base import Agent, Skill, Task

class DataScientistAgent(Agent):
    """Custom Data Scientist persona."""

    def __init__(self, agent_id, **kwargs):
        default_skills = [
            Skill("python", 0.95, "programming"),
            Skill("machine_learning", 0.90, "ml"),
            Skill("statistics", 0.90, "analytics"),
            Skill("deep_learning", 0.85, "ml"),
        ]

        super().__init__(
            agent_id=agent_id,
            persona="data_scientist",
            skills=kwargs.get("skills", default_skills),
            **kwargs,
        )

    async def decide(self):
        """Decision logic."""
        if self.current_tasks:
            return f"execute_task:{self.current_tasks[0].id}"
        return None

    async def execute_task(self, task: Task):
        """Task execution."""
        if task.type == "train_model":
            return await self._train_model(task.context)
        # ... handle other task types
```

### Custom Skills

```python
# Define specialized skills
skills = [
    Skill("python", 0.95, "programming"),
    Skill("tensorflow", 0.85, "ml"),
    Skill("pytorch", 0.80, "ml"),
    Skill("mlflow", 0.90, "ml_ops"),
    Skill("docker", 0.85, "devops"),
]

agent = DataScientistAgent(
    agent_id="ds_001",
    skills=skills,
    event_bus=registry.event_bus,
)
```

### Proactive Behaviors

```python
class ProactiveEngineer(DataEngineerAgent):
    """Engineer that proactively monitors systems."""

    async def decide(self):
        """Enhanced decision logic with proactive monitoring."""
        # Priority 1: Assigned tasks
        if self.current_tasks:
            return f"execute_task:{self.current_tasks[0].id}"

        # Priority 2: Proactive monitoring (when idle)
        if self.state == AgentState.IDLE:
            if self.monitored_tables:
                return "proactive_monitor"

        return None
```

## Integration with Unistax

The agent framework integrates seamlessly with existing unistax infrastructure:

### Logging

```python
from unistax.logging import get_logger

logger = get_logger(__name__)  # Structured logging
```

### Events

```python
from unistax.events import EventBus

event_bus = EventBus()  # Shared across all agents
```

### Metrics

```python
from unistax.metrics import MetricsManager

metrics = MetricsManager()  # Track agent performance
```

### Security

The REST API (below) authenticates with JWT bearer tokens (`unistax.security.JWT`),
enforces role-based access, and rate limits callers (`unistax.ratelimit`). The core
agent classes themselves do not authenticate: they are in-process objects and trust
their caller.

## Best Practices

### 1. Use Shared EventBus

Always create a single EventBus and share it across all agents:

```python
# Good
event_bus = EventBus()
agent1 = DataEngineerAgent("a1", event_bus=event_bus)
agent2 = DataAnalystAgent("a2", event_bus=event_bus)

# Bad - agents can't communicate
agent1 = DataEngineerAgent("a1")
agent2 = DataAnalystAgent("a2")
```

### 2. Register Agents

Always register agents with the registry for discovery:

```python
registry = AgentRegistry()
agent = DataEngineerAgent("eng_001", event_bus=registry.event_bus)
registry.register(agent)  # Essential for discovery
```

### 3. Use Skill-Based Assignment

Let the framework match tasks to agents:

```python
# Good - automatic matching
task = Task(
    type="optimize_query",
    required_skills={"sql": 0.8, "performance_tuning": 0.7},
)

for agent in registry.find_available():
    can_do, confidence = agent.can_do(task)
    if can_do and confidence > 0.85:
        await agent.accept_task(task)
        break
```

### 4. Monitor Metrics

Track agent performance:

```python
import asyncio

async def monitor_agents():
    while True:
        for agent in registry.agents.values():
            metrics = agent.get_metrics()
            if metrics["success_rate"] < 0.8:
                logger.warning(f"Agent {agent.agent_id} has low success rate")

        await asyncio.sleep(60)
```

### 5. Handle Failures Gracefully

```python
try:
    result = await agent.execute_task(task)
except Exception as e:
    logger.error(f"Task {task.id} failed: {e}")
    # Task automatically marked as FAILED
    # Metrics updated
    # Failure event published
```

## Testing

```bash
cd python
pip install -e ".[dev,api,agents-api,security,database]"
pytest tests            # agent framework, REST/WebSocket API, security (SQLite)
```

Run the API suite against PostgreSQL (the production database):

```bash
AGENT_API_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/agents_test \
  pytest tests/agents/api
```

The suite covers the cognitive cycle, skills/tasks, teams and registry, personas,
orchestration, intelligence modules, and the API (authentication and authorisation,
rate limiting, request hardening, agents/teams/tasks/workflows/knowledge, restart
persistence, cancellation, shutdown and the WebSocket stream).

## Running the API (REST + WebSocket)

`unistax.agents.api` exposes the framework over HTTP and WebSocket. It is a
**single-process service** backed by a SQL database (see [Limits](#limits)).

### Quick start

```bash
pip install "unistax[agents-api]"

export UNISTAX_AGENT_API_JWT_SECRET=$(openssl rand -hex 32)   # >= 32 chars, required
python -m unistax.agents.api                                  # http://0.0.0.0:8000

# an access token for yourself (admin/operator/viewer)
TOKEN=$(python -m unistax.agents.api.auth --subject me --role admin)

curl -X POST localhost:8000/api/v1/agents -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"agent_id":"eng_1","persona":"engineer"}'
curl -X POST localhost:8000/api/v1/tasks  -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' \
     -d '{"task_type":"quality_check","context":{"table":"orders"}}'
```

OpenAPI docs are served at `/api/v1/docs`. Embed it instead with
`create_agent_api(settings)`, or run `uvicorn --factory unistax.agents.api.app:create_agent_api`.
The service **refuses to start** with authentication enabled and no signing key.

### Configuration

Environment variables (prefix `UNISTAX_AGENT_API_`); see `settings.py` for the full list.

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET` / `JWT_PUBLIC_KEY` | none (required) | Signing secret (HS*, min 32/48/64 chars) or verification key (RS*/ES*) |
| `JWT_ALGORITHM`, `JWT_AUDIENCE`, `JWT_ISSUER` | `HS256`, none, none | Token validation |
| `AUTH_ENABLED` | `true` | `false` disables auth entirely (everyone is admin). Never in production |
| `DATABASE_URL` | `sqlite+aiosqlite:///./agents.db` | Use `postgresql+asyncpg://user:pass@host/db` in production |
| `AUTO_CREATE_TABLES` | `true` | Creates missing tables at startup; it does not migrate existing ones |
| `RESTORE_ON_START` | `true` | Rebuild agents, teams and the knowledge graph from the database |
| `CORS_ORIGINS` | none | Comma-separated origins. `*` is rejected |
| `RATE_LIMIT`, `RATE_LIMIT_WINDOW` | `120` / `60` | Requests per caller per window |
| `EXPENSIVE_RATE_LIMIT` | `30` | Tighter cap for starting tasks/workflows |
| `MAX_RUNNING_TASKS` | `20` | Global cap on concurrently executing tasks |
| `MAX_REQUEST_BYTES` | `1048576` | Request body limit (413 above it) |
| `SHUTDOWN_TIMEOUT` | `15` | Seconds running work may finish before being cancelled |
| `WS_MAX_CONNECTIONS`, `WS_QUEUE_SIZE` | `100` / `256` | WebSocket cap and per-connection backlog |
| `DOCS_ENABLED` | `true` | Serve `/api/v1/docs`, `/redoc`, `/openapi.json` |

### Authentication and roles

Send `Authorization: Bearer <jwt>`. Tokens must be signed with the configured key,
carry `sub` and `exp`, and a `role` (or `roles`) claim:

| Role | Can |
|---|---|
| `viewer` | Read everything; subscribe to the event stream |
| `operator` | + submit/cancel tasks, create/run/cancel workflows, write to the knowledge graph, see `agent_message` events |
| `admin` | + create/update/delete agents and teams |

Tokens without an expiry, with an unknown role, or signed with another key are rejected.
`/health/live` and `/health/ready` need no token.

### Endpoints (all under `/api/v1`)

| Area | Endpoints |
|---|---|
| Agents | `POST/GET /agents`, `GET/PATCH/DELETE /agents/{id}` |
| Tasks | `POST /tasks` (202), `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/cancel` |
| Teams | `POST/GET /teams`, `GET/PATCH/DELETE /teams/{id}`, `GET /teams/{id}/members` |
| Discovery | `GET /discovery/by-persona/{p}`, `/by-skill`, `/by-team/{id}`, `POST /discovery/for-task`, `GET /discovery/statistics` |
| Workflows | `POST/GET /workflows`, `GET /workflows/{id}[/status]`, `POST /workflows/{id}/execute` (202), `POST /workflows/{id}/cancel`, `DELETE /workflows/{id}` |
| Knowledge | `POST/GET /knowledge/nodes`, `GET /knowledge/nodes/{id}[/edges\|/dependencies\|/consumers\|/producers]`, `POST /knowledge/edges`, `POST/GET /knowledge/best-practices`, `POST /knowledge/issues`, `GET /knowledge/statistics` |
| Metrics | `GET /metrics/system`, `GET /metrics/agents/{id}`, `GET /metrics/prometheus` |
| Events | `WS /ws/events`, `WS /ws/agents/{agent_id}` |

List endpoints are paginated (`page`, `page_size` <= 200). Successful responses use
the `APIResponse` envelope (`{"success", "data", "message"}`); errors are
`{"detail": ...}` with 401/403/404/409/413/422/429 as appropriate.

### Task and workflow semantics

- `POST /tasks` validates the request, picks an agent, **queues** the task and returns
  `202` immediately. Poll `GET /tasks/{id}` or watch the event stream.
- Without `agent_id`, the agent is chosen from those whose persona supports the task type
  and whose skills meet `required_skills` (best skill match, then least loaded). Unsupported
  types and unmatched skills are `422`.
- Tasks for a busy agent wait for a free slot (`max_concurrent_tasks`) rather than failing.
- Statuses: `pending → in_progress → completed | failed | cancelled`.
- Workflows are validated on creation (unknown dependencies, cycles, unsupported task
  types are `422`). A failed step marks its dependents `skipped` and the workflow `failed`.
- **Restarts do not resume work.** Tasks and workflows that were queued or running when the
  process stopped are marked `failed` ("Interrupted by server restart" / "...shutdown") so
  nothing is silently lost or silently re-run.

### WebSocket event stream

Authenticate with the `Authorization` header, or (browsers) send
`{"action":"auth","token":"<jwt>"}` as the first message. Tokens in the URL are not accepted.
Then optionally filter: `{"action":"subscribe","event_types":["task_completed"],"agent_id":"eng_1"}`.
Event types: `task_assigned`, `task_completed`, `task_failed`, `agent_state_changed`,
`agent_message` (operator+), `collaboration_requested`, `workflow_finished`.
Slow consumers are disconnected (close code 1013) instead of blocking the service;
auth failures close with 4401/4403.

### Observability

`X-Request-ID` is accepted/generated, returned, and attached to log records.
`/metrics/prometheus` exposes gauges (agents, tasks and workflows by status, queue depth,
WebSocket connections); scrape it with a bearer token. `/health/live` and `/health/ready`
(database reachable) are for orchestrator probes.

### Deployment

```bash
cd python
docker build -f Dockerfile.agent-api -t unistax-agent-api .
docker compose -f docker-compose.agent-api.yml up        # API + PostgreSQL
```

### Limits

Know these before relying on the service:

- **One process, one replica.** Agents, scheduling, the event stream and rate-limit counters
  live in process memory. Running several workers/replicas gives each its own agents and
  limits. Horizontal scale needs the Phase 4 items (shared messaging, distributed agents).
- **No resume after a crash or restart** (see above). Only tasks, workflows, agents, teams
  and the knowledge graph are persisted.
- **Schema creation only.** `AUTO_CREATE_TABLES` creates missing tables; there are no
  migrations yet, so schema changes need a manual migration (Alembic is recommended).
- Rate limits are per caller and per process; terminate TLS and enforce global limits at
  your gateway. Behind a proxy set `FORWARDED_ALLOW_IPS`.
- Persona task handlers are currently **simulations** that return representative results;
  they do not touch real warehouses or pipelines until you implement them.
- `unistax.agents.task_integration` (Celery) is a scaffold: the worker task is a placeholder
  and is not used by the API.

## Intelligence Features

The agent framework includes advanced intelligence capabilities that enable agents to learn, plan, and optimize collaboratively.

### Reinforcement Learning

Add Q-learning to any persona by mixing in `RLAgent`:

```python
from unistax.agents import DataEngineerAgent
from unistax.agents.intelligence import RLAgent


class SmartEngineer(RLAgent, DataEngineerAgent):
    """Engineer that learns which action to take from experience."""


agent = SmartEngineer("eng_rl")
agent.enable_rl_learning(learning_rate=0.1, exploration_rate=0.2)

state = agent.get_current_state()  # tasks_pending, success_rate, ...
action = agent.rl_policy.select_action(state, ["process_task", "wait", "delegate"])

# ... perform the action, observe the outcome ...
reward = agent.calculate_reward(finished_task)
agent.rl_policy.record_experience(state, action, reward, agent.get_current_state())
agent.rl_policy.train_on_batch(batch_size=32)  # replay + exploration decay

agent.rl_policy.save_policy("policy.json")  # and .load_policy(...)
```

**Key Features:**
- Q-learning for state-action value estimation
- Experience replay buffer for batch learning
- Epsilon-greedy exploration strategy with decay
- Save/load policies for persistence

### Knowledge Graph

Agents share knowledge and best practices through a collaborative knowledge graph:

```python
from unistax.agents.intelligence import AgentKnowledgeGraph, NodeType, RelationType

# Create shared knowledge graph
kg = AgentKnowledgeGraph()

# Agent adds knowledge about a dataset
kg.add_node(
    node_id="customers_table",
    node_type=NodeType.DATASET,
    properties={
        "table": "dim_customers",
        "size_mb": 450,
        "quality_score": 0.95,
    },
    agent_id="steward_001",
)

# Track data lineage
kg.add_edge(
    source_id="etl_pipeline_001",
    target_id="customers_table",
    relation_type=RelationType.PRODUCES,
    agent_id="engineer_001",
)

# Share best practice
kg.add_best_practice(
    practice_id="bp_data_quality",
    topic="data_quality",
    description="Always validate foreign keys before loading dimension tables",
    agent_id="engineer_002",
    related_nodes=["customers_table"],
)

# Query knowledge
dependencies = kg.get_dependencies("customers_table")
consumers = kg.get_consumers("customers_table")
best_practices = kg.get_best_practices(topic="data_quality")
```

**Key Features:**
- Graph-based knowledge representation
- Node types: datasets, pipelines, models, agents, tasks, insights, best practices, issues
- Relationship types: dependencies, production, consumption, training, execution
- Transitive dependency resolution
- Best practice sharing
- Issue tracking and impact analysis

### HTN Planning

Hierarchical Task Network planning enables agents to decompose complex tasks:

```python
from unistax.agents.intelligence import HTNPlanner, HTNTask, HTNMethod, HTNOperator, TaskType

# Create HTN planner
planner = HTNPlanner()

# Define primitive operators
fetch_op = HTNOperator(
    name="fetch_data",
    preconditions={"source": "available"},
    effects={"data": "fetched"},
)
clean_op = HTNOperator(
    name="clean_data",
    preconditions={"data": "fetched"},
    effects={"data": "clean"},
)
analyze_op = HTNOperator(
    name="analyze_data",
    preconditions={"data": "clean"},
    effects={"result": "ready"},
)

planner.add_operator(fetch_op)
planner.add_operator(clean_op)
planner.add_operator(analyze_op)

# Define compound task
full_analysis = HTNTask("complete_analysis", TaskType.COMPOUND)
planner.add_task(full_analysis)

# Define decomposition method
method = HTNMethod(
    name="standard_analysis_method",
    task_name="complete_analysis",
    subtasks=[
        HTNTask("fetch_data", TaskType.PRIMITIVE),
        HTNTask("clean_data", TaskType.PRIMITIVE),
        HTNTask("analyze_data", TaskType.PRIMITIVE),
    ],
)
planner.add_method(method)

# Generate plan
initial_state = {"source": "available"}
plan = planner.plan(full_analysis, initial_state)

# Execute plan
final_state = planner.execute_plan(plan, initial_state)
```

**Key Features:**
- Hierarchical task decomposition
- Multiple decomposition methods per task
- Precondition checking
- State-based planning
- Plan validation and execution

### Swarm Intelligence

Collaborative optimization using nature-inspired algorithms:

**Ant Colony Optimization (ACO)** for path finding and task allocation:

```python
from unistax.agents.intelligence import AntColonyOptimizer

# Create ACO optimizer
aco = AntColonyOptimizer(
    n_ants=20,
    alpha=1.0,  # Pheromone importance
    beta=2.0,   # Heuristic importance
    evaporation_rate=0.1,
)

# Add task graph edges
aco.add_edge("task_A", "task_B", distance=2.0)
aco.add_edge("task_B", "task_C", distance=3.0)
aco.add_edge("task_A", "task_C", distance=6.0)

# Find optimal path
best_path, best_cost = aco.optimize(
    start="task_A",
    goal="task_C",
    n_iterations=100,
)
print(f"Best path: {best_path}, Cost: {best_cost}")
```

**Particle Swarm Optimization (PSO)** for hyperparameter tuning:

```python
from unistax.agents.intelligence import ParticleSwarmOptimizer
import numpy as np

# Define objective function (e.g., model performance)
def evaluate_hyperparameters(params):
    learning_rate, batch_size, dropout = params
    # Train model and return validation error
    return validation_error

# Create PSO optimizer
pso = ParticleSwarmOptimizer(
    n_particles=30,
    dimensions=3,
    bounds=[
        (0.0001, 0.1),    # learning_rate
        (16, 128),        # batch_size
        (0.0, 0.5),       # dropout
    ],
    objective_func=evaluate_hyperparameters,
    minimize=True,
)

# Optimize
best_params, best_score = pso.optimize(n_iterations=100)
print(f"Best hyperparameters: {best_params}, Score: {best_score}")
```

**Key Features:**
- Ant Colony Optimization for discrete path finding
- Particle Swarm Optimization for continuous optimization
- Pheromone-based learning (ACO)
- Velocity-based exploration (PSO)
- Configurable swarm parameters

### Using Intelligence Features with Agents

The mixins are cooperative, so they combine with each other (in any order) and with
any persona:

```python
from unistax.agents import DataEngineerAgent
from unistax.agents.intelligence import HTNAgent, RLAgent, SwarmAgent


class IntelligentEngineer(RLAgent, HTNAgent, SwarmAgent, DataEngineerAgent):
    pass


agent = IntelligentEngineer("eng_1")
agent.enable_rl_learning()          # agent.rl_policy
agent.setup_aco(n_ants=10)          # agent.aco
agent.htn_planner.add_operator(...)  # agent.htn_planner
```

## Roadmap

### Phase 1: Core Framework (Completed ✅)
- [x] Base agent class with cognitive cycle
- [x] Skills and task management
- [x] Hierarchical teams
- [x] Agent registry and discovery
- [x] Data Engineer persona
- [x] Data Analyst persona
- [x] EventBus integration
- [x] Metrics tracking
- [x] Comprehensive tests

### Phase 2: Advanced Features (Completed ✅)
- [ ] Task queue integration (unistax.tasks + Celery): scaffold only, the worker task is a placeholder (the API schedules tasks in-process)
- [x] Security integration (JWT, rate limiting) in the REST API; secrets via `unistax.secrets`
- [x] Data Scientist persona
- [x] Data Steward persona
- [x] Orchestrator for multi-agent workflows

### Phase 3: Intelligence (Completed ✅)
- [x] ML-based decision making (Reinforcement Learning)
- [x] Knowledge graph integration
- [x] HTN (Hierarchical Task Network) planning
- [x] Swarm intelligence algorithms (ACO, PSO)

### API and Production Hardening (Completed ✅)
- [x] REST + WebSocket API with JWT auth, roles, rate limiting, request hardening
- [x] Database persistence (SQLite/PostgreSQL) for agents, teams, tasks, workflows, knowledge graph
- [x] Graceful shutdown, restart recovery, health probes, Prometheus metrics
- [x] Docker image + compose, CI job (SQLite + PostgreSQL)
- [ ] Schema migrations (Alembic)
- [ ] Resume/retry of interrupted work
- [ ] Real persona implementations (current handlers are simulations)

### Phase 4: Scale (Future 🔮)
- [ ] Redis-based distributed messaging
- [ ] Agent persistence and recovery
- [ ] Load balancing across agents
- [ ] Multi-datacenter agent deployment

## Examples

See `python/examples/` for complete working examples:

- `agent_collaboration_demo.py` - Basic agent collaboration (in-process)
- See "Running the API" above for HTTP usage
- More examples coming soon!

## Contributing

When adding new agent personas:

1. Extend the `Agent` base class
2. Implement `decide()` and `execute_task()`
3. Define default skills
4. Add persona-specific methods
5. Write comprehensive tests
6. Update this documentation

## License

Part of the Unistax project.
