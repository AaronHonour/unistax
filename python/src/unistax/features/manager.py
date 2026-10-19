"""Feature flag manager."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .storage import FeatureStorage


class FeatureStatus(str, Enum):
    """Feature status."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    ROLLOUT = "rollout"


@dataclass
class Feature:
    """Feature flag."""

    name: str
    status: FeatureStatus = FeatureStatus.DISABLED
    description: str | None = None
    rollout_percentage: int = 0
    targeting_rules: dict[str, Any] = field(default_factory=dict[str, Any])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FeatureManager:
    """Manage feature flags."""

    def __init__(self, storage: "FeatureStorage") -> None:
        """Initialize feature manager.

        Args:
            storage: Feature storage backend
        """
        self.storage = storage

    def is_enabled(
        self,
        feature_name: str,
        user_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Check if feature is enabled.

        Args:
            feature_name: Feature name
            user_id: User ID
            context: Additional context

        Returns:
            True if enabled
        """
        feature = self.storage.get(feature_name)
        if not feature:
            return False

        if feature.status == FeatureStatus.DISABLED:
            return False

        if feature.status == FeatureStatus.ENABLED:
            return True

        if feature.status == FeatureStatus.ROLLOUT:
            return self._check_rollout(feature, user_id, context)

        return False

    def enable(self, feature_name: str) -> None:
        """Enable feature.

        Args:
            feature_name: Feature name
        """
        feature = self.storage.get(feature_name) or Feature(name=feature_name)
        feature.status = FeatureStatus.ENABLED
        feature.updated_at = datetime.now(timezone.utc)
        self.storage.save(feature)

    def disable(self, feature_name: str) -> None:
        """Disable feature.

        Args:
            feature_name: Feature name
        """
        feature = self.storage.get(feature_name)
        if feature:
            feature.status = FeatureStatus.DISABLED
            feature.updated_at = datetime.now(timezone.utc)
            self.storage.save(feature)

    def set_rollout(self, feature_name: str, percentage: int) -> None:
        """Set rollout percentage.

        Args:
            feature_name: Feature name
            percentage: Rollout percentage (0-100)
        """
        feature = self.storage.get(feature_name) or Feature(name=feature_name)
        feature.status = FeatureStatus.ROLLOUT
        feature.rollout_percentage = max(0, min(100, percentage))
        feature.updated_at = datetime.now(timezone.utc)
        self.storage.save(feature)

    def _check_rollout(
        self,
        feature: Feature,
        user_id: str | None,
        context: dict[str, Any] | None,
    ) -> bool:
        """Check if user is in rollout.

        Args:
            feature: Feature
            user_id: User ID
            context: Context

        Returns:
            True if in rollout
        """
        if not user_id:
            return False

        # Simple hash-based rollout
        hash_value = hash(f"{feature.name}:{user_id}") % 100
        return hash_value < feature.rollout_percentage
