"""Event model for audit and history tracking."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    """Get current UTC time using timezone-aware datetime."""
    return datetime.now(timezone.utc)


class EventType(Enum):
    """Types of events in the system."""

    # Node events
    NODE_HEALTH_CHECK = "node_health_check"
    NODE_STATUS_CHANGED = "node_status_changed"
    NODE_FAILURE_DETECTED = "node_failure_detected"
    NODE_FAILURE_CONFIRMED = "node_failure_confirmed"

    # Replacement events
    REPLACEMENT_JOB_CREATED = "replacement_job_created"
    REPLACEMENT_JOB_STARTED = "replacement_job_started"
    REPLACEMENT_STAGE_ADVANCED = "replacement_stage_advanced"
    REPLACEMENT_JOB_COMPLETED = "replacement_job_completed"
    REPLACEMENT_JOB_FAILED = "replacement_job_failed"
    REPLACEMENT_JOB_CANCELLED = "replacement_job_cancelled"
    REPLACEMENT_RETRY_STARTED = "replacement_retry_started"

    # VPS events
    VPS_CREATED = "vps_created"
    VPS_IP_CHECKED = "vps_ip_checked"
    VPS_IP_REJECTED = "vps_ip_rejected"
    VPS_DELETED = "vps_deleted"
    VPS_DELETE_FAILED = "vps_delete_failed"

    # SSH events
    SSH_CONNECTED = "ssh_connected"
    SSH_CONNECTION_FAILED = "ssh_connection_failed"

    # Deployment events
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETED = "deployment_completed"
    DEPLOYMENT_FAILED = "deployment_failed"
    DEPLOYMENT_VERIFIED = "deployment_verified"
    DEPLOYMENT_VERIFICATION_FAILED = "deployment_verification_failed"

    # Master events
    MASTER_UPDATE_STARTED = "master_update_started"
    MASTER_UPDATED = "master_updated"
    MASTER_UPDATE_FAILED = "master_update_failed"
    MASTER_VERIFIED = "master_verified"
    MASTER_VERIFICATION_FAILED = "master_verification_failed"

    # System events
    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"
    SYSTEM_ERROR = "system_error"
    CONFIG_CHANGED = "config_changed"


@dataclass
class Event:
    """Represents an event in the system.

    Events are used for audit logging, debugging, and providing
    visibility into system operations.
    """

    id: int | None = None
    event_type: EventType = EventType.NODE_HEALTH_CHECK

    # Entity references
    node_id: int | None = None
    node_name: str | None = None
    replacement_job_id: int | None = None
    vps_id: str | None = None

    # Event data
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    # Severity
    level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Timing
    created_at: datetime = field(default_factory=_now)

    # IMPORTANT: This field should NEVER contain secrets
    # All sensitive data must be redacted before storing
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary representation."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "replacement_job_id": self.replacement_job_id,
            "vps_id": self.vps_id,
            "message": self.message,
            "details": self.details,
            "level": self.level,
            "created_at": self.created_at.isoformat(),
            "redacted": self.redacted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Create event from dictionary representation."""
        return cls(
            id=data.get("id"),
            event_type=EventType(data["event_type"]),
            node_id=data.get("node_id"),
            node_name=data.get("node_name"),
            replacement_job_id=data.get("replacement_job_id"),
            vps_id=data.get("vps_id"),
            message=data.get("message", ""),
            details=data.get("details", {}),
            level=data.get("level", "INFO"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data and isinstance(data["created_at"], str)
            else _now(),
            redacted=data.get("redacted", False),
        )


def create_event(
    event_type: EventType,
    message: str,
    node_id: int | None = None,
    node_name: str | None = None,
    replacement_job_id: int | None = None,
    vps_id: str | None = None,
    details: dict[str, Any] | None = None,
    level: str = "INFO",
) -> Event:
    """Factory function to create an event.

    This function ensures proper event creation with all required fields.
    """
    return Event(
        event_type=event_type,
        message=message,
        node_id=node_id,
        node_name=node_name,
        replacement_job_id=replacement_job_id,
        vps_id=vps_id,
        details=details or {},
        level=level,
    )
