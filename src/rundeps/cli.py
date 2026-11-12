"""Command line interface."""

from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .analyzer import AnalysisError, analyze, is_stdlib, local_module_names
from .environment import (
    DEFAULT_MAX_RETRIES,
    PROJECT_DIR,
    EnvProblem,
    Project,
    create_venv,
    distribution_index,
    load_config,
    load_state,
    probe,
    record_packages,
)
from .installer import InstallError, install, require_pip
from .models import Analysis, Resolution
from .output import console
from .resolver import Resolver, dedupe, installed_index, load_import_map, merged_index
from .runner import missing_module, run_script


@dataclass
class Plan:
    analysis: Analysis
    found: dict[str, str | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    resolutions: dict[str, Resolution] = field(default_factory=dict)
    packages: list[str] = field(default_factory=list)
    unknown: list[Resolution] = field(default_factory=list)

    @property
    def installable(self) -> list[Resolution]:
        return [self.resolutions[name] for name in self.missing if self.resolutions[name].installable]

    @property
    def pairs(self) -> list[tuple[str, str]]:
        return [(name, self.resolutions[name].package or name) for name in self.missing
                if name in self.resolutions and self.resolutions[name].package]


def build_resolver(project: Project | None) -> Resolver:
    index = installed_index()
    mapping = None

    if project is not None:
        if project.config_path.is_file():
            custom = load_config(project).get("mappings")
            if isinstance(custom, dict):
                mapping = dict(custom)
        # A package sitting in the project venv is evidence too.
        if project.python.exists():
            index = merged_index(index, distribution_index(project.python))

    return Resolver(index=index, mapping=mapping)


def build_plan(
    analysis: Analysis,
    resolver: Resolver,
    python: Path | None,
) -> Plan:
    """Work out what is missing.

    ``python=None`` means the target environment does not exist yet, so every
    third-party import is missing by definition -- that is the honest answer for
    a virtual environment that is about to be created empty.
    """
    plan = Plan(analysis=analysis)
    wanted = analysis.third_party
    if not wanted:
        return plan

    resolved = {name: resolver.resolve(name, analysis.module_for(name)) for name in wanted}

    if python is None:
        status: dict[str, dict] = {}
    else:
        try:
            status = probe(python, [(name, resolved[name].package or "") for name in wanted])
        except EnvProblem:
            status = {}

    for name in wanted:
        info = status.get(name) or {}
        if info.get("found"):
            plan.found[name] = info.get("version")
            continue
        plan.missing.append(name)
        plan.resolutions[name] = resolved[name]

    trusted = [item for item in plan.resolutions.values() if item.installable]
    plan.packages = [item.package for item in dedupe(trusted) if item.package]
    plan.unknown = [item for item in plan.resolutions.values() if not item.installable]
    return plan


def _visible_python(project: Project) -> Path:
    """The interpreter we would inspect. Never creates anything."""
    if project.python.exists():
        return project.python
    return Path(sys.executable)


def _ensure_venv(project: Project) -> Path:
    if project.python.exists():
        return project.python
    console.blank()
    console.hint("Creating isolated environment...")
    return create_venv(project.venv_dir)


def _install_packages(
    python: Path,
    packages: list[str],
    venv_dir: Path | None,
    project: Project,
    verbose: bool,
) -> list[str]:
    require_pip(python, venv=venv_dir)
    result = install(python, packages, venv=venv_dir, verbose=verbose)

    versions: dict[str, str | None] = {}
    if result.ok:
        try:
            status = probe(python, [(name, name) for name in result.ok])
        except EnvProblem:
            status = {}
        versions = {name: (status.get(name) or {}).get("version") for name in result.ok}

        width = max(len(name) for name in result.ok)
        for name in result.ok:
            version = versions.get(name)
            console.write(f"  {console.ok_mark} {name:<{width}}  {console.dim(version) if version else ''}".rstrip())

    for name, detail in result.failed.items():
        console.error(f"could not install {name}")
        for line in detail.splitlines()[-6:]:
            console.hint(line)

    if result.ok and project.initialised:
        record_packages(project, versions)

    return list(result.ok)


def _write_stream(text: str) -> None:
    if not text:
        return
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _elapsed(started: float) -> str:
    return f"{time.monotonic() - started:.2f}s"


def _summary(analysis: Analysis, plan: Plan) -> None:
    total = len(analysis.imports)
    missing = len(plan.missing)
    noun = "import" if total == 1 else "imports"

    if not missing:
        console.field(console.ok_mark, "Dependencies", console.dim(f"{total} {noun} · all available"))
        return

    console.field(console.warn_mark, "Dependencies", f"{total} {noun} · {missing} missing")
    console.blank()
    console.pairs(plan.pairs)

    if plan.unknown:
        console.blank()
        for resolution in plan.unknown:
            console.write(f"      {console.unknown_mark} {resolution.import_name}")
            console.write(f"        {console.dim('possible package:')} {resolution.package}")
            console.write(f"        {console.dim('confidence:')} {resolution.confidence.value}")
        console.blank()
        console.note("RunDeps won't install these automatically.")
        console.blank()
        console.hint("Install manually:")
        for resolution in plan.unknown:
            console.hint(f"  rundeps install {resolution.package}")


def _finish(code: int, started: float) -> int:
    console.blank()
    console.rule()
    if code == 0:
        console.field(console.ok_mark, "Done", console.dim(_elapsed(started)))
    else:
        console.field(console.bad_mark, "Failed", console.dim(_elapsed(started)))
    return code


# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> int:
    script = Path(args.script)

    try:
        analysis = analyze(script)
    except AnalysisError as exc:
        console.error(str(exc))
        return 2

    project = Project.locate(script)
    resolver = build_resolver(project)
    plan = build_plan(analysis, resolver, _visible_python(project))

    console.title("dependency scan")
    console.blank()

    third_party = len(analysis.third_party)
    console.field(console.ok_mark, "Standard library", str(len(analysis.stdlib)))
    if analysis.local:
        console.field(console.ok_mark, "Local", str(len(analysis.local)))
    console.field(console.ok_mark, "Third-party", str(third_party))

    if plan.missing:
        console.field(console.warn_mark, "Missing", str(len(plan.missing)))
        console.blank()
        console.pairs(plan.pairs)
    else:
        console.field(console.ok_mark, "Missing", "none")

    if plan.unknown:
        console.blank()
        console.field(console.warn_mark, "Unresolved", str(len(plan.unknown)))
        for resolution in plan.unknown:
            console.write(f"      {resolution.import_name}{console.dim(f'  (possible: {resolution.package})')}")

    if args.verbose:
        console.blank()
        console.hint(f"script:      {script}")
        console.hint(f"interpreter: {_visible_python(project)}")
        if analysis.stdlib:
            console.hint("stdlib:      " + ", ".join(analysis.stdlib))
        if analysis.local:
            console.hint("local:       " + ", ".join(analysis.local))

    console.blank()
    console.hint("No changes made.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    script = Path(args.script)
    project = Project.locate(script)
    started = time.monotonic()

    try:
        analysis = analyze(script)
    except AnalysisError as exc:
        console.error(str(exc))
        return 2

    resolver = build_resolver(project)
    isolated = not args.no_isolation
    venv_exists = project.python.exists()

    # A fresh isolated environment is empty, so probing it is pointless: every
    # third-party import is missing until we install it.
    probe_python: Path | None
    if not isolated:
        probe_python = Path(sys.executable)
    elif venv_exists:
        probe_python = project.python
    else:
        probe_python = None

    plan = build_plan(analysis, resolver, probe_python)

    console.title(script.name)
    console.blank()
    _summary(analysis, plan)

    if args.verbose:
        console.blank()
        console.hint(f"project:     {project.root}")
        console.hint(f"environment: {'current python' if not isolated else project.venv_dir}")
        for resolution in plan.resolutions.values():
            console.hint(f"{resolution.import_name}: {resolution.reason}")

    if args.dry_run:
        console.blank()
        console.field(console.cyan("~"), "Dry run", console.dim("nothing installed, nothing executed"))
        if plan.packages:
            console.blank()
            console.note("Would install:")
            for package in plan.packages:
                console.write(f"      {package}")
        else:
            console.blank()
            console.hint("Nothing to install.")
        return 0

    if isolated:
        if venv_exists:
            target_python, venv_dir = project.python, project.venv_dir
        else:
            try:
                target_python = _ensure_venv(project)
            except EnvProblem as exc:
                console.error(str(exc))
                if plan.packages:
                    console.hint("Re-run with --no-isolation to use the current environment.")
                return 1
            venv_dir = project.venv_dir
    else:
        target_python, venv_dir = Path(sys.executable), None

    if plan.packages:
        console.blank()
        noun = "package needs" if len(plan.packages) == 1 else "packages need"
        destination = "the current environment" if not isolated else f"{PROJECT_DIR}/venv"
        console.note(f"{len(plan.packages)} {noun} to be installed.")

        if not console.ask(f"Install into {destination}?", assume=True if args.yes else None):
            console.blank()
            console.hint("Nothing installed.")
            if plan.missing:
                console.hint(f"The script needs: {', '.join(plan.missing)}")
            return 1

        console.blank()
        try:
            installed = _install_packages(target_python, plan.packages, venv_dir, project, args.verbose)
        except (InstallError, EnvProblem) as exc:
            console.error(str(exc))
            return 1
        if not installed:
            return 1

    console.blank()
    console.field(console.cyan("i"), "Environment", console.dim(_python_label(target_python)))
    console.write(f"  {console.play_mark} {console.dim('Running')}")

    attempts: set[str] = set()
    retries = 0

    while True:
        try:
            result = run_script(target_python, script, args.script_args, venv=venv_dir)
        except KeyboardInterrupt:
            console.blank()
            return 130

        if result.stdout:
            _write_stream(result.stdout)

        if result.returncode == 0:
            if result.stderr:
                sys.stderr.write(result.stderr)
                sys.stderr.flush()
            return _finish(0, started)

        name = missing_module(result.stderr)

        if name is None:
            # Not a dependency problem: report the error, keep the noise down.
            _show_failure(result.stderr, verbose=args.verbose)
            return _finish(result.returncode, started)

        if name in attempts:
            console.error(f"{script.name} still cannot import {name} after installing it")
            return _finish(result.returncode, started)

        if name in local_module_names(script) or is_stdlib(name):
            _show_failure(result.stderr, verbose=args.verbose)
            return _finish(result.returncode, started)

        if retries >= args.max_retries:
            _show_failure(result.stderr, verbose=args.verbose)
            console.hint(f"Reached the retry limit ({args.max_retries}).")
            return _finish(result.returncode, started)

        resolution = resolver.resolve(name)
        _show_failure(result.stderr, verbose=args.verbose)

        console.blank()
        console.note("RunDeps can resolve this dependency.")
        console.blank()
        console.pairs([(name, resolution.package or name)])
        console.write(f"      {console.dim('confidence:')} {resolution.confidence.value}")

        if not resolution.installable:
            console.blank()
            console.note("Confidence is too low to install automatically.")
            console.blank()
            console.hint("Install manually:")
            console.hint(f"  rundeps install {resolution.package}")
            return _finish(result.returncode, started)

        console.blank()
        approved = console.ask(
            f"Install {resolution.package} and retry?",
            assume=True if args.yes and resolution.trusted else None,
        )
        if not approved:
            console.blank()
            console.hint("RunDeps stopped without changing anything.")
            console.hint(f"Tip: rundeps install {resolution.package}")
            return _finish(result.returncode, started)

        attempts.add(name)
        retries += 1
        console.blank()
        try:
            installed = _install_packages(target_python, [resolution.package or name], venv_dir, project, args.verbose)
        except (InstallError, EnvProblem) as exc:
            console.error(str(exc))
            return _finish(result.returncode, started)

        if not installed:
            return _finish(result.returncode, started)

        console.blank()
        console.write(f"  {console.play_mark} {console.dim(f'Retrying {script.name}')}")


def _python_label(python: Path) -> str:
    return f"Python {platform.python_version()} · {python}"


def _show_failure(stderr: str, *, verbose: bool) -> None:
    """One readable error block. The traceback is opt-in."""
    console.blank()
    console.write(f"  {console.bad_mark} {console.red('Process failed')}")
    console.blank()

    if verbose:
        for line in (stderr or "").rstrip().splitlines()[-40:]:
            console.hint(line)
        return

    lines = [line.strip() for line in (stderr or "").strip().splitlines() if line.strip()]
    detail = lines[-2:] if len(lines) >= 2 else lines

    for line in detail:
        # "ModuleNotFoundError: No module named 'x'" reads better split up.
        if ": " in line:
            kind, _, message = line.partition(": ")
            console.write(f"      {kind}")
            console.write(f"      {message}")
        else:
            console.write(f"      {line}")


def cmd_requirements(args: argparse.Namespace) -> int:
    script = Path(args.script)

    try:
        analysis = analyze(script)
    except AnalysisError as exc:
        console.error(str(exc))
        return 2

    project = Project.locate(script)
    resolver = build_resolver(project)
    python = args.interpreter or _visible_python(project)
    plan = build_plan(analysis, resolver, python)

    names = sorted(set(plan.found) | set(plan.missing), key=str.lower)
    resolutions = {name: resolver.resolve(name, analysis.module_for(name)) for name in names}

    recorded = load_state(project).get("packages") or {}
    lines: list[str] = []
    skipped: list[Resolution] = []

    for name in names:
        resolution = resolutions[name]
        if resolution.package is None or not resolution.installable:
            skipped.append(resolution)
            continue
        if args.freeze:
            version = recorded.get(resolution.package) or plan.found.get(name)
            lines.append(f"{resolution.package}=={version}" if version else resolution.package)
        else:
            lines.append(resolution.package)

    lines = sorted(dict.fromkeys(lines), key=str.lower)
    text = "".join(f"{line}\n" for line in lines)

    if args.stdout:
        sys.stdout.write(text)
        return 0

    target = Path(args.output) if args.output else script.parent / "requirements.txt"

    if args.dry_run:
        console.title("requirements")
        console.blank()
        console.hint(f"Would write {target}:")
        console.blank()
        sys.stdout.write(text)
        if skipped:
            console.hint(f"skipped {len(skipped)} unresolved import(s)")
        return 0

    target.write_text(text, encoding="utf-8")
    console.title("requirements")
    console.blank()
    console.ok(f"Wrote {target}")
    console.hint(f"{len(lines)} package(s)")
    for resolution in skipped:
        console.hint(f"unresolved: {resolution.import_name} (possible: {resolution.package})")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = Project(root)

    console.title("init")
    console.blank()

    project.dir.mkdir(exist_ok=True)
    console.ok(f"{PROJECT_DIR}/")

    if project.config_path.exists() and not args.force:
        console.hint(f"{PROJECT_DIR}/config.toml exists, left untouched")
    else:
        project.config_path.write_text(
            "# RunDeps project configuration.\n"
            "[rundeps]\n"
            "isolation = true\n"
            f"max_retries = {DEFAULT_MAX_RETRIES}\n",
            encoding="utf-8",
        )
        console.ok(f"{PROJECT_DIR}/config.toml")

    ignore_inside = project.dir / ".gitignore"
    if not ignore_inside.exists():
        ignore_inside.write_text("*\n!.gitignore\n", encoding="utf-8")
        console.ok(f"{PROJECT_DIR}/.gitignore")

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if not any(line.strip().rstrip("/") == PROJECT_DIR for line in existing.splitlines()):
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}{PROJECT_DIR}/\n")
        console.ok("Added .rundeps/ to .gitignore")

    console.blank()
    console.hint("Next: rundeps run <script>")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    project = Project.locate(Path.cwd())

    console.title("install")
    console.blank()

    if args.no_isolation:
        console.field(console.warn_mark, "Environment", "current python (less safe)")
        python, venv_dir = Path(sys.executable), None
    else:
        try:
            python = _ensure_venv(project)
        except EnvProblem as exc:
            console.error(str(exc))
            return 1
        venv_dir = project.venv_dir
        console.field(console.ok_mark, "Environment", str(project.venv_dir))

    console.blank()
    console.pairs([(name, "") for name in args.packages])

    if not console.ask(f"Install {len(args.packages)} package(s)?", assume=True if args.yes else None):
        console.hint("Nothing installed.")
        return 1

    console.blank()
    try:
        installed = _install_packages(python, args.packages, venv_dir, project, args.verbose)
    except (InstallError, EnvProblem) as exc:
        console.error(str(exc))
        return 1

    return 0 if len(installed) == len(args.packages) else 1


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def cmd_doctor(args: argparse.Namespace) -> int:
    console.title("doctor")
    console.blank()

    checks = [
        ("venv", _has_module("venv")),
        ("pip", _has_module("pip")),
        ("tomllib", _has_module("tomllib")),
        ("stdlib list", hasattr(sys, "stdlib_module_names")),
    ]
    healthy = all(ok for _, ok in checks[:2])

    console.field(console.ok_mark, "Python", f"{platform.python_version()} ({platform.python_implementation()})")
    console.field(console.ok_mark, "Platform", f"{platform.system()} {platform.release()}")
    console.blank()
    for label, available in checks:
        console.field(console.ok_mark if available else console.bad_mark, label,
                      "" if available else console.dim("missing"))
    console.blank()
    console.field(console.ok_mark, "Mappings", f"{len(load_import_map())} import-to-package rules")

    project = Project.locate(Path.cwd())
    console.blank()
    if project.initialised:
        console.field(console.ok_mark, "Project", str(project.root))
        console.field(console.ok_mark, "Environment",
                      "ready" if project.python.exists() else "not created yet")
    else:
        console.field(console.warn_mark, "Project", "not initialised (run: rundeps init)")

    console.blank()
    if healthy:
        console.hint("No blocking problems found.")
    else:
        console.hint("venv and pip are required.")
    return 0 if healthy else 1


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rundeps",
        description="Run Python without hunting for dependencies.",
    )
    parser.add_argument("--version", action="version", version=f"rundeps {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="resolve missing packages, then run a script")
    run_parser.add_argument("script", help="path to the .py file")
    run_parser.add_argument("--dry-run", action="store_true", help="show the plan without installing or running")
    run_parser.add_argument("--yes", "-y", action="store_true", help="approve high-confidence installs")
    run_parser.add_argument("--no-isolation", action="store_true", help="use the current environment (less safe)")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="show diagnostics and full tracebacks")
    run_parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        metavar="N",
        help=f"runtime dependency retries (default: {DEFAULT_MAX_RETRIES})",
    )
    run_parser.set_defaults(func=cmd_run, script_args=[])

    scan_parser = sub.add_parser("scan", help="report dependencies without changing anything")
    scan_parser.add_argument("script", help="path to the .py file")
    scan_parser.add_argument("--verbose", "-v", action="store_true")
    scan_parser.set_defaults(func=cmd_scan)

    req_parser = sub.add_parser("requirements", help="write a requirements.txt for a script")
    req_parser.add_argument("script", help="path to the .py file")
    req_parser.add_argument("--freeze", action="store_true", help="pin versions RunDeps recorded")
    req_parser.add_argument("-o", "--output", help="output path (default: next to the script)")
    req_parser.add_argument("--stdout", action="store_true", help="print instead of writing a file")
    req_parser.add_argument("--dry-run", action="store_true", help="show what would be written")
    req_parser.add_argument("--interpreter", type=Path, help=argparse.SUPPRESS)
    req_parser.set_defaults(func=cmd_requirements)

    init_parser = sub.add_parser("init", help="initialise RunDeps for a project")
    init_parser.add_argument("path", nargs="?", default=".", help="project directory (default: .)")
    init_parser.add_argument("--force", action="store_true", help="overwrite config.toml")
    init_parser.set_defaults(func=cmd_init)

    doctor_parser = sub.add_parser("doctor", help="check that this machine can run RunDeps")
    doctor_parser.add_argument("--no-isolation", action="store_true", help=argparse.SUPPRESS)
    doctor_parser.set_defaults(func=cmd_doctor)

    install_parser = sub.add_parser("install", help="install packages into the RunDeps environment")
    install_parser.add_argument("packages", nargs="+", help="PyPI package names")
    install_parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    install_parser.add_argument("--no-isolation", action="store_true", help="use the current environment")
    install_parser.add_argument("--verbose", "-v", action="store_true")
    install_parser.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # Everything after a bare -- belongs to the target script.
    script_args: list[str] = []
    if "--" in raw:
        index = raw.index("--")
        raw, script_args = raw[:index], raw[index + 1 :]

    parser = build_parser()
    args = parser.parse_args(raw)

    if hasattr(args, "script_args"):
        args.script_args = script_args
    elif script_args:
        parser.error("arguments after -- are only supported by 'rundeps run'")

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        console.blank()
        return 130
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
