from pathlib import Path

import pytest

from rundeps.analyzer import AnalysisError, analyze, is_stdlib, local_module_names


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_stdlib_imports(tmp_path):
    script = write(tmp_path, "a.py", "import os\nimport json\nimport pathlib\n")
    analysis = analyze(script)

    assert analysis.stdlib == ["json", "os", "pathlib"]
    assert analysis.third_party == []
    assert all(record.kind.value == "stdlib" for record in analysis.imports)


def test_third_party_imports(tmp_path):
    script = write(
        tmp_path,
        "b.py",
        "import requests\nimport pandas as pd\nfrom PIL import Image\n"
        "from bs4 import BeautifulSoup\nfrom sklearn.model_selection import train_test_split\n",
    )
    analysis = analyze(script)

    assert sorted(analysis.third_party) == ["PIL", "bs4", "pandas", "requests", "sklearn"]


def test_local_module_is_not_third_party(tmp_path):
    write(tmp_path, "utils.py", "VALUE = 1\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    script = write(tmp_path, "c.py", "import utils\nimport pkg\nimport requests\n")

    analysis = analyze(script)

    assert analysis.local == ["pkg", "utils"]
    assert analysis.third_party == ["requests"]


def test_local_package_shadows_stdlib_name(tmp_path):
    write(tmp_path, "json.py", "")
    script = write(tmp_path, "d.py", "import json\n")

    assert analyze(script).local == ["json"]


def test_relative_imports_are_ignored(tmp_path):
    script = write(tmp_path, "e.py", "from .utils import thing\nfrom .. import other\n")

    analysis = analyze(script)

    assert analysis.imports == []


def test_duplicate_imports_collapse(tmp_path):
    script = write(
        tmp_path,
        "f.py",
        "import requests\nimport requests\nfrom requests import get\nimport requests.sessions\n",
    )
    analysis = analyze(script)

    assert analysis.third_party == ["requests"]
    assert len(analysis.imports) == 1
    assert analysis.imports[0].lineno == 1


def test_aliases_keep_the_import_name(tmp_path):
    script = write(tmp_path, "g.py", "import numpy as np\nfrom collections import OrderedDict as OD\n")
    analysis = analyze(script)

    assert analysis.third_party == ["numpy"]
    assert analysis.stdlib == ["collections"]


def test_imports_inside_functions_are_found(tmp_path):
    script = write(
        tmp_path,
        "h.py",
        "def load():\n    import yaml\n    return yaml.safe_load('{}')\n",
    )

    assert analyze(script).third_party == ["yaml"]


def test_dotted_import_records_full_module(tmp_path):
    script = write(tmp_path, "i.py", "from google.protobuf import message\n")
    analysis = analyze(script)

    assert analysis.third_party == ["google"]
    assert analysis.module_for("google") == "google.protobuf"


def test_syntax_error_is_reported(tmp_path):
    script = write(tmp_path, "j.py", "def broken(:\n    pass\n")

    with pytest.raises(AnalysisError, match="syntax error"):
        analyze(script)


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(AnalysisError, match="no such file"):
        analyze(tmp_path / "nope.py")


def test_non_python_file_is_rejected(tmp_path):
    path = write(tmp_path, "notes.txt", "hello\n")

    with pytest.raises(AnalysisError, match="expected a .py file"):
        analyze(path)


def test_encoding_cookie_is_respected(tmp_path):
    path = tmp_path / "k.py"
    path.write_bytes("# -*- coding: latin-1 -*-\n# caf\xe9\nimport requests\n".encode("latin-1"))

    assert analyze(path).third_party == ["requests"]


def test_is_stdlib():
    assert is_stdlib("os")
    assert is_stdlib("asyncio")
    assert not is_stdlib("requests")
    assert not is_stdlib("PIL")


def test_local_module_names_includes_script_stem(tmp_path):
    script = write(tmp_path, "solo.py", "")

    assert "solo" in local_module_names(script)
