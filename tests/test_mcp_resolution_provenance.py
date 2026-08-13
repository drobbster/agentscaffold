"""What a response says about how it was scoped (Plan 257, Group B).

The field report behind ADR-026 could only be diagnosed by instrumenting
resolution, because a response answered from the wrong project was byte-for-byte
as convincing as a correct one: ``scaffold_projects`` was the sole tool that
disclosed any provenance, and nothing disclosed that a ``working_path`` had been
ignored. These tests hold that reporting in place, on a real dispatch rather than
on the helper alone, since the helper being right is worth nothing if the
response never carries it.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures.multiproject import ALPHA, BETA


def _dispatch(tool: str, **arguments: Any) -> dict[str, Any]:
    from agentscaffold.mcp.server import _dispatch_tool

    return _dispatch_tool(tool, arguments)


def test_a_response_names_the_project_that_answered(two_project_workspace) -> None:
    """Which project, which root, and which tier decided."""
    result = _dispatch("scaffold_orient", working_path=str(two_project_workspace.source_file(BETA)))

    meta = result["meta"]
    assert meta["project"] == BETA
    assert meta["project_root"] == str(two_project_workspace.beta)
    assert meta["resolution_source"] == "working_path"
    assert meta["project_registered"] is True
    assert "working_path_unmatched" not in meta


def test_an_ignored_working_path_is_reported_as_unmatched(
    two_project_workspace, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The silent case, and the reason this reporting exists.

    A ``working_path`` that resolves to no project is dropped and the call is
    answered from the anchor instead -- which is indistinguishable from the path
    having been honoured. Here the path is real but belongs to no project, and the
    anchor is alpha, so a response about alpha comes back to a caller who asked
    about somewhere else entirely. Saying so is what lets an agent notice.
    """
    import agentscaffold.mcp.server as server_mod

    monkeypatch.setattr(
        server_mod, "_effective_mcp_root", lambda *a, **k: two_project_workspace.alpha
    )
    outside = tmp_path / "not-a-project"
    outside.mkdir()

    result = _dispatch("scaffold_orient", working_path=str(outside))

    meta = result["meta"]
    assert meta["project"] == ALPHA
    assert meta["resolution_source"] == "startup_anchor"
    assert meta["working_path_unmatched"] is True


def test_a_refusal_says_what_to_send_next() -> None:
    """An agent has to act on a refusal, so it carries arguments, not just prose."""
    from agentscaffold.mcp.errors import AmbiguousProjectError

    payload = AmbiguousProjectError("nope", candidates=["alpha", "beta"]).to_response()

    assert payload["error_code"] == "ambiguous_project"
    assert set(payload["retry_with"]) == {"working_path", "project"}
    assert "scaffold_projects" in payload["remediation"]


@pytest.mark.parametrize(
    "error_cls",
    ["AmbiguousProjectError", "UnknownProjectError", "RegistryUnavailableError"],
)
def test_remediations_only_name_commands_that_exist(error_cls: str) -> None:
    """Advice that does not run is worse than none.

    Two of these told the caller to run ``scaffold workspace list`` to see the
    candidates, which reports the current workspace manifest rather than the
    registry these candidates come from; the third pointed at
    ``scaffold workspace register``, which is not a command at all.
    """
    from agentscaffold.mcp import errors as errors_mod

    remediation = getattr(errors_mod, error_cls).default_remediation

    assert remediation
    assert "scaffold workspace list" not in remediation
    assert "scaffold workspace register" not in remediation
