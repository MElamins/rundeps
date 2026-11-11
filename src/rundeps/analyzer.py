"""Static import analysis.

The scan never imports or executes the target file: everything comes from
``ast`` plus the file's sibling modules.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from .models import Analysis, ImportKind, ImportRecord


class AnalysisError(Exception):
    """The script could not be read or parsed."""


class _ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: dict[str, tuple[str, int]] = {}

    def _remember(self, dotted: str, lineno: int) -> None:
        top = dotted.split(".", 1)[0]
        if not top.isidentifier():
            return
        # Keep the first occurrence: that is the line the user sees in an error.
        self.found.setdefault(top, (dotted, lineno))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._remember(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            # from .utils import thing -- explicitly relative, never external.
            return
        if node.module:
            self._remember(node.module, node.lineno)


def is_stdlib(name: str) -> bool:
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is not None and name in stdlib:
        return True
    return name in sys.builtin_module_names


def local_module_names(script: Path) -> set[str]:
    """Modules Python would find next to the script."""

    names = {script.stem}
    try:
        entries = list(script.parent.iterdir())
    except OSError:
        return names

    for entry in entries:
        try:
            if entry.suffix == ".py" and entry.is_file():
                names.add(entry.stem)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                names.add(entry.name)
        except OSError:
            continue

    names.discard("__init__")
    names.discard("")
    return names


def read_tree(script: Path) -> ast.Module:
    try:
        source = script.read_bytes()
    except OSError as exc:
        raise AnalysisError(f"cannot read {script}: {exc.strerror or exc}") from exc

    # Passing bytes lets ast honour the file's own coding cookie.
    try:
        return ast.parse(source, filename=str(script))
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        raise AnalysisError(f"syntax error in {script.name} ({location}): {exc.msg}") from exc
    except ValueError as exc:
        raise AnalysisError(f"cannot parse {script}: {exc}") from exc


def analyze(script: Path) -> Analysis:
    script = Path(script).expanduser()
    if not script.exists():
        raise AnalysisError(f"no such file: {script}")
    if not script.is_file():
        raise AnalysisError(f"not a file: {script}")
    if script.suffix != ".py":
        raise AnalysisError(f"expected a .py file, got {script.name}")

    tree = read_tree(script)
    collector = _ImportCollector()
    collector.visit(tree)

    locals_ = local_module_names(script)
    records = []
    for name, (dotted, lineno) in collector.found.items():
        # A sibling module shadows the standard library, exactly like the interpreter.
        if name in locals_:
            kind = ImportKind.LOCAL
        elif is_stdlib(name):
            kind = ImportKind.STDLIB
        else:
            kind = ImportKind.THIRD_PARTY
        records.append(ImportRecord(name=name, module=dotted, kind=kind, lineno=lineno))

    records.sort(key=lambda record: (record.lineno, record.name))
    return Analysis(path=script, imports=records)
