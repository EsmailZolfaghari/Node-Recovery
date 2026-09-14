"""Hetzner Cloud provider implementation.

This module implements the BaseProvider interface for Hetzner Cloud API.
API Documentation: https://docs.hetzner.cloud/
"""

import asyncio
from datetime import datetime
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


class HetznerProvider(BaseProvider):
    """Hetzner Cloud provider implementation."""

    BASE_URL = "https://api.hetzner.cloud/v1"

    def __init__(self, config: ProviderConfig):
        """Initialize Hetzner provider.

        Args:
            config: Provider configuration with API key.
        """
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize HTTP client with authentication."""
        if not self.config.api_key:
            raise AuthenticationError("Hetzner API key is required")

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
        return "hetzner"

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
        """Create a new VPS instance on Hetzner Cloud.

        Args:
            name: Name for the server.
            region: Datacenter location (e.g., 'fsn1', 'nbg1').
            plan: Server type (e.g., 'cx11', 'cx21').
            image: OS image (e.g., 'ubuntu-22.04').
            ssh_key_id: SSH key ID to inject.
            ipv6_enabled: Whether to enable IPv6.
            metadata: User data/tags.

        Returns:
            VPSInfo with created server details.

        Raises:
            ProviderError: If server creation fails.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        # Use defaults from config if not provided
        region = region or self.config.region or "fsn1"
        plan = plan or self.config.plan or "cx11"
        image = image or self.config.image or "ubuntu-22.04"

        payload: dict[str, Any] = {
            "name": name,
            "server_type": plan,
            "location": region,
            "image": image,
            "start_after_create": True,
        }

        if ssh_key_id:
            payload["ssh_keys"] = [ssh_key_id]

        if not ipv6_enabled:
            payload["public_net"] = {"enable_ipv4": True, "enable_ipv6": False}

        if metadata:
            payload["labels"] = metadata

        try:
            response = await self._client.post("/servers", json=payload)
            
            if response.status_code == 401:
                raise AuthenticationError("Invalid Hetzner API key")
            elif response.status_code == 422:
                error_data = response.json()
                raise ValidationError(f"Invalid request: {error_data.get('error', {})}")
            elif response.status_code >= 400:
                raise ProviderError(f"Failed to create server: {response.status_code}")

            data = response.json()
            server = data.get("server", {})
            
            return self._parse_server(server)

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def get_vps(self, vps_id: str) -> VPSInfo:
        """Get server information from Hetzner Cloud.

        Args:
            vps_id: Hetzner server ID.

        Returns:
            VPSInfo with server details.

        Raises:
            NotFoundError: If server does not exist.
            ProviderError: If retrieval fails.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        try:
            response = await self._client.get(f"/servers/{vps_id}")

            if response.status_code == 404:
                raise NotFoundError(f"Server {vps_id} not found")
            elif response.status_code == 401:
                raise AuthenticationError("Invalid Hetzner API key")
            elif response.status_code >= 400:
                raise ProviderError(f"Failed to get server: {response.status_code}")

            data = response.json()
            return self._parse_server(data.get("server", {}))

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def delete_vps(self, vps_id: str) -> bool:
        """Delete a server from Hetzner Cloud.

        Args:
            vps_id: Hetzner server ID.

        Returns:
            True if deletion was successful.

        Raises:
            NotFoundError: If server does not exist.
            ProviderError: If deletion fails.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        try:
            response = await self._client.delete(f"/servers/{vps_id}")

            if response.status_code == 404:
                raise NotFoundError(f"Server {vps_id} not found")
            elif response.status_code == 401:
                raise AuthenticationError("Invalid Hetzner API key")
            elif response.status_code >= 400:
                raise ProviderError(f"Failed to delete server: {response.status_code}")

            return True

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def list_vps(self, tags: dict[str, str] | None = None) -> list[VPSInfo]:
        """List servers from Hetzner Cloud.

        Args:
            tags: Filter by labels.

        Returns:
            List of VPSInfo for matching servers.
        """
        if not self._client:
            raise ProviderError("Provider not initialized")

        params: dict[str, Any] = {}
        if tags:
            label_filters = [f"{k}={v}" for k, v in tags.items()]
            params["label_selector"] = ",".join(label_filters)

        try:
            response = await self._client.get("/servers", params=params)

            if response.status_code >= 400:
                raise ProviderError(f"Failed to list servers: {response.status_code}")

            data = response.json()
            servers = data.get("servers", [])
            return [self._parse_server(s) for s in servers]

        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {str(e)}")

    async def wait_for_active(
        self, vps_id: str, timeout_seconds: int = 300, poll_interval_seconds: int = 5
    ) -> VPSInfo:
        """Wait for server to become active.

        Args:
            vps_id: Hetzner server ID.
            timeout_seconds: Maximum time to wait.
            poll_interval_seconds: Time between status checks.

        Returns:
            VPSInfo with updated status.

        Raises:
            TimeoutError: If server doesn't become active within timeout.
            ProviderError: If status check fails.
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Server {vps_id} did not become active within {timeout_seconds}s")

            try:
                vps = await self.get_vps(vps_id)
                if vps.is_active():
                    return vps
            except NotFoundError:
                pass  # Server might still be provisioning

            await asyncio.sleep(poll_interval_seconds)

    def _parse_server(self, server_data: dict[str, Any]) -> VPSInfo:
        """Parse Hetzner server response into VPSInfo.

        Args:
            server_data: Raw server data from API.

        Returns:
            VPSInfo with parsed server information.
        """
        # Extract IPv4 address
        ipv4 = None
        ipv6 = None
        
        public_net = server_data.get("public_net", {})
        if public_net:
            ipv4_info = public_net.get("ipv4", {})
            if isinstance(ipv4_info, dict):
                ipv4 = ipv4_info.get("ip")
            
            ipv6_info = public_net.get("ipv6", {})
            if isinstance(ipv6_info, dict):
                ipv6 = ipv6_info.get("ip")

        # Extract datacenter/region
        datacenter = None
        region = None
        country = None
        
        dc_data = server_data.get("datacenter", {})
        if dc_data:
            datacenter = dc_data.get("name")
            location = dc_data.get("location", {})
            if location:
                region = location.get("name")
                country = location.get("country")

        # Parse timestamps
        created_at = None
        if server_data.get("created"):
            try:
                created_at = datetime.fromisoformat(server_data["created"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return VPSInfo(
            id=str(server_data.get("id", "")),
            provider="hetzner",
            name=server_data.get("name"),
            status=server_data.get("status", "unknown"),
            ipv4=ipv4,
            ipv6=ipv6,
            hostname=server_data.get("name"),
            region=region,
            datacenter=datacenter,
            country=country,
            plan=server_data.get("server_type"),
            created_at=created_at,
            raw_data=server_data,
        )


def create_hetzner_provider(config: ProviderConfig) -> HetznerProvider:
    """Factory function to create Hetzner provider.

    Args:
        config: Provider configuration.

    Returns:
        Configured HetznerProvider instance.
    """
    return HetznerProvider(config)
