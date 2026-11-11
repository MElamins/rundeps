import json
from pathlib import Path

import pytest

from rundeps.cli import main


@pytest.fixture()
def plain_script(tmp_path: Path) -> Path:
    path = tmp_path / "hello.py"
    path.write_text("import json\nimport os\nprint('hi', json.dumps({'ok': True}))\n", encoding="utf-8")
    return path


@pytest.fixture()
def yaml_script(tmp_path: Path) -> Path:
    path = tmp_path / "uses_yaml.py"
    path.write_text("import os\nimport yaml\nprint(yaml.safe_load('a: 1'))\n", encoding="utf-8")
    return path


def test_scan_reports_categories(plain_script, capsys):
    assert main(["scan", str(plain_script)]) == 0
    out = capsys.readouterr().out

    assert "Standard library" in out
    assert "json" in out
    assert "Missing" in out
    assert "No files changed. No packages installed." in out


def test_scan_resolves_mismatched_import_name(yaml_script, capsys):
    assert main(["scan", str(yaml_script)]) == 0
    out = capsys.readouterr().out

    assert "PyYAML" in out
    assert "yaml" in out


def test_scan_marks_unknown_imports(monkeypatch, tmp_path, capsys):
    script = tmp_path / "weird.py"
    script.write_text("import something_weird\n", encoding="utf-8")

    assert main(["scan", str(script)]) == 0
    out = capsys.readouterr().out

    assert "Unknown" in out
    assert "something_weird" in out


def test_scan_does_not_create_project_files(plain_script):
    main(["scan", str(plain_script)])

    assert not (plain_script.parent / ".rundeps").exists()


def test_scan_rejects_missing_file(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "nope.py")]) == 2
    assert "no such file" in capsys.readouterr().out


def test_scan_reports_syntax_error(tmp_path, capsys):
    script = tmp_path / "broken.py"
    script.write_text("def x(:\n", encoding="utf-8")

    assert main(["scan", str(script)]) == 2
    assert "syntax error" in capsys.readouterr().out


def test_requirements_writes_only_script_dependencies(yaml_script, tmp_path):
    target = tmp_path / "reqs.txt"

    assert main(["requirements", str(yaml_script), "-o", str(target)]) == 0
    content = target.read_text(encoding="utf-8")

    assert "PyYAML" in content
    assert "os" not in content


def test_requirements_stdout_is_machine_readable(yaml_script, capsys):
    assert main(["requirements", str(yaml_script), "--stdout"]) == 0

    assert capsys.readouterr().out.strip() == "PyYAML"


def test_requirements_freeze_uses_recorded_versions(yaml_script, tmp_path):
    project = yaml_script.parent / ".rundeps"
    project.mkdir()
    (project / "state.json").write_text(json.dumps({"packages": {"PyYAML": "6.0.1"}}), encoding="utf-8")
    target = tmp_path / "pinned.txt"

    assert main(["requirements", str(yaml_script), "--freeze", "-o", str(target)]) == 0

    assert target.read_text(encoding="utf-8").strip() == "PyYAML==6.0.1"


def test_requirements_dry_run_writes_nothing(yaml_script, tmp_path):
    target = tmp_path / "never.txt"

    assert main(["requirements", str(yaml_script), "--dry-run", "-o", str(target)]) == 0

    assert not target.exists()


def test_dry_run_skips_install_and_execution(tmp_path, capsys):
    marker = tmp_path / "executed.marker"
    script = tmp_path / "writes.py"
    script.write_text(
        f"import yaml\nopen({str(marker)!r}, 'w').write('ran')\n",
        encoding="utf-8",
    )

    assert main(["run", str(script), "--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "Dry run" in out
    assert "PyYAML" in out
    assert not marker.exists()
    assert not (tmp_path / ".rundeps" / "venv").exists()


def test_dry_run_never_calls_pip(monkeypatch, tmp_path):
    def explode(*args, **kwargs):
        raise AssertionError("pip must not run during --dry-run")

    monkeypatch.setattr("rundeps.cli.install", explode)
    script = tmp_path / "needs_yaml.py"
    script.write_text("import yaml\n", encoding="utf-8")

    assert main(["run", str(script), "--dry-run"]) == 0


def test_unknown_import_is_not_installed_even_with_yes(monkeypatch, tmp_path, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("low-confidence packages must never be installed")

    monkeypatch.setattr("rundeps.cli.install", explode)
    monkeypatch.setattr("rundeps.cli._ensure_venv", explode)

    script = tmp_path / "weird.py"
    script.write_text("import something_weird\n", encoding="utf-8")

    code = main(["run", str(script), "--yes", "--no-isolation"])
    out = capsys.readouterr().out

    assert code != 0
    assert "low confidence" in out.lower() or "too low" in out.lower()


def test_run_passes_arguments_after_separator(monkeypatch, tmp_path):
    output = tmp_path / "args.json"
    script = tmp_path / "echo_args.py"
    script.write_text(
        "import json, sys\n"
        f"json.dump(sys.argv[1:], open({str(output)!r}, 'w'))\n",
        encoding="utf-8",
    )

    code = main(["run", str(script), "--no-isolation", "--", "--flag", "value with space"])

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == ["--flag", "value with space"]


def test_run_propagates_exit_code(tmp_path):
    script = tmp_path / "exits.py"
    script.write_text("import sys\nsys.exit(4)\n", encoding="utf-8")

    assert main(["run", str(script), "--no-isolation"]) == 4


def test_run_reports_success(tmp_path, capsys):
    script = tmp_path / "ok.py"
    script.write_text("print('done')\n", encoding="utf-8")

    assert main(["run", str(script), "--no-isolation"]) == 0
    out = capsys.readouterr().out

    assert "done" in out
    assert "Process finished successfully." in out


def test_run_does_not_modify_the_script(yaml_script, tmp_path):
    before = yaml_script.read_bytes()

    main(["run", str(yaml_script), "--dry-run"])

    assert yaml_script.read_bytes() == before


def test_init_creates_config_and_gitignore(tmp_path):
    assert main(["init", str(tmp_path)]) == 0

    config = tmp_path / ".rundeps" / "config.toml"
    assert config.is_file()
    assert "[rundeps]" in config.read_text(encoding="utf-8")
    assert ".rundeps/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_init_is_idempotent(tmp_path):
    main(["init", str(tmp_path)])
    config = tmp_path / ".rundeps" / "config.toml"
    config.write_text("[rundeps]\nmax_retries = 9\n", encoding="utf-8")
    gitignore = tmp_path / ".gitignore"

    assert main(["init", str(tmp_path)]) == 0

    assert "max_retries = 9" in config.read_text(encoding="utf-8")
    assert gitignore.read_text(encoding="utf-8").count(".rundeps") == 1


def test_doctor_runs(tmp_path, capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out

    assert "Interpreter" in out
    assert "venv" in out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert "rundeps" in capsys.readouterr().out


def test_script_args_rejected_for_scan(plain_script):
    with pytest.raises(SystemExit):
        main(["scan", str(plain_script), "--", "extra"])
