"""Tests for config-reference resolution (Plan 216)."""

from __future__ import annotations

import pytest

from agentscaffold.graph.config_refs import (
    CONFIDENCE_FILE_AND_SYMBOL,
    CONFIDENCE_FILE_ONLY,
    _extract_references,
    _module_to_path,
    _resolve_reference,
    process_config_references,
)
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend


class TestExtractReferences:
    def test_allowlisted_yaml_key(self):
        refs = _extract_references("class: libs.strategies.momentum.MomentumStrategy")
        assert refs == [("class", "libs.strategies.momentum.MomentumStrategy")]

    def test_non_allowlisted_key_ignored(self):
        # ``name`` is not in the allowlist even though the value is dotted.
        assert _extract_references("name: libs.foo.Bar") == []

    def test_non_dotted_value_ignored(self):
        assert _extract_references("class: MomentumStrategy") == []

    def test_entrypoint_colon_form(self):
        refs = _extract_references("entrypoint: pkg.mod:Handler")
        assert refs == [("entrypoint", "pkg.mod:Handler")]

    def test_toml_equals_form(self):
        refs = _extract_references('factory = "a.b.c.Factory"')
        assert refs == [("factory", "a.b.c.Factory")]

    def test_json_quoted_form(self):
        refs = _extract_references('  "target": "a.b.Thing",')
        assert refs == [("target", "a.b.Thing")]

    def test_arbitrary_scalar_not_extracted(self):
        # Even a dotted value is ignored when its key is not allowlisted.
        assert _extract_references("threshold: yield_curve.flat_threshold") == []


class TestModuleToPath:
    def test_resolves_module_file(self):
        paths = {"libs/strategies/momentum.py": "id1"}
        assert _module_to_path(["libs", "strategies", "momentum"], paths) == (
            "libs/strategies/momentum.py"
        )

    def test_resolves_package_init(self):
        paths = {"libs/strategies/__init__.py": "id1"}
        assert _module_to_path(["libs", "strategies"], paths) == ("libs/strategies/__init__.py")

    def test_src_prefix_fallback(self):
        paths = {"src/pkg/mod.py": "id1"}
        assert _module_to_path(["pkg", "mod"], paths) == "src/pkg/mod.py"

    def test_unresolved(self):
        assert _module_to_path(["nope", "missing"], {}) is None


class TestResolveReference:
    def test_file_and_symbol(self):
        paths = {"libs/strategies/momentum.py": "id1"}
        defs = {"libs/strategies/momentum.py": {"MomentumStrategy"}}
        by_sym = {"MomentumStrategy": ["libs/strategies/momentum.py"]}
        target, symbol, conf = _resolve_reference(
            "libs.strategies.momentum.MomentumStrategy", paths, defs, by_sym
        )
        assert target == "libs/strategies/momentum.py"
        assert symbol == "MomentumStrategy"
        assert conf == CONFIDENCE_FILE_AND_SYMBOL

    def test_file_only_when_full_path_is_module(self):
        paths = {"libs/config/settings.py": "id1"}
        target, symbol, conf = _resolve_reference("libs.config.settings", paths, {}, {})
        assert target == "libs/config/settings.py"
        assert symbol == ""
        assert conf == CONFIDENCE_FILE_ONLY

    def test_reexport_via_unique_symbol(self):
        # Module resolves to an __init__ that does not define the symbol, but the
        # symbol is uniquely defined elsewhere -> point to the real owner.
        paths = {"libs/strategies/__init__.py": "id1"}
        defs = {"libs/strategies/momentum.py": {"MomentumStrategy"}}
        by_sym = {"MomentumStrategy": ["libs/strategies/momentum.py"]}
        target, symbol, conf = _resolve_reference(
            "libs.strategies.MomentumStrategy", paths, defs, by_sym
        )
        assert target == "libs/strategies/momentum.py"
        assert symbol == "MomentumStrategy"
        assert conf == CONFIDENCE_FILE_AND_SYMBOL

    def test_unresolved(self):
        assert _resolve_reference("nope.missing.Thing", {}, {}, {}) == (None, "", 0.0)


@pytest.fixture()
def graph():
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    yield store
    store.close()


def _make_file(store, path: str, language: str = "python") -> None:
    store.create_node(
        "File",
        {
            "id": f"file::{path}",
            "path": path,
            "language": language,
            "size": 1,
            "lastModified": "0",
            "lineCount": 1,
            "contentHash": "h",
        },
    )


def _make_class(store, name: str, file_path: str) -> None:
    store.create_node(
        "Class",
        {
            "id": f"class::{file_path}::{name}",
            "name": name,
            "filePath": file_path,
            "startLine": 1,
            "endLine": 2,
            "isExported": True,
        },
    )


class TestProcessConfigReferences:
    def _setup(self, store, tmp_path):
        code_path = "libs/strategies/momentum.py"
        cfg_path = "configs/strategy_registry.yaml"
        (tmp_path / "libs" / "strategies").mkdir(parents=True)
        (tmp_path / "libs" / "strategies" / "momentum.py").write_text(
            "class MomentumStrategy:\n    pass\n"
        )
        (tmp_path / "configs").mkdir(parents=True)
        (tmp_path / "configs" / "strategy_registry.yaml").write_text(
            "momentum:\n  class: libs.strategies.momentum.MomentumStrategy\n"
        )
        _make_file(store, code_path)
        _make_file(store, cfg_path, language="yaml")
        _make_class(store, "MomentumStrategy", code_path)
        return cfg_path, code_path

    def test_creates_edge_with_symbol_and_confidence(self, graph, tmp_path):
        cfg_path, code_path = self._setup(graph, tmp_path)

        result = process_config_references(graph, tmp_path)

        assert result["edges"] == 1
        assert result["config_files"] == 1
        rows = graph.query("SELECT src, dst, confidence, refKey, symbol FROM CONFIG_REFERENCES")
        assert len(rows) == 1
        row = rows[0]
        assert row["src"] == f"file::{cfg_path}"
        assert row["dst"] == f"file::{code_path}"
        assert row["confidence"] == CONFIDENCE_FILE_AND_SYMBOL
        assert row["symbol"] == "MomentumStrategy"

    def test_idempotent(self, graph, tmp_path):
        self._setup(graph, tmp_path)
        process_config_references(graph, tmp_path)
        process_config_references(graph, tmp_path)
        assert graph.edge_count("CONFIG_REFERENCES") == 1

    def test_removed_reference_is_pruned(self, graph, tmp_path):
        self._setup(graph, tmp_path)
        process_config_references(graph, tmp_path)
        assert graph.edge_count("CONFIG_REFERENCES") == 1

        # Remove the reference from the config and reprocess.
        (tmp_path / "configs" / "strategy_registry.yaml").write_text("momentum: {}\n")
        process_config_references(graph, tmp_path)
        assert graph.edge_count("CONFIG_REFERENCES") == 0

    def test_no_config_files(self, graph, tmp_path):
        _make_file(graph, "libs/strategies/momentum.py")
        result = process_config_references(graph, tmp_path)
        assert result["edges"] == 0
        assert result["config_files"] == 0
