"""Live benchmark support for AgentScaffold.

The benchmark package is intentionally offline-first: command wiring, dependency
checks, and dry-run planning live in the base package, while live model execution
requires the optional ``agentscaffold[benchmark]`` extra and explicit user flags.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
