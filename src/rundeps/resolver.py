"""Turning import names into installable distribution names.

Resolution order, highest confidence first:

1. Explicit entry in ``data/import_map.json`` (dotted paths beat top-level names).
2. Distribution metadata from an environment that actually has the module.
3. A normalized guess of the project name, flagged as low confidence.

RunDeps never installs a low-confidence guess on its own.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.metadata import packages_distributions
from pathlib import Path
from typing import Iterable, Mapping

from .models import Confidence, Resolution
from .names import canonicalize, guessed_distribution


DATA_DIR = Path(__file__).with_name("data")


@lru_cache(maxsize=1)
def load_import_map() -> dict[str, str]:
    raw = json.loads((DATA_DIR / "import_map.json").read_text(encoding="utf-8"))
    mappings = raw.get("mappings", {})
    return {str(key): str(value) for key, value in mappings.items()}


def _pick_distribution(candidates: Iterable[str], import_name: str) -> str | None:
    names = [name for name in candidates if name]
    if not names:
        return None

    wanted = canonicalize(import_name)
    for name in names:
        if canonicalize(name) == wanted:
            return name
    # python-dateutil declares "dateutil": the closest name wins over a random sibling.
    for name in names:
        if canonicalize(name).replace("-", "") == wanted.replace("-", ""):
            return name
    return sorted(names)[0]


class Resolver:
    """Resolves import names using a mapping plus optional distribution metadata.

    ``index`` maps a top-level import name to the distributions that provide it,
    as returned by :func:`importlib.metadata.packages_distributions`.
    """

    def __init__(
        self,
        index: Mapping[str, list[str]] | None = None,
        mapping: Mapping[str, str] | None = None,
    ) -> None:
        self._mapping = dict(mapping if mapping is not None else load_import_map())
        self._index = dict(index or {})

    def resolve(self, import_name: str, module: str | None = None) -> Resolution:
        # A dotted key such as "google.protobuf" is more specific than "google".
        if module and module != import_name and module in self._mapping:
            return Resolution(import_name, self._mapping[module], Confidence.HIGH, "known import mapping")

        if import_name in self._mapping:
            return Resolution(import_name, self._mapping[import_name], Confidence.HIGH, "known import mapping")

        installed = _pick_distribution(self._index.get(import_name, []), import_name)
        if installed:
            return Resolution(import_name, installed, Confidence.HIGH, "distribution metadata")

        guess = guessed_distribution(import_name)
        if guess == import_name.lower():
            # requests -> requests. The spelling agrees with itself, but nothing
            # has confirmed such a project exists, so --yes still will not
            # approve it unattended.
            return Resolution(import_name, guess, Confidence.MEDIUM, "import name matches project name")
        return Resolution(import_name, guess, Confidence.LOW, "name guessed from import")

    def resolve_all(self, imports: Iterable[str]) -> list[Resolution]:
        return [self.resolve(name) for name in imports]


def installed_index() -> dict[str, list[str]]:
    """Import name -> distributions, for the interpreter running RunDeps."""
    try:
        return {name: list(dists) for name, dists in packages_distributions().items()}
    except Exception:
        # Broken site-packages should not take the whole tool down.
        return {}


def merged_index(*indexes: Mapping[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for index in indexes:
        for name, dists in index.items():
            known = merged.setdefault(name, [])
            known.extend(d for d in dists if d not in known)
    return merged


def dedupe(resolutions: Iterable[Resolution]) -> list[Resolution]:
    """Keep one resolution per distribution, preferring the strongest evidence."""
    best: dict[str, Resolution] = {}
    order = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
    for resolution in resolutions:
        if resolution.package is None:
            continue
        key = canonicalize(resolution.package)
        current = best.get(key)
        if current is None or order[resolution.confidence] > order[current.confidence]:
            best[key] = resolution
    return sorted(best.values(), key=lambda item: canonicalize(item.package or ""))
