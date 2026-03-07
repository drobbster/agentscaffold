---
study_id: STU-2026-01-15-cache-ttl-comparison
title: Cache TTL vs LRU Eviction Strategy Comparison
study_type: ab_comparison
status: complete
outcome: variant_preferred
confidence: high
tags:
  - caching
  - performance
  - data
related_plans:
  - 42
started: "2026-01-15"
completed: "2026-01-17"
artifacts:
  - path: libs/data/cache.py
---

# Cache TTL vs LRU Eviction Strategy Comparison

## Overview

Compared TTL-based cache eviction (Plan 042 approach) with LRU eviction to determine
which strategy provides better hit rates for market data workloads.

## Variants

### A: TTL-based eviction (baseline)
- Fixed 60-second TTL for all entries
- MLflow run: `run-ttl-001`

### B: LRU eviction (variant)
- LRU with 1000-entry cap
- MLflow run: `run-lru-001`

## Results

| Metric          | TTL (A) | LRU (B) |
|-----------------|---------|---------|
| Hit rate        | 72%     | 85%     |
| Avg latency ms  | 12      | 8       |
| Memory peak MB  | 45      | 62      |

## Decision

LRU variant preferred for higher hit rate, though with slightly more memory usage.
The memory trade-off is acceptable for the expected workload.
