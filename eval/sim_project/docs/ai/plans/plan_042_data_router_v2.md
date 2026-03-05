# Plan 042: Data Router V2

## Metadata
- Status: Complete
- Type: feature
- Created: 2025-11-01
- Last Updated: 2025-11-15
- Architecture Layer(s): 1 (Data)
- Approval Required: No
- Breaking change: No

## Objective
Refactor DataRouter to support multiple providers and add caching layer.

## Non-Goals
- Real-time streaming data
- Historical data backfill

## File Impact Map

| File | Change Type | Notes |
|------|-------------|-------|
| libs/data/router.py | Modify | Add multi-provider support |
| libs/data/cache.py | New | TTL-based caching |
| libs/data/providers/base.py | New | Provider interface |
| libs/data/providers/alpaca.py | New | Alpaca implementation |
| libs/data/providers/polygon.py | New | Polygon implementation |
| tests/unit/test_router.py | New | Router unit tests |
| tests/unit/test_cache.py | New | Cache unit tests |

## Tests
- tests/unit/test_router.py
- tests/unit/test_cache.py
- Target coverage: 90%

## Execution Steps
- [x] Step 1: Create BaseProvider interface
- [x] Step 2: Implement AlpacaProvider
- [x] Step 3: Implement PolygonProvider
- [x] Step 4: Add DataCache with TTL
- [x] Step 5: Refactor DataRouter
- [x] Step 6: Write tests

## Validation
```bash
pytest tests/unit/test_router.py tests/unit/test_cache.py -v
ruff check libs/data/
```

## Rollback Plan
Revert to single-provider DataRouter.

## Risks & Mitigations
- Risk: Cache staleness -> Mitigation: TTL-based expiry
