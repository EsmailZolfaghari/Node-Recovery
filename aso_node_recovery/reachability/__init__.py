"""Reachability checking module.

This module provides abstractions for checking IP address reachability
from multiple locations worldwide.
"""

from aso_node_recovery.reachability.base import (
    BaseReachabilityChecker,
    CheckHostUnavailableError,
    ReachabilityError,
    ReachabilityResult,
    ReachabilityStatus,
)
from aso_node_recovery.reachability.check_host import (
    CheckHostChecker,
    MockReachabilityChecker,
    create_check_host_checker,
    create_mock_checker,
)

__all__ = [
    # Base classes
    "BaseReachabilityChecker",
    "ReachabilityChecker",
    "ReachabilityResult",
    "ReachabilityStatus",
    "ReachabilityError",
    "CheckHostUnavailableError",
    # Implementations
    "CheckHostChecker",
    "MockReachabilityChecker",
    # Factory functions
    "create_check_host_checker",
    "create_mock_checker",
]

# Alias for backward compatibility
ReachabilityChecker = BaseReachabilityChecker
