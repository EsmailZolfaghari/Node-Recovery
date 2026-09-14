"""Replacement job model and stage definitions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    """Get current UTC time using timezone-aware datetime."""
    return datetime.now(timezone.utc)


class ReplacementStage(Enum):
    """Stages of a replacement job."""

    PENDING = "pending"
    CONFIRMING_FAILURE = "confirming_failure"
    CREATING_VPS = "creating_vps"
    CHECKING_IP = "checking_ip"
    WAITING_SSH = "waiting_ssh"
    DEPLOYING_3XUI = "deploying_3xui"
    VERIFYING_DEPLOYMENT = "verifying_deployment"
    UPDATING_MASTER = "updating_master"
    VERIFYING_MASTER = "verifying_master"
    FINAL_HEALTH_CHECK = "final_health_check"
    CLEANING_UP = "cleaning_up"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplacementStatus(Enum):
    """Status of a replacement job."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ReplacementJob:
    """Represents a replacement job for a node.

    This is the core orchestrating entity that manages the entire
    replacement workflow from failure detection to old VPS cleanup.
    """

    node_id: int
    node_name: str

    # ID is optional - will be set by database after creation
    id: int | None = None

    # Stage tracking
    current_stage: ReplacementStage = ReplacementStage.PENDING
    status: ReplacementStatus = ReplacementStatus.PENDING

    # VPS tracking
    old_vps_id: str | None = None
    old_vps_ip: str | None = None
    new_vps_id: str | None = None
    new_vps_ip: str | None = None

    # Attempt tracking
    attempt_number: int = 1
    max_attempts: int = 5
    ip_check_attempts: int = 0
    max_ip_check_attempts: int = 3

    # Error tracking
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0

    # Stage progress
    stage_progress: dict[str, Any] = field(default_factory=dict)

    # Timing
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = field(default_factory=_now)

    # Flags
    old_vps_deleted: bool = False
    master_updated: bool = False
    deployment_verified: bool = False

    def start(self) -> None:
        """Start the replacement job."""
        self.status = ReplacementStatus.RUNNING
        self.current_stage = ReplacementStage.CONFIRMING_FAILURE
        self.started_at = _now()
        self.updated_at = _now()

    def advance_stage(self, stage: ReplacementStage) -> None:
        """Advance to the next stage."""
        self.current_stage = stage
        self.updated_at = _now()

    def mark_completed(self) -> None:
        """Mark job as completed."""
        self.status = ReplacementStatus.COMPLETED
        self.current_stage = ReplacementStage.COMPLETED
        self.completed_at = _now()
        self.updated_at = _now()

    def mark_failed(self, error_message: str, error_details: dict[str, Any] | None = None) -> None:
        """Mark job as failed."""
        self.status = ReplacementStatus.FAILED
        self.current_stage = ReplacementStage.FAILED
        self.error_message = error_message
        if error_details:
            self.error_details = error_details
        self.completed_at = _now()
        self.updated_at = _now()

    def mark_cancelled(self) -> None:
        """Mark job as cancelled."""
        self.status = ReplacementStatus.CANCELLED
        self.current_stage = ReplacementStage.CANCELLED
        self.completed_at = _now()
        self.updated_at = _now()

    def can_retry(self) -> bool:
        """Check if job can be retried."""
        return self.attempt_number < self.max_attempts and self.status != ReplacementStatus.COMPLETED

    def increment_attempt(self) -> None:
        """Increment attempt counter."""
        self.attempt_number += 1
        self.retry_count += 1
        self.updated_at = _now()

    def should_delete_old_vps(self) -> bool:
        """Check if old VPS should be deleted.

        CRITICAL SAFETY RULE: Only delete old VPS when:
        1. New VPS is fully deployed and verified
        2. Master has been updated and verified
        3. Final health check passed
        """
        return (
            self.status == ReplacementStatus.COMPLETED
            and self.new_vps_id is not None
            and self.new_vps_ip is not None
            and self.deployment_verified
            and self.master_updated
            and not self.old_vps_deleted
        )

    def get_progress_summary(self) -> str:
        """Get human-readable progress summary."""
        stage_descriptions = {
            ReplacementStage.PENDING: "Waiting to start",
            ReplacementStage.CONFIRMING_FAILURE: "Confirming node failure",
            ReplacementStage.CREATING_VPS: "Creating new VPS",
            ReplacementStage.CHECKING_IP: "Checking IP reachability",
            ReplacementStage.WAITING_SSH: "Waiting for SSH access",
            ReplacementStage.DEPLOYING_3XUI: "Deploying 3X-UI",
            ReplacementStage.VERIFYING_DEPLOYMENT: "Verifying deployment",
            ReplacementStage.UPDATING_MASTER: "Updating Master 3X-UI",
            ReplacementStage.VERIFYING_MASTER: "Verifying Master sync",
            ReplacementStage.FINAL_HEALTH_CHECK: "Running final health check",
            ReplacementStage.CLEANING_UP: "Cleaning up old VPS",
            ReplacementStage.COMPLETED: "Completed successfully",
            ReplacementStage.FAILED: "Failed",
            ReplacementStage.CANCELLED: "Cancelled",
        }
        return stage_descriptions.get(self.current_stage, "Unknown stage")
