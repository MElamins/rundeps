# RunDeps

**Run Python without hunting for dependencies.**

You found a Python script somewhere. You ran it. Python said `ModuleNotFoundError`.
You installed a package. You ran it again. A different dependency was missing.

```text
$ python script.py
ModuleNotFoundError: No module named 'requests'
$ pip install requests
$ python script.py
ModuleNotFoundError: No module named 'yaml'
$ pip install PyYAML
$ python script.py
ModuleNotFoundError: No module named 'PIL'
...
```

RunDeps handles the boring part:

```text
$ rundeps run script.py
```

It reads the script, works out what it actually imports, checks what is already
available, resolves import names to PyPI names (`PIL` → `Pillow`), shows you the
list, asks once, installs into a project-local virtual environment, and then runs
the script. Your script is not modified, and your global Python is not touched.

---

## Why it exists

There is a gap between "here is a file" and "this file runs". Git repositories
with a `requirements.txt` are fine; a single `script.py` pasted into a tutorial or
a chat is not. RunDeps closes that gap without asking you to become a packaging
expert, and without silently installing things you did not agree to.

The workflow is the feature:

> **Analyze → Resolve → Confirm → Isolate → Install → Run → Recover**

RunDeps does not claim to be the first tool that installs Python dependencies. It
is an opinionated, transparent implementation of that whole path in one command,
safe by default.

---

## Install

RunDeps has **no runtime dependencies** — only the standard library.

```bash
python -m pip install rundeps
```

From source, for development:

```bash
git clone https://github.com/your-name/rundeps.git
cd rundeps
python -m pip install -e ".[dev]"
```

Requires Python **3.10 or newer** on Windows, macOS or Linux.

---

## Quick start

```bash
rundeps run examples/missing_dependency.py
```

That script imports `requests` and `yaml`. If neither is available, you get:

```text
RunDeps
────────────────────────────────────────────────────
Scanning missing_dependency.py...

Imports found
  ✓ sys        standard library
  ✗ requests   missing
  ✗ yaml       missing

Resolving missing imports
  requests  →  requests
  yaml      →  PyYAML

! 2 missing dependencies

Install 2 package(s)
  requests
  PyYAML

Proceed? [Y/n]
```

Answer yes and RunDeps creates `.rundeps/venv`, installs into it, and runs your
script with that interpreter. Answer no and nothing happens at all.

To look before you leap:

```bash
rundeps scan examples/missing_dependency.py   # report only, changes nothing
rundeps run  examples/missing_dependency.py --dry-run
```

---

## Commands

| Command | What it does |
| --- | --- |
| `rundeps run <script>` | Scan, resolve, confirm, install, then execute the script |
| `rundeps scan <script>` | Report the dependency picture and change nothing |
| `rundeps requirements <script>` | Write a `requirements.txt` for that script only |
| `rundeps init [path]` | Create `.rundeps/` config and add it to `.gitignore` |
| `rundeps install <package>...` | Install explicit packages into the project environment |
| `rundeps doctor` | Check the interpreter, venv support, pip, and project state |

### `rundeps run` options

| Flag | Effect |
| --- | --- |
| `--dry-run` | Show the plan. Installs nothing, runs nothing. |
| `--yes`, `-y` | Approve **high-confidence** installs only. Low-confidence guesses are still refused. |
| `--no-isolation` | Use the current environment instead of `.rundeps/venv`. Less safe, clearly labelled. |
| `--verbose`, `-v` | Show the interpreter, project root, and why each import resolved. |
| `--max-retries N` | How many runtime dependency retries to allow (default `3`). |

### Passing arguments to your script

Everything after a bare `--` goes to the target program untouched:

```bash
rundeps run script.py -- input.txt --mode fast
```

`script.py` receives `["input.txt", "--mode", "fast"]` exactly as written.

### `rundeps requirements`

