"""Provider implementations for VPS management.

This module provides abstractions and implementations for multiple VPS providers
(Hetzner, Linode, etc.) allowing the system to work with different providers
in a unified way.
"""

from aso_node_recovery.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
    NotFoundError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
)
from aso_node_recovery.providers.hetzner import HetznerProvider, create_hetzner_provider
from aso_node_recovery.providers.linode import LinodeProvider, create_linode_provider

__all__ = [
    # Base classes
    "BaseProvider",
    "ProviderConfig",
    # Exceptions
    "ProviderError",
    "NotFoundError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    # Provider implementations
    "HetznerProvider",
    "LinodeProvider",
    # Factory functions
    "create_hetzner_provider",
    "create_linode_provider",
]
