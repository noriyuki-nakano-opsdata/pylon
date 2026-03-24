"""Bundled app-side runner for experiment sandboxes."""

from __future__ import annotations

from pylon.sandbox.self_hosted_runtime import RuntimeCommandConfig
from pylon.sandbox.self_hosted_runtime import main as runtime_main


def main() -> None:
    runtime_main(
        RuntimeCommandConfig(
            mode_env_var="PYLON_FIRECRACKER_RUNNER_MODE",
            delegate_command_env_var="PYLON_FIRECRACKER_DELEGATE_COMMAND",
        )
    )


if __name__ == "__main__":
    main()
