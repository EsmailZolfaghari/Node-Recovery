"""Replacement orchestrator service.

This is the core orchestration engine that manages the entire
node replacement workflow, coordinating between providers,
reachability checks, deployment, and master updates.
"""

import asyncio
from datetime import datetime
from typing import Any

import structlog

from aso_node_recovery.config.settings import settings
from aso_node_recovery.database.repository import UnitOfWork
from aso_node_recovery.deployer.ssh import DeploymentManager, SSHConnection, SSHConfig
from aso_node_recovery.master.client import Master3XUI, MasterConfig, MasterNode
from aso_node_recovery.models.event import Event, EventType
from aso_node_recovery.models.node import NodeStatus
from aso_node_recovery.models.replacement import (
    ReplacementJob,
    ReplacementStage,
    ReplacementStatus,
)
from aso_node_recovery.providers.base import BaseProvider, ProviderError
from aso_node_recovery.reachability.base import BaseReachabilityChecker

logger = structlog.get_logger(__name__)


class ReplacementOrchestrator:
    """Orchestrates the complete node replacement workflow.

    This class is responsible for:
    - Managing replacement job lifecycle
    - Coordinating between different system components
    - Handling failures and retries
    - Ensuring atomic operations where needed
    - Maintaining safety invariants (especially old VPS deletion)
    """

    def __init__(
        self,
        uow: UnitOfWork,
        provider: BaseProvider,
        reachability_checker: BaseReachabilityChecker,
        master_client: Master3XUI,
        dry_run: bool = False,
    ):
        """Initialize orchestrator.

        Args:
            uow: Unit of work for database operations.
            provider: VPS provider instance.
            reachability_checker: IP reachability checker.
            master_client: Master 3X-UI client.
            dry_run: If True, skip actual destructive operations.
        """
        self.uow = uow
        self.provider = provider
        self.reachability_checker = reachability_checker
        self.master_client = master_client
        self.dry_run = dry_run
        self._running_jobs: dict[int, asyncio.Task] = {}

    async def start_replacement(self, node_id: int, reason: str = "Manual trigger") -> ReplacementJob | None:
        """Start a replacement job for a node.

        Args:
            node_id: ID of the node to replace.
            reason: Reason for replacement.

        Returns:
            Created ReplacementJob or None if failed to create.
        """
        async with self.uow:
            # Check if node exists and can be replaced
            node = await self.uow.nodes.get_by_id(node_id)
            if not node:
                logger.error("Node not found", node_id=node_id)
                return None

            if not node.can_be_replaced():
                logger.warning(
                    "Node cannot be replaced",
                    node_id=node_id,
                    status=node.status.value,
                    replacement_in_progress=node.replacement_in_progress,
                )
                return None

            # Check for existing active replacement jobs
            existing_jobs = await self.uow.jobs.get_active_jobs_for_node(node_id)
            if existing_jobs:
                logger.warning(
                    "Active replacement job already exists",
                    node_id=node_id,
                    existing_job_id=existing_jobs[0].id,
                )
                return None

            # Check concurrency limits
            active_jobs_count = await self.uow.jobs.count_active_jobs()
            if active_jobs_count >= settings.replacement_max_concurrent:
                logger.warning(
                    "Max concurrent replacements reached",
                    active_count=active_jobs_count,
                    max_allowed=settings.replacement_max_concurrent,
                )
                return None

            # Mark node as having replacement in progress
            node.replacement_in_progress = True
            node.status = NodeStatus.REPLACING
            await self.uow.nodes.update(node)

            # Create replacement job
            job = ReplacementJob(
                node_id=node_id,
                node_name=node.name,
                old_vps_id=node.vps_id,
                old_vps_ip=node.ip_address,
                max_attempts=settings.replacement_max_attempts,
                max_ip_check_attempts=settings.reachability_max_attempts,
            )

            created_job = await self.uow.jobs.create(job)

            # Log event
            await self.uow.events.create(
                Event(
                    entity_type="replacement_job",
                    entity_id=created_job.id,
                    event_type=EventType.JOB_CREATED,
                    message=f"Replacement job created: {reason}",
                    metadata={"node_id": node_id, "reason": reason},
                )
            )

            await self.uow.commit()

            logger.info(
                "Replacement job created",
                job_id=created_job.id,
                node_id=node_id,
                node_name=node.name,
            )

            return created_job

    async def execute_job(self, job_id: int) -> bool:
        """Execute a replacement job.

        This is the main workflow executor that progresses through
        all stages of the replacement process.

        Args:
            job_id: ID of the job to execute.

        Returns:
            True if job completed successfully, False otherwise.
        """
        async with self.uow:
            job = await self.uow.jobs.get_by_id(job_id)
            if not job:
                logger.error("Job not found", job_id=job_id)
                return False

            if job.status != ReplacementStatus.RUNNING:
                job.start()
                await self.uow.jobs.update(job)
                await self.uow.commit()

        logger.info("Starting replacement job execution", job_id=job_id)

        try:
            # Progress through stages
            while True:
                async with self.uow:
                    job = await self.uow.jobs.get_by_id(job_id)
                    if not job:
                        return False

                    if job.status in (
                        ReplacementStatus.COMPLETED,
                        ReplacementStatus.FAILED,
                        ReplacementStatus.CANCELLED,
                    ):
                        break

                    stage_success = await self._execute_stage(job)

                    if not stage_success:
                        # Handle failure
                        await self._handle_job_failure(job)
                        break

                    # Check if completed
                    if job.current_stage == ReplacementStage.COMPLETED:
                        job.mark_completed()
                        await self.uow.jobs.update(job)

                        # Update node status
                        node = await self.uow.nodes.get_by_id(job.node_id)
                        if node:
                            node.status = NodeStatus.ACTIVE
                            node.ip_address = job.new_vps_ip
                            node.vps_id = job.new_vps_id
                            node.replacement_in_progress = False
                            node.last_health_check = datetime.utcnow()
                            await self.uow.nodes.update(node)

                        await self.uow.events.create(
                            Event(
                                entity_type="replacement_job",
                                entity_id=job.id,
                                event_type=EventType.JOB_COMPLETED,
                                message="Replacement completed successfully",
                                metadata={
                                    "new_ip": job.new_vps_ip,
                                    "old_vps_id": job.old_vps_id,
                                },
                            )
                        )

                        await self.uow.commit()
                        logger.info("Replacement job completed", job_id=job_id)
                        break

                    await self.uow.jobs.update(job)
                    await self.uow.commit()

        except Exception as e:
            logger.exception("Unexpected error during job execution", job_id=job_id, error=str(e))
            async with self.uow:
                job = await self.uow.jobs.get_by_id(job_id)
                if job:
                    await self._handle_job_failure(job, error=str(e))
                    await self.uow.commit()
            return False

        return True

    async def _execute_stage(self, job: ReplacementJob) -> bool:
        """Execute a single stage of the replacement workflow.

        Args:
            job: Current replacement job.

        Returns:
            True if stage succeeded, False otherwise.
        """
        stage = job.current_stage

        logger.debug("Executing stage", stage=stage.value, job_id=job.id)

        try:
            if stage == ReplacementStage.CONFIRMING_FAILURE:
                return await self._stage_confirm_failure(job)

            elif stage == ReplacementStage.CREATING_VPS:
                return await self._stage_create_vps(job)

            elif stage == ReplacementStage.CHECKING_IP:
                return await self._stage_check_ip(job)

            elif stage == ReplacementStage.WAITING_SSH:
                return await self._stage_wait_ssh(job)

            elif stage == ReplacementStage.DEPLOYING_3XUI:
                return await self._stage_deploy_3xui(job)

            elif stage == ReplacementStage.VERIFYING_DEPLOYMENT:
                return await self._stage_verify_deployment(job)

            elif stage == ReplacementStage.UPDATING_MASTER:
                return await self._stage_update_master(job)

            elif stage == ReplacementStage.VERIFYING_MASTER:
                return await self._stage_verify_master(job)

            elif stage == ReplacementStage.FINAL_HEALTH_CHECK:
                return await self._stage_final_health_check(job)

            elif stage == ReplacementStage.CLEANING_UP:
                return await self._stage_cleanup(job)

            else:
                logger.warning("Unknown stage", stage=stage.value)
                return False

        except Exception as e:
            logger.exception(
                "Stage execution failed",
                stage=stage.value,
                job_id=job.id,
                error=str(e),
            )
            return False

    async def _stage_confirm_failure(self, job: ReplacementJob) -> bool:
        """Confirm that node failure is persistent."""
        logger.info("Confirming node failure", job_id=job.id, node_id=job.node_id)

        # Get current node state
        async with self.uow:
            node = await self.uow.nodes.get_by_id(job.node_id)
            if not node:
                job.mark_failed("Node not found")
                return False

        # Perform multiple health checks to confirm persistent failure
        check_count = settings.failure_confirmation_checks
        failed_checks = 0

        for i in range(check_count):
            is_healthy = await self._check_node_health(job.node_id)
            if is_healthy:
                logger.warning(
                    "Node appears healthy during confirmation",
                    job_id=job.id,
                    check_number=i + 1,
                )
                failed_checks = 0
                break
            else:
                failed_checks += 1
                logger.debug(
                    "Health check failed",
                    job_id=job.id,
                    check_number=i + 1,
                    total_failures=failed_checks,
                )

            if i < check_count - 1:
                await asyncio.sleep(settings.failure_confirmation_interval_seconds)

        if failed_checks >= check_count:
            logger.info("Failure confirmed as persistent", job_id=job.id)
            job.advance_stage(ReplacementStage.CREATING_VPS)
            return True
        else:
            logger.info("Failure not confirmed, node may be recovering", job_id=job.id)
            job.mark_failed(
                "Failure not confirmed - node recovered",
                {"failed_checks": failed_checks, "required_checks": check_count},
            )
            return False

    async def _check_node_health(self, node_id: int) -> bool:
        """Check if a node is healthy.

        Args:
            node_id: Node ID to check.

        Returns:
            True if node is healthy, False otherwise.
        """
        async with self.uow:
            node = await self.uow.nodes.get_by_id(node_id)
            if not node:
                return False

            # Check via reachability
            if node.ip_address:
                is_reachable = await self.reachability_checker.check(node.ip_address)
                if not is_reachable:
                    return False

            # Check via Master if available
            if self.master_client:
                try:
                    master_node = await self.master_client.get_node(node.master_node_id)
                    if master_node and not master_node.enabled:
                        return False
                except Exception:
                    pass

            return True

    async def _stage_create_vps(self, job: ReplacementJob) -> bool:
        """Create new VPS instance."""
        logger.info("Creating new VPS", job_id=job.id, node_name=job.node_name)

        if self.dry_run:
            logger.info("[DRY RUN] Would create VPS", job_id=job.id)
            job.new_vps_id = "dry-run-vps-id"
            job.new_vps_ip = "dry-run-ip"
            job.advance_stage(ReplacementStage.CHECKING_IP)
            return True

        try:
            vps_name = f"{job.node_name}-new-{job.attempt_number}"

            vps_info = await self.provider.create_vps(
                name=vps_name,
                metadata={"aso_node_recovery": "true", "job_id": str(job.id)},
            )

            # Wait for VPS to become active
            vps_info = await self.provider.wait_for_active(
                vps_info.id,
                timeout_seconds=settings.vps_activation_timeout_seconds,
            )

            job.new_vps_id = vps_info.id
            job.new_vps_ip = vps_info.ip_address

            logger.info(
                "VPS created successfully",
                job_id=job.id,
                vps_id=vps_info.id,
                ip=vps_info.ip_address,
            )

            job.advance_stage(ReplacementStage.CHECKING_IP)
            return True

        except ProviderError as e:
            logger.error("Failed to create VPS", job_id=job.id, error=str(e))
            job.error_message = f"VPS creation failed: {e.message}"
            job.error_details = e.details
            return False

    async def _stage_check_ip(self, job: ReplacementJob) -> bool:
        """Check if new VPS IP is reachable."""
        logger.info("Checking IP reachability", job_id=job.id, ip=job.new_vps_ip)

        if not job.new_vps_ip:
            logger.error("No IP address available for checking", job_id=job.id)
            return False

        if self.dry_run:
            logger.info("[DRY RUN] Would check IP", job_id=job.id, ip=job.new_vps_ip)
            job.advance_stage(ReplacementStage.WAITING_SSH)
            return True

        job.ip_check_attempts += 1

        is_reachable = await self.reachability_checker.check(job.new_vps_ip)

        if is_reachable:
            logger.info("IP is reachable", job_id=job.id, ip=job.new_vps_ip)
            job.advance_stage(ReplacementStage.WAITING_SSH)
            return True
        else:
            logger.warning(
                "IP is not reachable",
                job_id=job.id,
                ip=job.new_vps_ip,
                attempt=job.ip_check_attempts,
            )

            if job.ip_check_attempts >= job.max_ip_check_attempts:
                # Max attempts reached, destroy VPS and retry or fail
                logger.warning(
                    "Max IP check attempts reached",
                    job_id=job.id,
                    attempts=job.ip_check_attempts,
                )

                if not self.dry_run and job.new_vps_id:
                    try:
                        await self.provider.delete_vps(job.new_vps_id)
                        logger.info("Temporary VPS deleted", job_id=job.id, vps_id=job.new_vps_id)
                    except Exception as e:
                        logger.warning("Failed to delete temporary VPS", job_id=job.id, error=str(e))

                if job.can_retry():
                    job.increment_attempt()
                    job.ip_check_attempts = 0
                    job.advance_stage(ReplacementStage.CREATING_VPS)
                    return True
                else:
                    job.mark_failed(
                        "IP repeatedly unreachable",
                        {"attempts": job.ip_check_attempts},
                    )
                    return False
            else:
                # Retry after delay
                await asyncio.sleep(settings.reachability_retry_delay_seconds)
                return True

    async def _stage_wait_ssh(self, job: ReplacementJob) -> bool:
        """Wait for SSH to become available on new VPS."""
        logger.info("Waiting for SSH access", job_id=job.id, ip=job.new_vps_ip)

        if self.dry_run:
            logger.info("[DRY RUN] Would wait for SSH", job_id=job.id)
            job.advance_stage(ReplacementStage.DEPLOYING_3XUI)
            return True

        ssh_config = SSHConfig(
            host=job.new_vps_ip,
            username=settings.ssh_username,
            port=settings.ssh_port,
            key_file=settings.ssh_key_file,
            timeout_seconds=settings.ssh_connection_timeout_seconds,
        )

        deployer = DeploymentManager(ssh_config)

        max_attempts = settings.ssh_max_attempts
        for attempt in range(max_attempts):
            try:
                await deployer.connect()
                logger.info("SSH connection successful", job_id=job.id, ip=job.new_vps_ip)
                await deployer.close()
                job.advance_stage(ReplacementStage.DEPLOYING_3XUI)
                return True
            except Exception as e:
                logger.debug(
                    "SSH connection attempt failed",
                    job_id=job.id,
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(settings.ssh_retry_delay_seconds)

        logger.error("SSH never became available", job_id=job.id, ip=job.new_vps_ip)
        return False

    async def _stage_deploy_3xui(self, job: ReplacementJob) -> bool:
        """Deploy 3X-UI on new VPS."""
        logger.info("Deploying 3X-UI", job_id=job.id, ip=job.new_vps_ip)

        if self.dry_run:
            logger.info("[DRY RUN] Would deploy 3X-UI", job_id=job.id)
            job.deployment_verified = True
            job.advance_stage(ReplacementStage.VERIFYING_DEPLOYMENT)
            return True

        ssh_config = SSHConfig(
            host=job.new_vps_ip,
            username=settings.ssh_username,
            port=settings.ssh_port,
            key_file=settings.ssh_key_file,
            timeout_seconds=settings.ssh_operation_timeout_seconds,
        )

        deployer = DeploymentManager(ssh_config)

        try:
            await deployer.connect()

            # Install 3X-UI
            install_success = await deployer.install_3xui()
            if not install_success:
                logger.error("3X-UI installation failed", job_id=job.id)
                await deployer.close()
                return False

            logger.info("3X-UI installed successfully", job_id=job.id)

            # Get node info
            node_info = await deployer.get_node_info()
            if node_info:
                job.stage_progress["node_info"] = node_info
                logger.info("Got node info from new VPS", job_id=job.id)

            await deployer.close()

            job.deployment_verified = True
            job.advance_stage(ReplacementStage.VERIFYING_DEPLOYMENT)
            return True

        except Exception as e:
            logger.error("3X-UI deployment failed", job_id=job.id, error=str(e))
            return False

    async def _stage_verify_deployment(self, job: ReplacementJob) -> bool:
        """Verify that 3X-UI deployment is working."""
        logger.info("Verifying deployment", job_id=job.id)

        if self.dry_run:
            logger.info("[DRY RUN] Would verify deployment", job_id=job.id)
            job.advance_stage(ReplacementStage.UPDATING_MASTER)
            return True

        # Connect and verify 3X-UI is running
        ssh_config = SSHConfig(
            host=job.new_vps_ip,
            username=settings.ssh_username,
            port=settings.ssh_port,
            key_file=settings.ssh_key_file,
        )

        deployer = DeploymentManager(ssh_config)

        try:
            await deployer.connect()
            is_running = await deployer.verify_3xui_running()
            await deployer.close()

            if is_running:
                logger.info("Deployment verified", job_id=job.id)
                job.advance_stage(ReplacementStage.UPDATING_MASTER)
                return True
            else:
                logger.error("Deployment verification failed", job_id=job.id)
                return False

        except Exception as e:
            logger.error("Deployment verification failed", job_id=job.id, error=str(e))
            return False

    async def _stage_update_master(self, job: ReplacementJob) -> bool:
        """Update Master 3X-UI with new node information."""
        logger.info("Updating Master", job_id=job.id, new_ip=job.new_vps_ip)

        if self.dry_run:
            logger.info("[DRY RUN] Would update Master", job_id=job.id)
            job.master_updated = True
            job.advance_stage(ReplacementStage.VERIFYING_MASTER)
            return True

        async with self.uow:
            node = await self.uow.nodes.get_by_id(job.node_id)
            if not node:
                job.mark_failed("Node not found during master update")
                return False

            if not node.master_node_id:
                logger.error("Node has no master_node_id", job_id=job.id, node_id=job.node_id)
                job.mark_failed("Cannot update Master - node has no master_node_id")
                return False

        try:
            success = await self.master_client.update_node_backend(
                node_id=node.master_node_id,
                new_ip=job.new_vps_ip,
            )

            if success:
                logger.info("Master updated successfully", job_id=job.id)
                job.master_updated = True
                job.advance_stage(ReplacementStage.VERIFYING_MASTER)
                return True
            else:
                logger.error("Master update returned false", job_id=job.id)
                return False

        except Exception as e:
            logger.error("Master update failed", job_id=job.id, error=str(e))
            return False

    async def _stage_verify_master(self, job: ReplacementJob) -> bool:
        """Verify that Master has been properly updated."""
        logger.info("Verifying Master sync", job_id=job.id)

        if self.dry_run:
            logger.info("[DRY RUN] Would verify Master", job_id=job.id)
            job.advance_stage(ReplacementStage.FINAL_HEALTH_CHECK)
            return True

        async with self.uow:
            node = await self.uow.nodes.get_by_id(job.node_id)
            if not node or not node.master_node_id:
                return False

        try:
            master_node = await self.master_client.get_node(node.master_node_id)
            if not master_node:
                logger.error("Node not found in Master", job_id=job.id)
                return False

            if master_node.ip != job.new_vps_ip:
                logger.error(
                    "Master IP does not match new VPS IP",
                    job_id=job.id,
                    master_ip=master_node.ip,
                    new_ip=job.new_vps_ip,
                )
                return False

            if not master_node.enabled:
                logger.error("Node is disabled in Master", job_id=job.id)
                return False

            logger.info("Master verification successful", job_id=job.id)
            job.advance_stage(ReplacementStage.FINAL_HEALTH_CHECK)
            return True

        except Exception as e:
            logger.error("Master verification failed", job_id=job.id, error=str(e))
            return False

    async def _stage_final_health_check(self, job: ReplacementJob) -> bool:
        """Perform final health check before cleanup."""
        logger.info("Performing final health check", job_id=job.id)

        if self.dry_run:
            logger.info("[DRY RUN] Would perform final health check", job_id=job.id)
            job.advance_stage(ReplacementStage.CLEANING_UP)
            return True

        # Check reachability of new node
        is_reachable = await self.reachability_checker.check(job.new_vps_ip)
        if not is_reachable:
            logger.error("Final health check failed - new node unreachable", job_id=job.id)
            return False

        # Verify Master can see the node
        async with self.uow:
            node = await self.uow.nodes.get_by_id(job.node_id)
            if node and node.master_node_id:
                is_enabled = await self.master_client.verify_node_status(node.master_node_id)
                if not is_enabled:
                    logger.error("Final health check failed - node not enabled in Master", job_id=job.id)
                    return False

        logger.info("Final health check passed", job_id=job.id)
        job.advance_stage(ReplacementStage.CLEANING_UP)
        return True

    async def _stage_cleanup(self, job: ReplacementJob) -> bool:
        """Clean up old VPS if safe to do so."""
        logger.info("Cleaning up old VPS", job_id=job.id)

        if not job.should_delete_old_vps():
            logger.warning(
                "Cannot delete old VPS - safety conditions not met",
                job_id=job.id,
                status=job.status.value,
                new_vps_id=job.new_vps_id,
                deployment_verified=job.deployment_verified,
                master_updated=job.master_updated,
            )
            # Still mark as completed even if we can't delete old VPS
            job.mark_completed()
            return True

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would delete old VPS",
                job_id=job.id,
                old_vps_id=job.old_vps_id,
            )
            job.old_vps_deleted = True
            job.mark_completed()
            return True

        if job.old_vps_id:
            try:
                await self.provider.delete_vps(job.old_vps_id)
                logger.info(
                    "Old VPS deleted successfully",
                    job_id=job.id,
                    old_vps_id=job.old_vps_id,
                )
                job.old_vps_deleted = True

                async with self.uow:
                    await self.uow.events.create(
                        Event(
                            entity_type="replacement_job",
                            entity_id=job.id,
                            event_type=EventType.CLEANUP_COMPLETED,
                            message="Old VPS safely removed",
                            metadata={"old_vps_id": job.old_vps_id},
                        )
                    )

            except Exception as e:
                logger.error(
                    "Failed to delete old VPS",
                    job_id=job.id,
                    old_vps_id=job.old_vps_id,
                    error=str(e),
                )
                # Don't fail the job - old VPS preservation is safer than premature deletion
                job.error_message = f"Cleanup warning: {str(e)}"

        job.mark_completed()
        return True

    async def _handle_job_failure(self, job: ReplacementJob, error: str | None = None) -> None:
        """Handle job failure with proper cleanup and state management.

        Args:
            job: Failed job.
            error: Optional error message.
        """
        if error:
            job.error_message = error

        logger.error(
            "Job failed",
            job_id=job.id,
            node_id=job.node_id,
            stage=job.current_stage.value,
            error=job.error_message,
        )

        # Determine if we should retry
        if job.can_retry() and self._is_retryable_failure(job):
            logger.info(
                "Attempting retry",
                job_id=job.id,
                attempt=job.attempt_number,
                max_attempts=job.max_attempts,
            )

            job.increment_attempt()
            job.ip_check_attempts = 0
            job.current_stage = ReplacementStage.CREATING_VPS
            job.status = ReplacementStatus.RUNNING

            # Clean up failed VPS if exists
            if job.new_vps_id and not self.dry_run:
                try:
                    await self.provider.delete_vps(job.new_vps_id)
                    logger.info("Failed VPS cleaned up for retry", job_id=job.id, vps_id=job.new_vps_id)
                except Exception as e:
                    logger.warning("Failed to clean up VPS for retry", job_id=job.id, error=str(e))
        else:
            job.mark_failed(job.error_message or "Max retries exceeded")

            # CRITICAL: Do NOT delete old VPS on failure
            logger.warning(
                "Old VPS preserved due to job failure",
                job_id=job.id,
                old_vps_id=job.old_vps_id,
                old_vps_ip=job.old_vps_ip,
            )

            # Update node status
            async with self.uow:
                node = await self.uow.nodes.get_by_id(job.node_id)
                if node:
                    node.replacement_in_progress = False
                    node.status = NodeStatus.UNKNOWN
                    await self.uow.nodes.update(node)

                await self.uow.events.create(
                    Event(
                        entity_type="replacement_job",
                        entity_id=job.id,
                        event_type=EventType.JOB_FAILED,
                        message=f"Replacement failed: {job.error_message}",
                        metadata={
                            "stage": job.current_stage.value,
                            "preserved_old_vps": job.old_vps_id,
                        },
                    )
                )

    def _is_retryable_failure(self, job: ReplacementJob) -> bool:
        """Determine if a failure is retryable.

        Args:
            job: Failed job.

        Returns:
            True if failure should be retried.
        """
        # Failures before VPS creation are always retryable
        if job.current_stage in (
            ReplacementStage.PENDING,
            ReplacementStage.CONFIRMING_FAILURE,
            ReplacementStage.CREATING_VPS,
        ):
            return True

        # IP check failures are retryable (will create new VPS)
        if job.current_stage == ReplacementStage.CHECKING_IP:
            return True

        # Later stage failures might be retryable depending on configuration
        return settings.replacement_retry_later_stages
