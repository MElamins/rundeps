"""Command line interface."""

from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
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
    def has_missing(self) -> bool:
        return bool(self.missing)


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


def build_plan(analysis: Analysis, python: Path, resolver: Resolver) -> Plan:
    plan = Plan(analysis=analysis)
    wanted = analysis.third_party
    if not wanted:
        return plan

    resolved = {name: resolver.resolve(name, analysis.module_for(name)) for name in wanted}
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
    console.write()
    console.write("Creating isolated environment...")
    python = create_venv(project.venv_dir)
    console.ok("Environment ready", str(project.venv_dir))
    return python


def _print_imports(plan: Plan) -> None:
    analysis = plan.analysis
    console.heading("Imports found")
    if not analysis.imports:
        console.plain(console.dim("none"))
        return

    stdlib = [record.name for record in analysis.imports if record.kind.value == "stdlib"]
    local = [record.name for record in analysis.imports if record.kind.value == "local"]

    for record in analysis.imports:
        if record.kind.value == "stdlib":
            console.item(console.ok_mark, record.name, "standard library")
        elif record.kind.value == "local":
            console.item(console.ok_mark, record.name, "local")
        elif record.name in plan.found:
            version = plan.found[record.name]
            console.item(console.ok_mark, record.name, f"installed {version}" if version else "installed")
        else:
            console.item(console.bad_mark, record.name, "missing")

    if stdlib:
        console.detail(f"{len(stdlib)} standard library import(s)")
    if local:
        console.detail(f"{len(local)} local import(s)")


def _print_resolution(plan: Plan) -> None:
    if plan.resolutions:
        console.heading("Resolving missing imports")
        width = max(len(name) for name in plan.resolutions)
        for name, resolution in plan.resolutions.items():
            console.plain(f"{name:<{width}}  →  {resolution.package}")

    if plan.unknown:
        console.heading("Could not confidently resolve")
        for resolution in plan.unknown:
            console.item(console.warn_mark, resolution.import_name)
            console.plain(console.dim(f"possible package: {resolution.package}  (low confidence)"))
        console.write()
        console.hint("RunDeps will not install these automatically.")
        console.hint("If you know the package, install it explicitly and rerun:")
        for resolution in plan.unknown:
            console.hint(f"  rundeps install {resolution.package}")


def _install_packages(
    python: Path,
    packages: list[str],
    venv_dir: Path | None,
    project: Project,
    verbose: bool,
) -> list[str]:
    require_pip(python, venv=venv_dir)
    result = install(python, packages, venv=venv_dir, verbose=verbose)

    for name in result.ok:
        console.ok(f"Installed {name}")
    for name, detail in result.failed.items():
        console.error(f"could not install {name}")
        for line in detail.splitlines()[-6:]:
            console.hint(line)

    if result.ok and project.initialised:
        try:
            status = probe(python, [(name, name) for name in result.ok])
        except EnvProblem:
            status = {}
        record_packages(project, {name: (status.get(name) or {}).get("version") for name in result.ok})

    return list(result.ok)


def _write_stream(text: str) -> None:
    if not text:
        return
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _report_exit(code: int) -> int:
    console.write()
    if code == 0:
        console.write(console.green("Process finished successfully."))
    else:
        console.write(console.red(f"Process exited with code {code}."))
    return code


def _list_or_none(names) -> None:
    names = list(names)
    if not names:
        console.plain(console.dim("none"))
    for name in names:
        console.plain(name)


# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> int:
    script = Path(args.script)
    project = Project.locate(script)

    try:
        analysis = analyze(script)
    except AnalysisError as exc:
        console.error(str(exc))
        return 2

    console.banner()
    console.heading("Script")
    console.plain(str(script))

    python = _visible_python(project)
    plan = build_plan(analysis, python, build_resolver(project))

    console.heading("Standard library")
    _list_or_none(plan.analysis.stdlib)
    console.heading("Local")
    _list_or_none(plan.analysis.local)
    console.heading("Installed")
    _list_or_none(sorted(plan.found, key=str.lower))
    console.heading("Missing")
    _list_or_none(plan.missing)

    if plan.resolutions:
        console.heading("Resolved packages")
        width = max(len(name) for name in plan.resolutions)
        for name, resolution in plan.resolutions.items():
            console.plain(f"{name:<{width}}  →  {resolution.package}")

    console.heading("Unknown")
    _list_or_none([item.import_name for item in plan.unknown])

    console.write()
    console.detail(f"Interpreter: {python}")
    console.write("No files changed. No packages installed.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    script = Path(args.script)
    project = Project.locate(script)

    console.banner()
    console.write(f"Scanning {script.name}...")

    try:
        analysis = analyze(script)
    except AnalysisError as exc:
        console.error(str(exc))
        return 2

    resolver = build_resolver(project)
    probe_python = Path(sys.executable) if args.no_isolation else _visible_python(project)
    plan = build_plan(analysis, probe_python, resolver)

    _print_imports(plan)
    _print_resolution(plan)

    console.write()
    if plan.has_missing:
        console.warn(f"{len(plan.missing)} missing {'dependency' if len(plan.missing) == 1 else 'dependencies'}")
    else:
        console.ok("No missing dependencies")

    if args.no_isolation:
        console.write()
        console.warn("Isolation is off", "packages would go into your current environment")

    if args.verbose:
        console.write()
        console.detail(f"interpreter: {probe_python}")
        console.detail(f"project:     {project.root}")
        console.detail(f"environment: {'current python' if args.no_isolation else project.venv_dir}")
        for resolution in plan.resolutions.values():
            console.detail(f"{resolution.import_name}: {resolution.reason}")

    if args.dry_run:
        console.heading("Dry run: nothing will be installed or executed")
        if plan.packages:
            console.plain("Would install:")
            for package in plan.packages:
                console.plain(f"  {package}")
        else:
            console.plain("Nothing to install.")
        if plan.unknown:
            console.write()
            console.plain("Would skip (low confidence):")
            for resolution in plan.unknown:
                console.plain(f"  {resolution.import_name}  (possible: {resolution.package})")
        return 0

    target_python = probe_python
    venv_dir = None
    if not args.no_isolation and project.python.exists():
        venv_dir = project.venv_dir

    install_list = plan.packages

    if install_list and not args.no_isolation:
        try:
            target_python = _ensure_venv(project)
        except EnvProblem as exc:
            console.error(str(exc))
            console.hint("Re-run with --no-isolation to use the current environment.")
            return 1
        venv_dir = project.venv_dir

        if target_python != probe_python:
            # A fresh environment has none of the script's dependencies yet,
            # so the authoritative plan is the one for that interpreter.
            plan = build_plan(analysis, target_python, resolver)
            install_list = plan.packages

    if install_list:
        console.heading(f"Install {len(install_list)} package(s)")
        for package in install_list:
            console.plain(package)
        console.write()
        if not console.ask("Proceed?", assume=True if args.yes else None):
            console.write()
            console.hint("Nothing installed.")
            if plan.missing:
                console.hint(f"The script needs: {', '.join(plan.missing)}")
            return 1
        console.write()
        try:
            installed = _install_packages(target_python, install_list, venv_dir, project, args.verbose)
        except (InstallError, EnvProblem) as exc:
            console.error(str(exc))
            return 1
        if not installed:
            return 1

    console.write()
    console.write(f"Running {script.name}")
    console.rule()

    attempts: set[str] = set()
    retries = 0

    while True:
        try:
            result = run_script(target_python, script, args.script_args, venv=venv_dir)
        except KeyboardInterrupt:
            console.write()
            return 130

        _write_stream(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
            sys.stderr.flush()

        if result.returncode == 0:
            return _report_exit(0)

        name = missing_module(result.stderr)
        if name is None:
            return _report_exit(result.returncode)

        if name in attempts:
            console.error(f"{script.name} still cannot import {name} after installing it")
            return result.returncode

        if name in local_module_names(script) or is_stdlib(name):
            # A broken import inside the project is not a packaging problem.
            return _report_exit(result.returncode)

        if retries >= args.max_retries:
            console.write()
            console.hint(f"Reached the retry limit ({args.max_retries}).")
            return result.returncode

        resolution = resolver.resolve(name)
        console.write()
        console.write(console.warn_mark + " RunDeps detected a missing runtime dependency.")
        console.plain(f"import:      {name}")
        console.plain(f"package:     {resolution.package}")
        console.plain(f"confidence:  {resolution.confidence.value}")
        console.plain(f"evidence:    {resolution.reason}")

        if not resolution.installable:
            console.write()
            console.hint("Confidence is too low to install automatically.")
            console.hint(f"If you know the package: rundeps install {resolution.package}")
            return result.returncode

        approved = console.ask(
            f"Install {resolution.package} and retry?",
            assume=True if args.yes and resolution.trusted else None,
        )
        if not approved:
            return result.returncode

        attempts.add(name)
        retries += 1
        try:
            installed = _install_packages(target_python, [resolution.package or name], venv_dir, project, args.verbose)
        except (InstallError, EnvProblem) as exc:
            console.error(str(exc))
            return result.returncode

        if not installed:
            return result.returncode

        console.write()
        console.write(f"Retrying {script.name}")
        console.rule()


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
    plan = build_plan(analysis, python, resolver)

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
        console.banner()
        console.plain(f"Would write {target}:")
        console.write()
        sys.stdout.write(text)
        if skipped:
            console.hint(f"skipped {len(skipped)} unresolved import(s)")
        return 0

    target.write_text(text, encoding="utf-8")
    console.banner()
    console.ok(f"Wrote {target}", f"{len(lines)} package(s)")
    for resolution in skipped:
        console.warn(resolution.import_name, f"unresolved, possible: {resolution.package}")
    if not args.freeze:
        console.hint("Use --freeze to pin versions RunDeps recorded.")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = Project(root)

    console.banner()
    project.dir.mkdir(exist_ok=True)
    console.write(f"Created {PROJECT_DIR}/")

    if project.config_path.exists() and not args.force:
        console.hint(f"{PROJECT_DIR}/config.toml already exists, left untouched")
    else:
        project.config_path.write_text(
            "# RunDeps project configuration.\n"
            "[rundeps]\n"
            "isolation = true\n"
            f"max_retries = {DEFAULT_MAX_RETRIES}\n",
            encoding="utf-8",
        )
        console.write(f"Created {PROJECT_DIR}/config.toml")

    ignore_inside = project.dir / ".gitignore"
    if not ignore_inside.exists():
        ignore_inside.write_text("*\n!.gitignore\n", encoding="utf-8")
        console.write(f"Created {PROJECT_DIR}/.gitignore")

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if not any(line.strip().rstrip("/") == PROJECT_DIR for line in existing.splitlines()):
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}{PROJECT_DIR}/\n")
        console.write("Added .rundeps/ to .gitignore")

    console.write()
    console.ok("Ready", "rundeps run <script>")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    project = Project.locate(Path.cwd())
    console.banner()

    if args.no_isolation:
        console.warn("Installing into the current environment", "less safe")
        python, venv_dir = Path(sys.executable), None
    else:
        try:
            python = _ensure_venv(project)
        except EnvProblem as exc:
            console.error(str(exc))
            return 1
        venv_dir = project.venv_dir

    console.plain("Packages: " + ", ".join(args.packages))
    console.write()
    if not console.ask(f"Install {len(args.packages)} package(s)?", assume=True if args.yes else None):
        console.hint("Nothing installed.")
        return 1

    console.write()
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
    console.banner()

    console.heading("Interpreter")
    console.plain(f"executable:  {sys.executable}")
    console.plain(f"version:     {platform.python_version()} ({platform.python_implementation()})")
    console.plain(f"platform:    {platform.system()} {platform.release()}")

    console.heading("Capabilities")
    checks = [
        ("venv module", _has_module("venv")),
        ("pip module", _has_module("pip")),
        ("tomllib (config parsing)", _has_module("tomllib")),
        ("stdlib module list", hasattr(sys, "stdlib_module_names")),
    ]
    for label, available in checks:
        console.item(console.ok_mark if available else console.bad_mark, label)

    console.heading("Mapping data")
    console.plain(f"{len(load_import_map())} known import-to-package mappings")

    console.heading("Project")
    project = Project.locate(Path.cwd() / ".")
    console.plain(f"root:        {project.root}")
    if project.initialised:
        console.item(console.ok_mark, f"{PROJECT_DIR}/", "initialised")
        console.plain(f"environment: {'ready' if project.python.exists() else 'not created yet'}")
        if project.python.exists():
            console.plain(f"interpreter: {project.python}")
    else:
        console.item(console.warn_mark, f"{PROJECT_DIR}/", "not initialised (run: rundeps init)")

    console.heading("Install target")
    if args.no_isolation:
        console.item(console.warn_mark, "current environment", "--no-isolation requested")
    else:
        console.item(console.ok_mark, "project-local virtual environment", "default")

    healthy = all(available for _, available in checks[:2])
    console.write()
    console.write("No blocking problems found." if healthy else "At least one required capability is missing.")
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
    run_parser.add_argument("--verbose", "-v", action="store_true", help="show diagnostic detail")
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
        console.write()
        return 130
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
