"""Installing distributions into the selected interpreter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .environment import child_env
from .names import is_valid_package_name
from .output import console
from .proc import run, tail


class InstallError(Exception):
    """pip is unavailable or returned something unusable."""


@dataclass
class InstallResult:
    ok: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def changed_anything(self) -> bool:
        return bool(self.ok)


def _pip_cmd(python: Path, packages: Sequence[str]) -> list[str]:
    return [str(python), "-m", "pip", "install", "--disable-pip-version-check", *packages]


def install(python: Path, packages: Sequence[str], *, venv: Path | None, verbose: bool = False) -> InstallResult:
    """Install packages one at a time, so one bad name cannot sink the batch."""
    result = InstallResult()

    for package in packages:
        if not is_valid_package_name(package):
            result.failed[package] = "not a valid package name"
            continue

        if verbose:
            console.detail("pip install " + package)

        proc = run(_pip_cmd(python, [package]), env=child_env(venv), timeout=1800)
        if proc.returncode == 0:
            result.ok.append(package)
        else:
            result.failed[package] = tail(proc.stderr or proc.stdout) or f"pip exited with {proc.returncode}"

    return result


def require_pip(python: Path, *, venv: Path | None) -> str:
    """Confirm the target interpreter can run pip, and return its version."""
    proc = run([str(python), "-m", "pip", "--version"], env=child_env(venv), timeout=300)
    if proc.returncode != 0:
        raise InstallError(
            f"{python} has no working pip.\n"
            f"  {tail(proc.stderr or proc.stdout, 3)}"
        )
    parts = proc.stdout.split()
    return parts[1] if len(parts) > 1 else "unknown"
