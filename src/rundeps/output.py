"""Terminal presentation.

Everything that decides how RunDeps looks lives here, so the command layer can
deal in data instead of escape sequences. Colour and symbols degrade on their
own: redirected output, CI logs, ``NO_COLOR`` and legacy Windows consoles get
plain ASCII with no escapes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence, TextIO

RULE_WIDTH = 45


@dataclass(frozen=True)
class Symbols:
    ok: str
    bad: str
    warn: str
    arrow: str
    play: str
    unknown: str


UNICODE_SYMBOLS = Symbols(ok="✓", bad="✗", warn="!", arrow="→", play="▶", unknown="?")
ASCII_SYMBOLS = Symbols(ok="+", bad="x", warn="!", arrow="->", play=">", unknown="?")


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
        "✓→▶─".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


class Console:
    """Small formatter. Resolves the stream lazily so redirection still works."""

    def __init__(self, stream: TextIO | None = None, *, color: bool | None = None,
                 unicode: bool | None = None) -> None:
        self._stream = stream
        self._color = color
        self._unicode = unicode

    @property
    def stream(self) -> TextIO:
        return self._stream or sys.stdout

    @property
    def color(self) -> bool:
        return self._color if self._color is not None else _supports_color(self.stream)

    @property
    def unicode(self) -> bool:
        return self._unicode if self._unicode is not None else _supports_unicode(self.stream)

    @property
    def sym(self) -> Symbols:
        return UNICODE_SYMBOLS if self.unicode else ASCII_SYMBOLS

    # -- primitives ---------------------------------------------------------
    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

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

    def cyan(self, text: str) -> str:
        return self._paint(text, "36")

    @property
    def ok_mark(self) -> str:
        return self.green(self.sym.ok)

    @property
    def bad_mark(self) -> str:
        return self.red(self.sym.bad)

    @property
    def warn_mark(self) -> str:
        return self.yellow(self.sym.warn)

    @property
    def play_mark(self) -> str:
        return self.cyan(self.sym.play)

    @property
    def unknown_mark(self) -> str:
        return self.yellow(self.sym.unknown)

    @property
    def arrow(self) -> str:
        return self.sym.arrow

    # -- layout -------------------------------------------------------------
    def write(self, text: str = "") -> None:
        print(text, file=self.stream)
        self.stream.flush()

    def blank(self) -> None:
        self.write()

    def rule(self) -> None:
        self.write("  " + self.dim("─" * RULE_WIDTH))

    def title(self, name: str) -> None:
        self.write(f"  {self.cyan(self.bold('RunDeps'))} {self.dim('·')} {self.bold(name)}")
        self.rule()

    def status(self, mark: str, text: str) -> None:
        self.write(f"  {mark} {text}")

    def field(self, mark: str, label: str, value: str = "") -> None:
        """A two-column status line: one glance gives one fact."""
        gap = " " * max(2, 16 - len(label))
        self.write(f"  {mark} {label}{gap}{value}".rstrip())

    def pairs(self, items: Iterable[tuple[str, str]], *, indent: str = "      ") -> None:
        """Aligned ``import → package`` rows."""
        rows = list(items)
        if not rows:
            return
        width = max(len(left) for left, _ in rows)
        for left, right in rows:
            self.write(f"{indent}{left:<{width}}  {self.arrow} {right}")

    def lines(self, lines: Sequence[str], *, indent: str = "      ") -> None:
        for line in lines:
            self.write(f"{indent}{line}")

    def note(self, text: str) -> None:
        self.write(f"  {text}")

    def ok(self, text: str, extra: str = "") -> None:
        """Green check plus an optional dim suffix."""
        tail = f"  {self.dim(extra)}" if extra else ""
        self.write(f"  {self.ok_mark} {text}{tail}")

    def warn(self, text: str, extra: str = "") -> None:
        tail = f"  {self.dim(extra)}" if extra else ""
        self.write(f"  {self.warn_mark} {text}{tail}")

    def hint(self, text: str) -> None:
        self.write(f"  {self.dim(text)}")

    def error(self, text: str) -> None:
        self.blank()
        self.write(f"  {self.red(self.sym.bad)} {self.red(text)}")

    # -- interaction --------------------------------------------------------
    def interactive(self) -> bool:
        try:
            return bool(sys.stdin and sys.stdin.isatty())
        except (AttributeError, ValueError):
            return False

    def ask(self, question: str, *, default: bool = True, assume: bool | None = None) -> bool:
        """Yes/no prompt.

        Without a readable terminal the answer is No: an unattended run must
        never install something the user did not approve with --yes.
        """
        if assume is not None:
            return assume
        if not self.interactive():
            self.hint("No terminal for confirmation; assuming No.")
            return False

        suffix = "[Y/n]" if default else "[y/N]"
        try:
            answer = input(f"  {question} {suffix} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.write()
            return False

        if not answer:
            return default
        return answer in {"y", "yes"}


console = Console()
