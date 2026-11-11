"""Terminal output. Deliberately small: no UI framework, no emoji soup."""

from __future__ import annotations

import os
import sys
from typing import TextIO


def _supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _supports_unicode(stream: TextIO) -> bool:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "✓✗→".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


class Console:
    """Thin wrapper over stdout.

    The stream is resolved on every call so redirecting ``sys.stdout`` (pipes,
    test capture) keeps working after import time.
    """

    def __init__(self, stream: TextIO | None = None, *, color: bool | None = None) -> None:
        self._stream = stream
        self._color = color

    @property
    def stream(self) -> TextIO:
        return self._stream or sys.stdout

    @property
    def color(self) -> bool:
        return self._color if self._color is not None else _supports_color(self.stream)

    @property
    def unicode(self) -> bool:
        return _supports_unicode(self.stream)

    # -- primitives ---------------------------------------------------------
    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def write(self, text: str = "") -> None:
        print(text, file=self.stream)
        self.stream.flush()

    def dim(self, text: str) -> str:
        return self._paint(text, "2")

    def bold(self, text: str) -> str:
        return self._paint(text, "1")

    def green(self, text: str) -> str:
        return self._paint(text, "32")

    def red(self, text: str) -> str:
        return self._paint(text, "31")

    def yellow(self, text: str) -> str:
        return self._paint(text, "33")

    # -- marks --------------------------------------------------------------
    @property
    def ok_mark(self) -> str:
        return self.green("✓" if self.unicode else "+")

    @property
    def bad_mark(self) -> str:
        return self.red("✗" if self.unicode else "x")

    @property
    def warn_mark(self) -> str:
        return self.yellow("!" if self.unicode else "!")

    # -- structured output --------------------------------------------------
    def banner(self, subtitle: str | None = None) -> None:
        self.write(self.bold("RunDeps") + (f"  {self.dim(subtitle)}" if subtitle else ""))
        self.rule()

    def rule(self, width: int = 52) -> None:
        self.write(self.dim("─" * width))

    def heading(self, text: str) -> None:
        self.write()
        self.write(self.bold(text))

    def item(self, mark: str, label: str, note: str = "") -> None:
        tail = f"  {self.dim(note)}" if note else ""
        self.write(f"  {mark} {label}{tail}")

    def ok(self, label: str, note: str = "") -> None:
        self.item(self.ok_mark, label, note)

    def missing(self, label: str, note: str = "") -> None:
        self.item(self.bad_mark, label, note)

    def warn(self, label: str, note: str = "") -> None:
        self.item(self.warn_mark, label, note)

    def plain(self, text: str = "") -> None:
        self.write(f"  {text}" if text else "")

    def detail(self, text: str) -> None:
        self.write(self.dim(f"  {text}"))

    def hint(self, text: str) -> None:
        self.write(self.dim(f"  {text}"))

    def error(self, text: str) -> None:
        self.write()
        self.write(f"{self.red('error')}: {text}")

    # -- interaction --------------------------------------------------------
    def interactive(self) -> bool:
        try:
            return bool(sys.stdin and sys.stdin.isatty())
        except (AttributeError, ValueError):
            return False

    def ask(self, question: str, *, default: bool = True, assume: bool | None = None) -> bool:
        """Ask a yes/no question.

        Without a readable terminal we never guess "yes": an unattended run must
        not install anything the user did not approve with --yes.
        """
        if assume is not None:
            return assume
        if not self.interactive():
            self.hint("No terminal available for confirmation; treating as No.")
            return False

        suffix = "[Y/n]" if default else "[y/N]"
        try:
            answer = input(f"{question} {suffix} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.write()
            return False

        if not answer:
            return default
        return answer in {"y", "yes"}


console = Console()
