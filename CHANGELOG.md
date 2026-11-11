# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0

First release. What it actually does:

### Added

- `rundeps run <script>` — scans, resolves, asks, installs into an isolated
  environment, executes the script and returns its exit code.
- `rundeps scan <script>` — read-only report of standard library, local,
  installed, missing and unresolvable imports.
- `rundeps requirements <script>` — writes requirements for that one script, with
  `--freeze`, `--stdout`, `-o` and `--dry-run`.
- `rundeps init [path]` — creates `.rundeps/`, a small `config.toml`, and adds the
  directory to `.gitignore`.
- `rundeps install <package>...` — explicit installs into the project environment.
- `rundeps doctor` — reports interpreter, venv/pip availability and project state.
- AST import analysis with stdlib detection via `sys.stdlib_module_names`, local
  sibling detection, relative-import exclusion, and duplicate collapsing.
- Import-to-distribution resolution from a JSON mapping, installed distribution
  metadata, and normalized name guesses, each carrying a confidence level.
- Runtime `ModuleNotFoundError` recovery with a configurable retry cap
  (`--max-retries`, default 3), one attempt per module.
- Confirmation before every install; `--yes` only approves high-confidence
  packages; low-confidence names are never installed automatically.
- `--dry-run`, `--no-isolation`, `--verbose`, and `--` pass-through for the target
  script's own arguments.
- Project-local virtual environment at `.rundeps/venv` created with `venv`.
- Per-project mapping overrides via `[mappings]` in `.rundeps/config.toml`.
- Test suite covering analysis, resolution, environment handling, runtime
  detection and CLI behaviour, plus a Windows/macOS/Linux CI matrix.

### Known limitations

- Static analysis cannot see dynamic imports; the runtime fallback covers the
  common case only.
- Resolution depends on the mapping file plus installed metadata; unusual
  packages fall back to low confidence and manual installs.
- No lockfile, no version-constraint inference, no wheel caching.
- RunDeps does not audit package code or scan for vulnerabilities.
