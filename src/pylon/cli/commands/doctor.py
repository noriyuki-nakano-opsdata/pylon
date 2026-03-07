"""pylon doctor command."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click


def _check_python_version() -> tuple[str, bool]:
    v = sys.version_info
    ok = v >= (3, 12)
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    return (f"{label} ({'OK' if ok else 'FAIL: >= 3.12 required'})", ok)


def _check_pylon_yaml() -> tuple[str, bool]:
    path = Path.cwd() / "pylon.yaml"
    if not path.exists():
        return ("pylon.yaml: NOT FOUND", False)
    try:
        from pylon.dsl.parser import load_project
        load_project(".")
        return ("pylon.yaml: OK (valid)", True)
    except Exception as e:
        return (f"pylon.yaml: INVALID ({e})", False)


def _check_docker() -> tuple[str, bool]:
    docker = shutil.which("docker")
    if docker:
        return ("Docker: OK (found)", True)
    return ("Docker: NOT FOUND", False)


def _check_packages() -> tuple[str, bool]:
    missing = []
    for pkg in ("click", "yaml", "pydantic"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return (f"Packages: MISSING ({', '.join(missing)})", False)
    return ("Packages: OK", True)


@click.command()
@click.pass_context
def doctor(ctx: click.Context, **kwargs: object) -> None:
    """Check Pylon environment and configuration."""
    checks = [
        _check_python_version(),
        _check_pylon_yaml(),
        _check_docker(),
        _check_packages(),
    ]

    all_ok = True
    for message, ok in checks:
        symbol = "+" if ok else "x"
        click.echo(f"  [{symbol}] {message}")
        if not ok:
            all_ok = False

    if all_ok:
        click.echo("\nAll checks passed.")
    else:
        click.echo("\nSome checks failed. Fix the issues above.")
