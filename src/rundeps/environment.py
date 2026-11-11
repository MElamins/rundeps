"""Project layout, the isolated virtual environment and interpreter probing."""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import __version__
from .proc import run

DEFAULT_MAX_RETRIES = 3
PROJECT_DIR = ".rundeps"

_PROBE = r"""
import json, sys
from importlib import metadata, util

out = {}
for name, dist in json.loads(sys.argv[1]):
    spec = None
    try:
        spec = util.find_spec(name)
    except Exception:
        spec = None
    found = spec is not None
    version = None
    if found and dist:
        try:
            version = metadata.version(dist)
        except Exception:
            version = None
    out[name] = {"found": bool(found), "version": version}
print(json.dumps(out))
"""


class EnvProblem(Exception):
    """The environment could not be created or inspected."""


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


@dataclass(frozen=True)
class Project:
    root: Path

    @classmethod
    def locate(cls, start: Path) -> "Project":
        """Find the nearest project directory, walking up from a file or folder."""
        start = Path(start).expanduser()
        folder = start if start.is_dir() else start.parent
        for candidate in (folder, *folder.parents):
            if (candidate / PROJECT_DIR).is_dir():
                return cls(candidate)
        return cls(folder)

    @property
    def dir(self) -> Path:
        return self.root / PROJECT_DIR

    @property
    def config_path(self) -> Path:
        return self.dir / "config.toml"

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    @property
    def venv_dir(self) -> Path:
        return self.dir / "venv"

    @property
    def python(self) -> Path:
        return venv_python(self.venv_dir)

    @property
    def initialised(self) -> bool:
        return self.dir.is_dir()


def create_venv(venv_dir: Path) -> Path:
    """Create a virtual environment with the interpreter running RunDeps."""
    proc = run([sys.executable, "-m", "venv", venv_dir], timeout=900)
    python = venv_python(venv_dir)
    if proc.returncode != 0 or not python.exists():
        detail = (proc.stderr or proc.stdout).strip()
        raise EnvProblem(
            f"could not create a virtual environment in {venv_dir}"
            + (f"\n{detail}" if detail else "")
        )
    return python


def pip_version(python: Path) -> str | None:
    proc = run([python, "-m", "pip", "--version"], timeout=180)
    if proc.returncode != 0:
        return None
    parts = proc.stdout.split()
    return parts[1] if len(parts) > 1 else "unknown"


def probe(python: Path, entries: Sequence[tuple[str, str]]) -> dict[str, dict]:
    """Ask an interpreter which modules import and which versions they are.

    Runs in a subprocess so RunDeps never imports the target's dependencies.
    """
    if not entries:
        return {}

    payload = json.dumps([[name, dist] for name, dist in entries])
    proc = run([python, "-c", _PROBE, payload], timeout=300, env=child_env(None))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise EnvProblem(
            f"could not inspect {python}"
            + (f": {detail[-1]}" if detail else "")
        )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise EnvProblem(f"unexpected output while inspecting {python}") from exc


_INDEX_PROBE = r"""
import json
from importlib import metadata

try:
    index = metadata.packages_distributions()
except Exception:
    index = {}
print(json.dumps({name: list(dists) for name, dists in index.items()}))
"""


def distribution_index(python: Path) -> dict[str, list[str]]:
    """Import name -> distributions, as seen by another interpreter."""
    proc = run([python, "-c", _INDEX_PROBE], timeout=300, env=child_env(None))
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name): [str(d) for d in dists] for name, dists in data.items() if isinstance(dists, list)}


def child_env(venv: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    # A stale PYTHONHOME makes any venv unusable.
    env.pop("PYTHONHOME", None)
    if venv is not None:
        env["VIRTUAL_ENV"] = str(venv)
    return env


def load_config(project: Project) -> dict:
    path = project.config_path
    if not path.is_file():
        return {}

    text = path.read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:
        return _parse_simple_toml(text)

    try:
        data = tomllib.loads(text)
    except Exception:
        return _parse_simple_toml(text)

    section = data.get("rundeps")
    merged = dict(data)
    if isinstance(section, dict):
        merged.update(section)
    return merged


def _parse_simple_toml(text: str) -> dict:
    """Fallback for Python 3.10, where tomllib does not exist.

    Only flat ``key = value`` pairs matter for RunDeps' small config file.
    """
    out: dict = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            out[key] = value[1:-1]
        elif value.lower() in {"true", "false"}:
            out[key] = value.lower() == "true"
        else:
            try:
                out[key] = int(value)
            except ValueError:
                out[key] = value
    return out


def load_state(project: Project) -> dict:
    try:
        data = json.loads(project.state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_packages(project: Project, versions: Mapping[str, str | None]) -> None:
    """Remember what RunDeps installed, so later runs and --freeze can use it."""
    state = load_state(project)
    packages = dict(state.get("packages") or {})
    for name, version in versions.items():
        if version:
            packages[name] = version
        else:
            packages.setdefault(name, "")

    state.update(
        {
            "rundeps": __version__,
            "python": platform.python_version(),
            "packages": packages,
        }
    )
    project.dir.mkdir(parents=True, exist_ok=True)
    project.state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def read_gitignore(root: Path) -> str:
    path = root / ".gitignore"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
