# Learnings Tracker

## Pending Learnings

### L042-1
- Plan: 042
- Description: Cache invalidation on provider switch was missed. Router should clear cache when provider changes.
- Target: libs/data/router.py
- Status: pending

### L042-2
- Plan: 042
- Description: normalize_ohlcv should handle missing fields gracefully with defaults, not raise KeyError.
- Target: libs/data/normalizer.py
- Status: pending

### L055-1
- Plan: 055
- Description: MeanReversionStrategy history grows unbounded. Should cap at 2x window size.
- Target: libs/strategy/mean_reversion.py
- Status: pending

### L055-2
- Plan: 055
- Description: Strategy base class should track decision_id for traceability.
- Target: libs/strategy/base.py
- Status: incorporated

## Incorporated Learnings

### L042-3
- Plan: 042
- Description: Provider validate() should be called before first fetch.
- Target: libs/data/router.py
- Status: incorporated
