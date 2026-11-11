# Contributing to RunDeps

Thanks for taking a look. RunDeps is small on purpose — a few modules of plain
Python with no runtime dependencies — so it should be easy to reason about.

## Development setup

```bash
git clone https://github.com/your-name/rundeps.git
cd rundeps
python -m pip install -e ".[dev]"
```

Python 3.10+ is required. Run the CLI from the source tree without installing:

```bash
python -m rundeps scan examples/basic.py
```

## Running tests

```bash
pytest                    # full suite, no network needed
pytest tests/test_analyzer.py -v
python -m build           # verify the package still builds
```

Tests are offline by design. They monkeypatch the installer and pip calls, and
create environments with `venv.create(with_pip=False)` so nothing is downloaded.
If you add a test that genuinely needs PyPI, mark it:

```python
@pytest.mark.network
def test_something_against_pypi():
    ...
```

and it will be excluded when running `pytest -m "not network"`.

## Project structure

| Path | Responsibility |
| --- | --- |
| `src/rundeps/cli.py` | Argument parsing and the command flows |
| `src/rundeps/analyzer.py` | AST scan, stdlib/local/third-party classification |
| `src/rundeps/resolver.py` | Import name → distribution, with confidence |
| `src/rundeps/environment.py` | Project layout, venv creation, interpreter probing |
| `src/rundeps/installer.py` | pip invocation and failure reporting |
| `src/rundeps/runner.py` | Running the script, extracting `ModuleNotFoundError` |
| `src/rundeps/output.py` | Terminal formatting |
| `src/rundeps/models.py` | Shared dataclasses |
| `src/rundeps/names.py` | PEP 503 normalization, package-name validation |
| `src/rundeps/proc.py` | Subprocess helper |

The dependency direction is one-way: `cli` → everything else, and the other
modules do not import `cli`.

## Adding an import mapping

Mappings live in `src/rundeps/data/import_map.json`, not in Python code. Add an
entry only when the import name and the PyPI name genuinely differ:

```json
{
  "mappings": {
    "PIL": "Pillow",
    "yourimport": "your-package"
  }
}
```

Guidelines:

- Keys are the **top-level import name**, case sensitive (`PIL`, not `pil`).
- A dotted key such as `google.protobuf` is allowed and takes priority over the
  bare top-level name — use it when one namespace has several distributions.
- Do not add entries where the names match (`requests` → `requests`). Those
  resolve without help and would only hide resolution bugs.
- Prefer the distribution people actually install (`psycopg2-binary` over
  `psycopg2`) when that is the sensible default.
- Add a test in `tests/test_resolver.py` for anything non-obvious.

## Making a change

1. Open an issue first for anything larger than a bug fix, so the design can be
   discussed before you write it.
2. Keep the diff focused. One concern per pull request.
3. Match the existing style: functions over class hierarchies, `pathlib` over
   `os.path`, subprocess argument lists rather than shell strings.
4. Add or update tests. A behaviour change without a test is not finished.
5. Update `CHANGELOG.md` under the unreleased section.
6. Run `pytest` and `python -m build` before pushing.

## Reporting bugs

Include:

- your OS and Python version (`rundeps doctor` output is ideal),
- the command you ran,
- the full output, including anything pip printed,
- the script that triggered it if you can share it — the import block alone is
  usually enough.

Do not paste tokens, credentials or private package index URLs into an issue.

## Security issues

Do not open a public issue for a security problem. See [SECURITY.md](SECURITY.md).
