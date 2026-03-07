"""Tests for Pylon secret management."""

import time

from pylon.secrets.audit import AccessAction, AccessLogEntry, SecretAudit
from pylon.secrets.manager import SecretManager
from pylon.secrets.rotation import RotationPolicy, SecretRotation
from pylon.secrets.vault import InMemoryVaultProvider, VaultConfig, build_path

# ---------------------------------------------------------------------------
# SecretManager
# ---------------------------------------------------------------------------

class TestSecretManager:
    def test_store_and_get(self):
        mgr = SecretManager()
        mgr.store("db/password", "s3cret")
        secret = mgr.get("db/password")
        assert secret is not None
        assert secret.value == "s3cret"
        assert secret.version == 1

    def test_get_nonexistent(self):
        mgr = SecretManager()
        assert mgr.get("nope") is None

    def test_versioning(self):
        mgr = SecretManager()
        mgr.store("key", "v1")
        mgr.store("key", "v2")
        mgr.store("key", "v3")
        latest = mgr.get("key")
        assert latest is not None
        assert latest.value == "v3"
        assert latest.version == 3
        assert mgr.version_count("key") == 3

    def test_get_specific_version(self):
        mgr = SecretManager()
        mgr.store("key", "first")
        mgr.store("key", "second")
        v1 = mgr.get_version("key", 1)
        assert v1 is not None
        assert v1.value == "first"
        v2 = mgr.get_version("key", 2)
        assert v2 is not None
        assert v2.value == "second"

    def test_get_version_out_of_range(self):
        mgr = SecretManager()
        mgr.store("key", "val")
        assert mgr.get_version("key", 0) is None
        assert mgr.get_version("key", 2) is None

    def test_get_version_nonexistent_key(self):
        mgr = SecretManager()
        assert mgr.get_version("nope", 1) is None

    def test_delete(self):
        mgr = SecretManager()
        mgr.store("key", "val")
        assert mgr.delete("key") is True
        assert mgr.get("key") is None

    def test_delete_nonexistent(self):
        mgr = SecretManager()
        assert mgr.delete("nope") is False

    def test_list_all(self):
        mgr = SecretManager()
        mgr.store("db/password", "pw")
        mgr.store("api/key", "ak")
        result = mgr.list()
        assert len(result) == 2
        keys = {m.key for m in result}
        assert keys == {"db/password", "api/key"}

    def test_list_with_prefix(self):
        mgr = SecretManager()
        mgr.store("db/password", "pw")
        mgr.store("db/host", "localhost")
        mgr.store("api/key", "ak")
        result = mgr.list("db/")
        assert len(result) == 2
        assert all(m.key.startswith("db/") for m in result)

    def test_metadata_preserved(self):
        mgr = SecretManager()
        mgr.store("key", "val", metadata={"env": "prod"})
        secret = mgr.get("key")
        assert secret is not None
        assert secret.metadata == {"env": "prod"}

    def test_expires_at(self):
        mgr = SecretManager()
        future = time.time() + 3600
        mgr.store("key", "val", expires_at=future)
        secret = mgr.get("key")
        assert secret is not None
        assert secret.expires_at == future

    def test_encryption_roundtrip(self):
        mgr = SecretManager()
        mgr.store("key", "hello world")
        secret = mgr.get("key")
        assert secret is not None
        assert secret.value == "hello world"

    def test_stored_value_is_encrypted(self):
        """Verify that the stored bytes are not plaintext or simple base64."""
        mgr = SecretManager()
        mgr.store("key", "sensitive-data")
        stored = mgr._store["key"][-1]
        # The encrypted_value should be bytes, not a simple encoding of the plaintext
        assert isinstance(stored.encrypted_value, bytes)
        assert b"sensitive-data" not in stored.encrypted_value

    def test_different_keys_produce_different_ciphertext(self):
        mgr1 = SecretManager(encryption_key=b"key-one-" * 4)
        mgr2 = SecretManager(encryption_key=b"key-two-" * 4)
        mgr1.store("k", "same-value")
        mgr2.store("k", "same-value")
        # Different master keys should produce different encrypted values
        assert mgr1._store["k"][-1].encrypted_value != mgr2._store["k"][-1].encrypted_value


# ---------------------------------------------------------------------------
# VaultProvider
# ---------------------------------------------------------------------------

class TestVaultProvider:
    def test_put_and_get(self):
        vault = InMemoryVaultProvider()
        vault.put("secret/default/db", {"password": "abc"})
        data = vault.get("secret/default/db")
        assert data == {"password": "abc"}

    def test_get_nonexistent(self):
        vault = InMemoryVaultProvider()
        assert vault.get("nope") is None

    def test_delete(self):
        vault = InMemoryVaultProvider()
        vault.put("key", {"v": "1"})
        assert vault.delete("key") is True
        assert vault.get("key") is None

    def test_delete_nonexistent(self):
        vault = InMemoryVaultProvider()
        assert vault.delete("nope") is False

    def test_list_with_prefix(self):
        vault = InMemoryVaultProvider()
        vault.put("secret/t1/a", {"v": "1"})
        vault.put("secret/t1/b", {"v": "2"})
        vault.put("secret/t2/c", {"v": "3"})
        result = vault.list("secret/t1")
        assert len(result) == 2

    def test_build_path(self):
        assert build_path("secret", "tenant-1", "db-pass") == "secret/tenant-1/db-pass"

    def test_build_path_empty_parts(self):
        assert build_path("secret", "", "key") == "secret/key"

    def test_config_defaults(self):
        cfg = VaultConfig()
        assert cfg.address == "http://127.0.0.1:8200"
        assert cfg.mount_path == "secret"

    def test_config_custom(self):
        cfg = VaultConfig(address="https://vault.prod:8200", token="root", namespace="ns1")
        assert cfg.namespace == "ns1"
        assert cfg.token == "root"


