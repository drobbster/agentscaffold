"""Change range, rule rows in verification, and the completion gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentscaffold.review.changes import plan_changes, validate_ref

pytest.importorskip("duckdb", reason="duckdb not installed")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


def _init(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")


def _commit(repo: Path, files: dict[str, str], message: str = "change") -> str:
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _branch(repo: Path, name: str, files: dict[str, str]) -> None:
    _git(repo, "checkout", "-q", "-b", name, "main")
    _commit(repo, files, f"work on {name}")


def _merge(repo: Path, name: str, message: str | None = None) -> None:
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", message or f"Merge branch '{name}'", name)


@pytest.fixture()
def plain(tmp_path: Path) -> Path:
    repo = tmp_path / "plain"
    _write(repo, {"base.txt": "base\n"})
    _init(repo)
    return repo


# ---------------------------------------------------------------------------
# Ref validation and change range
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["-x", "--output=x", "a b", "", "x;rm", "$(id)"])
def test_unsafe_refs_are_refused(ref: str):
    with pytest.raises(ValueError):
        validate_ref(ref)


@pytest.mark.parametrize("ref", ["main", "feature/281-x", "abc123", "origin/staging", "v1.2.0"])
def test_ordinary_refs_are_accepted(ref: str):
    assert validate_ref(ref) == ref


def test_an_unsafe_base_ref_never_reaches_git(plain: Path, monkeypatch: pytest.MonkeyPatch):
    import agentscaffold.review.changes as changes

    def boom(*_a, **_k):
        raise AssertionError("git was called")

    monkeypatch.setattr(changes.subprocess, "run", boom)
    with pytest.raises(ValueError):
        plan_changes(plain, 281, base_ref="--output=x")


def test_merged_branches_give_exactly_their_files(plain: Path):
    _branch(plain, "feature/281-impl", {"a.py": "a\n"})
    _merge(plain, "feature/281-impl")
    _branch(plain, "feature/290-other", {"o.py": "o\n"})
    _merge(plain, "feature/290-other", "Merge pull request #281 from me/feature/290-other")
    _branch(plain, "docs/281-completion", {"d.md": "d\n"})
    _merge(plain, "docs/281-completion", "Merge pull request #19 from me/docs/281-completion")

    changes = plan_changes(plain, 281)
    assert changes.source == "merged_branches"
    assert changes.files == ["a.py", "d.md"]
    assert "2 merge" in changes.detail


def test_plan_prefixed_branch_names_count(plain: Path):
    _branch(plain, "docs/plan-281-review", {"a.md": "a\n"})
    _merge(plain, "docs/plan-281-review", "Merge pull request #7 from me/docs/plan-281-review")
    _branch(plain, "feature/plan-2810-other", {"o.py": "o\n"})
    _merge(plain, "feature/plan-2810-other")

    assert plan_changes(plain, 281).files == ["a.md"]


def test_squash_merges_naming_the_plan_count(plain: Path):
    _commit(plain, {"a.py": "a\n"}, "Plans 280, 281: evaluation book (#348)")
    _commit(plain, {"b.py": "b\n"}, "Plan 281 Steps 4-5: shadow run")
    _commit(plain, {"c.py": "c\n"}, "Plan 2810: unrelated (#349)")
    _commit(plain, {"d.py": "d\n"}, "Fix the 281 typo (#350)")

    changes = plan_changes(plain, 281)
    assert changes.source == "merged_branches"
    assert changes.files == ["a.py"]
    assert "squash" in changes.detail


def test_merges_into_the_base_branch_count_from_another_checkout(plain: Path):
    _branch(plain, "feature/281-impl", {"a.py": "a\n"})
    _merge(plain, "feature/281-impl")
    _git(plain, "checkout", "-q", "-b", "feature/other", "main~1")
    _commit(plain, {"x.py": "x\n"})
    _git(plain, "merge", "--no-ff", "-q", "-m", "Merge main into feature/other", "main")

    assert plan_changes(plain, 281).files == ["a.py"]


def test_merges_into_any_existing_base_branch_count(plain: Path):
    _git(plain, "checkout", "-q", "-b", "staging", "main")
    _git(plain, "checkout", "-q", "-b", "feature/281-impl", "staging")
    _commit(plain, {"a.py": "a\n"})
    _git(plain, "checkout", "-q", "staging")
    _git(
        plain, "merge", "--no-ff", "-q", "-m", "Merge branch 'feature/281-impl'", "feature/281-impl"
    )
    _git(plain, "checkout", "-q", "main")

    assert plan_changes(plain, 281).files == ["a.py"]


def test_an_unmerged_plan_branch_includes_uncommitted_and_untracked(plain: Path):
    _branch(plain, "feature/281-work", {"b.py": "b\n"})
    _write(plain, {"base.txt": "edited\n", "u.py": "u\n"})

    changes = plan_changes(plain, 281)
    assert changes.source == "unmerged_branch"
    assert changes.files == ["b.py", "base.txt", "u.py"]
    assert "main" in changes.detail


def test_a_configured_base_branch_is_used(plain: Path):
    _branch(plain, "staging", {"s.py": "s\n"})
    _git(plain, "checkout", "-q", "-b", "feature/281-work", "staging")
    _commit(plain, {"b.py": "b\n"})

    assert plan_changes(plain, 281, base_branch="staging").files == ["b.py"]
    assert plan_changes(plain, 281, base_branch="main").files == ["b.py", "s.py"]


def test_a_merged_plan_and_its_open_completion_branch_are_combined(plain: Path):
    _branch(plain, "feature/281-impl", {"a.py": "a\n"})
    _merge(plain, "feature/281-impl")
    _branch(plain, "docs/281-completion", {"d.md": "d\n"})

    changes = plan_changes(plain, 281)
    assert changes.source == "merged_branches+unmerged_branch"
    assert changes.files == ["a.py", "d.md"]


def test_direct_commits_use_the_commit_recorded_at_review(plain: Path):
    reviewed = _git(plain, "rev-parse", "HEAD")
    _commit(plain, {"c.py": "c\n"})
    _write(plain, {"base.txt": "edited\n"})

    changes = plan_changes(plain, 281, reviewed_commit=reviewed)
    assert changes.source == "reviewed_commits"
    assert changes.files == ["base.txt", "c.py"]


def test_base_ref_wins(plain: Path):
    start = _git(plain, "rev-parse", "HEAD")
    _branch(plain, "feature/281-impl", {"a.py": "a\n"})
    _merge(plain, "feature/281-impl")
    _commit(plain, {"later.py": "x\n"})

    changes = plan_changes(plain, 281, base_ref=start)
    assert changes.source == "base_ref"
    assert changes.files == ["a.py", "later.py"]


def test_without_git_the_file_impact_map_is_used(tmp_path: Path):
    changes = plan_changes(tmp_path, 281, impact_paths=["src/x.py", "src/x.py", "y.py"])
    assert changes.source == "file_impact_map"
    assert changes.files == ["src/x.py", "y.py"]


def test_a_plan_with_no_branch_and_no_review_falls_back_to_the_impact_map(plain: Path):
    _commit(plain, {"c.py": "c\n"})
    changes = plan_changes(plain, 281, impact_paths=["c.py"])
    assert changes.source == "file_impact_map"


# ---------------------------------------------------------------------------
# Rule rows on an indexed project under git
# ---------------------------------------------------------------------------

ROUTER = "libs/data/router.py"
CONTRACT = "docs/ai/contracts/router_interface.md"
ARCH_LOG = "docs/ai/architectural_design_changelog.md"
WORKFLOW = "docs/ai/state/workflow_state.md"


def _plan(number: int, *, files: list[str], extra_meta: str = "") -> str:
    rows = "\n".join(f"| {f} | Modify | change |" for f in files)
    return (
        f"# Plan {number:03d}: Router change {number}\n\n## 0. Metadata\n- Plan: {number}\n"
        f"- Status: In Progress\n- Breaking change: No\n{extra_meta}\n"
        "## 6. File Impact Map\n| File | Change Type | Notes |\n|------|-------------|-------|\n"
        f"{rows}\n\n## 8. Execution Steps\n- [x] Step 1: Do it.\n"
    )


ADR = """# ADR-007: Router boundary

