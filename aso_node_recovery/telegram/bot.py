"""Telegram bot integration for ASO Node Recovery.

This module provides a Telegram bot interface for monitoring and controlling
the node replacement system. It is designed as an optional control plane -
the core system works without Telegram.

Features:
- Status overview
- Node list and details
- Manual replacement trigger
- Job progress tracking
- Cancel/pause/resume jobs
- Event history
- Health checks
- Dry run mode toggle
"""

import asyncio
from typing import Any

import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from aso_node_recovery.config.settings import settings
from aso_node_recovery.database.repository import UnitOfWork
from aso_node_recovery.models.event import EventType
from aso_node_recovery.models.replacement import ReplacementJob, ReplacementStatus
from aso_node_recovery.services.orchestrator import ReplacementOrchestrator

logger = structlog.get_logger(__name__)


class TelegramBot:
    """Telegram bot for ASO Node Recovery control and monitoring.

    This class implements the Telegram bot interface and handles all
    bot commands, callbacks, and notifications.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        orchestrator_factory: callable,
        bot_token: str | None = None,
        allowed_user_ids: list[int] | None = None,
    ):
        """Initialize Telegram bot.

        Args:
            uow: Unit of work for database operations.
            orchestrator_factory: Factory function to create orchestrator instances.
            bot_token: Telegram bot token.
            allowed_user_ids: List of user IDs allowed to use the bot.
        """
        self.uow = uow
        self.orchestrator_factory = orchestrator_factory
        self.bot_token = bot_token or settings.telegram_bot_token
        self.allowed_user_ids = allowed_user_ids or settings.telegram_allowed_user_ids
        self._application: Application | None = None
        self._bot: Bot | None = None
        self._running = False

    async def initialize(self) -> bool:
        """Initialize the Telegram bot.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if not self.bot_token:
            logger.warning("Telegram bot token not configured, bot disabled")
            return False

        if not self.allowed_user_ids:
            logger.warning("No allowed user IDs configured for Telegram bot")
            return False

        try:
            # Create bot application
            self._application = (
                Application.builder().token(self.bot_token).build()
            )

            # Register command handlers
            self._application.add_handler(CommandHandler("start", self._cmd_start))
            self._application.add_handler(CommandHandler("help", self._cmd_help))
            self._application.add_handler(CommandHandler("status", self._cmd_status))
            self._application.add_handler(CommandHandler("nodes", self._cmd_nodes))
            self._application.add_handler(CommandHandler("jobs", self._cmd_jobs))
            self._application.add_handler(CommandHandler("events", self._cmd_events))
            self._application.add_handler(CommandHandler("health", self._cmd_health))
            self._application.add_handler(CommandHandler("dryrun", self._cmd_dryrun))

            # Manual replacement command with node parameter
            self._application.add_handler(
                CommandHandler("replace", self._cmd_replace)
            )

            # Callback query handler for inline buttons
            self._application.add_handler(
                CallbackQueryHandler(self._callback_handler)
            )

            # Start the bot
            await self._application.initialize()
            await self._application.start()

            self._bot = self._application.bot
            self._running = True

            logger.info(
                "Telegram bot initialized",
                bot_username=self._bot.username if self._bot else None,
            )

            return True

        except Exception as e:
            logger.error("Failed to initialize Telegram bot", error=str(e))
            return False

    async def shutdown(self) -> None:
        """Shutdown the Telegram bot."""
        self._running = False

        if self._application:
            try:
                await self._application.stop()
                await self._application.shutdown()
            except Exception as e:
                logger.error("Error shutting down Telegram bot", error=str(e))

        logger.info("Telegram bot shut down")

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized to use the bot.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if user is authorized.
        """
        return user_id in self.allowed_user_ids

    async def _check_auth(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Check authorization and send warning if unauthorized.

        Args:
            update: Update object.
            context: Context object.

        Returns:
            True if authorized.
        """
        if not update.effective_user:
            return False

        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text(
                "⛔ Unauthorized access. You are not allowed to use this bot."
            )
            logger.warning(
                "Unauthorized bot access attempt",
                user_id=update.effective_user.id,
                username=update.effective_user.username,
            )
            return False

        return True

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        if not await self._check_auth(update, context):
            return

        welcome_message = """
🤖 **ASO Node Recovery Bot**

I help you manage automatic VPS node replacement.

Use /help to see available commands.
        """
        await update.message.reply_text(welcome_message.strip())

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        if not await self._check_auth(update, context):
            return

        help_text = """
📖 **Available Commands:**

/status - System overview
/nodes - List all nodes
/jobs - Active replacement jobs
/events - Recent events
/health - Health check
/dryrun - Toggle dry run mode
/replace <node_id> - Manually replace a node

**When replacement is running:**
You'll receive progress updates automatically.
        """
        await update.message.reply_text(help_text.strip())

    async def _cmd_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command - show system overview."""
        if not await self._check_auth(update, context):
            return

        async with self.uow:
            # Count nodes by status
            all_nodes = await self.uow.nodes.get_all()
            active_count = sum(1 for n in all_nodes if n.status.value == "active")
            unhealthy_count = sum(
                1 for n in all_nodes if n.status.value == "unhealthy"
            )
            replacing_count = sum(
                1 for n in all_nodes if n.status.value == "replacing"
            )

            # Count active jobs
            active_jobs = await self.uow.jobs.get_active_jobs()
            job_count = len(active_jobs)

            # Get recent events
            recent_events = await self.uow.events.get_recent(limit=5)

        status_message = f"""
