# Plan 012: Legacy Data Loader

## Metadata
- Status: Ready
- Type: feature
- Created: 2025-06-01
- Last Updated: 2025-06-15
- Architecture Layer(s): 1 (Data)
- Approval Required: No
- Breaking change: No

## Objective
Add a CSV data loader for historical backtesting.

## Non-Goals
- Real-time data

## File Impact Map

| File | Change Type | Notes |
|------|-------------|-------|
| libs/data/csv_loader.py | New | CSV parser |
| libs/data/router.py | Modify | Register CSV provider |
| tests/unit/test_csv_loader.py | New | Loader tests |

## Tests
- tests/unit/test_csv_loader.py
- Target coverage: 80%

## Execution Steps
- [ ] Step 1: Create CSVLoader class
- [ ] Step 2: Register in DataRouter
- [ ] Step 3: Write tests

## Validation
```bash
pytest tests/unit/test_csv_loader.py -v
```

## Rollback Plan
Remove csv_loader.py

## Risks & Mitigations
- Risk: Large file memory usage -> Mitigation: Streaming parser