## Status
Accepted

## Related
- Related Plans: Plan 092
"""


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_config: str = "") -> Path:
    from tests.fixtures.lone_project import build_lone_project

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    repo = build_lone_project(
        tmp_path,
        extra_config=extra_config,
        extra_files={
            ".gitignore": ".scaffold/\ndocs/ai/state/governance.json\n",
            ROUTER: "def route():\n    return 1\n",
            CONTRACT: "# Router interface\n",
            ARCH_LOG: "# Architecture changelog\n",
            "CHANGELOG.md": "# Changelog\n",
            "docs/ai/plans/plan_092_router_boundary.md": _plan(92, files=[ROUTER]),
            "docs/ai/plans/plan_093_router_tweak.md": _plan(93, files=[ROUTER]),
            "docs/ai/plans/plan_094_router_contract.md": _plan(94, files=[ROUTER, CONTRACT]),
            "docs/ai/plans/plan_095_config_change.md": _plan(
                95, files=["scaffold.yaml"], extra_meta="- Approved: 2026-11-04 by reviewer\n"
            ),
            "docs/ai/adrs/adr-007-router-boundary.md": ADR,
        },
    )
    _init(repo)
    return repo


def _rows(repo: Path, tmp_path: Path, plan: int, **kwargs) -> dict[str, dict]:
    from agentscaffold.config import load_config
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.review.verify import compliance_items

    store = DuckPGQBackend(tmp_path / "lone.duckdb", read_only=True)
    try:
        items = compliance_items(
            store, plan, root=repo, config=load_config(repo / "scaffold.yaml"), **kwargs
        )
    finally:
        store.close()
    return {i.check: {"status": i.status, "detail": i.detail, **i.evidence} for i in items}


def test_rows_name_the_change_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "def route():\n    return 2\n"})
    rows = _rows(repo, tmp_path, 93)
    assert rows["workflow_state_updated"]["change_source"] == "unmerged_branch"
    assert "unmerged_branch" in rows["workflow_state_updated"]["detail"]


def test_workflow_state_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    assert _rows(repo, tmp_path, 93)["workflow_state_updated"]["status"] == "warn"
    _commit(repo, {WORKFLOW: "# Workflow\nPlan 93 complete.\n"})
    assert _rows(repo, tmp_path, 93)["workflow_state_updated"]["status"] == "pass"


def test_architecture_changelog_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    assert _rows(repo, tmp_path, 93)["architecture_changelog"]["status"] == "skip"
    _commit(repo, {ARCH_LOG: "# Architecture changelog\n- tweak\n"})
    assert _rows(repo, tmp_path, 93)["architecture_changelog"]["status"] == "warn"

    _branch(repo, "feature/92-boundary", {ROUTER: "x = 3\n"})
    assert _rows(repo, tmp_path, 92)["architecture_changelog"]["status"] == "warn"
    _commit(repo, {ARCH_LOG: "# Architecture changelog\n- boundary\n"})
    assert _rows(repo, tmp_path, 92)["architecture_changelog"]["status"] == "pass"


def test_package_changelog_skips_unless_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    row = _rows(repo, tmp_path, 93)["package_changelog"]
    assert row["status"] == "skip"
    assert "not configured" in row["detail"]


def test_package_changelog_when_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch, "compliance:\n  package_changelog: CHANGELOG.md\n")
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    assert _rows(repo, tmp_path, 93)["package_changelog"]["status"] == "warn"
    _commit(repo, {"CHANGELOG.md": "# Changelog\n- tweak\n"})
    assert _rows(repo, tmp_path, 93)["package_changelog"]["status"] == "pass"


def test_contract_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    assert _rows(repo, tmp_path, 93)["contract_with_interface"]["status"] == "skip"

    _branch(repo, "feature/94-contract", {ROUTER: "x = 3\n"})
    assert _rows(repo, tmp_path, 94)["contract_with_interface"]["status"] == "warn"
    _commit(repo, {CONTRACT: "# Router interface\nv1.1\n"})
    assert _rows(repo, tmp_path, 94)["contract_with_interface"]["status"] == "pass"


def test_read_only_paths_need_a_recorded_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    config = (repo / "scaffold.yaml").read_text()
    _branch(repo, "feature/93-tweak", {"scaffold.yaml": config + "# edited\n"})
    row = _rows(repo, tmp_path, 93)["read_only_paths"]
    assert row["status"] == "fail"
    assert row["paths"] == ["scaffold.yaml"]

    _branch(repo, "feature/95-config", {"scaffold.yaml": config + "# approved\n"})
    assert _rows(repo, tmp_path, 95)["read_only_paths"]["status"] == "pass"

    _branch(repo, "feature/94-contract", {ROUTER: "x = 3\n"})
    assert _rows(repo, tmp_path, 94)["read_only_paths"]["status"] == "skip"


def test_pre_review_disposition_lists_only_findings_that_need_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.findings import record_finding, resolve_finding

    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    store = DuckPGQBackend(tmp_path / "lone.duckdb")
    try:

        def rec(review_type: str, category: str, text: str) -> str:
            return record_finding(
                store, plan_number=93, review_type=review_type, category=category, finding=text
            )["id"]

        needs = {
            rec("devils_advocate", "RISK", "Agent risk."),
            rec("human", "GAP", "Human gap."),
            rec("pre_review", "PRECEDENT", "Earlier finding about the router."),
        }
        rec("pre_review", "RISK", "Automated risk.")
        rec("pre_review", "DEPENDENCY", "Dependency note.")
        rec("pre_review", "CONSUMER_AUDIT", "Consumer note.")
        rec("pre_review", "TEST_COVERAGE", "Coverage note.")
        rec("devils_advocate", "HISTORY", "Churn statistic.")
        rec("post_retro", "RISK", "Retro risk.")
    finally:
        store.close()

    row = _rows(repo, tmp_path, 93)["pre_review_disposition"]
    assert row["status"] == "warn"
    assert set(row["undisposed"]) == needs

    store = DuckPGQBackend(tmp_path / "lone.duckdb")
    try:
        for fid in needs:
            resolve_finding(store, fid, resolution="Handled.", disposition="not_applicable")
    finally:
        store.close()
    assert _rows(repo, tmp_path, 93)["pre_review_disposition"]["status"] == "pass"


def test_a_rule_set_off_is_omitted_and_levels_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _project(
        tmp_path,
        monkeypatch,
        "compliance:\n  rules:\n    workflow_state_updated: 'off'\n    read_only_paths: warn\n",
    )
    config = (repo / "scaffold.yaml").read_text()
    _branch(repo, "feature/93-tweak", {"scaffold.yaml": config + "# edited\n"})
    rows = _rows(repo, tmp_path, 93)
    assert "workflow_state_updated" not in rows
    assert rows["read_only_paths"]["status"] == "warn"


def _dispatch(repo: Path, monkeypatch: pytest.MonkeyPatch, name: str, **args) -> dict:
    from agentscaffold.mcp import freshness
    from agentscaffold.mcp.server import _dispatch_tool

    monkeypatch.setattr(
        freshness, "evaluate_freshness", lambda *_a, **_k: {"freshness_status": "fresh"}
    )
    return _dispatch_tool(name, {"working_path": str(repo), **args})


def _checks(result: dict) -> dict[str, str]:
    return {v["check"]: v["status"] for v in result["retro"]["verification"]}


GATE = "gates:\n  in_progress_to_complete:\n    compliance: {level}\n"


def test_gate_block_stops_completion_before_retro_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _project(tmp_path, monkeypatch, GATE.format(level="block"))
    config = (repo / "scaffold.yaml").read_text()
    _branch(repo, "feature/93-tweak", {"scaffold.yaml": config + "# edited\n"})

    result = _dispatch(repo, monkeypatch, "scaffold_complete_plan", plan_number=93)
    assert result["gate_blocked"] is True
    assert [r["check"] for r in result["failing"]] == ["read_only_paths"]
    assert result["findings_written"]["count"] == 0

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(tmp_path / "lone.duckdb", read_only=True)
    try:
        n = store.query(
            "SELECT count(*) AS n FROM ReviewFinding WHERE planNumber = 93"
            " AND reviewType = 'post_retro'"
        )[0]["n"]
    finally:
        store.close()
    assert n == 0


def test_gate_warn_reports_and_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch, GATE.format(level="warn"))
    config = (repo / "scaffold.yaml").read_text()
    _branch(repo, "feature/93-tweak", {"scaffold.yaml": config + "# edited\n"})

    result = _dispatch(repo, monkeypatch, "scaffold_complete_plan", plan_number=93)
    assert not result.get("gate_blocked")
    assert _checks(result)["read_only_paths"] == "fail"


def test_gate_defaults_to_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.review.verify import _gate_level

    assert ScaffoldConfig().gates.in_progress_to_complete.compliance == "off"
    assert _gate_level(None) == "off"

    repo = _project(tmp_path, monkeypatch)
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    checks = _checks(_dispatch(repo, monkeypatch, "scaffold_complete_plan", plan_number=93))
    assert "plan_compliance" in checks
    assert not {"read_only_paths", "workflow_state_updated", "pre_review_disposition"} & set(checks)


def test_gate_off_omits_the_rule_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch, GATE.format(level="'off'"))
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})

    result = _dispatch(repo, monkeypatch, "scaffold_complete_plan", plan_number=93)
    checks = _checks(result)
    assert "plan_compliance" in checks
    assert not {"read_only_paths", "workflow_state_updated", "pre_review_disposition"} & set(checks)


def test_begin_plan_records_the_reviewed_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, monkeypatch)
    head = _git(repo, "rev-parse", "HEAD")
    _dispatch(repo, monkeypatch, "scaffold_begin_plan", plan_number=93)

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.review.queries import get_plan_review

    store = DuckPGQBackend(tmp_path / "lone.duckdb", read_only=True)
    try:
        review = get_plan_review(store, 93)
    finally:
        store.close()
    assert review is not None
    assert review["reviewedCommits"] == {"lone": head}


def test_cli_verify_takes_a_plan_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from typer.testing import CliRunner

    from agentscaffold.cli import app

    repo = _project(tmp_path, monkeypatch, GATE.format(level="warn"))
    _branch(repo, "feature/93-tweak", {ROUTER: "x = 2\n"})
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(app, ["review", "verify", "--plan", "93"])
    assert result.exit_code == 0, result.output
    assert "workflow_state_updated" in result.output
    positional = CliRunner().invoke(app, ["review", "verify", "93"])
    assert positional.exit_code == 0, positional.output
