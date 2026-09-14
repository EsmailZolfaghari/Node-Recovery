"""Node model representing a logical node in the system."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    """Get current UTC time using timezone-aware datetime."""
    return datetime.now(timezone.utc)


class NodeStatus(Enum):
    """Status of a node."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    FAILED = "failed"
    REPLACING = "replacing"
    MAINTENANCE = "maintenance"


@dataclass
class Node:
    """Represents a logical node in the system.

    A Node is a logical entity that can be backed by different VPS instances
    over time through replacement operations.
    """

    id: int
    name: str
    description: str | None = None
    provider: str | None = None
    region: str | None = None
    status: NodeStatus = NodeStatus.HEALTHY

    # Current VPS information
    current_vps_id: str | None = None
    current_ip: str | None = None

    # Health tracking
    consecutive_failures: int = 0
    last_health_check: datetime | None = None
    last_successful_check: datetime | None = None

    # Replacement tracking
    active_replacement_job_id: int | None = None
    replacement_history: list[int] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_healthy(self) -> None:
        """Mark node as healthy."""
        self.status = NodeStatus.HEALTHY
        self.consecutive_failures = 0
        self.last_health_check = _now()
        self.last_successful_check = _now()
        self.updated_at = _now()

    def mark_unhealthy(self) -> None:
        """Mark node as unhealthy."""
        self.status = NodeStatus.UNHEALTHY
        self.consecutive_failures += 1
        self.last_health_check = _now()
        self.updated_at = _now()

    def mark_failed(self) -> None:
        """Mark node as failed."""
        self.status = NodeStatus.FAILED
        self.last_health_check = _now()
        self.updated_at = _now()

    def mark_replacing(self, job_id: int) -> None:
        """Mark node as being replaced."""
        self.status = NodeStatus.REPLACING
        self.active_replacement_job_id = job_id
        self.updated_at = _now()

    def clear_replacement(self) -> None:
        """Clear active replacement after completion."""
        if self.active_replacement_job_id is not None:
            self.replacement_history.append(self.active_replacement_job_id)
        self.active_replacement_job_id = None
        self.updated_at = _now()

    def update_vps_info(self, vps_id: str, ip: str) -> None:
        """Update VPS information for this node."""
        self.current_vps_id = vps_id
        self.current_ip = ip
        self.updated_at = _now()

    def is_replaceable(self) -> bool:
        """Check if node can be replaced."""
        return self.status in (NodeStatus.FAILED, NodeStatus.UNHEALTHY) and (
            self.active_replacement_job_id is None
        )

    @property
    def can_be_replaced(self) -> bool:
        """Check if node can be replaced (property alias)."""
        return self.is_replaceable()

    @property
    def vps_id(self) -> str | None:
        """Get current VPS ID (alias for current_vps_id)."""
        return self.current_vps_id

    @property
    def ip_address(self) -> str | None:
        """Get current IP address (alias for current_ip)."""
        return self.current_ip

    @property
    def replacement_in_progress(self) -> bool:
        """Check if replacement is in progress."""
        return self.active_replacement_job_id is not None

    @replacement_in_progress.setter
    def replacement_in_progress(self, value: bool) -> None:
        """Set replacement in progress flag.
        
        Note: This setter only clears the flag. To set it to True,
        use mark_replacing(job_id) method instead, since we need
        the actual job_id.
        """
        if not value:
            self.active_replacement_job_id = None
        # Setting to True requires a job_id, use mark_replacing() instead

    @property
    def master_node_id(self) -> str | None:
        """Get master node ID from metadata."""
        if self.metadata and "master_node_id" in self.metadata:
            return self.metadata.get("master_node_id")
        return self.name  # Fallback to node name
