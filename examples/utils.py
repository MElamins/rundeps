"""A sibling module imported by basic.py.

RunDeps resolves this as a local import and never looks for a PyPI package
named "utils".
"""

import re

_NON_WORD = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _NON_WORD.sub("-", text.strip().lower()).strip("-")
