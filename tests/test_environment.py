import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from rundeps.environment import (
    EnvProblem,
    Project,
    create_venv,
    load_config,
    load_state,
    probe,
    record_packages,
    venv_python,
)


def test_venv_python_path_shape():
    path = venv_python(Path("/tmp/project/.rundeps/venv"))

    if sys.platform == "win32":
        assert path.as_posix().endswith("Scripts/python.exe")
    else:
        assert path.as_posix().endswith("bin/python")


def test_project_locate_walks_up_to_marker(tmp_path):
    (tmp_path / ".rundeps").mkdir()
    nested = tmp_path / "pkg" / "deep"
    nested.mkdir(parents=True)
    script = nested / "run.py"
    script.write_text("", encoding="utf-8")

    assert Project.locate(script).root == tmp_path


def test_project_locate_falls_back_to_script_folder(tmp_path):
    script = tmp_path / "run.py"
    script.write_text("", encoding="utf-8")

    project = Project.locate(script)

    assert project.root == tmp_path
    assert not project.initialised


def test_create_venv_produces_a_working_interpreter(tmp_path):
    """Uses venv.create directly so the test never needs the network."""
    target = tmp_path / "venv"
    venv.create(target, with_pip=False, clear=True)

    python = venv_python(target)
    assert python.exists()

    proc = subprocess.run([str(python), "-c", "print('ok')"], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "ok"


def test_create_venv_helper_creates_interpreter(tmp_path):
    python = create_venv(tmp_path / "venv")

    assert python.exists()
    proc = subprocess.run([str(python), "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert str(tmp_path.resolve()) in proc.stdout


def test_probe_reports_missing_and_present_modules():
    status = probe(Path(sys.executable), [("json", "json"), ("definitely_not_a_module_xyz", "")])

    assert status["json"]["found"] is True
    assert status["definitely_not_a_module_xyz"]["found"] is False


def test_probe_returns_empty_for_no_entries():
    assert probe(Path(sys.executable), []) == {}


def test_probe_raises_for_unusable_interpreter(tmp_path):
    fake = tmp_path / "not-python"
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)

    with pytest.raises(EnvProblem):
        probe(fake, [("json", "")])


def test_record_packages_writes_state(tmp_path):
    project = Project(tmp_path)
    project.dir.mkdir()
    record_packages(project, {"Pillow": "10.0.0"})
    record_packages(project, {"PyYAML": None})

    state = json.loads(project.state_path.read_text(encoding="utf-8"))

    assert state["packages"]["Pillow"] == "10.0.0"
    assert state["packages"]["PyYAML"] == ""
    assert load_state(project)["packages"]["Pillow"] == "10.0.0"


def test_load_config_reads_section(tmp_path):
    project = Project(tmp_path)
    project.dir.mkdir()
    project.config_path.write_text(
        '[rundeps]\nisolation = true\nmax_retries = 5\n\n[mappings]\nbs4 = "internal-bs4"\n',
        encoding="utf-8",
    )

    config = load_config(project)

    assert config["isolation"] is True
    assert config["max_retries"] == 5
    assert config["mappings"] == {"bs4": "internal-bs4"}


def test_load_config_without_file_is_empty(tmp_path):
    assert load_config(Project(tmp_path)) == {}


def test_load_state_survives_corrupt_json(tmp_path):
    project = Project(tmp_path)
    project.dir.mkdir()
    project.state_path.write_text("{not json", encoding="utf-8")

    assert load_state(project) == {}
