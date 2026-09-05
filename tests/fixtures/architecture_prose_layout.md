# System Architecture -- prose layout (no Components Paths column)

Mirrors the rebellion-trading-system architecture doc: layer sections use
Purpose / Current State / Components tables without a Paths column, and
express locations as inline backticked paths.

## Layer 1: Data Foundation

### Purpose
Ingest and store market data.

### Components

| Component | Status | Plan(s) | Notes |
|-----------|--------|---------|-------|
| Market data adapters | Complete | 001 | See `data/adapters/` |
| Feature store | Complete | 110 | Feast views under `data/features/` |

## Layer 2: Alpha Generation

### Purpose
Generate per-asset trading signals.

### Current State: STRONG

See `libs/performance/` module and `libs/strategies/` for strategy classes.

### Components

| Component | Status | Plan(s) | Notes |
|-----------|--------|---------|-------|
| Strategy base classes | Complete | 001, 002 | AlphaStrategy |

## Layer 3: Alpha Combination & Strategy Selection

### Purpose
Combine signals.

**Location**: `libs/selection/`

### Components

| Component | Status | Notes |
|-----------|--------|-------|
| Selector | Complete | MaskablePPO |

## Layer 4: Portfolio Construction

**Paths**: `pipeline/portfolio_construction.py`, `libs/portfolio/`

### Components

| Component | Status | Notes |
|-----------|--------|-------|
| Optimizer | Complete | |

## Layer 5: Risk Management

Risk limits live in `libs/risk/` and `libs/risk/posture.py`.

## Layer 6: Execution

Order routing in `apps/execution/` and `pipeline/execution.py`.
