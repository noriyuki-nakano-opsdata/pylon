"""Root conftest — shared fixtures for all Pylon tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.memory import MemoryRepository
from pylon.repository.workflow import WorkflowRepository


@pytest.fixture
def checkpoint_repo() -> CheckpointRepository:
    return CheckpointRepository()


@pytest.fixture
def workflow_repo() -> WorkflowRepository:
    return WorkflowRepository()


@pytest.fixture
def audit_repo() -> AuditRepository:
    return AuditRepository()


@pytest.fixture
def memory_repo() -> MemoryRepository:
    return MemoryRepository()


@pytest.fixture
def mock_llm_handler() -> AsyncMock:
    """Mock LLM handler returning a simple response dict."""
    handler = AsyncMock()
    handler.side_effect = lambda node_id, state: {
        f"{node_id}_output": f"result_from_{node_id}"
    }
    return handler
