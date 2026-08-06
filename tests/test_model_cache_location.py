"""Tests for embedding weights cache location (Plan 249, Step A7c).

``search.cache_dir`` defaults to ``.scaffold/models``, a *project*-relative path.
That is deterministic and offline-capable, which is what Plan 227 wanted, but it
also means every project keeps its own copy of byte-identical weights: four
warmed caches were measured on the development machine at 87 MB each.

The step as written proposed resolving them at the workspace root. Measurement
showed that fixes nothing -- the four caches were four unrelated lone repos, and
for a lone repo the workspace root collapses to the project root. Model weights
are content-addressed by Hugging Face, carry nothing project-specific, and are
freely re-downloadable, so their natural scope is the user, not the workspace.

Two properties matter beyond "they end up in one place". An explicit
``cache_dir`` must still win, because pinning weights inside a repo is a
legitimate choice for an air-gapped build. And a project that has already warmed
a local cache must keep using it rather than being made to re-download 87 MB the
first time it runs after upgrading.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig, SearchConfig

DEFAULT_CACHE_DIR = SearchConfig.model_fields["cache_dir"].default


def _config(cache_dir: str | None = None) -> ScaffoldConfig:
    """A config whose search block uses *cache_dir*, or the shipped default."""
    if cache_dir is None:
        return ScaffoldConfig()
    return ScaffoldConfig(search=SearchConfig(cache_dir=cache_dir))


def _project(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
    return root


def _warm(cache_dir: Path) -> Path:
    """Create the marker Hugging Face leaves in a populated cache directory."""
    (cache_dir / "models--sentence-transformers--all-MiniLM-L6-v2" / "blobs").mkdir(
        parents=True, exist_ok=True
    )
    return cache_dir


@pytest.fixture()
def cache_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the user cache root somewhere isolated and empty."""
    target = tmp_path / "xdg-cache"
    target.mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(target))
    monkeypatch.delenv("AGENTSCAFFOLD_MODEL_CACHE", raising=False)
    return target / "agentscaffold"


# ---------------------------------------------------------------------------
# The behaviour the step exists to produce
# ---------------------------------------------------------------------------


def test_projects_share_one_cache_directory(cache_home: Path, tmp_path: Path) -> None:
    """The point of the step: N projects, one copy of the weights.

    These are deliberately *unrelated* repos with no workspace manifest between
    them, because that is the shape the 349 MB was actually measured in.
    """
    from agentscaffold.paths import resolve_model_cache_dir

    resolved = {
        resolve_model_cache_dir(_config(), start=_project(tmp_path / name, name))
        for name in ("alpha", "beta", "gamma", "delta")
    }

    assert len(resolved) == 1
    assert resolved.pop() == cache_home / "models"


def test_lone_repo_no_longer_caches_inside_the_repo(cache_home: Path, tmp_path: Path) -> None:
    """The default stops writing 87 MB into the source tree."""
    from agentscaffold.paths import resolve_model_cache_dir

    solo = _project(tmp_path / "solo", "solo")
    resolved = resolve_model_cache_dir(_config(), start=solo)

    assert resolved is not None
    assert solo not in resolved.parents
    assert resolved == cache_home / "models"


# ---------------------------------------------------------------------------
# Overrides: an explicit choice is never overridden
# ---------------------------------------------------------------------------


def test_absolute_cache_dir_is_honoured(cache_home: Path, tmp_path: Path) -> None:
    from agentscaffold.paths import resolve_model_cache_dir

    pinned = tmp_path / "pinned-weights"
    resolved = resolve_model_cache_dir(
        _config(str(pinned)), start=_project(tmp_path / "alpha", "alpha")
    )

    assert resolved == pinned


def test_explicit_relative_cache_dir_stays_project_relative(
    cache_home: Path, tmp_path: Path
) -> None:
    """A relative path the user actually wrote is a deliberate project-local pin.

    Only the shipped default is redirected; anything else is someone's choice.
    """
    from agentscaffold.paths import resolve_model_cache_dir

    alpha = _project(tmp_path / "alpha", "alpha")
    resolved = resolve_model_cache_dir(_config("vendor/weights"), start=alpha)

    assert resolved == alpha / "vendor/weights"


def test_empty_cache_dir_still_means_the_huggingface_default(
    cache_home: Path, tmp_path: Path
) -> None:
    from agentscaffold.paths import resolve_model_cache_dir

    alpha = _project(tmp_path / "alpha", "alpha")
    assert resolve_model_cache_dir(_config(""), start=alpha) is None


