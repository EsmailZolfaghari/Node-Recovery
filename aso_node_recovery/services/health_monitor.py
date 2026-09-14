"""Health monitor service.

This module provides continuous health monitoring for all nodes
and triggers automatic replacement when persistent failures are detected.
"""

import asyncio
from datetime import datetime
from typing import Callable

import structlog

from aso_node_recovery.config.settings import settings
from aso_node_recovery.database.repository import UnitOfWork
from aso_node_recovery.models.event import Event, EventType
from aso_node_recovery.models.node import NodeStatus
from aso_node_recovery.services.orchestrator import ReplacementOrchestrator

logger = structlog.get_logger(__name__)


class HealthMonitor:
    """Monitors node health and triggers replacements on persistent failures.

    This class is responsible for:
    - Periodically checking node health via ping
    - Distinguishing between temporary and persistent failures
    - Triggering automatic replacement jobs when needed
    - Preventing duplicate replacement jobs
    """

    def __init__(
        self,
        uow: UnitOfWork,
        orchestrator: ReplacementOrchestrator,
        ping_interval_seconds: int = 30,
        consecutive_failures_threshold: int = 3,
        failure_confirmation_retries: int = 2,
        dry_run: bool = False,
    ):
        """Initialize health monitor.

        Args:
            uow: Unit of work for database operations.
            orchestrator: Replacement orchestrator instance.
            ping_interval_seconds: Interval between health checks.
            consecutive_failures_threshold: Number of consecutive failures before action.
            failure_confirmation_retries: Number of confirmation retries before marking as failed.
            dry_run: If True, skip actual replacement actions.
        """
        self.uow = uow
        self.orchestrator = orchestrator
        self.ping_interval_seconds = ping_interval_seconds
        self.consecutive_failures_threshold = consecutive_failures_threshold
        self.failure_confirmation_retries = failure_confirmation_retries
        self.dry_run = dry_run

        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._failure_counts: dict[int, int] = {}
        self._confirmation_counts: dict[int, int] = {}

    async def start(self) -> None:
        """Start the health monitoring loop."""
        if self._running:
            logger.warning("Health monitor already running")
            return

        self._running = True
        logger.info(
            "Starting health monitor",
            ping_interval=self.ping_interval_seconds,
            failure_threshold=self.consecutive_failures_threshold,
            confirmation_retries=self.failure_confirmation_retries,
        )

        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the health monitoring loop."""
        if not self._running:
            return

        logger.info("Stopping health monitor...")
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        # Clear state
        self._failure_counts.clear()
        self._confirmation_counts.clear()

        logger.info("Health monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_all_nodes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}", exc_info=True)

            await asyncio.sleep(self.ping_interval_seconds)

    async def _check_all_nodes(self) -> None:
        """Check health of all active nodes."""
        async with self.uow:
            nodes = await self.uow.nodes.get_all_nodes()

        for node in nodes:
            if node.status not in (NodeStatus.ACTIVE, NodeStatus.UNHEALTHY):
                continue

            if node.replacement_in_progress:
                logger.debug(
                    "Skipping node with replacement in progress",
                    node_id=node.id,
                    node_name=node.name,
                )
                continue

            await self._check_node_health(node)

    async def _check_node_health(self, node) -> None:
        """Check health of a single node.

        Args:
            node: Node to check.
        """
        if not node.vps or not node.vps.ip_address:
            logger.warning(
                "Node has no VPS IP address",
                node_id=node.id,
                node_name=node.name,
            )
            return

        ip = node.vps.ip_address
        node_id = node.id

        # Perform ping check
        is_healthy = await self._ping_node(ip)

        if is_healthy:
            # Reset failure counters
            self._failure_counts[node_id] = 0
            self._confirmation_counts[node_id] = 0

            # Update node status to healthy
            async with self.uow:
                node.mark_healthy()
                await self.uow.nodes.update(node)

                # Log health success event
                await self.uow.events.add(
                    Event.create(
                        entity_type="node",
                        entity_id=node.id,
                        event_type=EventType.HEALTH_CHECK_PASSED,
                        data={"ip": ip},
                    )
                )
                await self.uow.commit()

            logger.debug(
                "Node health check passed",
                node_id=node.id,
                node_name=node.name,
                ip=ip,
            )
        else:
            # Increment failure counter
            current_failures = self._failure_counts.get(node_id, 0) + 1
            self._failure_counts[node_id] = current_failures

            logger.debug(
                "Node health check failed",
                node_id=node.id,
                node_name=node.name,
                ip=ip,
                consecutive_failures=current_failures,
            )

            # Check if threshold reached
            if current_failures >= self.consecutive_failures_threshold:
                await self._confirm_failure(node, ip)

    async def _ping_node(self, ip: str) -> bool:
        """Ping a node to check its health.

        Args:
            ip: IP address to ping.

        Returns:
            True if ping successful, False otherwise.
        """
        try:
            # Use reachability checker if available
            if hasattr(self.orchestrator, 'reachability_checker'):
                result = await self.orchestrator.reachability_checker.check(ip)
                return result.is_reachable

            # Fallback: simple ping using subprocess
            process = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", "5", ip,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return_code = await process.wait()
            return return_code == 0

        except Exception as e:
            logger.warning(f"Ping failed for {ip}: {e}")
            return False

    async def _confirm_failure(self, node, ip: str) -> None:
        """Confirm persistent failure before triggering replacement.

        Args:
            node: Node that appears to have failed.
            ip: IP address of the node.
        """
        node_id = node.id

        # Increment confirmation counter
        current_confirmations = self._confirmation_counts.get(node_id, 0) + 1
        self._confirmation_counts[node_id] = current_confirmations

        logger.info(
            "Failure confirmation attempt",
            node_id=node_id,
            node_name=node.name,
            ip=ip,
            confirmation_attempt=current_confirmations,
            max_retries=self.failure_confirmation_retries,
        )

        # Check if we've exhausted confirmation retries
        if current_confirmations <= self.failure_confirmation_retries:
            # Mark node as unhealthy for visibility
            async with self.uow:
                node.mark_unhealthy()
                await self.uow.nodes.update(node)
                await self.uow.commit()

            logger.info(
                "Node marked as unhealthy, continuing confirmation",
                node_id=node_id,
                node_name=node.name,
            )
            return

        # Confirmations exhausted - this is a persistent failure
        logger.warning(
            "Persistent failure confirmed",
            node_id=node_id,
            node_name=node.name,
            ip=ip,
            total_failures=self._failure_counts.get(node_id, 0),
        )

        # Trigger replacement
        await self._trigger_replacement(node, ip)

    async def _trigger_replacement(self, node, ip: str) -> None:
        """Trigger automatic replacement for a failed node.

        Args:
            node: Node to replace.
            ip: Current IP address (for logging).
        """
        node_id = node.id
        node_name = node.name

        # Reset counters
        self._failure_counts.pop(node_id, None)
        self._confirmation_counts.pop(node_id, None)

        logger.warning(
            "Triggering automatic replacement",
            node_id=node_id,
            node_name=node_name,
            old_ip=ip,
        )

        # Create replacement job
        if not self.dry_run:
            job = await self.orchestrator.start_replacement(
                node_id=node_id,
                reason=f"Automatic: Persistent failure detected (IP: {ip})",
            )

            if job:
                logger.info(
                    "Replacement job created",
                    job_id=job.id,
                    node_id=node_id,
                    node_name=node_name,
                )

                # Log event
                async with self.uow:
                    await self.uow.events.add(
                        Event.create(
                            entity_type="node",
                            entity_id=node_id,
                            event_type=EventType.REPLACEMENT_STARTED,
                            data={
                                "reason": "Persistent failure",
                                "old_ip": ip,
                                "automatic": True,
                            },
                        )
                    )
                    await self.uow.commit()
            else:
                logger.error(
                    "Failed to create replacement job",
                    node_id=node_id,
                    node_name=node_name,
                )
        else:
            logger.info(
                "[DRY RUN] Would trigger replacement",
                node_id=node_id,
                node_name=node_name,
                old_ip=ip,
            )

            # In dry run mode, still update node status
            async with self.uow:
                node.mark_replacing()
                await self.uow.nodes.update(node)
                await self.uow.commit()
