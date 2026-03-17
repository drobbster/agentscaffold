"""Internal hook dispatch engine for AgentScaffold — Step B.5.

Dispatches lifecycle events to registered handlers.  Used by the CLI to
trigger side-effects such as incremental indexing and auto-orient.

Usage::

    from agentscaffold.hooks.engine import HookEngine, fire

    engine = HookEngine()
    engine.register(HookEvent.POST_TOOL_USE, my_handler)
    engine.fire(HookEvent.POST_TOOL_USE, tool="Edit", path="src/foo.py")

    # Module-level fire() uses the default engine
    fire(HookEvent.SESSION_START)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agentscaffold.hooks.events import HookEvent

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., None]


class HookEngine:
    """Lightweight synchronous hook dispatcher.

    Handlers are called in registration order.  Exceptions raised by
    handlers are caught and logged so that a failing hook never blocks
    the primary CLI operation.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._handlers: dict[HookEvent, list[HandlerFn]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def register(self, event: HookEvent, handler: HandlerFn) -> None:
        """Register *handler* to be called when *event* fires."""
        self._handlers.setdefault(event, []).append(handler)

    def unregister(self, event: HookEvent, handler: HandlerFn) -> None:
        """Remove *handler* from *event*. No-op if not registered."""
        handlers = self._handlers.get(event, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def fire(self, event: HookEvent, **kwargs: Any) -> None:
        """Dispatch *event* to all registered handlers.

        Args:
            event: The lifecycle event to fire.
            **kwargs: Arbitrary keyword arguments forwarded to handlers.
        """
        if not self._enabled:
            return
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(**kwargs)
            except Exception:
                logger.exception("Hook handler %r raised for event %s", handler, event)

    def handler_count(self, event: HookEvent) -> int:
        """Return the number of registered handlers for *event*."""
        return len(self._handlers.get(event, []))


# ---------------------------------------------------------------------------
# Default engine wired with built-in handlers
# ---------------------------------------------------------------------------

_default_engine = HookEngine()


def _incremental_index_handler(**kwargs: Any) -> None:
    """Trigger incremental graph index after a file-mutating tool use."""
    from pathlib import Path  # noqa: PLC0415

    from agentscaffold.config import load_config  # noqa: PLC0415
    from agentscaffold.graph import graph_available, index  # noqa: PLC0415

    config = load_config()
    if not graph_available(config):
        return
    try:
        index(path=Path.cwd(), config=config, incremental=True)
    except Exception:
        logger.exception("Incremental index hook failed")


def _auto_orient_handler(**kwargs: Any) -> None:
    """Run scaffold orient at session start."""
    try:
        from typer.testing import CliRunner  # noqa: PLC0415

        from agentscaffold.cli import app  # noqa: PLC0415

        runner = CliRunner()
        runner.invoke(app, ["orient"])
    except Exception:
        logger.debug("Auto-orient hook failed (non-fatal)")


def wire_default_handlers(engine: HookEngine | None = None) -> None:
    """Wire built-in handlers to *engine* (or the default engine)."""
    target = engine or _default_engine
    target.register(HookEvent.POST_TOOL_USE, _incremental_index_handler)
    target.register(HookEvent.SESSION_START, _auto_orient_handler)


def fire(event: HookEvent, **kwargs: Any) -> None:
    """Fire *event* on the default engine."""
    _default_engine.fire(event, **kwargs)


def get_default_engine() -> HookEngine:
    """Return the module-level default engine."""
    return _default_engine
