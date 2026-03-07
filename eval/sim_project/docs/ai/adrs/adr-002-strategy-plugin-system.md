# ADR-2: Strategy Plugin System

## Status

Accepted

## Date

2025-11-20

## Context

New trading strategies need to be added frequently. A monolithic approach makes it
difficult to test individual strategies in isolation.

## Decision

Use an abstract base class pattern with a plugin registry for strategy discovery.
Each strategy implements BaseStrategy and is registered via entry points.

## Consequences

- Easy to add new strategies without modifying core code
- Each strategy can be tested independently
- Slightly more complex initialization

## Related

Related Plans: Plan 55
Related ADRs: ADR-1
