"""Master 3X-UI integration layer.

This module handles communication with the Master 3X-UI instance
to manage nodes, update backend information, and verify synchronization.

API Reference: https://github.com/MHSanaei/3x-ui
"""

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class MasterConfig:
    """Configuration for Master 3X-UI connection."""

    base_url: str
    username: str
    password: str
    api_path: str = "/api/"
    timeout_seconds: float = 30.0


@dataclass
class MasterNode:
    """Represents a node in Master 3X-UI."""

    id: int
    name: str
    ip: str
    port: int
    status: str
    enabled: bool
    remarks: str | None = None
    last_seen: str | None = None
    raw_data: dict[str, Any] | None = None


@dataclass
class MasterAuthResponse:
    """Response from authentication."""

    success: bool
    token: str | None = None
    message: str | None = None


@dataclass
class MasterApiResponse:
    """Generic API response from Master."""

    success: bool
    data: Any | None = None
    message: str | None = None


class MasterError(Exception):
    """Base exception for Master errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class MasterAuthenticationError(MasterError):
    """Exception raised when authentication fails."""

    pass


class MasterNotFoundError(MasterError):
    """Exception raised when node is not found."""

    pass


class MasterConnectionError(MasterError):
    """Exception raised when connection to Master fails."""

    pass


class Master3XUI:
    """Client for interacting with Master 3X-UI instance.

    This class provides methods to:
    - Authenticate with Master
    - List nodes
    - Get node details
    - Update node backend information
    - Verify node status
    - Health check
    """

    def __init__(self, config: MasterConfig):
        """Initialize Master client.

        Args:
            config: Master configuration including credentials.
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._authenticated = False

    async def initialize(self) -> None:
        """Initialize HTTP client and authenticate."""
        if not self.config.base_url:
            raise MasterError("Master base URL is required")

        if not self.config.username or not self.config.password:
            raise MasterAuthenticationError("Username and password are required")

        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.timeout_seconds),
            headers={"Content-Type": "application/json"},
        )

        await self._authenticate()

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._token = None
        self._authenticated = False

    async def _authenticate(self) -> None:
        """Authenticate with Master 3X-UI.

        Note: 3X-UI uses form-based authentication with session cookies.
        The exact API endpoint may vary based on version.
        """
        if not self._client:
            raise MasterConnectionError("Client not initialized")

        try:
            # 3X-UI typically uses /login endpoint with form data
            response = await self._client.post(
                "/login",
                data={
                    "username": self.config.username,
                    "password": self.config.password,
                },
                follow_redirects=True,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self._authenticated = True
                    # Store session cookie for subsequent requests
                    return
                else:
                    raise MasterAuthenticationError(
                        f"Authentication failed: {data.get('msg', 'Unknown error')}"
                    )
            else:
                raise MasterAuthenticationError(
                    f"Authentication failed with status {response.status_code}"
                )

        except httpx.HTTPStatusError as e:
            raise MasterAuthenticationError(f"HTTP error during authentication: {e}")
        except httpx.RequestError as e:
            raise MasterConnectionError(f"Connection error during authentication: {e}")

    async def _ensure_authenticated(self) -> None:
        """Ensure client is authenticated, re-authenticate if needed."""
        if not self._authenticated:
            await self._authenticate()

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> MasterApiResponse:
        """Make authenticated request to Master.

        Args:
            method: HTTP method.
            endpoint: API endpoint.
            json: Request body.
            params: Query parameters.

        Returns:
            Parsed API response.

        Raises:
            MasterError: If request fails.
        """
        if not self._client:
            raise MasterConnectionError("Client not initialized")

        await self._ensure_authenticated()

        try:
            response = await self._client.request(
                method=method,
                url=endpoint,
                json=json,
                params=params,
            )

            if response.status_code == 200:
                data = response.json()
                return MasterApiResponse(
                    success=data.get("success", False),
                    data=data.get("obj"),
                    message=data.get("msg"),
                )
            else:
                return MasterApiResponse(
                    success=False,
                    message=f"HTTP {response.status_code}: {response.text}",
                )

        except httpx.RequestError as e:
            raise MasterConnectionError(f"Request failed: {e}")

    async def health_check(self) -> bool:
        """Check if Master is accessible.

        Returns:
            True if Master is reachable and responsive.
        """
        if not self._client:
            return False

        try:
            response = await self._client.get("/")
            return response.status_code in (200, 302)
        except Exception:
            return False

    async def list_nodes(self) -> list[MasterNode]:
        """List all nodes in Master 3X-UI.

        Returns:
            List of MasterNode objects.

        Note:
            The actual API endpoint depends on 3X-UI version.
            This implements a generic approach that may need adjustment.
        """
        response = await self._request("GET", "/panel/api/inbounds")

        if not response.success:
            raise MasterError(f"Failed to list nodes: {response.message}")

        nodes = []
        if response.data:
            # Parse based on 3X-UI API structure
            for item in response.data:
                node = MasterNode(
                    id=item.get("id", 0),
                    name=item.get("remark", f"Node-{item.get('id')}"),
                    ip=item.get("listen", "0.0.0.0"),
                    port=item.get("port", 443),
                    status="active" if item.get("enable", True) else "disabled",
                    enabled=item.get("enable", True),
                    remarks=item.get("remark"),
                    raw_data=item,
                )
                nodes.append(node)

        return nodes

    async def get_node(self, node_id: int) -> MasterNode | None:
        """Get details of a specific node.

        Args:
            node_id: Node identifier.

        Returns:
            MasterNode if found, None otherwise.
        """
        nodes = await self.list_nodes()
        for node in nodes:
            if node.id == node_id:
                return node
        return None

    async def find_node_by_remark(self, remark: str) -> MasterNode | None:
        """Find node by remark/name.

        Args:
            remark: Node remark/name to search for.

        Returns:
            MasterNode if found, None otherwise.
        """
        nodes = await self.list_nodes()
        for node in nodes:
            if node.remarks == remark or node.name == remark:
                return node
        return None

    async def update_node(
        self,
        node_id: int,
        ip: str | None = None,
        port: int | None = None,
        enabled: bool | None = None,
        remark: str | None = None,
    ) -> bool:
        """Update node information in Master.

        Args:
            node_id: Node identifier.
            ip: New IP address.
            port: New port.
            enabled: Enable/disable node.
            remark: New remark.

        Returns:
            True if update was successful.

        Raises:
            MasterNotFoundError: If node doesn't exist.
            MasterError: If update fails.
        """
        current_node = await self.get_node(node_id)
        if not current_node:
            raise MasterNotFoundError(f"Node {node_id} not found")

        update_data = {
            "id": node_id,
        }

        if ip is not None:
            update_data["listen"] = ip
        if port is not None:
            update_data["port"] = port
        if enabled is not None:
            update_data["enable"] = enabled
        if remark is not None:
            update_data["remark"] = remark

        response = await self._request(
            "PUT", f"/panel/api/inbounds/{node_id}/update", json=update_data
        )

        if not response.success:
            raise MasterError(f"Failed to update node: {response.message}")

        return True

    async def update_node_backend(
        self,
        node_id: int,
        new_ip: str,
        new_port: int | None = None,
    ) -> bool:
        """Update node backend information when replacing VPS.

        This is the key method for node replacement - it updates the
        existing logical node with new VPS information without creating
        a duplicate.

        Args:
            node_id: Logical node ID in Master.
            new_ip: New VPS IP address.
            new_port: New port (optional, keeps existing if None).

        Returns:
            True if update was successful.

        Raises:
            MasterNotFoundError: If node doesn't exist.
            MasterError: If update fails.
        """
        return await self.update_node(
            node_id=node_id,
            ip=new_ip,
            port=new_port,
        )

    async def enable_node(self, node_id: int) -> bool:
        """Enable a node.

        Args:
            node_id: Node identifier.

        Returns:
            True if successful.
        """
        return await self.update_node(node_id=node_id, enabled=True)

    async def disable_node(self, node_id: int) -> bool:
        """Disable a node.

        Args:
            node_id: Node identifier.

        Returns:
            True if successful.
        """
        return await self.update_node(node_id=node_id, enabled=False)

    async def verify_node_status(self, node_id: int) -> bool:
        """Verify that a node is properly configured and active.

        Args:
            node_id: Node identifier.

        Returns:
            True if node is active and properly configured.
        """
        node = await self.get_node(node_id)
        if not node:
            return False

        return node.enabled and node.status == "active"

    async def test_node_connectivity(self, node_id: int) -> bool:
        """Test connectivity to a node from Master.

        Args:
            node_id: Node identifier.

        Returns:
            True if Master can connect to the node.
        """
        node = await self.get_node(node_id)
        if not node:
            return False

        # This would depend on 3X-UI's specific API for testing connectivity
        # For now, we check if the node is enabled and has valid IP
        return node.enabled and node.ip not in ("", "0.0.0.0")
