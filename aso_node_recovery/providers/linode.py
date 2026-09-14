"""Linode (Akamai) provider implementation.

This module implements the BaseProvider interface for Linode API.
API Documentation: https://www.linode.com/docs/api/
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from aso_node_recovery.models.vps import VPSInfo
from aso_node_recovery.providers.base import (
    AuthenticationError,
    BaseProvider,
    NotFoundError,
    ProviderConfig,
    ProviderError,
    RateLimitError,
    ValidationError,
)


class LinodeProvider(BaseProvider):
    """Linode provider implementation."""

    BASE_URL = "https://api.linode.com/v4"

    def __init__(self, config: ProviderConfig):
        """Initialize Linode provider.

        Args:
            config: Provider configuration with API key.
        """
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize HTTP client with authentication."""
        if not self.config.api_key:
            raise AuthenticationError("Linode API key is required")

        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def name(self) -> str:
        """Return provider name."""
        return "linode"

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
        """Create a new Linode instance.

        Args:
            name: Name/label for the Linode.
            region: Region ID (e.g., 'us-east', 'eu-central').
            plan: Plan ID (e.g., 'g6-nanode-1').
            image: Image ID (e.g., 'linode/ubuntu22.04').
            ssh_key_id: SSH key ID to inject.
            ipv6_enabled: Whether to enable IPv6.
            metadata: User data/tags.

        Returns:
            VPSInfo with created Linode details.

        Raises:
            ProviderError: If Linode creation fails.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        # Use defaults from config if not provided
        region = region or self.config.region or "us-east"
        plan = plan or self.config.plan or "g6-nanode-1"
        image = image or self.config.image or "linode/ubuntu22.04"

        payload: dict[str, Any] = {
            "label": name,
            "region": region,
            "type": plan,
            "image": image,
            "booted": True,
        }

        # Configure network interfaces
        interfaces = [{"purpose": "public"}]
        if ipv6_enabled:
            interfaces[0]["ipv4"] = "any"
        else:
            payload["ipv4"] = "any"  # IPv4 only
        
        payload["interfaces"] = interfaces

        # SSH key configuration
        if ssh_key_id:
            payload["authorized_keys"] = [ssh_key_id]

        # Metadata/tags via tags field
        if metadata:
            payload["tags"] = list(metadata.keys())

        try:
            response = await self._client.post("/linode/instances", json=payload)

            if response.status_code == 401:
                raise AuthenticationError("Invalid Linode API key")
            elif response.status_code == 400:
                error_data = response.json()
                raise ValidationError(f"Invalid request: {error_data.get('errors', [])}")
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimitError(
                    "Linode API rate limit exceeded",
                    retry_after=int(retry_after) if retry_after else None,
                )
            elif response.status_code >= 400:
                raise ProviderError(f"Failed to create Linode: {response.status_code}")

            data = response.json()
            return self._parse_linode(data)

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def get_vps(self, vps_id: str) -> VPSInfo:
        """Get Linode instance information.

        Args:
            vps_id: Linode ID.

        Returns:
            VPSInfo with Linode details.

        Raises:
            NotFoundError: If Linode does not exist.
            ProviderError: If retrieval fails.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        try:
            response = await self._client.get(f"/linode/instances/{vps_id}")

            if response.status_code == 404:
                raise NotFoundError(f"Linode {vps_id} not found")
            elif response.status_code == 401:
                raise AuthenticationError("Invalid Linode API key")
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimitError(
                    "Linode API rate limit exceeded",
                    retry_after=int(retry_after) if retry_after else None,
                )
            elif response.status_code >= 400:
                raise ProviderError(f"Failed to get Linode: {response.status_code}")

            data = response.json()
            return self._parse_linode(data)

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def delete_vps(self, vps_id: str) -> bool:
        """Delete a Linode instance.

        Args:
            vps_id: Linode ID.

        Returns:
            True if deletion was successful.

        Raises:
            NotFoundError: If Linode does not exist.
            ProviderError: If deletion fails.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        try:
            response = await self._client.delete(f"/linode/instances/{vps_id}")

            if response.status_code == 404:
                raise NotFoundError(f"Linode {vps_id} not found")
            elif response.status_code == 401:
                raise AuthenticationError("Invalid Linode API key")
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimitError(
                    "Linode API rate limit exceeded",
                    retry_after=int(retry_after) if retry_after else None,
                )
            elif response.status_code >= 400:
                raise ProviderError(f"Failed to delete Linode: {response.status_code}")

            return True

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def list_vps(self, tags: dict[str, str] | None = None) -> list[VPSInfo]:
        """List Linode instances.

        Args:
            tags: Filter by tags.

        Returns:
            List of VPSInfo for matching instances.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        params: dict[str, Any] = {}
        
        try:
            response = await self._client.get("/linode/instances", params=params)

            if response.status_code >= 400:
                raise ProviderError(f"Failed to list Linodes: {response.status_code}")

            data = response.json()
            linodes = data.get("data", [])
            
            # Filter by tags if specified
            if tags:
                tag_keys = set(tags.keys())
                linodes = [
                    l for l in linodes
                    if any(t in tag_keys for t in l.get("tags", []))
                ]
            
            return [self._parse_linode(l) for l in linodes]

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def wait_for_active(
        self, vps_id: str, timeout_seconds: int = 300, poll_interval_seconds: int = 5
    ) -> VPSInfo:
        """Wait for Linode to become running.

        Args:
            vps_id: Linode ID.
            timeout_seconds: Maximum time to wait.
            poll_interval_seconds: Time between status checks.

        Returns:
            VPSInfo with updated status.

        Raises:
            TimeoutError: If Linode doesn't become active within timeout.
            ProviderError: If status check fails.
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Linode {vps_id} did not become active within {timeout_seconds}s")

            try:
                vps = await self.get_vps(vps_id)
                if vps.is_active():
                    return vps
            except NotFoundError:
                pass  # Linode might still be provisioning

            await asyncio.sleep(poll_interval_seconds)

    def _parse_linode(self, linode_data: dict[str, Any]) -> VPSInfo:
        """Parse Linode response into VPSInfo.

        Args:
            linode_data: Raw Linode data from API.

        Returns:
            VPSInfo with parsed Linode information.
        """
        # Extract IP addresses
        ipv4 = None
        ipv6 = None
        
        ipv4_addresses = linode_data.get("ipv4", [])
        if ipv4_addresses and isinstance(ipv4_addresses, list):
            ipv4 = ipv4_addresses[0]
        elif isinstance(ipv4_addresses, str):
            ipv4 = ipv4_addresses
        
        ipv6_address = linode_data.get("ipv6")
        if ipv6_address and isinstance(ipv6_address, dict):
            ipv6 = ipv6_address.get("global")
        elif isinstance(ipv6_address, str):
            ipv6 = ipv6_address

        # Parse timestamps
        created_at = None
        if linode_data.get("created"):
            try:
                created_at = datetime.fromisoformat(linode_data["created"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return VPSInfo(
            id=str(linode_data.get("id", "")),
            provider="linode",
            label=linode_data.get("label"),
            status=linode_data.get("status", "unknown"),
            ipv4=ipv4,
            ipv6=ipv6,
            hostname=linode_data.get("label"),
            region=linode_data.get("region"),
            datacenter=linode_data.get("region"),
            plan=linode_data.get("type"),
            created_at=created_at,
            raw_data=linode_data,
        )


def create_linode_provider(config: ProviderConfig) -> LinodeProvider:
    """Factory function to create Linode provider.

    Args:
        config: Provider configuration.

    Returns:
        Configured LinodeProvider instance.
    """
    return LinodeProvider(config)