```bash
rundeps requirements script.py            # writes requirements.txt next to the script
rundeps requirements script.py --freeze   # pins versions RunDeps recorded
rundeps requirements script.py --stdout   # print instead of writing
rundeps requirements script.py -o reqs.txt
```

Only imports from that script are included — standard-library modules and local
files are excluded, and your global environment's installed packages are never
dumped into the file.

---

## How resolution works

Import names and distribution names are not the same thing. `PIL` is installed by
`pip install Pillow`. RunDeps resolves in this order:

1. **Explicit mapping** from `src/rundeps/data/import_map.json` (highest confidence).
   Dotted keys such as `google.protobuf` beat the bare top-level name.
2. **Installed distribution metadata** via `importlib.metadata.packages_distributions()`,
   so a package that is already present resolves from evidence, not guesswork.
3. **Normalized name guess** (`my_module` → `my-module`), marked low confidence.

The confidence levels drive behaviour:

| Confidence | Source | Auto-approved by `--yes`? | Installed when you confirm? |
| --- | --- | --- | --- |
| high | known mapping or metadata | yes | yes |
| medium | import name already matches the project name | **no** | yes |
| low | a guess | **no** | **no** |

`medium` exists because `requests` is spelled the same way as its distribution,
but nothing has confirmed such a project exists. It is still shown to you and can
be installed after you say yes; it is never installed unattended.

### When RunDeps is not sure

```text
$ rundeps scan weird.py

Could not confidently resolve
  ! something_weird
    possible package: something-weird  (low confidence)

  RunDeps will not install these automatically.
  If you know the package, install it explicitly and rerun:
    rundeps install something-weird
```

That is the whole policy: **uncertainty never turns into an installation.**

### Runtime fallback

Static analysis cannot see `importlib.import_module("name")` or imports guarded
behind a branch. So after running your script, RunDeps watches for a
`ModuleNotFoundError` in stderr, extracts the top-level module name, and offers
one targeted install-and-retry:

```text
Running runtime_import.py
────────────────────────────────────────────────────
humanize: not available yet

! RunDeps detected a missing runtime dependency.
  import:      humanize
  package:     humanize
  confidence:  medium
  evidence:    import name matches project name

Install humanize and retry? [Y/n]
```

Retries are capped by `--max-retries` (default 3), each module is attempted once,
and only a genuine `ModuleNotFoundError` triggers this path — a `ValueError` in
your script is never mistaken for a missing package.

---

## Safety model

Dependency installation is a security-sensitive operation. RunDeps is intentionally
conservative:

- **Nothing is installed without consent.** Every package is printed before it is
  installed, and every install is confirmed. There is no "just do it" default.
- **Isolated by default.** Packages go into `.rundeps/venv`, created with `venv`
  from the interpreter running RunDeps. Your global environment is not modified.
  `--no-isolation` exists, is opt-in, and says so on screen.
- **No shell strings.** Every subprocess takes an argument list; nothing is passed
  through a shell. Installation always uses `python -m pip` of the selected
  interpreter.
- **Your files are untouched.** The script is parsed, never rewritten. `scan` and
  `--dry-run` create no files at all.
- **No code execution during scanning.** Imports are collected from `ast`; packages
  are never imported to find out what they need. Import availability is probed in
  a *separate* short-lived interpreter.
- **No guessing on unknown packages.** Low-confidence names are reported and
  refused, not installed.
- **No network beyond pip.** No telemetry, no source upload, no AI service, no API
  keys, nothing written to your home directory.
- **No secrets in output.** RunDeps reads no credentials and prints none; `doctor`
  reports interpreter and project state only.

What RunDeps does **not** do: it does not audit package code, scan for
vulnerabilities, verify signatures, or prevent a malicious package you approved
from doing harm. It is a workflow tool with good defaults, not a security scanner.
Approve package names you recognise.

---

## Environments

