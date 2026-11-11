"""Name handling for imports and distributions."""

from __future__ import annotations

import re

_VALID = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")
_STRIP = re.compile(r"[^A-Za-z0-9._-]+")


def canonicalize(name: str) -> str:
    """PEP 503 normalization: PyYAML and pyyaml are the same distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


def is_valid_package_name(name: str) -> bool:
    """Reject anything pip could read as an option, path or requirement string."""
    if not name or name.startswith(("-", ".", "_")):
        return False
    if "://" in name or "/" in name or "\\" in name or " " in name:
        return False
    return bool(_VALID.match(name))


def guessed_distribution(import_name: str) -> str:
    """Turn an unknown import name into a plausible PyPI project name."""
    guess = _STRIP.sub("-", import_name.replace("_", "-")).strip("-.")
    return guess.lower() or import_name.lower()
