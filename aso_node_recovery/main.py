#!/usr/bin/env python3
"""ASO Node Recovery - Main Application Entry Point.

This is the main entry point for the ASO Node Recovery system.
It initializes all components and starts the health monitoring,
replacement orchestration, and Telegram bot services.
"""

import asyncio
import signal
import sys
from typing import Any

import structlog

from aso_node_recovery.config.settings import settings
from aso_node_recovery.core.logging import setup_logging
from aso_node_recovery.database.database import Database
from aso_node_recovery.database.repository import UnitOfWork
from aso_node_recovery.deployer.ssh import DeploymentManager, SSHConfig
from aso_node_recovery.master.client import Master3XUI, MasterConfig
from aso_node_recovery.providers.hetzner import HetznerProvider
from aso_node_recovery.providers.linode import LinodeProvider
from aso_node_recovery.reachability.check_host import CheckHostChecker
from aso_node_recovery.services.health_monitor import HealthMonitor
from aso_node_recovery.services.orchestrator import ReplacementOrchestrator
from aso_node_recovery.telegram.bot import TelegramBot

logger = structlog.get_logger(__name__)


class ASORecoveryApp:
    """Main application class for ASO Node Recovery.

    This class manages the lifecycle of all system components:
    - Database connection
    - Provider clients
    - Health monitor
    - Replacement orchestrator
    - Telegram bot
    """

    def __init__(self, dry_run: bool = False, debug: bool = False):
        """Initialize the application.

        Args:
            dry_run: If True, skip actual destructive operations.
            debug: If True, enable debug logging.
        """
        self.dry_run = dry_run or settings.dry_run.enabled
        self.debug = debug or settings.debug
        
        # Setup logging
        setup_logging(level="DEBUG" if self.debug else settings.logging.level)
        
        # Core components
        self.db: Database | None = None
        self.uow: UnitOfWork | None = None
        self.provider: Any = None
        self.reachability_checker: Any = None
        self.master_client: Master3XUI | None = None
        self.orchestrator: ReplacementOrchestrator | None = None
        self.health_monitor: HealthMonitor | None = None
        self.telegram_bot: TelegramBot | None = None
        
        # State
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        logger.info(
            "ASO Node Recovery initialized",
            dry_run=self.dry_run,
            debug=self.debug,
        )

    async def initialize(self) -> bool:
        """Initialize all application components.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        try:
            # Initialize database
            logger.info("Initializing database...")
            self.db = Database(settings.database.path)
            await self.db.initialize()
            self.uow = UnitOfWork(self.db)
            logger.info("Database initialized")

            # Initialize provider
            logger.info("Initializing provider...")
            self.provider = await self._initialize_provider()
            if not self.provider:
                logger.error("No provider configured or initialized")
                return False
            logger.info(f"Provider initialized: {self.provider.name}")

            # Initialize reachability checker
            logger.info("Initializing reachability checker...")
            self.reachability_checker = await self._initialize_reachability()
            if not self.reachability_checker:
                logger.error("Reachability checker not available")
                return False
            logger.info(f"Reachability checker initialized: {self.reachability_checker.name}")

            # Initialize Master client
            logger.info("Initializing Master 3X-UI client...")
            master_config = MasterConfig(
                base_url=f"http{'s' if settings.master.use_https else ''}://{settings.master.host}:{settings.master.port}",
                username=settings.master.username,
                password=settings.master.password.get_secret_value(),
            )
            self.master_client = Master3XUI(master_config)
            logger.info("Master client initialized")

            # Initialize orchestrator
            logger.info("Initializing replacement orchestrator...")
            self.orchestrator = ReplacementOrchestrator(
                uow=self.uow,
                provider=self.provider,
                reachability_checker=self.reachability_checker,
                master_client=self.master_client,
                dry_run=self.dry_run,
            )
            logger.info("Orchestrator initialized")

            # Initialize health monitor
            logger.info("Initializing health monitor...")
            self.health_monitor = HealthMonitor(
                uow=self.uow,
                orchestrator=self.orchestrator,
                ping_interval_seconds=settings.failure_detection.ping_interval_seconds,
                consecutive_failures_threshold=settings.failure_detection.consecutive_failures_threshold,
                failure_confirmation_retries=settings.failure_detection.failure_confirmation_retries,
                dry_run=self.dry_run,
            )
            logger.info("Health monitor initialized")

            # Initialize Telegram bot
            if settings.telegram.enabled:
                logger.info("Initializing Telegram bot...")
                
                def orchestrator_factory():
                    return ReplacementOrchestrator(
                        uow=self.uow,
                        provider=self.provider,
                        reachability_checker=self.reachability_checker,
                        master_client=self.master_client,
                        dry_run=self.dry_run,
                    )
                
                self.telegram_bot = TelegramBot(
                    uow=self.uow,
                    orchestrator_factory=orchestrator_factory,
                    bot_token=settings.telegram.bot_token.get_secret_value() if settings.telegram.bot_token else None,
                    allowed_user_ids=settings.telegram.admin_user_ids,
                )
                
                if await self.telegram_bot.initialize():
                    logger.info("Telegram bot initialized")
                else:
                    logger.warning("Telegram bot initialization failed, continuing without it")
            else:
                logger.info("Telegram bot disabled")

            # Recover any pending jobs
            logger.info("Checking for pending jobs to recover...")
            await self._recover_pending_jobs()
            
            logger.info("All components initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize application: {e}", exc_info=True)
            return False

    async def _initialize_provider(self) -> Any:
        """Initialize the appropriate VPS provider.

        Returns:
            Initialized provider instance or None.
        """
        # Try Hetzner first
        if settings.hetzner.api_token.get_secret_value():
            try:
                from aso_node_recovery.providers.base import ProviderConfig
                config = ProviderConfig(
                    api_key=settings.hetzner.api_token.get_secret_value(),
                    region="fsn1",
                    plan="cx11",
                    image="ubuntu-22.04",
                )
                provider = HetznerProvider(config)
                await provider.initialize()
                return provider
            except Exception as e:
                logger.warning(f"Hetzner provider initialization failed: {e}")

        # Try Linode
        if settings.linode.api_token.get_secret_value():
            try:
                from aso_node_recovery.providers.base import ProviderConfig
                config = ProviderConfig(
                    api_key=settings.linode.api_token.get_secret_value(),
                    region="us-east",
                    plan="g6-nanode-1",
                    image="linode/ubuntu22.04",
                )
                provider = LinodeProvider(config)
                await provider.initialize()
                return provider
            except Exception as e:
                logger.warning(f"Linode provider initialization failed: {e}")

        return None

    async def _initialize_reachability(self) -> Any:
        """Initialize reachability checker.

        Returns:
            Initialized checker instance or None.
        """
        try:
            checker = CheckHostChecker(
                nodes=None,  # Use defaults
                timeout_seconds=30,
            )
            await checker.initialize()
            return checker
        except Exception as e:
            logger.warning(f"Reachability checker initialization failed: {e}")
            return None

    async def _recover_pending_jobs(self) -> None:
        """Recover any pending replacement jobs from previous runs."""
        if not self.uow:
            return

        async with self.uow:
            pending_jobs = await self.uow.jobs.get_pending_jobs()
            running_jobs = await self.uow.jobs.get_running_jobs()
            
            jobs_to_recover = pending_jobs + running_jobs
            
            if jobs_to_recover:
                logger.info(f"Found {len(jobs_to_recover)} jobs to recover")
                
                for job in jobs_to_recover:
                    logger.info(
                        f"Recovering job {job.id} for node {job.node_name}",
                        stage=job.current_stage.value,
                        status=job.status.value,
                    )
                    
                    # Mark job for recovery
                    job.status = job.status  # Keep current status
                    job.updated_at = asyncio.datetime.now()  # type: ignore
                    
                    await self.uow.jobs.update(job)
                
                await self.uow.commit()
                logger.info(f"Recovered {len(jobs_to_recover)} jobs")

    async def start(self) -> None:
        """Start the application."""
        if not await self.initialize():
            logger.error("Failed to initialize application")
            return

        self._running = True
        logger.info("Starting ASO Node Recovery...")

        # Start health monitor
        if self.health_monitor:
            logger.info("Starting health monitor...")
            asyncio.create_task(self.health_monitor.start())

        # Run Telegram bot if enabled
        if self.telegram_bot and self.telegram_bot._running:
            logger.info("Starting Telegram bot...")
            # The bot runs in its own task managed by telegram.ext

        # Wait for shutdown signal
        logger.info("Application started. Press Ctrl+C to stop.")
        await self._shutdown_event.wait()

        logger.info("Shutdown signal received")

    async def stop(self) -> None:
        """Stop the application gracefully."""
        logger.info("Stopping ASO Node Recovery...")
        self._running = False

        # Stop health monitor
        if self.health_monitor:
            logger.info("Stopping health monitor...")
            await self.health_monitor.stop()

        # Stop Telegram bot
        if self.telegram_bot:
            logger.info("Stopping Telegram bot...")
            await self.telegram_bot.shutdown()

        # Close provider
        if self.provider:
            logger.info("Closing provider...")
            if hasattr(self.provider, 'close'):
                await self.provider.close()

        # Close reachability checker
        if self.reachability_checker:
            logger.info("Closing reachability checker...")
            if hasattr(self.reachability_checker, 'close'):
                await self.reachability_checker.close()

        # Close database
        if self.db:
            logger.info("Closing database...")
            await self.db.close()

        logger.info("ASO Node Recovery stopped")
        self._shutdown_event.set()

    def request_shutdown(self) -> None:
        """Request application shutdown."""
        if not self._running:
            return
        
        logger.info("Shutdown requested")
        asyncio.create_task(self.stop())


def create_app(dry_run: bool = False, debug: bool = False) -> ASORecoveryApp:
    """Create ASO Recovery application instance.

    Args:
        dry_run: Enable dry run mode.
        debug: Enable debug mode.

    Returns:
        Application instance.
    """
    return ASORecoveryApp(dry_run=dry_run, debug=debug)


async def main_async(dry_run: bool = False, debug: bool = False) -> None:
    """Async main function.

    Args:
        dry_run: Enable dry run mode.
        debug: Enable debug mode.
    """
    app = create_app(dry_run=dry_run, debug=debug)
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        app.request_shutdown()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await app.start()
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        await app.stop()
        raise


def main() -> None:
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="ASO Node Recovery - Automated VPS Node Recovery System"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enable dry run mode (no real actions)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    
    try:
        asyncio.run(main_async(dry_run=args.dry_run, debug=args.debug))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