```text
project/
├── script.py
└── .rundeps/
    ├── venv/          # isolated interpreter, created on first install
    ├── state.json     # packages RunDeps installed (used by --freeze)
    └── config.toml    # optional project settings
```

`rundeps init` creates the directory, a small `config.toml`, and adds `.rundeps/`
to your `.gitignore` (creating the file if needed).

```toml
# .rundeps/config.toml
[rundeps]
isolation = true
max_retries = 3
```

You can also override individual mappings per project:

```toml
[mappings]
bs4 = "my-internal-bs4"
```

RunDeps finds the nearest `.rundeps/` walking up from the script, so running a
script in `project/tools/x.py` still uses the project environment.

---

## Examples

| File | Shows |
| --- | --- |
| `examples/basic.py` | Standard library plus a sibling `utils.py` — nothing to install |
| `examples/missing_dependency.py` | Real third-party needs, including `yaml` → `PyYAML` |
| `examples/runtime_import.py` | A dependency static analysis cannot see |

```bash
rundeps scan examples/basic.py           # no third-party imports
rundeps run  examples/basic.py
rundeps scan examples/missing_dependency.py
rundeps run  examples/missing_dependency.py
rundeps run  examples/runtime_import.py
```

---

## Supported platforms

- **OS:** Windows, macOS, Linux.
- **Python:** 3.10, 3.11, 3.12, 3.13 (tested in CI).
- **Environment managers:** Python's own `venv` and `pip`. No Docker, no Conda
  requirement, no system packages.

---

## Limitations

Being honest about the edges:

- **Static analysis is static.** Dynamic imports, `__import__` with computed
  names, plugin systems and optional extras hide from the scanner. The runtime
  fallback catches the common case, not every case.
- **Only PyPI-style installs.** The installer speaks `pip`. Poetry, uv, PDM and
  Conda environments are not managed.
- **Name resolution can be wrong.** The mapping file covers common cases; unusual
  packages fall back to low confidence and a manual `rundeps install`.
- **One script at a time.** A project-wide import graph is not built yet, so
  `requirements` reflects a single file.
- **Version constraints are not inferred.** RunDeps installs current versions and
  can pin what it installed with `--freeze`; it does not read `install_requires`.
- **No lockfile, no caching of wheels, no vulnerability data.**
- **No guarantees about package safety.** See the safety model above.

---

## Architecture

```text
src/rundeps/
├── cli.py          argument parsing and the command flows
├── analyzer.py     AST scan: stdlib / local / third-party
├── resolver.py     import name → distribution, with confidence
├── environment.py  project layout, venv creation, interpreter probing
├── installer.py    pip invocation and failure reporting
├── runner.py       runs the script, extracts ModuleNotFoundError
├── output.py       small terminal formatting layer
├── models.py       the shared dataclasses
├── names.py        PEP 503 normalization and package-name validation
├── proc.py         subprocess helper (lists only, never shell strings)
└── data/
    └── import_map.json
```

The pieces are functions and small dataclasses, not a framework. `cli.py` wires
them together; each module can be exercised on its own, which is what the tests do.

---

## Development

```bash
python -m pip install -e ".[dev]"
pytest
pytest -m "not network"      # default: no network needed
python -m build              # wheel + sdist into dist/
```

Run the CLI straight from the source tree:

```bash
python -m rundeps scan examples/basic.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the structure and how to add a mapping.

---

## Roadmap

Shipped in 0.1.0: static analysis, resolution with confidence, confirmation,
isolated environments, install, run, runtime recovery, `scan`/`requirements`/
`init`/`doctor`.

Not started, roughly in order of value:

- Project-wide analysis instead of one file at a time
- Import-to-package resolution improvements and better confidence scoring
- Respecting version constraints already declared by the target project
- Lockfile generation with a stable hash input
- Support for PEP 723 inline script metadata
- Wheel caching so repeated runs are fast
- Optional package provenance and vulnerability information
- Editor integration, and notebook support

---

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Security issues should follow [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
