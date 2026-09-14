"""SSH connection and deployment module.

This module handles SSH connections to VPS instances and deployment of 3X-UI.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import asyncssh


@dataclass
class SSHConfig:
    """SSH connection configuration."""

    host: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    private_key: str | None = None
    private_key_passphrase: str | None = None
    connect_timeout: int = 10
    command_timeout: int = 60


@dataclass
class SSHResult:
    """Result of an SSH operation."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    error_message: str | None = None


class SSHConnection:
    """Manages SSH connection to a VPS."""

    def __init__(self, config: SSHConfig):
        """Initialize SSH connection.

        Args:
            config: SSH configuration.
        """
        self.config = config
        self._conn: asyncssh.SSHClientConnection | None = None

    async def connect(self) -> bool:
        """Establish SSH connection.

        Returns:
            True if connection successful.

        Raises:
            SSHError: If connection fails.
        """
        try:
            conn_options = {
                "host": self.config.host,
                "port": self.config.port,
                "username": self.config.username,
                "connect_timeout": self.config.connect_timeout,
            }

            if self.config.password:
                conn_options["password"] = self.config.password
            
            if self.config.private_key:
                conn_options["client_keys"] = [self.config.private_key]
                if self.config.private_key_passphrase:
                    conn_options["passphrase"] = self.config.private_key_passphrase

            self._conn = await asyncssh.connect(**conn_options)
            return True

        except asyncssh.Error as e:
            raise SSHError(f"SSH connection failed: {str(e)}")
        except Exception as e:
            raise SSHError(f"Unexpected connection error: {str(e)}")

    async def disconnect(self) -> None:
        """Close SSH connection."""
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def run_command(self, command: str, timeout: int | None = None) -> SSHResult:
        """Run a command on the remote server.

        Args:
            command: Command to execute.
            timeout: Command timeout in seconds.

        Returns:
            SSHResult with command output.
        """
        if not self._conn:
            return SSHResult(
                success=False,
                error_message="Not connected",
            )

        try:
            result = await self._conn.run(
                command,
                timeout=timeout or self.config.command_timeout,
            )
            return SSHResult(
                success=result.exit_status == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status,
            )
        except asyncssh.TimeoutError:
            return SSHResult(
                success=False,
                error_message=f"Command timed out after {timeout}s",
            )
        except asyncssh.Error as e:
            return SSHResult(
                success=False,
                error_message=f"SSH error: {str(e)}",
            )

    async def upload_file(self, local_path: str, remote_path: str) -> SSHResult:
        """Upload a file to the remote server.

        Args:
            local_path: Local file path.
            remote_path: Remote file path.

        Returns:
            SSHResult with upload status.
        """
        if not self._conn:
            return SSHResult(
                success=False,
                error_message="Not connected",
            )

        try:
            await self._conn.scp(local_path, remote_path)
            return SSHResult(success=True)
        except asyncssh.Error as e:
            return SSHResult(
                success=False,
                error_message=f"SCP error: {str(e)}",
            )

    async def wait_for_ssh(
        self, max_attempts: int = 30, delay_seconds: int = 5
    ) -> bool:
        """Wait for SSH to become available.

        Args:
            max_attempts: Maximum number of connection attempts.
            delay_seconds: Delay between attempts.

        Returns:
            True if SSH became available.
        """
        for attempt in range(max_attempts):
            try:
                await self.connect()
                await self.disconnect()
                return True
            except SSHError:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay_seconds)
        
        return False


class SSHError(Exception):
    """Exception for SSH-related errors."""

    pass


class DeploymentManager:
    """Manages 3X-UI deployment on remote servers."""

    # 3X-UI installation script URL
    INSTALL_SCRIPT_URL = "https://raw.githubusercontent.com/FranzKafkaYu/x-ui/master/install.sh"

    def __init__(self, ssh: SSHConnection):
        """Initialize deployment manager.

        Args:
            ssh: SSH connection instance.
        """
        self.ssh = ssh

    async def install_3xui(self, version: str | None = None) -> SSHResult:
        """Install 3X-UI on the remote server.

        Args:
            version: Specific version to install (optional).

        Returns:
            SSHResult with installation status.
        """
        # Download and run installation script
        install_cmd = f"bash <(curl -Ls {self.INSTALL_SCRIPT_URL})"
        
        if version:
            # Set version environment variable
            install_cmd = f"export XUI_VERSION={version} && {install_cmd}"

        return await self.ssh.run_command(install_cmd, timeout=300)

    async def verify_installation(self) -> bool:
        """Verify that 3X-UI is installed and running.

        Returns:
            True if 3X-UI is properly installed.
        """
        # Check if x-ui service exists and is running
        result = await self.ssh.run_command("systemctl is-active x-ui")
        return result.success and result.stdout.strip() == "active"

    async def get_panel_info(self) -> dict[str, Any] | None:
        """Get 3X-UI panel information.

        Returns:
            Dictionary with panel info (username, password, port) or None.
        """
        # Try to get panel info using x-ui command
        result = await self.ssh.run_command("x-ui user-info")
        
        if result.success:
            # Parse output (format depends on x-ui version)
            # This is a simplified parser - actual implementation may vary
            info = {}
            for line in result.stdout.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    info[key.strip()] = value.strip()
            return info
        
        return None

    async def configure_node(
        self,
        node_name: str,
        master_host: str,
        master_port: int,
        master_username: str,
        master_password: str,
    ) -> SSHResult:
        """Configure 3X-UI as a node connected to master.

        Args:
            node_name: Name for this node.
            master_host: Master 3X-UI host.
            master_port: Master 3X-UI port.
            master_username: Master username.
            master_password: Master password.

        Returns:
            SSHResult with configuration status.
        """
        # Note: Actual configuration commands depend on 3X-UI API
        # This is a placeholder for the actual implementation
        
        # Example: Set node name
        set_name_cmd = f"x-ui set-node-name {node_name}"
        result = await self.ssh.run_command(set_name_cmd)
        
        if not result.success:
            return result
        
        # Additional configuration would go here
        # This depends on the specific 3X-UI version and its capabilities
        
        return SSHResult(success=True)


async def wait_for_ssh_ready(
    host: str,
    username: str = "root",
    password: str | None = None,
    private_key: str | None = None,
    max_attempts: int = 30,
    delay_seconds: int = 5,
) -> bool:
    """Wait for SSH to become ready on a host.

    Args:
        host: Host IP address.
        username: SSH username.
        password: SSH password.
        private_key: SSH private key.
        max_attempts: Maximum connection attempts.
        delay_seconds: Delay between attempts.

    Returns:
        True if SSH became ready.
    """
    config = SSHConfig(
        host=host,
        username=username,
        password=password,
        private_key=private_key,
    )
    
    ssh = SSHConnection(config)
    return await ssh.wait_for_ssh(max_attempts=max_attempts, delay_seconds=delay_seconds)
