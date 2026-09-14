"""Repository layer for database operations."""

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from aso_node_recovery.database.models import NodeModel, ReplacementJobModel, EventModel
from aso_node_recovery.models.node import Node, NodeStatus
from aso_node_recovery.models.replacement import ReplacementJob, ReplacementStage, ReplacementStatus
from aso_node_recovery.models.event import Event, EventType

T = TypeVar("T")


def _now() -> datetime:
    """Get current UTC time using timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Repository(ABC, Generic[T]):
    """Base repository interface."""

    @abstractmethod
    async def get_by_id(self, id: int) -> T | None:
        """Get entity by ID."""
        pass

    @abstractmethod
    async def list_all(self) -> list[T]:
        """List all entities."""
        pass

    @abstractmethod
    async def create(self, entity: T) -> T:
        """Create a new entity."""
        pass

    @abstractmethod
    async def update(self, entity: T) -> T:
        """Update an existing entity."""
        pass

    @abstractmethod
    async def delete(self, id: int) -> bool:
        """Delete an entity by ID."""
        pass


class NodeRepository:
    """Repository for Node operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, node_id: int) -> Node | None:
        """Get node by ID."""
        result = await self.session.execute(
            select(NodeModel).where(NodeModel.id == node_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return self._to_entity(model)

    async def get_by_name(self, name: str) -> Node | None:
        """Get node by name."""
        result = await self.session.execute(
            select(NodeModel).where(NodeModel.name == name)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return self._to_entity(model)

    async def list_all(self) -> list[Node]:
        """List all nodes."""
        result = await self.session.execute(select(NodeModel))
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_status(self, status: NodeStatus) -> list[Node]:
        """List nodes by status."""
        result = await self.session.execute(
            select(NodeModel).where(NodeModel.status == status.value)
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_replaceable(self) -> list[Node]:
        """List nodes that can be replaced (failed/unhealthy without active job)."""
        result = await self.session.execute(
            select(NodeModel).where(
                NodeModel.status.in_(["failed", "unhealthy"]),
                NodeModel.active_replacement_job_id.is_(None),
            )
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def create(self, node: Node) -> Node:
        """Create a new node."""
        model = self._to_model(node)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return self._to_entity(model)

    async def update(self, node: Node) -> Node:
        """Update an existing node."""
        await self.session.execute(
            update(NodeModel)
            .where(NodeModel.id == node.id)
            .values(
                name=node.name,
                description=node.description,
                provider=node.provider,
                region=node.region,
                status=node.status.value,
                current_vps_id=node.current_vps_id,
                current_ip=node.current_ip,
                consecutive_failures=node.consecutive_failures,
                last_health_check=node.last_health_check,
                last_successful_check=node.last_successful_check,
                active_replacement_job_id=node.active_replacement_job_id,
                replacement_history=json.dumps(node.replacement_history),
                metadata_json=node.metadata,
                updated_at=_now(),
            )
        )
        await self.session.flush()
        return node

    async def delete(self, node_id: int) -> bool:
        """Delete a node by ID."""
        await self.session.execute(delete(NodeModel).where(NodeModel.id == node_id))
        return True

    async def count(self) -> int:
        """Count total nodes."""
        result = await self.session.execute(select(func.count()).select_from(NodeModel))
        return result.scalar_one()

    def _to_entity(self, model: NodeModel) -> Node:
        """Convert database model to entity."""
        import json

        return Node(
            id=model.id,
            name=model.name,
            description=model.description,
            provider=model.provider,
            region=model.region,
            status=NodeStatus(model.status),
            current_vps_id=model.current_vps_id,
            current_ip=model.current_ip,
            consecutive_failures=model.consecutive_failures,
            last_health_check=model.last_health_check,
            last_successful_check=model.last_successful_check,
            active_replacement_job_id=model.active_replacement_job_id,
            replacement_history=json.loads(model.replacement_history)
            if model.replacement_history
            else [],
            created_at=model.created_at,
            updated_at=model.updated_at,
            metadata=model.metadata_json or {},
        )

    def _to_model(self, entity: Node) -> NodeModel:
        """Convert entity to database model."""
        import json

        return NodeModel(
            id=entity.id,
            name=entity.name,
            description=entity.description,
            provider=entity.provider,
            region=entity.region,
            status=entity.status.value,
            current_vps_id=entity.current_vps_id,
            current_ip=entity.current_ip,
            consecutive_failures=entity.consecutive_failures,
            last_health_check=entity.last_health_check,
            last_successful_check=entity.last_successful_check,
            active_replacement_job_id=entity.active_replacement_job_id,
            replacement_history=json.dumps(entity.replacement_history),
            metadata_json=entity.metadata,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


class ReplacementJobRepository:
    """Repository for ReplacementJob operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, job_id: int) -> ReplacementJob | None:
        """Get job by ID."""
        result = await self.session.execute(
            select(ReplacementJobModel).where(ReplacementJobModel.id == job_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return self._to_entity(model)

    async def list_all(self) -> list[ReplacementJob]:
        """List all jobs."""
        result = await self.session.execute(select(ReplacementJobModel))
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_status(self, status: ReplacementStatus) -> list[ReplacementJob]:
        """List jobs by status."""
        result = await self.session.execute(
            select(ReplacementJobModel).where(ReplacementJobModel.status == status.value)
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_running(self) -> list[ReplacementJob]:
        """List running jobs."""
        result = await self.session.execute(
            select(ReplacementJobModel).where(ReplacementJobModel.status == "running")
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_node(self, node_id: int) -> list[ReplacementJob]:
        """List jobs for a specific node."""
        result = await self.session.execute(
            select(ReplacementJobModel)
            .where(ReplacementJobModel.node_id == node_id)
            .order_by(ReplacementJobModel.created_at.desc())
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def get_active_jobs_for_node(self, node_id: int) -> list[ReplacementJob]:
        """Get active replacement jobs for a node."""
        result = await self.session.execute(
            select(ReplacementJobModel)
            .where(
                ReplacementJobModel.node_id == node_id,
                ReplacementJobModel.status.in_(["pending", "running"]),
            )
            .order_by(ReplacementJobModel.created_at.desc())
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def count_active_jobs(self) -> int:
        """Count total active replacement jobs."""
        result = await self.session.execute(
            select(func.count())
            .select_from(ReplacementJobModel)
            .where(ReplacementJobModel.status.in_(["pending", "running"]))
        )
        return result.scalar() or 0

    async def create(self, job: ReplacementJob) -> ReplacementJob:
        """Create a new job."""
        model = self._to_model(job)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return self._to_entity(model)

    async def update(self, job: ReplacementJob) -> ReplacementJob:
        """Update an existing job."""
        await self.session.execute(
            update(ReplacementJobModel)
            .where(ReplacementJobModel.id == job.id)
            .values(
                current_stage=job.current_stage.value,
                status=job.status.value,
                old_vps_id=job.old_vps_id,
                old_vps_ip=job.old_vps_ip,
                new_vps_id=job.new_vps_id,
                new_vps_ip=job.new_vps_ip,
                attempt_number=job.attempt_number,
                max_attempts=job.max_attempts,
                ip_check_attempts=job.ip_check_attempts,
                max_ip_check_attempts=job.max_ip_check_attempts,
                error_message=job.error_message,
                error_details=job.error_details if job.error_details else None,
                retry_count=job.retry_count,
                stage_progress=job.stage_progress if job.stage_progress else None,
                started_at=job.started_at,
                completed_at=job.completed_at,
                old_vps_deleted=job.old_vps_deleted,
                master_updated=job.master_updated,
                deployment_verified=job.deployment_verified,
                updated_at=_now(),
            )
        )
        await self.session.flush()
        return job

    async def delete(self, job_id: int) -> bool:
        """Delete a job by ID."""
        await self.session.execute(
            delete(ReplacementJobModel).where(ReplacementJobModel.id == job_id)
        )
        return True

    async def count(self) -> int:
        """Count total jobs."""
        result = await self.session.execute(
            select(func.count()).select_from(ReplacementJobModel)
        )
        return result.scalar_one()

    async def count_running(self) -> int:
        """Count running jobs."""
        result = await self.session.execute(
            select(func.count())
            .select_from(ReplacementJobModel)
            .where(ReplacementJobModel.status == "running")
        )
        return result.scalar_one()

    def _to_entity(self, model: ReplacementJobModel) -> ReplacementJob:
        """Convert database model to entity."""
        return ReplacementJob(
            id=model.id,
            node_id=model.node_id,
            node_name=model.node_name,
            current_stage=ReplacementStage(model.current_stage),
            status=ReplacementStatus(model.status),
            old_vps_id=model.old_vps_id,
            old_vps_ip=model.old_vps_ip,
            new_vps_id=model.new_vps_id,
            new_vps_ip=model.new_vps_ip,
            attempt_number=model.attempt_number,
            max_attempts=model.max_attempts,
            ip_check_attempts=model.ip_check_attempts,
            max_ip_check_attempts=model.max_ip_check_attempts,
            error_message=model.error_message,
            error_details=model.error_details or {},
            retry_count=model.retry_count,
            stage_progress=model.stage_progress or {},
            created_at=model.created_at,
            started_at=model.started_at,
            completed_at=model.completed_at,
            updated_at=model.updated_at,
            old_vps_deleted=model.old_vps_deleted,
            master_updated=model.master_updated,
            deployment_verified=model.deployment_verified,
        )

    def _to_model(self, entity: ReplacementJob) -> ReplacementJobModel:
        """Convert entity to database model."""
        return ReplacementJobModel(
            id=entity.id,
            node_id=entity.node_id,
            node_name=entity.node_name,
            current_stage=entity.current_stage.value,
            status=entity.status.value,
            old_vps_id=entity.old_vps_id,
            old_vps_ip=entity.old_vps_ip,
            new_vps_id=entity.new_vps_id,
            new_vps_ip=entity.new_vps_ip,
            attempt_number=entity.attempt_number,
            max_attempts=entity.max_attempts,
            ip_check_attempts=entity.ip_check_attempts,
            max_ip_check_attempts=entity.max_ip_check_attempts,
            error_message=entity.error_message,
            error_details=entity.error_details if entity.error_details else None,
            retry_count=entity.retry_count,
            stage_progress=entity.stage_progress if entity.stage_progress else None,
            created_at=entity.created_at,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            updated_at=entity.updated_at,
            old_vps_deleted=entity.old_vps_deleted,
            master_updated=entity.master_updated,
            deployment_verified=entity.deployment_verified,
        )


class EventRepository:
    """Repository for Event operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, event_id: int) -> Event | None:
        """Get event by ID."""
        result = await self.session.execute(
            select(EventModel).where(EventModel.id == event_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return self._to_entity(model)

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Event]:
        """List events with pagination."""
        result = await self.session.execute(
            select(EventModel)
            .order_by(EventModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_node(self, node_id: int, limit: int = 100) -> list[Event]:
        """List events for a specific node."""
        result = await self.session.execute(
            select(EventModel)
            .where(EventModel.node_id == node_id)
            .order_by(EventModel.created_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_job(
        self, job_id: int, limit: int = 100
    ) -> list[Event]:
        """List events for a specific replacement job."""
        result = await self.session.execute(
            select(EventModel)
            .where(EventModel.replacement_job_id == job_id)
            .order_by(EventModel.created_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_type(
        self, event_type: EventType, limit: int = 100
    ) -> list[Event]:
        """List events by type."""
        result = await self.session.execute(
            select(EventModel)
            .where(EventModel.event_type == event_type.value)
            .order_by(EventModel.created_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def create(self, event: Event) -> Event:
        """Create a new event."""
        model = self._to_model(event)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return self._to_entity(model)

    async def delete(self, event_id: int) -> bool:
        """Delete an event by ID."""
        await self.session.execute(delete(EventModel).where(EventModel.id == event_id))
        return True

    async def delete_old(
        self, older_than: datetime, batch_size: int = 1000
    ) -> int:
        """Delete events older than specified date. Returns count of deleted events."""
        result = await self.session.execute(
            delete(EventModel).where(EventModel.created_at < older_than)
        )
        return result.rowcount or 0

    def _to_entity(self, model: EventModel) -> Event:
        """Convert database model to entity."""
        return Event(
            id=model.id,
            event_type=EventType(model.event_type),
            node_id=model.node_id,
            node_name=model.node_name,
            replacement_job_id=model.replacement_job_id,
            vps_id=model.vps_id,
            message=model.message,
            details=model.details or {},
            level=model.level,
            created_at=model.created_at,
            redacted=model.redacted,
        )

    def _to_model(self, entity: Event) -> EventModel:
        """Convert entity to database model."""
        return EventModel(
            id=entity.id,
            event_type=entity.event_type.value,
            node_id=entity.node_id,
            node_name=entity.node_name,
            replacement_job_id=entity.replacement_job_id,
            vps_id=entity.vps_id,
            message=entity.message,
            details=entity.details if entity.details else None,
            level=entity.level,
            created_at=entity.created_at,
            redacted=entity.redacted,
        )


class UnitOfWork:
    """Unit of Work pattern for managing database transactions.
    
    This class provides a context manager for atomic database operations,
    ensuring that all repositories share the same session and transaction.
    """
    
    def __init__(self, session_factory):
        """Initialize Unit of Work.
        
        Args:
            session_factory: Async session factory from SQLAlchemy.
        """
        self.session_factory = session_factory
        self._session = None
        self._nodes = None
        self._jobs = None
        self._events = None
    
    async def __aenter__(self):
        """Enter context manager - start transaction."""
        self._session = await self.session_factory()
        self._nodes = NodeRepository(self._session)
        self._jobs = ReplacementJobRepository(self._session)
        self._events = EventRepository(self._session)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - commit or rollback."""
        try:
            if exc_type is not None:
                await self.rollback()
            else:
                await self.commit()
        finally:
            await self._session.close()
    
    @property
    def nodes(self) -> NodeRepository:
        """Get node repository."""
        if self._nodes is None:
            raise RuntimeError("Unit of Work not initialized. Use 'async with' context.")
        return self._nodes
    
    @property
    def jobs(self) -> ReplacementJobRepository:
        """Get replacement job repository."""
        if self._jobs is None:
            raise RuntimeError("Unit of Work not initialized. Use 'async with' context.")
        return self._jobs
    
    @property
    def events(self) -> EventRepository:
        """Get event repository."""
        if self._events is None:
            raise RuntimeError("Unit of Work not initialized. Use 'async with' context.")
        return self._events
    
    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()
    
    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self._session.rollback()
