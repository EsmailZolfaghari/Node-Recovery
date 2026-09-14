"""Reachability checking abstraction layer.

This module defines the interface for checking IP reachability from multiple
locations/networks, allowing the system to verify if a new VPS IP is accessible
from the networks that matter to users.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReachabilityStatus(Enum):
    """Status of IP reachability check."""

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    PARTIAL = "partial"  # Reachable from some locations but not all
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class ReachabilityResult:
    """Result of a reachability check."""

    ip: str
    status: ReachabilityStatus
    checked_from: list[str]  # List of locations/checkers used
    reachable_from: list[str]  # Locations where IP is reachable
    unreachable_from: list[str]  # Locations where IP is unreachable
    
    # Detailed results per location
    details: dict[str, Any] | None = None
    
    # Error information if check failed
    error_message: str | None = None
    
    def is_good(self) -> bool:
        """Check if IP is considered good (reachable from all or most locations)."""
        return self.status == ReachabilityStatus.REACHABLE
    
    def is_bad(self) -> bool:
        """Check if IP is considered bad (unreachable from most locations)."""
        return self.status in (ReachabilityStatus.UNREACHABLE, ReachabilityStatus.ERROR)


class BaseReachabilityChecker(ABC):
    """Abstract base class for reachability checkers.

    All reachability checker implementations must inherit from this class
    and implement the abstract methods.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the reachability checker.

        This method should be called before any checks are performed.
        It should set up HTTP sessions, authentication, etc.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the reachability checker and cleanup resources."""
        pass

    @abstractmethod
    async def check_ip(self, ip: str) -> ReachabilityResult:
        """Check if an IP address is reachable.

        Args:
            ip: IP address to check.

        Returns:
            ReachabilityResult with check results.
        """
        pass

    @abstractmethod
    async def check_multiple_ips(self, ips: list[str]) -> dict[str, ReachabilityResult]:
        """Check multiple IP addresses.

        Args:
            ips: List of IP addresses to check.

        Returns:
            Dictionary mapping IP addresses to their reachability results.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this reachability checker."""
        pass


class ReachabilityError(Exception):
    """Base exception for reachability checker errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CheckHostUnavailableError(ReachabilityError):
    """Exception raised when check service is unavailable."""

    pass
