# Changelog

All notable changes to AgentScaffold are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to semantic versioning (pre-1.0: minor versions may
introduce additive features and small behavior changes).

## [0.4.1] - 2026-06-12

### Fixed
- README documentation links now use absolute GitHub URLs instead of relative paths,
  so they resolve correctly on the PyPI project page (relative links rendered dead on
  PyPI because they resolved against pypi.org rather than the repository).

## [0.4.0] - 2026-06-12

### Added
- **Cursor native hooks** (`scaffold agents hooks --platform cursor`): generates
  `.cursor/hooks.json` plus an `afterFileEdit` wrapper that keeps the knowledge graph
  fresh by running `scaffold index --incremental`. The wrapper is non-blocking and
  single-flight with a coalescing debounce, so rapid multi-file edits never stack and
  Cursor is never blocked.
- **Config-reference indexing** (Plan 216): a new `CONFIG_REFERENCES` graph edge links
  config files (YAML/JSON/TOML) to the code they wire dynamically. References are
  extracted only under an allowlist of keys (`class`, `_target_`, `type`, ...) and
  resolved to files/classes (confidence 0.9 for file+symbol, 0.7 for file-only). Config
  consumers now appear in `scaffold_impact` and `scaffold_context`, closing part of the
  config-driven-dispatch blind spot (e.g. editing a strategy class now shows
  `strategy_registry.yaml` as a dependent).
- **Graph coverage signaling** (Plan 214): `scaffold_orient` reports repository parse
  coverage; `scaffold_impact` / `scaffold_context` attach a coverage caveat when a target
  is in an unparsed language or returns no results, so absence of edges is not mistaken
  for absence of relationships. Generated agent rules include a "graph trust discipline"
  section.
- **Edge-confidence surfacing** (Plan 215): heuristic (low-confidence) call edges are
  annotated in tool markdown and counted (`heuristic_caller_count`), distinguishing
  guessed dispatch edges from resolved ones. `scaffold validate --check coverage` returns
  an on-demand coverage audit.
- **ReviewFinding ingestion** (Plans 212/213): `[CATEGORY]` markers in plan text are
  parsed into `ReviewFinding` nodes during governance indexing (widened matcher, severity
  support), with findings linked to the files they reference.
- **Incremental governance freshness gate** (Plan 213): governance documents are
  fingerprinted so a code-only edit skips the governance reingest while a doc edit forces
  a refresh.

### Changed
- **Default graph path is now `.scaffold/graph.duckdb`** (was `.scaffold/graph.db`) to
  reflect the DuckDB + DuckPGQ backend. Existing `.scaffold/graph.db` files can be deleted;
  `scaffold index` rebuilds the graph (it is a derived cache).
- **KuzuDB backend fully removed.** DuckDB + DuckPGQ is the only supported backend;
  `open_graph()` rejects any other `graph.backend` value. (See ADR-023 update.)
- Graph schema bumped to version 7 (new `CONFIG_REFERENCES` edge). The graph rebuilds
  automatically on first run after upgrade.
- `scaffold import --format claude` now reports clearly that Claude import is not yet
  supported instead of writing a placeholder file that looked like a successful import.

### Fixed
- Graph integrity and agent-facing rendering (Plan 212): query alias prefixes are stripped
  from tool output and relationships render as readable markdown.
- `__version__` was stale (`0.2.4`) and out of sync with the packaged version; both are now
  `0.4.0`.
- Documentation corrected across README, getting-started, user-guide, platform-integration,
  and ci-integration to reference the DuckPGQ graph at `.scaffold/graph.duckdb`.

## [0.3.1] - prior

Baseline prior to this changelog. See git history for details.
