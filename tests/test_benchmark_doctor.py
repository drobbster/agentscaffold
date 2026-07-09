"""Offline preflight tests for AgentScaffold Benchmark."""

from __future__ import annotations

from agentscaffold.benchmark.doctor import CheckStatus, check_api_key, check_pricing
from agentscaffold.benchmark.models import get_model


def test_api_key_check_warns_when_not_required() -> None:
    result = check_api_key(get_model("claude-haiku"), {}, required=False)

    assert result.status == CheckStatus.WARN
    assert result.required is False
    assert "OPENROUTER_API_KEY is not set" in result.message


def test_api_key_check_fails_when_required() -> None:
    result = check_api_key(get_model("claude-haiku"), {}, required=True)

    assert result.status == CheckStatus.FAIL
    assert result.required is True


def test_pricing_check_identifies_litellm_source() -> None:
    result = check_pricing(get_model("claude-haiku"))

    assert result.status == CheckStatus.PASS
    assert "litellm" in result.message
