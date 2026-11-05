"""Session-state hint attached to MCP tool responses.

A client that drops the server's initialize instructions still reads tool
results, so ``scaffold_orient`` and the governance write tools say when no
AgentScaffold session is open, and every other read reports the boolean alone.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from agentscaffold.graph.sessions import find_open_session

logger = logging.getLogger(__name__)

PROCEDURE_DELIVERY_ENV = "AGENTSCAFFOLD_MCP_INSTRUCTIONS"

PROCEDURE_HINT = "No open AgentScaffold session. Call scaffold_session_start, then scaffold_orient."

_DISABLED_VALUES = frozenset({"0", "false", "off"})


def procedure_delivery_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether instructions and response hints are on.

    ``0``, ``false`` and ``off`` (any case, surrounding whitespace ignored)
    disable both; any other value, or the variable being unset, enables them.
    """
    env = os.environ if environ is None else environ
    return env.get(PROCEDURE_DELIVERY_ENV, "").strip().lower() not in _DISABLED_VALUES


def session_meta(
    store: Any, project: str | None, *, with_hint: bool, idle_hours: float = 0
) -> dict[str, Any]:
    """``session_open`` (and, when asked and closed, ``procedure_hint``) for *project*.

    *project* must be the key the session writer stamps, matched exactly, or a
    session that is open will read as closed. A session idle beyond
    *idle_hours* reads as closed so the hint sends the agent to
    start a new one. The lookup only reads; it never starts or closes a session.
    Any failure yields ``{}`` so a hint can never break the tool it rides on.
    """
    try:
        session = find_open_session(
            store, project=project, exact_project=True, idle_hours=idle_hours
        )
        is_open = session is not None
    except Exception:
        logger.debug("Open-session lookup failed; omitting session meta", exc_info=True)
        return {}
    meta: dict[str, Any] = {"session_open": is_open}
    if with_hint and not is_open:
        meta["procedure_hint"] = PROCEDURE_HINT
    return meta
