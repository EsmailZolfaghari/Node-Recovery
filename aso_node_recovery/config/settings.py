"""Application settings and configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class HetznerSettings(BaseSettings):
    """Hetzner Cloud API settings."""

    api_token: SecretStr = Field(
        default=SecretStr(""),
        description="Hetzner Cloud API token",
    )


class LinodeSettings(BaseSettings):
    """Linode API settings."""

    api_token: SecretStr = Field(
        default=SecretStr(""),
        description="Linode API token",
    )


class MasterSettings(BaseSettings):
    """3X-UI Master settings."""

    host: str = Field(default="localhost", description="Master server hostname")
    port: int = Field(default=54321, description="Master server port")
    username: str = Field(default="admin", description="Master username")
    password: SecretStr = Field(
        default=SecretStr("admin"),
        description="Master password",
    )
    use_https: bool = Field(default=False, description="Use HTTPS for master connection")


class SSHSettings(BaseSettings):
    """SSH connection settings."""

    username: str = Field(default="root", description="Default SSH username")
    key_file: str | None = Field(default=None, description="Path to SSH private key file")
    password: SecretStr | None = Field(default=None, description="SSH password (if no key)")
    timeout: int = Field(default=30, description="SSH connection timeout in seconds")
    connect_timeout: int = Field(default=60, description="SSH connect timeout in seconds")


class ReachabilitySettings(BaseSettings):
    """Reachability check settings."""

    provider: Literal["check-host", "manual"] = Field(
        default="check-host",
        description="Reachability check provider",
    )
    check_host_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Check-Host.net API key",
    )
    min_reachable_countries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Minimum number of countries that must reach the IP",
    )


class FailureDetectionSettings(BaseSettings):
    """Failure detection settings."""

    ping_interval_seconds: int = Field(
        default=60,
        ge=10,
        description="Interval between health checks in seconds",
    )
    consecutive_failures_threshold: int = Field(
        default=3,
        ge=1,
        description="Number of consecutive failures before marking node as failed",
    )
    failure_confirmation_retries: int = Field(
        default=2,
        ge=1,
        description="Number of confirmation rounds before triggering replacement",
    )


class ReplacementSettings(BaseSettings):
    """Replacement job settings."""

    max_attempts: int = Field(
        default=5,
        ge=1,
        description="Maximum replacement attempts per node",
    )
    ip_check_max_retries: int = Field(
        default=3,
        ge=1,
        description="Maximum retries for IP reachability check",
    )
    ssh_ready_timeout_seconds: int = Field(
        default=300,
        ge=60,
        description="Timeout for SSH to become ready after VPS creation",
    )
    deployment_timeout_seconds: int = Field(
        default=600,
        ge=120,
        description="Timeout for 3X-UI deployment",
    )
    max_concurrent: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum concurrent replacement jobs",
    )


class FailureConfirmationSettings(BaseSettings):
    """Failure confirmation settings."""

    checks: int = Field(
        default=3,
        ge=1,
        description="Number of health checks to confirm failure",
    )
    interval_seconds: int = Field(
        default=30,
        ge=5,
        description="Interval between confirmation checks",
    )


class TelegramSettings(BaseSettings):
    """Telegram bot settings."""

    enabled: bool = Field(default=False, description="Enable Telegram bot")
    bot_token: SecretStr = Field(
        default=SecretStr(""),
        description="Telegram bot token",
    )
    admin_user_ids: list[int] = Field(
        default_factory=list,
        description="List of admin user IDs allowed to control the bot",
    )
    notify_on_failure: bool = Field(default=True, description="Notify on node failure")
    notify_on_replacement_start: bool = Field(
        default=True,
        description="Notify when replacement starts",
    )
    notify_on_replacement_complete: bool = Field(
        default=True,
        description="Notify when replacement completes",
    )
    notify_on_replacement_fail: bool = Field(
        default=True,
        description="Notify when replacement fails",
    )


class DatabaseSettings(BaseSettings):
    """Database settings."""

    path: str = Field(
        default="data/aso_recovery.db",
        description="Path to SQLite database file",
    )


class LoggingSettings(BaseSettings):
    """Logging settings."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Log level",
    )
    format_type: Literal["json", "console"] = Field(
        default="console",
        description="Log format type",
    )
    file_path: str | None = Field(
        default=None,
        description="Path to log file (None for stdout only)",
    )


class DryRunSettings(BaseSettings):
    """Dry run settings."""

    enabled: bool = Field(
        default=False,
        description="Enable dry run mode (no real actions)",
    )


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "ASO Node Recovery"
    debug: bool = Field(default=False, description="Enable debug mode")
    dry_run: DryRunSettings = Field(default_factory=DryRunSettings)

    # Provider settings
    hetzner: HetznerSettings = Field(default_factory=HetznerSettings)
    linode: LinodeSettings = Field(default_factory=LinodeSettings)

    # Master settings
    master: MasterSettings = Field(default_factory=MasterSettings)

    # SSH settings
    ssh: SSHSettings = Field(default_factory=SSHSettings)

    # Reachability settings
    reachability: ReachabilitySettings = Field(default_factory=ReachabilitySettings)

    # Failure detection settings
    failure_detection: FailureDetectionSettings = Field(
        default_factory=FailureDetectionSettings
    )

    # Replacement settings
    replacement: ReplacementSettings = Field(default_factory=ReplacementSettings)

    # Failure confirmation settings
    failure_confirmation: FailureConfirmationSettings = Field(
        default_factory=FailureConfirmationSettings
    )

    # Telegram settings
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)

    # Database settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

    # Logging settings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
