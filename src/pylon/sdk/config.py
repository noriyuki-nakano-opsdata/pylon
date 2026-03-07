from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SDKConfig:
    """Configuration for the Pylon SDK."""

    base_url: str = "http://localhost:8080"
    api_key: str | None = None
    timeout: int = 30
    max_retries: int = 3
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> SDKConfig:
        """Build config from PYLON_* environment variables.

        Recognized variables:
          PYLON_BASE_URL, PYLON_API_KEY, PYLON_TIMEOUT,
          PYLON_MAX_RETRIES, PYLON_LOG_LEVEL
        """
        kwargs: dict[str, Any] = {}

        if val := os.environ.get("PYLON_BASE_URL"):
            kwargs["base_url"] = val
        if val := os.environ.get("PYLON_API_KEY"):
            kwargs["api_key"] = val
        if val := os.environ.get("PYLON_TIMEOUT"):
            kwargs["timeout"] = int(val)
        if val := os.environ.get("PYLON_MAX_RETRIES"):
            kwargs["max_retries"] = int(val)
        if val := os.environ.get("PYLON_LOG_LEVEL"):
            kwargs["log_level"] = val

        return cls(**kwargs)

    @classmethod
    def from_file(cls, path: str | Path) -> SDKConfig:
        """Load config from a pylon.yaml file.

        The YAML file should contain top-level keys matching the field names
        of this dataclass (base_url, api_key, timeout, max_retries, log_level).
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        with file_path.open() as fh:
            data = yaml.safe_load(fh) or {}

        if not isinstance(data, dict):
            raise ValueError(f"Expected YAML mapping at top level, got {type(data).__name__}")

        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)
