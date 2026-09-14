"""Provider abstraction layer for VPS management.

This module defines the interface that all VPS providers must implement,
allowing the system to work with multiple providers (Hetzner, Linode, etc.)
in a unified way.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from aso_node_recovery.models.vps import VPSInfo


@dataclass
class ProviderConfig:
    """Configuration for a VPS provider."""

    name: str
    api_key: str
    api_endpoint: str | None = None
    region: str | None = None
    plan: str | None = None
    image: str | None = None
    ssh_key_id: str | None = None
    extra_config: dict[str, Any] | None = None


class BaseProvider(ABC):
    """Abstract base class for VPS providers.

    All provider implementations must inherit from this class
    and implement all abstract methods.
    """

    def __init__(self, config: ProviderConfig):
        """Initialize the provider with configuration.

        Args:
            config: Provider configuration including API credentials.
        """
        self.config = config
        self._session: Any = None

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize provider client and session.

        This method should be called before any other operations.
        It should set up HTTP sessions, authentication, etc.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close provider client and cleanup resources.

        This method should be called when the provider is no longer needed.
        """
        pass

    @abstractmethod
    async def create_vps(
        self,
        name: str,
        region: str | None = None,
        plan: str | None = None,
        image: str | None = None,
        ssh_key_id: str | None = None,
        ipv6_enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> VPSInfo:
        """Create a new VPS instance.

        Args:
            name: Name for the VPS instance.
            region: Region/datacenter for the VPS (uses default if None).
            plan: Server type/plan (uses default if None).
            image: OS image to use (uses default if None).
            ssh_key_id: SSH key ID to inject (uses default if None).
            ipv6_enabled: Whether to enable IPv6.
            metadata: Additional metadata/tags for the VPS.

        Returns:
            VPSInfo with details of the created VPS.

        Raises:
            ProviderError: If VPS creation fails.
        """
        pass

    @abstractmethod
    async def get_vps(self, vps_id: str) -> VPSInfo:
        """Get information about an existing VPS.

        Args:
            vps_id: Provider-specific VPS identifier.

        Returns:
            VPSInfo with current VPS details.

        Raises:
            NotFoundError: If VPS does not exist.
            ProviderError: If retrieval fails.
        """
        pass

    @abstractmethod
    async def delete_vps(self, vps_id: str) -> bool:
        """Delete a VPS instance.

        Args:
            vps_id: Provider-specific VPS identifier.

        Returns:
            True if deletion was successful.

        Raises:
            NotFoundError: If VPS does not exist.
            ProviderError: If deletion fails.
        """
        pass

    @abstractmethod
    async def list_vps(self, tags: dict[str, str] | None = None) -> list[VPSInfo]:
        """List VPS instances, optionally filtered by tags.

        Args:
            tags: Filter by tags/labels.

        Returns:
            List of VPSInfo for matching instances.
        """
        pass

    @abstractmethod
    async def wait_for_active(
        self, vps_id: str, timeout_seconds: int = 300, poll_interval_seconds: int = 5
    ) -> VPSInfo:
        """Wait for VPS to become active.

        Args:
            vps_id: Provider-specific VPS identifier.
            timeout_seconds: Maximum time to wait.
            poll_interval_seconds: Time between status checks.

        Returns:
            VPSInfo with updated status.

        Raises:
            TimeoutError: If VPS doesn't become active within timeout.
            ProviderError: If status check fails.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""
        pass


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(ProviderError):
    """Exception raised when a resource is not found."""

    pass


class AuthenticationError(ProviderError):
    """Exception raised when authentication fails."""

    pass


class RateLimitError(ProviderError):
    """Exception raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.retry_after = retry_after


class ValidationError(ProviderError):
    """Exception raised when validation fails."""

    pass
