"""VPS information model."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class VPSInfo:
    """Represents information about a VPS instance.

    This is a provider-agnostic model that holds common VPS information
    regardless of the underlying provider (Hetzner, Linode, etc.).
    """

    id: str
    provider: str
    name: str | None = None
    status: str = "unknown"  # active, inactive, building, etc.

    # Network information
    ipv4: str | None = None
    ipv6: str | None = None
    hostname: str | None = None

    # Location
    region: str | None = None
    datacenter: str | None = None
    country: str | None = None

    # Hardware
    plan: str | None = None
    cpu_cores: int | None = None
    memory_mb: int | None = None
    disk_gb: int | None = None

    # Timing
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Provider-specific metadata
    raw_data: dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Check if VPS is active and running."""
        return self.status.lower() in ("active", "running", "online")

    def has_ip(self) -> bool:
        """Check if VPS has an IP address assigned."""
        return self.ipv4 is not None and len(self.ipv4.strip()) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name,
            "status": self.status,
            "ipv4": self.ipv4,
            "ipv6": self.ipv6,
            "hostname": self.hostname,
            "region": self.region,
            "datacenter": self.datacenter,
            "country": self.country,
            "plan": self.plan,
            "cpu_cores": self.cpu_cores,
            "memory_mb": self.memory_mb,
            "disk_gb": self.disk_gb,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "raw_data": self.raw_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VPSInfo":
        """Create from dictionary representation."""
        created_at = None
        if data.get("created_at"):
            try:
                created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass

        updated_at = None
        if data.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(data["updated_at"])
            except (ValueError, TypeError):
                pass

        return cls(
            id=data["id"],
            provider=data["provider"],
            name=data.get("name"),
            status=data.get("status", "unknown"),
            ipv4=data.get("ipv4"),
            ipv6=data.get("ipv6"),
            hostname=data.get("hostname"),
            region=data.get("region"),
            datacenter=data.get("datacenter"),
            country=data.get("country"),
            plan=data.get("plan"),
            cpu_cores=data.get("cpu_cores"),
            memory_mb=data.get("memory_mb"),
            disk_gb=data.get("disk_gb"),
            created_at=created_at,
            updated_at=updated_at,
            raw_data=data.get("raw_data", {}),
        )
