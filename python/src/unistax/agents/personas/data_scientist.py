"""Data Scientist Agent Persona.

Specialized agent for data science and machine learning tasks including:
- ML model training and evaluation
- Feature engineering and selection
- Experiment tracking and management
- Model deployment and monitoring
- Statistical analysis and hypothesis testing
"""

from typing import Any, ClassVar

from unistax.agents.base import Agent, AgentState, Skill, Task
from unistax.events import EventBus
from unistax.logging import get_logger
from unistax.metrics import MetricsManager

logger = get_logger(__name__)


class DataScientistAgent(Agent):
    """Data Scientist agent persona.

    Capabilities:
    - Train and evaluate ML models
    - Perform feature engineering
    - Run experiments and A/B tests
    - Deploy models to production
    - Monitor model performance
    - Collaborate on ML pipelines

    Examples:
        >>> # Create registry and shared infrastructure
        >>> from unistax.agents import AgentRegistry, Skill
        >>> from unistax.metrics import MetricsManager
        >>>
        >>> registry = AgentRegistry()
        >>>
        >>> # Create data scientist with skills
        >>> scientist = DataScientistAgent(
        ...     agent_id="ds_001",
        ...     event_bus=registry.event_bus,
        ...     metrics_manager=registry.metrics_manager,
        ...     skills=[
        ...         Skill("python", 0.95, "programming"),
        ...         Skill("machine_learning", 0.90, "ml"),
        ...         Skill("statistics", 0.90, "analytics"),
        ...         Skill("deep_learning", 0.85, "ml"),
        ...     ]
        ... )
        >>> registry.register(scientist)
    """

    TASK_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "train_model",
            "evaluate_model",
            "engineer_features",
            "run_experiment",
            "deploy_model",
            "tune_hyperparameters",
            "analyze_model",
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
        """Initialize Data Scientist agent.

        Args:
            agent_id: Unique identifier for agent
            event_bus: Shared EventBus for communication
            metrics_manager: Shared MetricsManager for metrics
            skills: Custom skills (uses defaults if None)
            team_id: Team this agent belongs to
            **kwargs: Additional Agent constructor arguments
        """
        # Default skills for Data Scientist
        default_skills = [
            Skill("python", 0.95, "programming"),
            Skill("machine_learning", 0.90, "ml"),
            Skill("statistics", 0.90, "analytics"),
            Skill("deep_learning", 0.85, "ml"),
            Skill("feature_engineering", 0.85, "ml"),
            Skill("experiment_design", 0.80, "research"),
            Skill("model_deployment", 0.75, "ml_ops"),
            Skill("sql", 0.70, "database"),
        ]

        super().__init__(
            agent_id=agent_id,
            persona="data_scientist",
            skills=skills or default_skills,
            event_bus=event_bus,
            metrics_manager=metrics_manager,
            team_id=team_id,
            **kwargs,
        )

        # Data Scientist specific attributes
        self.models_trained: set[str] = set()
        self.experiments_run: int = 0
        self.models_deployed: int = 0
        self.features_engineered: int = 0

        logger.info(f"Data Scientist {agent_id} initialized")

    async def decide(self) -> str | None:
        """Decide what action to take next.

        Decision priority:
        1. Execute assigned tasks
        2. Monitor deployed models (if idle)
        3. Run scheduled experiments
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
        if self.state == AgentState.IDLE and self.models_trained:
            return "proactive_monitor"

        # Nothing to do
        return None

    async def execute_task(self, task: Task) -> Any:
        """Execute a data science task.

        Supports task types:
        - train_model: Train ML model
        - evaluate_model: Evaluate model performance
        - engineer_features: Create new features
        - run_experiment: Run A/B test or experiment
        - deploy_model: Deploy model to production
        - tune_hyperparameters: Optimize model parameters
        - analyze_model: Analyze model behavior

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

        if task_type == "train_model":
            return await self._train_model(context)

        elif task_type == "evaluate_model":
            return await self._evaluate_model(context)

        elif task_type == "engineer_features":
            return await self._engineer_features(context)

        elif task_type == "run_experiment":
            return await self._run_experiment(context)

        elif task_type == "deploy_model":
            return await self._deploy_model(context)

        elif task_type == "tune_hyperparameters":
            return await self._tune_hyperparameters(context)

        elif task_type == "analyze_model":
            return await self._analyze_model(context)

        else:
            raise ValueError(f"Unknown task type: {task_type}")

    # ========================================================================
    # Task execution methods
    # ========================================================================

    async def _train_model(self, context: dict[str, Any]) -> dict[str, Any]:
        """Train a machine learning model.

        Args:
            context: Model training specification

        Returns:
            Training result
        """
        model_name = context.get("name", "unnamed_model")
        model_type = context.get("type", "classification")
        features = context.get("features", [])

        logger.info(f"{self.agent_id} training model: {model_name}")

        # Simulate model training
        # In real implementation, this would:
        # 1. Load and prepare data
        # 2. Split train/validation sets
        # 3. Train model (sklearn, tensorflow, pytorch)
        # 4. Track with MLflow or similar
        # 5. Save model artifacts

        self.models_trained.add(model_name)

        return {
            "status": "success",
            "model_name": model_name,
            "model_type": model_type,
            "metrics": {
                "accuracy": 0.89,
                "precision": 0.87,
                "recall": 0.91,
                "f1_score": 0.89,
            },
            "training_time_minutes": 12.5,
            "features_used": len(features),
            "model_path": f"/models/{model_name}/v1",
        }

    async def _evaluate_model(self, context: dict[str, Any]) -> dict[str, Any]:
        """Evaluate model performance.

        Args:
            context: Evaluation specification

        Returns:
            Evaluation result
        """
        model_name = context.get("model", "")
        test_dataset = context.get("test_dataset", "")

        logger.info(f"{self.agent_id} evaluating model: {model_name}")

        # Simulate model evaluation
        # In real implementation, this would:
        # 1. Load model and test data
        # 2. Generate predictions
        # 3. Calculate metrics
        # 4. Create confusion matrix
        # 5. Analyze errors

        return {
            "status": "success",
            "model_name": model_name,
            "test_dataset": test_dataset,
            "metrics": {
                "accuracy": 0.91,
                "precision": 0.89,
                "recall": 0.93,
                "f1_score": 0.91,
                "auc_roc": 0.95,
            },
            "confusion_matrix": [[450, 50], [30, 470]],
            "samples_tested": 1000,
        }

    async def _engineer_features(self, context: dict[str, Any]) -> dict[str, Any]:
        """Engineer new features from data.

        Args:
            context: Feature engineering specification

        Returns:
            Feature engineering result
        """
        dataset = context.get("dataset", "")

        logger.info(f"{self.agent_id} engineering features for: {dataset}")

        # Simulate feature engineering
        # In real implementation, this would:
        # 1. Analyze existing features
        # 2. Create derived features
        # 3. Select best features (correlation, importance)
        # 4. Validate feature quality
        # 5. Document feature definitions

        self.features_engineered += 1

        return {
            "status": "success",
            "dataset": dataset,
            "features_created": [
                {"name": "customer_lifetime_months", "type": "numeric", "importance": 0.85},
                {"name": "purchase_frequency_ratio", "type": "numeric", "importance": 0.78},
                {"name": "avg_basket_size", "type": "numeric", "importance": 0.72},
                {"name": "seasonality_index", "type": "numeric", "importance": 0.65},
            ],
            "total_features": 4,
            "feature_importance_method": "random_forest",
        }

    async def _run_experiment(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run an experiment or A/B test.

        Args:
            context: Experiment specification

        Returns:
            Experiment result
        """
        experiment_name = context.get("name", "")
        variants = context.get("variants", ["A", "B"])

        logger.info(f"{self.agent_id} running experiment: {experiment_name}")

        # Simulate experiment
        # In real implementation, this would:
        # 1. Design experiment (power analysis)
        # 2. Split traffic to variants
        # 3. Collect metrics
        # 4. Perform statistical tests
        # 5. Determine winner

        self.experiments_run += 1

        return {
            "status": "success",
            "experiment_name": experiment_name,
            "variants": variants,
            "results": {
                "A": {"conversion_rate": 0.045, "samples": 5000},
                "B": {"conversion_rate": 0.052, "samples": 5000},
            },
            "statistical_significance": True,
            "p_value": 0.012,
            "winner": "B",
            "lift": "+15.6%",
        }

    async def _deploy_model(self, context: dict[str, Any]) -> dict[str, Any]:
        """Deploy model to production.

        Args:
            context: Deployment specification

        Returns:
            Deployment result
        """
        model_name = context.get("model", "")
        environment = context.get("environment", "production")

        logger.info(f"{self.agent_id} deploying model: {model_name} to {environment}")

        # Simulate model deployment
        # In real implementation, this would:
        # 1. Package model artifacts
        # 2. Create serving endpoint
        # 3. Configure monitoring
        # 4. Run smoke tests
        # 5. Enable traffic

        self.models_deployed += 1

        return {
            "status": "success",
            "model_name": model_name,
            "environment": environment,
            "endpoint": f"https://api.example.com/models/{model_name}/predict",
            "version": "v1.0.0",
            "deployment_time": "2024-01-15 14:30:00",
            "monitoring_enabled": True,
        }

    async def _tune_hyperparameters(self, context: dict[str, Any]) -> dict[str, Any]:
        """Optimize model hyperparameters.

        Args:
            context: Hyperparameter tuning specification

        Returns:
            Tuning result
        """
        model_name = context.get("model", "")
        method = context.get("method", "grid_search")

        logger.info(f"{self.agent_id} tuning hyperparameters for: {model_name}")

        # Simulate hyperparameter tuning
        # In real implementation, this would:
        # 1. Define parameter space
        # 2. Run optimization (grid, random, bayesian)
        # 3. Cross-validate each configuration
        # 4. Select best parameters
        # 5. Retrain with optimal config

        return {
            "status": "success",
            "model_name": model_name,
            "method": method,
            "best_params": {
                "learning_rate": 0.001,
                "max_depth": 8,
                "n_estimators": 200,
                "min_samples_split": 10,
            },
            "best_score": 0.93,
            "trials_run": 150,
            "improvement": "+3.2%",
        }

    async def _analyze_model(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze model behavior and performance.

        Args:
            context: Analysis specification

        Returns:
            Analysis result
        """
        model_name = context.get("model", "")
        analysis_type = context.get("type", "feature_importance")

        logger.info(f"{self.agent_id} analyzing model: {model_name}")

        # Simulate model analysis
        # In real implementation, this would:
        # 1. Load model and data
        # 2. Run SHAP or LIME
        # 3. Analyze feature importance
        # 4. Check for bias
        # 5. Generate explanations

        return {
            "status": "success",
            "model_name": model_name,
            "analysis_type": analysis_type,
            "insights": [
                {
                    "finding": "Customer age is most important feature",
                    "importance": 0.28,
                },
                {
                    "finding": "Purchase frequency highly predictive",
                    "importance": 0.22,
                },
                {
                    "finding": "Seasonal patterns detected",
                    "importance": 0.18,
                },
            ],
            "potential_issues": [
                "Slight gender bias detected (5% difference)",
                "Model performance degrades for age > 65",
            ],
        }

    # ========================================================================
    # Proactive behaviors
    # ========================================================================

    async def _proactive_monitor(self):
        """Proactively monitor deployed models.

        This runs when the agent is idle to detect model drift and issues.
        """
        logger.info(f"{self.agent_id} performing proactive model monitoring")

        # In real implementation, this would:
        # 1. Check model performance metrics
        # 2. Detect data drift
        # 3. Analyze prediction distributions
        # 4. Create alerts for issues
        # 5. Trigger retraining if needed

        logger.debug(f"{self.agent_id} monitored {len(self.models_trained)} models")

    def add_model(self, model_name: str):
        """Add a model to monitor.

        Args:
            model_name: Model identifier
        """
        self.models_trained.add(model_name)
        logger.info(f"{self.agent_id} now monitoring model: {model_name}")

    def get_scientist_stats(self) -> dict[str, Any]:
        """Get data scientist specific statistics.

        Returns:
            Statistics dictionary
        """
        base_metrics = self.get_metrics()

        return {
            **base_metrics,
            "models_trained": len(self.models_trained),
            "experiments_run": self.experiments_run,
            "models_deployed": self.models_deployed,
            "features_engineered": self.features_engineered,
        }
