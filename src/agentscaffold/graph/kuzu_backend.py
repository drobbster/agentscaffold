"""KuzuBackend public entry point.

Re-exports KuzuBackend from store.py. Consumers may import from either location:

    from agentscaffold.graph.kuzu_backend import KuzuBackend
    from agentscaffold.graph.store import KuzuBackend  # also fine
"""

from agentscaffold.graph.store import KuzuBackend

__all__ = ["KuzuBackend"]
