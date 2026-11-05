"""A source file is tested when a test module imports it.

The review rows used to look only for ``test_<stem>.py`` and counted documents
as untested source, so most of a plan's test-coverage row was noise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentscaffold.review.test_presence import (
    graph_has_test_importer,
    is_test_path,
    module_name,
    source_has_tests,
)
from agentscaffold.review.verify import VerificationItem, _check_test_delta


def _package(root: Path) -> None:
    pkg = root / "src" / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "sub" / "__init__.py").write_text("")
    (pkg / "mod_a.py").write_text("def f():\n    return 1\n")
    (pkg / "sub" / "mod_b.py").write_text("def g():\n    return 2\n")
    (root / "tests").mkdir()


def _write_test(root: Path, name: str, body: str) -> None:
    (root / "tests" / name).write_text(body)


def _has_tests(root: Path, fpath: str) -> bool:
    with patch("agentscaffold.review.test_presence.ql", return_value=[]):
        return source_has_tests(MagicMock(), fpath, root=root)


# ---------------------------------------------------------------------------
# Module names
# ---------------------------------------------------------------------------


def test_module_name_walks_packages_above_src(tmp_path: Path) -> None:
    _package(tmp_path)
    assert module_name(tmp_path, "src/pkg/mod_a.py") == "pkg.mod_a"
    assert module_name(tmp_path, "src/pkg/sub/mod_b.py") == "pkg.sub.mod_b"
    assert module_name(tmp_path, "src/pkg/sub/__init__.py") == "pkg.sub"


def test_module_name_top_level_script(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text("")
    assert module_name(tmp_path, "scripts/tool.py") == "tool"


def test_module_name_non_python_is_none(tmp_path: Path) -> None:
    assert module_name(tmp_path, "src/pkg/view.ts") is None


def test_module_name_repo_path(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    lib = tmp_path / "libs" / "shared"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text("")
    (lib / "util.py").write_text("")
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    assert module_name(project, "@repo/libs/shared/util.py") == "shared.util"


# ---------------------------------------------------------------------------
# Disk: test modules that import the source module
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "from pkg.mod_a import f\n",
        "from pkg import mod_a\n",
        "import pkg.mod_a as m\n",
        "from pkg.mod_a import (\n    f,\n)\n",
        "def test_x():\n    from pkg.mod_a import f\n    assert f() == 1\n",
    ],
)
def test_differently_named_test_module_counts(tmp_path: Path, body: str) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "test_feature_283.py", body)
    assert _has_tests(tmp_path, "src/pkg/mod_a.py")


def test_import_of_another_module_does_not_count(tmp_path: Path) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "test_other.py", "from pkg.sub.mod_b import g\n")
    assert not _has_tests(tmp_path, "src/pkg/mod_a.py")
    assert _has_tests(tmp_path, "src/pkg/sub/mod_b.py")


def test_importing_the_package_does_not_cover_its_modules(tmp_path: Path) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "test_pkg.py", "import pkg\n")
    assert not _has_tests(tmp_path, "src/pkg/mod_a.py")


def test_helper_module_in_tests_does_not_count(tmp_path: Path) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "helpers.py", "from pkg.mod_a import f\n")
    _write_test(tmp_path, "conftest.py", "from pkg.mod_a import f\n")
    assert not _has_tests(tmp_path, "src/pkg/mod_a.py")


def test_unparseable_test_module_is_skipped(tmp_path: Path) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "test_broken.py", "def broken(:\n")
    _write_test(tmp_path, "test_good.py", "from pkg import mod_a\n")
    assert _has_tests(tmp_path, "src/pkg/mod_a.py")


def test_new_test_module_is_seen_after_a_previous_call(tmp_path: Path) -> None:
    _package(tmp_path)
    assert not _has_tests(tmp_path, "src/pkg/mod_a.py")
    _write_test(tmp_path, "test_late.py", "from pkg.mod_a import f\n")
    assert _has_tests(tmp_path, "src/pkg/mod_a.py")


def test_stem_match_still_counts(tmp_path: Path) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "test_mod_a.py", "def test_x():\n    assert True\n")
    assert _has_tests(tmp_path, "src/pkg/mod_a.py")


# ---------------------------------------------------------------------------
# Graph: IMPORTS edges from test files
# ---------------------------------------------------------------------------


def _ql_with_importers(importers: list[str]) -> Any:
    def fake(_store: Any, sql: str = "", **_kw: Any) -> list[dict[str, Any]]:
        if "IMPORTS" in sql:
            return [{"a.path": p} for p in importers]
        return []

    return fake


def test_graph_importer_in_tests_counts() -> None:
    with patch(
        "agentscaffold.review.test_presence.ql",
        side_effect=_ql_with_importers(["src/pkg/other.py", "tests/test_feature.py"]),
    ):
        assert graph_has_test_importer(MagicMock(), "src/pkg/mod_a.py")


def test_graph_importer_outside_tests_does_not_count() -> None:
    with patch(
        "agentscaffold.review.test_presence.ql",
        side_effect=_ql_with_importers(["src/pkg/other.py", "src/pkg/contest.py"]),
    ):
        assert not graph_has_test_importer(MagicMock(), "src/pkg/mod_a.py")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_x.py", True),
        ("pkg/tests/unit/test_x.py", True),
        ("pkg/mod_test.go", True),
        ("web/src/view.test.ts", True),
        ("web/src/view.spec.tsx", True),
        ("tests/conftest.py", False),
        ("tests/helpers.py", False),
        ("src/pkg/attestation.py", False),
        ("src/pkg/contest.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected


# ---------------------------------------------------------------------------
# Retro test_delta row
# ---------------------------------------------------------------------------


def test_test_delta_skips_documents(tmp_path: Path) -> None:
    _package(tmp_path)
    _write_test(tmp_path, "test_feature.py", "from pkg import mod_a\n")
    out: list[VerificationItem] = []
    with (
        patch("agentscaffold.review.test_presence.ql", return_value=[]),
        patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path),
    ):
        _check_test_delta(
            MagicMock(),
            {"src/pkg/mod_a.py", "docs/guide.md", "CHANGELOG.md", "config/app.yaml"},
            out,
        )
    assert out[0].status == "pass"
    assert "all 1 source files" in out[0].detail


def test_test_delta_uses_graph_language(tmp_path: Path) -> None:
    out: list[VerificationItem] = []
    rows = [{"f.path": "bin/run", "f.language": "python"}]
    with (
        patch("agentscaffold.review.test_presence.ql", return_value=[]),
        patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path),
        patch("agentscaffold.review.verify.query_root", return_value=tmp_path),
    ):
        _check_test_delta(MagicMock(), {"bin/run"}, out, rows=rows)
    assert out[0].status == "warn"
    assert out[0].evidence["untested"] == ["bin/run"]


def test_test_delta_with_no_source_files_is_skip(tmp_path: Path) -> None:
    out: list[VerificationItem] = []
    with patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path):
        _check_test_delta(MagicMock(), {"docs/guide.md", "README.md"}, out)
    assert out[0].check == "test_delta"
    assert out[0].status == "skip"
    assert "no source files" in out[0].detail.lower()


def test_test_delta_still_warns_on_untested_code(tmp_path: Path) -> None:
    _package(tmp_path)
    out: list[VerificationItem] = []
    with (
        patch("agentscaffold.review.test_presence.ql", return_value=[]),
        patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path),
    ):
        _check_test_delta(MagicMock(), {"src/pkg/mod_a.py", "docs/guide.md"}, out)
    assert out[0].status == "warn"
    assert out[0].evidence["untested"] == ["src/pkg/mod_a.py"]
