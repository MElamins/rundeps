"""A script that genuinely needs a third-party package.

    rundeps scan examples/missing_dependency.py
    rundeps run  examples/missing_dependency.py

The import name is ``yaml`` but the distribution is ``PyYAML`` -- RunDeps
resolves it from its mapping data and tells you before installing anything.
"""

import sys

import requests
import yaml


def main() -> None:
    config = yaml.safe_load("""
    name: rundeps
    requires:
      - python
      - pip
    """)

    print(f"python {sys.version.split()[0]}")
    print("config:", config)
    print("requests version:", requests.__version__)


if __name__ == "__main__":
    main()
