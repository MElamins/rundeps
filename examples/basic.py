"""Standard library only: RunDeps should find nothing to install.

    rundeps run examples/basic.py
"""

import json
import os
from collections import Counter
from pathlib import Path

from utils import slugify  # a sibling module, not a PyPI package


def main() -> None:
    words = slugify("RunDeps Handles The Boring Part").split("-")
    payload = {
        "counts": dict(Counter(words)),
        "script": Path(__file__).name,
        "cwd": os.getcwd(),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
