"""Process helpers: every external command goes through here."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping, Sequence


class ProcessError(Exception):
    """A command could not be started, or did not finish.

    ``subprocess`` reports an unusable executable in platform-specific ways:
    ``[WinError 193] is not a valid Win32 application`` on Windows,
    ``PermissionError`` or ``Exec format error`` on POSIX. Callers only care
    that the interpreter is unusable, so the distinction stops here.
    """


def run(
    cmd: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with an argument list and captured text output."""
    argv = [str(part) for part in cmd]
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(f"{argv[0]} did not finish within {timeout}s") from exc
    except OSError as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
        raise ProcessError(f"cannot run {argv[0]}: {reason}") from exc


def tail(text: str, lines: int = 15) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return "\n".join(stripped.splitlines()[-lines:])
