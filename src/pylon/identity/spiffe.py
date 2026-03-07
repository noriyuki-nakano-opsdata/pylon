"""SPIFFE/SPIRE workload identity types and manager.

In-memory simulation of SPIRE registration and SVID issuance.
Production implementation would communicate with the SPIRE Agent API.
"""

from __future__ import annotations

import enum
import hmac
import time
import uuid
from dataclasses import dataclass, field


class SVIDType(enum.Enum):
    """SVID credential type."""

    X509 = "x509"
    JWT = "jwt"


@dataclass
class SpiffeId:
    """SPIFFE identity URI."""

    trust_domain: str
    path: str

    @property
    def uri(self) -> str:
        return f"spiffe://{self.trust_domain}{self.path}"

    @classmethod
    def from_uri(cls, uri: str) -> SpiffeId:
        """Parse a spiffe:// URI into a SpiffeId."""
        if not uri.startswith("spiffe://"):
            raise ValueError(f"Invalid SPIFFE URI: {uri}")
        rest = uri[len("spiffe://"):]
        slash_idx = rest.find("/")
        if slash_idx == -1:
            return cls(trust_domain=rest, path="/")
        return cls(trust_domain=rest[:slash_idx], path=rest[slash_idx:])

    @classmethod
    def for_tenant(cls, cluster: str, tenant_id: str) -> SpiffeId:
        return cls(trust_domain=f"pylon.{cluster}", path=f"/tenant/{tenant_id}")

    @classmethod
    def for_agent(cls, cluster: str, tenant_id: str, agent_id: str) -> SpiffeId:
        return cls(
            trust_domain=f"pylon.{cluster}",
            path=f"/tenant/{tenant_id}/agent/{agent_id}",
        )


@dataclass
class SVID:
    """SPIFFE Verifiable Identity Document."""

    spiffe_id: SpiffeId
    svid_type: SVIDType
    issued_at: float
    expires_at: float
    ttl_seconds: int = 3600

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class SpireRegistrationEntry:
    """SPIRE workload registration entry."""

    entry_id: str
    spiffe_id: SpiffeId
    parent_id: SpiffeId
    selectors: list[dict[str, str]] = field(default_factory=list)
    ttl: int = 3600


class WorkloadIdentityManager:
    """Manages SPIFFE/SPIRE workload identities.

    In-memory simulation. Production implementation would use
    the SPIRE Server Registration API.
    """

    def __init__(self, trust_domain: str = "pylon.cluster1") -> None:
        self._trust_domain = trust_domain
        self._entries: dict[str, SpireRegistrationEntry] = {}
        self._svids: dict[str, SVID] = {}

    def create_registration(
        self,
        tenant_id: str,
        agent_id: str,
        selectors: list[dict[str, str]] | None = None,
    ) -> SpireRegistrationEntry:
        """Create a SPIRE registration entry for an agent workload."""
        entry_id = f"entry-{uuid.uuid4().hex[:8]}"
        spiffe_id = SpiffeId.for_agent(self._trust_domain, tenant_id, agent_id)
        parent_id = SpiffeId.for_tenant(self._trust_domain, tenant_id)

        entry = SpireRegistrationEntry(
            entry_id=entry_id,
            spiffe_id=spiffe_id,
            parent_id=parent_id,
            selectors=selectors or [{"type": "k8s_psat", "value": f"ns:{tenant_id}"}],
        )
        self._entries[entry_id] = entry
        return entry

    def get_svid(self, spiffe_id: SpiffeId, svid_type: SVIDType = SVIDType.X509) -> SVID:
        """Issue or retrieve an SVID for a SPIFFE ID."""
        uri = spiffe_id.uri
        if uri in self._svids and not self._svids[uri].is_expired:
            return self._svids[uri]

        now = time.time()
        svid = SVID(
            spiffe_id=spiffe_id,
            svid_type=svid_type,
            issued_at=now,
            expires_at=now + 3600,
            ttl_seconds=3600,
        )
        self._svids[uri] = svid
        return svid

    def validate_svid(self, svid: SVID) -> bool:
        """Validate an SVID is current and known."""
        if svid.is_expired:
            return False
        stored = self._svids.get(svid.spiffe_id.uri)
        if stored is None:
            return False
        return hmac.compare_digest(
            str(stored.issued_at).encode(),
            str(svid.issued_at).encode(),
        )

    def rotate_svid(self, svid: SVID) -> SVID:
        """Rotate an SVID — issue a new one with the same SPIFFE ID."""
        now = time.time()
        new_svid = SVID(
            spiffe_id=svid.spiffe_id,
            svid_type=svid.svid_type,
            issued_at=now,
            expires_at=now + svid.ttl_seconds,
            ttl_seconds=svid.ttl_seconds,
        )
        self._svids[svid.spiffe_id.uri] = new_svid
        return new_svid

    def list_entries(self, tenant_id: str) -> list[SpireRegistrationEntry]:
        """List all registration entries for a tenant."""
        prefix = f"/tenant/{tenant_id}"
        return [
            e for e in self._entries.values()
            if e.spiffe_id.path.startswith(prefix)
        ]

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a registration entry. Returns True if it existed."""
        return self._entries.pop(entry_id, None) is not None
