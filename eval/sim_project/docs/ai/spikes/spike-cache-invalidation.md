# Spike: Cache Invalidation on Provider Switch

| Field       | Value           |
|-------------|-----------------|
| Parent Plan | Plan 42         |
| Status      | Complete        |
| Created     | 2025-10-20      |
| Time-box    | 4 hours         |

## Hypothesis

When the DataRouter switches from one provider to another, stale cache entries from
the previous provider may cause incorrect data to be served.

## Approach

1. Write a test that populates cache with Provider A data
2. Switch router to Provider B
3. Verify whether stale Provider A data is returned

## Findings

Confirmed: cache entries are keyed by symbol only, not by provider.
Provider switch without cache clear returns stale data from previous provider.

## Decision

Add provider prefix to cache keys (e.g., `alpaca::AAPL`) so each provider
maintains its own namespace. This also enables comparison across providers
without cache conflicts.
