"""A dependency that static analysis cannot see.

    rundeps scan examples/runtime_import.py   # reports nothing missing
    rundeps run  examples/runtime_import.py   # detects it at runtime instead

The import only happens when the module name is built as a string, which is
exactly the case `ModuleNotFoundError` detection exists for.
"""

import importlib


def main() -> None:
    for name in ("textwrap", "json", "humanize"):
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError:
            print(f"{name}: not available yet")
            continue
        print(f"{name}: {module.__name__}")


if __name__ == "__main__":
    main()
