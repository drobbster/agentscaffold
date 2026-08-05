"""Structured error taxonomy for MCP tool responses (Plan 249, Step A6).

MCP tools return JSON to an agent rather than raising into a human's terminal, so
a failure has to be legible to a model: a stable code it can branch on, a message
it can relay, and a remediation it can act on.

The subsystems these errors wrap do not share a base class -- ``GraphLockError``
derives from ``RuntimeError``, ``ConfigError`` and ``ScopingError`` from
``Exception`` -- so this module composes over them via :func:`to_error_response`
instead of trying to retrofit a common ancestor onto code that predates it.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """Stable ``error_code`` values. Agents branch on these, so treat as API."""

    AMBIGUOUS_PROJECT = "ambiguous_project"
    UNKNOWN_PROJECT = "unknown_project"
    RESTRICTED_PROJECT = "restricted_project"
    REGISTRY_ERROR = "registry_error"
    GRAPH_LOCKED = "graph_locked"
    GRAPH_MISSING = "graph_missing"
    INVALID_ARGUMENT = "invalid_argument"
    INTERNAL_ERROR = "internal_error"


class McpToolError(Exception):
    """Base for failures that should reach the agent as structured JSON."""

    error_code: str = ErrorCode.INTERNAL_ERROR
    default_remediation: str = ""

    def __init__(
        self,
        message: str,
        *,
        candidates: list[str] | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.candidates = list(candidates or [])
        self.remediation = remediation or self.default_remediation

    def to_response(self) -> dict[str, Any]:
        """Render as the JSON payload a tool returns in place of a result."""
        payload: dict[str, Any] = {
            "error_code": self.error_code,
            "error": self.message,
            "message": self.message,
        }
        if self.candidates:
            payload["candidates"] = self.candidates
        else:
            # Always present so a caller can branch on emptiness without a
            # membership check first.
            payload["candidates"] = []
        if self.remediation:
            payload["remediation"] = self.remediation
        return payload


class AmbiguousProjectError(McpToolError):
    """No resolution tier matched and more than one answer was possible.

    Deliberately not recoverable by guessing. The pre-Plan-249 behaviour was to
    federate across every project or answer from the server's launch directory,
    and a plausible answer scoped to the wrong project is far harder for an agent
    to notice than a refusal it must act on.
    """

    error_code = ErrorCode.AMBIGUOUS_PROJECT
    default_remediation = (
        "Pass project=<name> or working_path=<file or dir>. "
        "Run 'scaffold workspace list' to see registered projects."
    )


class UnknownProjectError(McpToolError):
    """An explicit project name matched nothing in the registry."""

    error_code = ErrorCode.UNKNOWN_PROJECT
    default_remediation = "Run 'scaffold workspace list' to see registered projects."


class RestrictedProjectError(McpToolError):
    """The resolved project is outside the ``--restrict-to`` allowlist.

    Distinct from ``unknown_project``: the project exists and resolved fine, it
    is simply not one this server was started to serve.
    """

    error_code = ErrorCode.RESTRICTED_PROJECT
    default_remediation = (
        "This server was started with --restrict-to. "
        "Restart without it, or add the project to the allowlist."
    )


class RegistryUnavailableError(McpToolError):
    """The workspace registry could not be read or written."""

    error_code = ErrorCode.REGISTRY_ERROR
    default_remediation = (
        "Check ~/.agentscaffold/registry.yaml, "
        "or re-register with 'scaffold workspace register'."
    )


class GraphLockedError(McpToolError):
    """The graph is held by an in-flight write; the call is retryable."""

    error_code = ErrorCode.GRAPH_LOCKED
    default_remediation = "An index or another write is in progress. Retry shortly."


class InvalidArgumentError(McpToolError):
    """The call was malformed or its configuration could not be loaded."""

    error_code = ErrorCode.INVALID_ARGUMENT


def to_error_response(exc: BaseException) -> dict[str, Any]:
    """Map any exception onto the taxonomy.

    Foreign exceptions are classified by type rather than by message so the
    mapping does not break when upstream wording changes.
    """
    if isinstance(exc, McpToolError):
        return exc.to_response()

    from agentscaffold.config import ConfigError
    from agentscaffold.graph import GraphLockError
    from agentscaffold.workspace_registry import RegistryError

    # RegistryError subclasses ConfigError, so it must be tested first.
    if isinstance(exc, RegistryError):
        return RegistryUnavailableError(str(exc)).to_response()

    if isinstance(exc, GraphLockError):
        return GraphLockedError(str(exc)).to_response()

    if isinstance(exc, ConfigError):
        return InvalidArgumentError(
            str(exc),
            remediation="Check scaffold.yaml for the resolved project.",
        ).to_response()

    return McpToolError(str(exc) or exc.__class__.__name__).to_response()
