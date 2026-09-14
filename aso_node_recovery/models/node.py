"""Node model representing a logical node in the system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_healthy(self) -> None:
        """Mark node as healthy."""
        self.status = NodeStatus.HEALTHY
        self.consecutive_failures = 0
        self.last_health_check = datetime.utcnow()
        self.last_successful_check = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def mark_unhealthy(self) -> None:
        """Mark node as unhealthy."""
        self.status = NodeStatus.UNHEALTHY
        self.consecutive_failures += 1
        self.last_health_check = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def mark_failed(self) -> None:
        """Mark node as failed."""
        self.status = NodeStatus.FAILED
        self.last_health_check = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def mark_replacing(self, job_id: int) -> None:
        """Mark node as being replaced."""
        self.status = NodeStatus.REPLACING
        self.active_replacement_job_id = job_id
        self.updated_at = datetime.utcnow()

    def clear_replacement(self) -> None:
        """Clear active replacement after completion."""
        if self.active_replacement_job_id is not None:
            self.replacement_history.append(self.active_replacement_job_id)
        self.active_replacement_job_id = None
        self.updated_at = datetime.utcnow()

    def update_vps_info(self, vps_id: str, ip: str) -> None:
        """Update VPS information for this node."""
        self.current_vps_id = vps_id
        self.current_ip = ip
        self.updated_at = datetime.utcnow()

    def is_replaceable(self) -> bool:
        """Check if node can be replaced."""
        return self.status in (NodeStatus.FAILED, NodeStatus.UNHEALTHY) and (
            self.active_replacement_job_id is None
        )
