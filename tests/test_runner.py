import sys
from pathlib import Path

import pytest

from rundeps.runner import missing_module, run_script


@pytest.fixture()
def script(tmp_path: Path) -> Path:
    path = tmp_path / "app.py"
    path.write_text(
        "import sys\n"
        "print('hello from app')\n"
        "print('args:', sys.argv[1:])\n"
        "print('cwd:', __import__('os').getcwd())\n",
        encoding="utf-8",
    )
    return path


def test_run_script_captures_stdout(script, tmp_path):
    result = run_script(Path(sys.executable), script, [], venv=None)

    assert result.returncode == 0
    assert "hello from app" in result.stdout
    assert result.stderr == ""


def test_run_script_passes_arguments_unchanged(script):
    args = ["--input", "in put.txt", "--mode", "fast"]

    result = run_script(Path(sys.executable), script, args, venv=None)

    assert "args: ['--input', 'in put.txt', '--mode', 'fast']" in result.stdout


def test_run_script_uses_script_directory_as_cwd(script, tmp_path):
    result = run_script(Path(sys.executable), script, [], venv=None)

    assert f"cwd: {tmp_path.resolve()}" in result.stdout


def test_exit_code_is_propagated(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")

    result = run_script(Path(sys.executable), script, [], venv=None)

    assert result.returncode == 7


def test_missing_module_is_extracted(tmp_path):
    script = tmp_path / "needs.py"
    script.write_text("import definitely_missing_module_xyz\n", encoding="utf-8")

    result = run_script(Path(sys.executable), script, [], venv=None)
    name = missing_module(result.stderr)

    assert result.returncode != 0
    assert name == "definitely_missing_module_xyz"


def test_missing_module_returns_top_level_name():
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "sub.py", line 1, in <module>\n'
        "    import google.protobuf.message\n"
        "ModuleNotFoundError: No module named 'google'\n"
    )

    assert missing_module(stderr) == "google"


def test_dotted_module_name_is_reduced_to_top_level():
    stderr = "ModuleNotFoundError: No module named 'google.protobuf.message'"

    assert missing_module(stderr) == "google"


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        "Traceback (most recent call last):\nValueError: nope\n",
        "KeyError: 'ModuleNotFoundError: No module named \\'x\\''",
    ],
)
def test_unrelated_errors_are_not_dependency_errors(stderr):
    assert missing_module(stderr) is None


def test_runtime_missing_module_inside_function(tmp_path):
    script = tmp_path / "late.py"
    script.write_text(
        "def load():\n    import definitely_missing_module_xyz\n\nload()\n",
        encoding="utf-8",
    )

    result = run_script(Path(sys.executable), script, [], venv=None)

    assert missing_module(result.stderr) == "definitely_missing_module_xyz"