# ---------------------------------------------------------------------------
# SecretRotation
# ---------------------------------------------------------------------------

class TestSecretRotation:
    def test_schedule_and_get_policy(self):
        mgr = SecretManager()
        rot = SecretRotation(mgr)
        policy = RotationPolicy(interval_seconds=3600)
        rot.schedule_rotation("key", policy)
        assert rot.get_policy("key") is policy

    def test_cancel_rotation(self):
        mgr = SecretManager()
        rot = SecretRotation(mgr)
        rot.schedule_rotation("key", RotationPolicy())
        assert rot.cancel_rotation("key") is True
        assert rot.get_policy("key") is None

    def test_cancel_nonexistent(self):
        mgr = SecretManager()
        rot = SecretRotation(mgr)
        assert rot.cancel_rotation("nope") is False

    def test_rotate_creates_new_version(self):
        mgr = SecretManager()
        mgr.store("key", "old-value")
        rot = SecretRotation(mgr)
        rot.schedule_rotation("key", RotationPolicy())
        event = rot.rotate("key", "new-value")
        assert event is not None
        assert event.old_version == 1
        assert event.new_version == 2
        assert mgr.get("key").value == "new-value"

    def test_rotate_nonexistent_returns_none(self):
        mgr = SecretManager()
        rot = SecretRotation(mgr)
        assert rot.rotate("nope", "val") is None

    def test_get_events(self):
        mgr = SecretManager()
        mgr.store("a", "v1")
        mgr.store("b", "v1")
        rot = SecretRotation(mgr)
        rot.rotate("a", "v2")
        rot.rotate("b", "v2")
        assert len(rot.get_events()) == 2
        assert len(rot.get_events("a")) == 1

    def test_check_expiring_with_old_secret(self):
        mgr = SecretManager()
        mgr.store("key", "val")
        # Artificially age the secret
        versions = mgr._store["key"]
        versions[-1] = versions[-1].__class__(
            encrypted_value=versions[-1].encrypted_value,
            version=versions[-1].version,
            created_at=time.time() - 700_000,  # ~8 days old
            metadata={},
        )
        rot = SecretRotation(mgr)
        policy = RotationPolicy(max_age_seconds=604800)  # 7 days
        rot.schedule_rotation("key", policy)
        expiring = rot.check_expiring(threshold_seconds=3600)
        assert len(expiring) == 1
        assert expiring[0].key == "key"

    def test_check_expiring_fresh_secret(self):
        mgr = SecretManager()
        mgr.store("key", "val")
        rot = SecretRotation(mgr)
        rot.schedule_rotation("key", RotationPolicy(max_age_seconds=604800))
        expiring = rot.check_expiring(threshold_seconds=3600)
        assert len(expiring) == 0


# ---------------------------------------------------------------------------
# SecretAudit
# ---------------------------------------------------------------------------

class TestSecretAudit:
    def test_log_access(self):
        audit = SecretAudit()
        entry = audit.log_access("db/pass", "user1", AccessAction.READ)
        assert entry.key == "db/pass"
        assert entry.actor == "user1"
        assert entry.action == AccessAction.READ
        assert audit.count() == 1

    def test_query_by_key(self):
        audit = SecretAudit()
        audit.log_access("a", "u", AccessAction.READ)
        audit.log_access("b", "u", AccessAction.READ)
        result = audit.query(key="a")
        assert len(result) == 1

    def test_query_by_actor(self):
        audit = SecretAudit()
        audit.log_access("k", "alice", AccessAction.READ)
        audit.log_access("k", "bob", AccessAction.WRITE)
        result = audit.query(actor="alice")
        assert len(result) == 1

    def test_query_by_action(self):
        audit = SecretAudit()
        audit.log_access("k", "u", AccessAction.READ)
        audit.log_access("k", "u", AccessAction.WRITE)
        audit.log_access("k", "u", AccessAction.DELETE)
        result = audit.query(action=AccessAction.WRITE)
        assert len(result) == 1

    def test_query_by_time_range(self):
        audit = SecretAudit()
        now = time.time()
        audit.log_access("k", "u", AccessAction.READ)
        # Manually adjust timestamps for testing
        audit._entries[0] = AccessLogEntry(
            key="k", actor="u", action=AccessAction.READ, timestamp=now - 100
        )
        audit.log_access("k", "u", AccessAction.WRITE)
        result = audit.query(from_time=now - 50)
        assert len(result) == 1
        assert result[0].action == AccessAction.WRITE

    def test_query_no_filters(self):
        audit = SecretAudit()
        audit.log_access("a", "u", AccessAction.READ)
        audit.log_access("b", "u", AccessAction.WRITE)
        assert len(audit.query()) == 2

    def test_log_with_details(self):
        audit = SecretAudit()
        entry = audit.log_access("k", "u", AccessAction.ROTATE, details="scheduled")
        assert entry.details == "scheduled"

    def test_access_action_values(self):
        assert AccessAction.READ.value == "read"
        assert AccessAction.ROTATE.value == "rotate"
        assert AccessAction.LIST.value == "list"
