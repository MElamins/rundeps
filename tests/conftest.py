"""Shared test configuration.

The CLI tests must not depend on which packages happen to be installed in the
interpreter running pytest. Import availability is stubbed so "missing" means
missing, deterministically, on every machine and in CI.
"""

import pytest


@pytest.fixture(autouse=True)
def _nothing_is_installed(monkeypatch):
    def fake_probe(python, entries):
        return {name: {"found": False, "version": None} for name, _ in entries}

    monkeypatch.setattr("rundeps.cli.probe", fake_probe)
