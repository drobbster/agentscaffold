"""Plan 271: File Impact paths that live in a named sibling resolve there or skip."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentscaffold.config import ScaffoldConfig
from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.review.brief import generate_brief
from agentscaffold.review.file_impact_resolve import (
    ImplementationProjectError,
    resolve_plan_impacted_files,
)
from agentscaffold.review.verify import verify_implementation
from agentscaffold.workspace_registry import (
    find_registered_project_by_name,
    register_workspace,
)


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _index(root: Path) -> GraphBackend:
    from agentscaffold.config import find_config, load_config
    from agentscaffold.graph import open_graph

    config = load_config(find_config(start=root))
    run_pipeline(root=root, config=config)
    return open_graph(config, start=root)


def _gov_and_pkg(tmp_path: Path) -> tuple[Path, Path, GraphBackend, GraphBackend]:
    gov = tmp_path / "gov"
    pkg = tmp_path / "pkg"
    (gov / "docs/ai/plans").mkdir(parents=True)
    (gov / "docs/ai/contracts").mkdir(parents=True)
    (pkg / "src/pkg").mkdir(parents=True)
    (gov / "docs/ai/contracts" / "README.md").write_text("# contracts\n", encoding="utf-8")
    (pkg / "src/pkg/__init__.py").write_text("", encoding="utf-8")
    (pkg / "src/pkg/foo.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (pkg / "src/pkg/user.py").write_text("from .foo import foo\n", encoding="utf-8")
    _write_yaml(
        gov / "docs/ai/plans/101-sibling.md",
        """# Feature: sibling impact

## 0. Metadata
- Plan: 101
- Status: Draft

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/pkg/foo.py | Create | only in pkg |
| docs/ai/contracts/README.md | Modify | local |
""",
    )
    _write_yaml(
        gov / "scaffold.yaml",
        "framework:\n  project_name: gov\nimplementation_project: pkg\n",
    )
    _write_yaml(pkg / "scaffold.yaml", "framework:\n  project_name: pkg\n")
    gov_store = _index(gov)
    pkg_store = _index(pkg)
    return gov, pkg, gov_store, pkg_store


def test_implementation_project_rejects_a_path() -> None:
    with pytest.raises(ValidationError):
        ScaffoldConfig(implementation_project="/Users/daverobb/agentscaffold")
    with pytest.raises(ValidationError):
        ScaffoldConfig(implementation_project="~/code/agentscaffold")
    with pytest.raises(ValidationError):
        ScaffoldConfig(implementation_project="../agentscaffold")


def test_unregistered_implementation_project_errors_without_home_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    gov, _pkg, gov_store, pkg_store = _gov_and_pkg(tmp_path)
    try:
        cfg = ScaffoldConfig(implementation_project="not-registered")
        decoy = tmp_path / "home" / "not-registered" / "src/pkg/foo.py"
        decoy.parent.mkdir(parents=True)
        decoy.write_text("stolen\n", encoding="utf-8")
        with pytest.raises(ImplementationProjectError, match="not-registered"):
            resolve_plan_impacted_files(gov_store, 101, root=gov, config=cfg)
        assert decoy.is_file()
        assert find_registered_project_by_name("not-registered") is None
    finally:
        gov_store.close()
        pkg_store.close()


def test_sibling_path_resolves_when_implementation_project_is_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    gov, pkg, gov_store, pkg_store = _gov_and_pkg(tmp_path)
    try:
        register_workspace(gov, name="gov")
        register_workspace(pkg, name="pkg")
        cfg = ScaffoldConfig(implementation_project="pkg")
        result = resolve_plan_impacted_files(gov_store, 101, root=gov, config=cfg)
        try:
            by_path = {r["f.path"]: r for r in result.rows}
            assert by_path["src/pkg/foo.py"]["resolution"] == "sibling"
            assert by_path["src/pkg/foo.py"]["project"] == "pkg"
            assert by_path["docs/ai/contracts/README.md"]["resolution"] == "local"
            assert by_path["docs/ai/contracts/README.md"]["project"] == "gov"
        finally:
            result.close()

        brief = generate_brief(gov_store, 101, root=gov, config=cfg)
        assert brief["summary"]["files_impacted"] >= 1
        sibling = next(p for p in brief["file_profiles"] if p["path"] == "src/pkg/foo.py")
        assert sibling["project"] == "pkg"
        assert sibling["resolution"] == "sibling"
        assert sibling["direct_importers"] >= 1
        assert any("user.py" in p for p in sibling["top_importers"])
    finally:
        gov_store.close()
        pkg_store.close()


def test_unset_implementation_project_skips_sibling_and_does_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    gov, pkg, gov_store, pkg_store = _gov_and_pkg(tmp_path)
    try:
        register_workspace(gov, name="gov")
        register_workspace(pkg, name="pkg")
        cfg = ScaffoldConfig()
        result = resolve_plan_impacted_files(gov_store, 101, root=gov, config=cfg)
        try:
            foo = next(r for r in result.rows if r["f.path"] == "src/pkg/foo.py")
            assert foo["resolution"] == "skipped"
            assert foo["reason"] == "implementation_project_unset"
        finally:
            result.close()

        items = verify_implementation(gov_store, 101, root=gov, config=cfg)
        skip_items = [i for i in items if i.check == "plan_compliance" and i.status == "skip"]
        pass_items = [i for i in items if i.check == "plan_compliance" and i.status == "pass"]
        assert skip_items
        assert not (
            pass_items
            and "src/pkg/foo.py" in str(pass_items[0].detail)
            and "skipped" not in str(skip_items[0].detail)
        )
    finally:
        gov_store.close()
        pkg_store.close()


def test_local_path_wins_over_same_relative_path_in_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    gov, pkg, gov_store, pkg_store = _gov_and_pkg(tmp_path)
    try:
        (gov / "src/pkg").mkdir(parents=True)
        (gov / "src/pkg/foo.py").write_text("def local():\n    return 0\n", encoding="utf-8")
        register_workspace(gov, name="gov")
        register_workspace(pkg, name="pkg")
        cfg = ScaffoldConfig(implementation_project="pkg")
        result = resolve_plan_impacted_files(gov_store, 101, root=gov, config=cfg)
        try:
            foo = next(r for r in result.rows if r["f.path"] == "src/pkg/foo.py")
            assert foo["resolution"] == "local"
            assert foo["project"] == "gov"
        finally:
            result.close()
    finally:
        gov_store.close()
        pkg_store.close()


def test_path_under_home_but_not_registered_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(home))
    gov, pkg, gov_store, pkg_store = _gov_and_pkg(tmp_path)
    try:
        register_workspace(gov, name="gov")
        (home / "src/pkg").mkdir(parents=True)
        (home / "src/pkg/foo.py").write_text("nope\n", encoding="utf-8")
        cfg = ScaffoldConfig()
        result = resolve_plan_impacted_files(gov_store, 101, root=gov, config=cfg)
        try:
            foo = next(r for r in result.rows if r["f.path"] == "src/pkg/foo.py")
            assert foo["resolution"] == "skipped"
            assert foo["_root"] != home
        finally:
            result.close()
    finally:
        gov_store.close()
        pkg_store.close()