📊 **System Status**

🖥️ **Nodes:**
• Total: {len(all_nodes)}
• Active: {active_count}
• Unhealthy: {unhealthy_count}
• Replacing: {replacing_count}

🔄 **Active Jobs:** {job_count}

📝 **Recent Events:**
"""

        for event in recent_events:
            emoji = {
                EventType.JOB_CREATED: "🆕",
                EventType.JOB_COMPLETED: "✅",
                EventType.JOB_FAILED: "❌",
                EventType.CLEANUP_COMPLETED: "🧹",
            }.get(event.event_type, "•")

            status_message += f"\n{emoji} {event.message[:50]}"

        await update.message.reply_text(status_message.strip())

    async def _cmd_nodes(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /nodes command - list all nodes."""
        if not await self._check_auth(update, context):
            return

        async with self.uow:
            nodes = await self.uow.nodes.get_all()

        if not nodes:
            await update.message.reply_text("No nodes configured.")
            return

        nodes_message = "🖥️ **Configured Nodes:**\n\n"

        for node in nodes[:20]:  # Limit to 20 nodes
            status_emoji = {
                "active": "✅",
                "unhealthy": "⚠️",
                "unknown": "❓",
                "replacing": "🔄",
            }.get(node.status.value, "•")

            nodes_message += f"{status_emoji} **{node.name}**\n"
            nodes_message += f"   IP: `{node.ip_address}`\n"
            nodes_message += f"   Provider: {node.provider}\n"
            nodes_message += f"   Status: {node.status.value}\n\n"

        if len(nodes) > 20:
            nodes_message += f"... and {len(nodes) - 20} more nodes"

        await update.message.reply_text(nodes_message.strip())

    async def _cmd_jobs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /jobs command - show active replacement jobs."""
        if not await self._check_auth(update, context):
            return

        async with self.uow:
            jobs = await self.uow.jobs.get_active_jobs()

        if not jobs:
            await update.message.reply_text("No active replacement jobs.")
            return

        jobs_message = "🔄 **Active Replacement Jobs:**\n\n"

        for job in jobs:
            stage_emoji = {
                "confirming_failure": "🔍",
                "creating_vps": "🏗️",
                "checking_ip": "🌐",
                "waiting_ssh": "🔑",
                "deploying_3xui": "📦",
                "verifying_deployment": "✓",
                "updating_master": "📡",
                "verifying_master": "✓",
                "final_health_check": "🏥",
                "cleaning_up": "🧹",
            }.get(job.current_stage.value, "•")

            jobs_message += f"{stage_emoji} **Job #{job.id}** - {job.node_name}\n"
            jobs_message += f"   Stage: {job.get_progress_summary()}\n"
            jobs_message += f"   Attempt: {job.attempt_number}/{job.max_attempts}\n"
            jobs_message += f"   Old VPS: `{job.old_vps_id}`\n"
            if job.new_vps_id:
                jobs_message += f"   New VPS: `{job.new_vps_id}`\n"
            jobs_message += "\n"

        await update.message.reply_text(jobs_message.strip())

    async def _cmd_events(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /events command - show recent events."""
        if not await self._check_auth(update, context):
            return

        limit = 20
        if context.args and context.args[0].isdigit():
            limit = int(context.args[0])

        async with self.uow:
            events = await self.uow.events.get_recent(limit=limit)

        if not events:
            await update.message.reply_text("No recent events.")
            return

        events_message = f"📝 **Recent Events (last {len(events)}):**\n\n"

        for event in events:
            timestamp = event.created_at.strftime("%Y-%m-%d %H:%M:%S")
            events_message += f"`{timestamp}` - {event.message}\n"

        await update.message.reply_text(events_message.strip())

    async def _cmd_health(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /health command - perform health check."""
        if not await self._check_auth(update, context):
            return

        health_message = "🏥 **Health Check:**\n\n"

        # Check database
        try:
            async with self.uow:
                node_count = len(await self.uow.nodes.get_all())
            health_message += "✅ Database: Connected\n"
            health_message += f"   Nodes: {node_count}\n"
        except Exception as e:
            health_message += f"❌ Database: {str(e)}\n"

        # Check Master connectivity
        try:
            orchestrator = self.orchestrator_factory()
            if orchestrator.master_client:
                is_healthy = await orchestrator.master_client.health_check()
                health_message += (
                    "✅ Master 3X-UI: Connected\n"
                    if is_healthy
                    else "⚠️ Master 3X-UI: Reachable but issues detected\n"
                )
        except Exception as e:
            health_message += f"❌ Master 3X-UI: {str(e)}\n"

        # Check provider connectivity
        try:
            orchestrator = self.orchestrator_factory()
            if orchestrator.provider:
                health_message += f"✅ Provider ({orchestrator.provider.name}): Connected\n"
        except Exception as e:
            health_message += f"❌ Provider: {str(e)}\n"

        await update.message.reply_text(health_message.strip())

    async def _cmd_dryrun(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /dryrun command - toggle dry run mode."""
        if not await self._check_auth(update, context):
            return

        # Note: In a real implementation, this would toggle a global setting
        # For now, just show current status
        is_dry_run = settings.dry_run_mode
        status = "enabled" if is_dry_run else "disabled"

        message = f"🧪 **Dry Run Mode:** {status}\n\n"
        if is_dry_run:
            message += "No actual VPS will be created or deleted."
        else:
            message += "All operations will be performed live."

        await update.message.reply_text(message.strip())

    async def _cmd_replace(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /replace command - manually trigger node replacement."""
        if not await self._check_auth(update, context):
            return

        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text(
                "Usage: /replace <node_id>\n\nExample: /replace 1"
            )
            return

        node_id = int(context.args[0])

        # Confirm before proceeding
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Confirm", callback_data=f"replace_confirm_{node_id}"
                ),
                InlineKeyboardButton("❌ Cancel", callback_data="replace_cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        async with self.uow:
            node = await self.uow.nodes.get_by_id(node_id)

        if not node:
            await update.message.reply_text(f"Node {node_id} not found.")
            return

        confirm_message = f"""
⚠️ **Confirm Node Replacement**

Node: **{node.name}**
Current IP: `{node.ip_address}`
Provider: {node.provider}

This will create a new VPS and replace the current one.
Old VPS will be preserved until new one is fully verified.

Proceed?
        """

        await update.message.reply_text(confirm_message.strip(), reply_markup=reply_markup)

    async def _callback_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle callback queries from inline keyboards."""
        if not await self._check_auth(update, context):
            return

        query = update.callback_query
        data = query.data

        if data.startswith("replace_confirm_"):
            node_id = int(data.split("_")[-1])
            await self._handle_replace_confirm(query, node_id)

        elif data == "replace_cancel":
            await query.edit_message_text("Replacement cancelled.")

    async def _handle_replace_confirm(
        self, query, node_id: int
    ) -> None:
        """Handle replacement confirmation.

        Args:
            query: Callback query.
            node_id: Node ID to replace.
        """
        await query.edit_message_text("🔄 Starting replacement...")

        orchestrator = self.orchestrator_factory()

        job = await orchestrator.start_replacement(
            node_id=node_id, reason="Manual trigger via Telegram"
        )

        if job:
            await query.edit_message_text(
                f"✅ Replacement started for node {node_id}\n\n"
                f"Job ID: {job.id}\n"
                f"Stage: {job.get_progress_summary()}"
            )

            # Start job execution in background
            asyncio.create_task(self._execute_and_notify(job.id, query.from_user.id))
        else:
            await query.edit_message_text(
                f"❌ Failed to start replacement for node {node_id}\n\n"
                "The node may already be being replaced or cannot be replaced."
            )

    async def _execute_and_notify(self, job_id: int, user_id: int) -> None:
        """Execute job and send notifications.

        Args:
            job_id: Job ID to execute.
            user_id: User ID to notify.
        """
        orchestrator = self.orchestrator_factory()
        success = await orchestrator.execute_job(job_id)

        # Get final job state
        async with self.uow:
            job = await self.uow.jobs.get_by_id(job_id)

        if job:
            if success:
                notification = f"""
✅ **Replacement Completed Successfully**

Node: {job.node_name}
New IP: `{job.new_vps_ip}`
Old VPS: {'Removed' if job.old_vps_deleted else 'Preserved'}
                """
            else:
                notification = f"""
❌ **Replacement Failed**

Node: {job.node_name}
Stage: {job.current_stage.value}
Error: {job.error_message}

⚠️ Old VPS has been PRESERVED.
Manual intervention may be required.
                """

            if self._bot and user_id:
                try:
                    await self._bot.send_message(
                        chat_id=user_id, text=notification.strip()
                    )
                except Exception as e:
                    logger.error("Failed to send completion notification", error=str(e))

    async def send_notification(
        self,
        message: str,
        parse_mode: str = "Markdown",
        chat_id: int | None = None,
    ) -> bool:
        """Send a notification message.

        Args:
            message: Message to send.
            parse_mode: Parse mode (Markdown, HTML, etc.).
            chat_id: Specific chat ID (sends to all allowed users if None).

        Returns:
            True if message was sent successfully.
        """
        if not self._bot or not self._running:
            return False

        targets = [chat_id] if chat_id else self.allowed_user_ids

        success = True
        for target_chat_id in targets:
            try:
                await self._bot.send_message(
                    chat_id=target_chat_id,
                    text=message.strip(),
                    parse_mode=parse_mode,
                )
            except Exception as e:
                logger.error(
                    "Failed to send Telegram notification",
                    chat_id=target_chat_id,
                    error=str(e),
                )
                success = False

        return success

    async def notify_job_progress(
        self, job: ReplacementJob, stage_changed: bool = False
    ) -> None:
        """Send progress notification for a job.

        Args:
            job: Current replacement job.
            stage_changed: Whether the stage changed.
        """
        if not stage_changed:
            return  # Only notify on stage changes to avoid spam

        stage_emojis = {
            "pending": "⏳",
            "confirming_failure": "🔍",
            "creating_vps": "🏗️",
            "checking_ip": "🌐",
            "waiting_ssh": "🔑",
            "deploying_3xui": "📦",
            "verifying_deployment": "✓",
            "updating_master": "📡",
            "verifying_master": "✓",
            "final_health_check": "🏥",
            "cleaning_up": "🧹",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "⛔",
        }

        emoji = stage_emojis.get(job.current_stage.value, "•")
        progress = job.get_progress_summary()

        message = f"""
{emoji} **{job.node_name}**

{progress}

Attempt: {job.attempt_number}/{job.max_attempts}
        """

        if job.new_vps_ip:
            message += f"\nNew IP: `{job.new_vps_ip}`"

        await self.send_notification(message)
