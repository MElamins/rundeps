"""Small shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ImportKind(str, Enum):
    STDLIB = "stdlib"
    LOCAL = "local"
    THIRD_PARTY = "third-party"

    @property
    def label(self) -> str:
        return {
            ImportKind.STDLIB: "standard library",
            ImportKind.LOCAL: "local",
            ImportKind.THIRD_PARTY: "third-party",
        }[self]


@dataclass(frozen=True)
class ImportRecord:
    """One top-level import found in a script.

    ``module`` keeps the full dotted path of the first occurrence so that a
    mapping key like ``google.protobuf`` can win over the bare ``google``.
    """

    name: str
    module: str
    kind: ImportKind
    lineno: int


@dataclass
class Analysis:
    path: Path
    imports: list[ImportRecord] = field(default_factory=list)

    def _names(self, kind: ImportKind) -> list[str]:
        names = {record.name for record in self.imports if record.kind is kind}
        return sorted(names, key=str.lower)

    @property
    def stdlib(self) -> list[str]:
        return self._names(ImportKind.STDLIB)

    @property
    def local(self) -> list[str]:
        return self._names(ImportKind.LOCAL)

    @property
    def third_party(self) -> list[str]:
        return self._names(ImportKind.THIRD_PARTY)

    def module_for(self, name: str) -> str:
        for record in self.imports:
            if record.name == name and record.module != name:
                return record.module
        return name


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Resolution:
    import_name: str
    package: str | None
    confidence: Confidence
    reason: str

    @property
    def installable(self) -> bool:
        """Whether the package may enter a default install plan at all."""
        return self.package is not None and self.confidence is not Confidence.LOW

    @property
    def trusted(self) -> bool:
        """High enough confidence to install with only ``--yes`` behind it."""
        return self.package is not None and self.confidence is Confidence.HIGH


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
