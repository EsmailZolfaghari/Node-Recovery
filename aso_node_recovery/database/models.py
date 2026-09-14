"""SQLAlchemy ORM models for database tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class NodeModel(Base):
    """Node database model."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="healthy"
    )

    # Current VPS information
    current_vps_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max length

    # Health tracking
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_successful_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Replacement tracking
    active_replacement_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("replacement_jobs.id"), nullable=True
    )
    replacement_history: Mapped[str] = mapped_column(Text, default="[]")  # JSON array

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=True, default=dict
    )

    # Relationships
    replacement_jobs: Mapped[list["ReplacementJobModel"]] = relationship(
        "ReplacementJobModel",
        back_populates="node",
        foreign_keys="ReplacementJobModel.node_id"
    )
    events: Mapped[list["EventModel"]] = relationship(
        "EventModel",
        back_populates="node",
        foreign_keys="EventModel.node_id"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        import json

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "region": self.region,
            "status": self.status,
            "current_vps_id": self.current_vps_id,
            "current_ip": self.current_ip,
            "consecutive_failures": self.consecutive_failures,
            "last_health_check": self.last_health_check.isoformat()
            if self.last_health_check
            else None,
            "last_successful_check": self.last_successful_check.isoformat()
            if self.last_successful_check
            else None,
            "active_replacement_job_id": self.active_replacement_job_id,
            "replacement_history": json.loads(self.replacement_history)
            if self.replacement_history
            else [],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata_json or {},
        }


class ReplacementJobModel(Base):
    """Replacement job database model."""

    __tablename__ = "replacement_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id"), nullable=False, index=True
    )
    node_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stage tracking
    current_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # VPS tracking
    old_vps_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    old_vps_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    new_vps_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_vps_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Attempt tracking
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    ip_check_attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_ip_check_attempts: Mapped[int] = mapped_column(Integer, default=3)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Stage progress
    stage_progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True, default=dict)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Flags
    old_vps_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    master_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    deployment_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    node: Mapped["NodeModel"] = relationship(
        "NodeModel",
        back_populates="replacement_jobs",
        foreign_keys=[node_id]
    )
    events: Mapped[list["EventModel"]] = relationship(
        "EventModel",
        back_populates="replacement_job",
        foreign_keys="EventModel.replacement_job_id"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "current_stage": self.current_stage,
            "status": self.status,
            "old_vps_id": self.old_vps_id,
            "old_vps_ip": self.old_vps_ip,
            "new_vps_id": self.new_vps_id,
            "new_vps_ip": self.new_vps_ip,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "ip_check_attempts": self.ip_check_attempts,
            "max_ip_check_attempts": self.max_ip_check_attempts,
            "error_message": self.error_message,
            "error_details": self.error_details or {},
            "retry_count": self.retry_count,
            "stage_progress": self.stage_progress or {},
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "updated_at": self.updated_at.isoformat(),
            "old_vps_deleted": self.old_vps_deleted,
            "master_updated": self.master_updated,
            "deployment_verified": self.deployment_verified,
        }


class EventModel(Base):
    """Event database model for audit logging."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Event type
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Entity references
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id"), nullable=True, index=True
    )
    node_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    replacement_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("replacement_jobs.id"), nullable=True, index=True
    )
    vps_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Event data
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True, default=dict)

    # Severity
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    # Security flag
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    node: Mapped["NodeModel"] = relationship("NodeModel", back_populates="events")
    replacement_job: Mapped["ReplacementJobModel"] = relationship(
        "ReplacementJobModel", back_populates="events"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "replacement_job_id": self.replacement_job_id,
            "vps_id": self.vps_id,
            "message": self.message,
            "details": self.details or {},
            "level": self.level,
            "created_at": self.created_at.isoformat(),
            "redacted": self.redacted,
        }
