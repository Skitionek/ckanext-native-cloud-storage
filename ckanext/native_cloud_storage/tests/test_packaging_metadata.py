"""Regression checks that guard against packaging metadata drift.

`pyproject.toml` is the single source of truth for this package's
dependency and Python/CKAN support policy (see INSTALL.md). These tests
fail if:

  * the package can no longer be built / installed cleanly, or
  * `twine check` finds the built metadata invalid, or
  * the documented CKAN/Python support policy (INSTALL.md) drifts from
    `pyproject.toml`, or
  * conflicting version constraints exist between `pyproject.toml` and
    `requirements.txt`.

To update the support policy: bump the floors in `pyproject.toml`
`[project].dependencies` (the `ckan>=...` entry) and
`[project].requires-python`, then update the matching prerequisite lines
in `INSTALL.md`. Nothing else needs to change -- there is no setup.py.
"""

import re
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
INSTALL_MD = REPO_ROOT / "INSTALL.md"
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"


def _load_pyproject():
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)


def _ckan_floor_from_dependencies(dependencies):
    for dep in dependencies:
        match = re.match(r"^ckan\s*>=\s*([0-9][0-9A-Za-z.\-]*)", dep)
        if match:
            return match.group(1)
    return None


def test_pyproject_declares_ckan_and_python_floor():
    """pyproject.toml must declare both a CKAN floor and requires-python."""
    data = _load_pyproject()
    project = data["project"]

    requires_python = project.get("requires-python")
    assert requires_python, "pyproject.toml [project] must set requires-python"

    ckan_floor = _ckan_floor_from_dependencies(project.get("dependencies", []))
    assert ckan_floor, (
        "pyproject.toml [project].dependencies must pin a 'ckan>=X.Y.Z' floor"
    )


def test_install_md_matches_pyproject_support_policy():
    """INSTALL.md's documented CKAN/Python prerequisites must match pyproject.toml."""
    data = _load_pyproject()
    project = data["project"]

    ckan_floor = _ckan_floor_from_dependencies(project.get("dependencies", []))
    requires_python = project["requires-python"]
    py_floor_match = re.search(r">=\s*([0-9]+\.[0-9]+)", requires_python)
    assert py_floor_match, f"Unexpected requires-python format: {requires_python!r}"
    py_floor = py_floor_match.group(1)

    install_text = INSTALL_MD.read_text()

    assert f"CKAN {ckan_floor}+" in install_text, (
        f"INSTALL.md prerequisites must say 'CKAN {ckan_floor}+' to match "
        f"pyproject.toml's ckan>={ckan_floor} floor; update INSTALL.md or "
        "pyproject.toml's dependencies so they agree."
    )
    assert f"Python {py_floor}+" in install_text, (
        f"INSTALL.md prerequisites must say 'Python {py_floor}+' to match "
        f"pyproject.toml's requires-python={requires_python}; update "
        "INSTALL.md or pyproject.toml so they agree."
    )


def test_requirements_txt_does_not_conflict_with_pyproject():
    """requirements.txt must not pin a CKAN/Python floor that disagrees with pyproject.toml."""
    if not REQUIREMENTS_TXT.exists():
        pytest.skip("no requirements.txt present")

    data = _load_pyproject()
    ckan_floor = _ckan_floor_from_dependencies(data["project"].get("dependencies", []))

    req_text = REQUIREMENTS_TXT.read_text()
    req_ckan_matches = re.findall(r"^ckan\s*>=\s*([0-9][0-9A-Za-z.\-]*)", req_text, re.M)

    for req_floor in req_ckan_matches:
        assert req_floor == ckan_floor, (
            f"requirements.txt pins ckan>={req_floor} but pyproject.toml pins "
            f"ckan>={ckan_floor}; these must match (pyproject.toml is authoritative)."
        )


@pytest.mark.slow
def test_package_builds_and_passes_twine_check():
    """`python -m build --sdist` must succeed and `twine check` must pass on the result."""
    for tool in ("build", "twine"):
        if subprocess.run(
            [sys.executable, "-c", f"import {tool}"], capture_output=True
        ).returncode != 0:
            pytest.skip(f"'{tool}' is not installed in this environment")

    with tempfile.TemporaryDirectory() as tmpdir:
        build_result = subprocess.run(
            [sys.executable, "-m", "build", "--sdist", "--outdir", tmpdir],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert build_result.returncode == 0, (
            "python -m build --sdist failed:\n"
            f"stdout:\n{build_result.stdout}\nstderr:\n{build_result.stderr}"
        )

        sdists = list(Path(tmpdir).glob("*.tar.gz"))
        assert sdists, "python -m build did not produce an sdist"

        twine_result = subprocess.run(
            [sys.executable, "-m", "twine", "check", str(sdists[0])],
            capture_output=True,
            text=True,
        )
        assert twine_result.returncode == 0, (
            "twine check failed:\n"
            f"stdout:\n{twine_result.stdout}\nstderr:\n{twine_result.stderr}"
        )