def test_env_var_overrides_everything(cache_home: Path, tmp_path: Path, monkeypatch) -> None:
    """Mirrors AGENTSCAFFOLD_DB_PATH: one machine-level escape hatch."""
    from agentscaffold.paths import resolve_model_cache_dir

    override = tmp_path / "scratch-weights"
    monkeypatch.setenv("AGENTSCAFFOLD_MODEL_CACHE", str(override))

    alpha = _project(tmp_path / "alpha", "alpha")
    assert resolve_model_cache_dir(_config(), start=alpha) == override
    assert resolve_model_cache_dir(_config("vendor/weights"), start=alpha) == override


# ---------------------------------------------------------------------------
# Upgrade path: nobody re-downloads 87 MB because they upgraded
# ---------------------------------------------------------------------------


def test_existing_warm_project_cache_is_reused_when_shared_is_cold(
    cache_home: Path, tmp_path: Path
) -> None:
    """An already-warmed project keeps working; `scaffold gc` reclaims later."""
    from agentscaffold.paths import resolve_model_cache_dir

    alpha = _project(tmp_path / "alpha", "alpha")
    local = _warm(alpha / DEFAULT_CACHE_DIR)

    assert resolve_model_cache_dir(_config(), start=alpha) == local


def test_shared_cache_wins_once_it_is_warm(cache_home: Path, tmp_path: Path) -> None:
    """The fallback is a migration aid, not a permanent preference."""
    from agentscaffold.paths import resolve_model_cache_dir

    alpha = _project(tmp_path / "alpha", "alpha")
    _warm(alpha / DEFAULT_CACHE_DIR)
    shared = _warm(cache_home / "models")

    assert resolve_model_cache_dir(_config(), start=alpha) == shared


def test_cold_machine_warms_the_shared_cache(cache_home: Path, tmp_path: Path) -> None:
    """With nothing warmed anywhere, a new project must not seed a local copy."""
    from agentscaffold.paths import resolve_model_cache_dir

    alpha = _project(tmp_path / "alpha", "alpha")
    assert resolve_model_cache_dir(_config(), start=alpha) == cache_home / "models"


def test_an_empty_project_cache_directory_does_not_count_as_warm(
    cache_home: Path, tmp_path: Path
) -> None:
    """A bare `.scaffold/models` left by a failed warm must not pin the project."""
    from agentscaffold.paths import resolve_model_cache_dir

    alpha = _project(tmp_path / "alpha", "alpha")
    (alpha / DEFAULT_CACHE_DIR).mkdir(parents=True)

    assert resolve_model_cache_dir(_config(), start=alpha) == cache_home / "models"


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


def test_falls_back_to_dot_cache_without_xdg(tmp_path: Path, monkeypatch) -> None:
    from agentscaffold.paths import resolve_user_cache_dir

    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    if os.name != "nt":
        assert resolve_user_cache_dir() == (tmp_path / "home" / ".cache" / "agentscaffold")


# ---------------------------------------------------------------------------
# Residency
# ---------------------------------------------------------------------------


def test_embeddings_resolve_through_the_shared_location(
    cache_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """configure_embeddings must not keep its own project-relative rule."""
    pytest.importorskip("sentence_transformers", reason="search extra not installed")
    from agentscaffold.active_root import active_root
    from agentscaffold.graph import embeddings

    alpha = _project(tmp_path / "alpha", "alpha")
    with active_root(alpha):
        embeddings.configure_embeddings("all-MiniLM-L6-v2", DEFAULT_CACHE_DIR)
        resolved = embeddings._active_cache_dir()

    assert Path(resolved) == cache_home / "models"


def test_model_cache_is_bounded(monkeypatch) -> None:
    """Defence in depth for genuinely distinct models (Step A7c).

    Safe to evict here in a way it was *not* safe for the graph handle pool:
    dropping a model from the dict does not invalidate references callers
    already hold, whereas closing a DuckDB connection breaks an in-flight
    reader. So this is a plain bound, not a lease.
    """
    from agentscaffold.graph import embeddings

    monkeypatch.setattr(embeddings, "_model_cache", {})
    monkeypatch.setattr(embeddings, "MAX_CACHED_MODELS", 2)

    for i in range(4):
        embeddings._remember_model((f"model-{i}", None), object())

    assert len(embeddings._model_cache) == 2
    assert ("model-3", None) in embeddings._model_cache
    assert ("model-0", None) not in embeddings._model_cache
