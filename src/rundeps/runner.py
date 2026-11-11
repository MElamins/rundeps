"""Executing the target script."

The script is never imported into RunDeps' process: it runs in a child
interpreter, so its exit code, working directory and imports stay its own.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from .environment import child_env
from .models import RunResult
from .proc import run

# Only this exact shape counts as evidence of a missing dependency.
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '(?P<name>[^']+)'")
MISSING_ATTR = re.compile(r"ImportError: cannot import name '[^']+' from '(?P<name>[^']+)'")


def run_script(
    python: Path,
    script: Path,
    args: Sequence[str],
    *,
    venv: Path | None,
    timeout: float | None = None,
) -> RunResult:
    script = Path(script).resolve()
    proc = run(
        [python, script, *args],
        cwd=script.parent,
        env=child_env(venv),
        timeout=timeout,
    )
    return RunResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def missing_module(stderr: str) -> str | None:
    """Return the top-level module named by a ModuleNotFoundError, if any."""
    match = MISSING_MODULE.search(stderr)
    if not match:
        return None
    name = match.group("name").strip()
    if not name:
        return None
    return name.split(".", 1)[0]
