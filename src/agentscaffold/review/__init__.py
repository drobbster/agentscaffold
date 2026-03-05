"""Dialectic Engine -- graph-powered review system for AgentScaffold.

This subsystem generates evidence-based review content from graph queries
to strengthen adversarial reviews and the continuous improvement loop.

Modules:
    brief       - Pre-review dependency/history/learning/layer/contract brief
    challenges  - Graph-evidence-backed adversarial challenges
    gaps        - Consumer audit, integration points, similar patterns
    verify      - Post-implementation verification against plan and graph
    feedback    - Retrospective enrichment with pattern detection
    queries     - Reusable graph query building blocks
"""

from agentscaffold.review.brief import format_brief_markdown, generate_brief
from agentscaffold.review.challenges import (
    format_challenges_markdown,
    generate_challenges,
)
from agentscaffold.review.feedback import (
    format_retro_markdown,
    generate_retro_enrichment,
)
from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps
from agentscaffold.review.verify import (
    format_verification_markdown,
    verify_implementation,
)

__all__ = [
    "generate_brief",
    "format_brief_markdown",
    "generate_challenges",
    "format_challenges_markdown",
    "generate_gaps",
    "format_gaps_markdown",
    "verify_implementation",
    "format_verification_markdown",
    "generate_retro_enrichment",
    "format_retro_markdown",
]
