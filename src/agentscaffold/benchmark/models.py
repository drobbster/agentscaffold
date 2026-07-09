"""Model metadata for AgentScaffold Benchmark."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkModel:
    """Selectable model configuration for benchmark runs."""

    name: str
    model_id: str
    provider: str
    api_key_env: str
    pricing_source: str
    max_tokens: int
    temperature: float = 0.0


DEFAULT_MODEL = "claude-haiku"

BUILTIN_MODELS: dict[str, BenchmarkModel] = {
    "claude-haiku": BenchmarkModel(
        name="claude-haiku",
        model_id="openrouter/anthropic/claude-3.5-haiku",
        provider="openrouter",
        api_key_env="OPENROUTER_API_KEY",  # pragma: allowlist secret
        pricing_source="litellm",
        max_tokens=8192,
    ),
    "claude-sonnet": BenchmarkModel(
        name="claude-sonnet",
        model_id="openrouter/anthropic/claude-sonnet-4",
        provider="openrouter",
        api_key_env="OPENROUTER_API_KEY",  # pragma: allowlist secret
        pricing_source="litellm",
        max_tokens=16384,
    ),
}


def get_model(name: str) -> BenchmarkModel:
    """Return a built-in benchmark model by short name."""

    try:
        return BUILTIN_MODELS[name]
    except KeyError as exc:
        available = ", ".join(sorted(BUILTIN_MODELS))
        raise ValueError(
            f"Unknown benchmark model '{name}'. Available models: {available}"
        ) from exc
