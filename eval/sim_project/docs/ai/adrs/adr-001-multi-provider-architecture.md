# ADR-1: Multi-Provider Data Architecture

## Status

Accepted

## Date

2025-10-15

## Context

The system needs to support multiple data providers (Alpaca, Polygon) with failover
capability. A single-provider approach limits reliability and data coverage.

## Decision

Adopt a multi-provider architecture with a DataRouter that can switch between providers
based on availability and data type requirements.

## Consequences

- Increased complexity in the data layer
- Better reliability through failover
- Ability to compare data quality across providers

## Related

Related Plans: Plan 42, Plan 55
Related ADRs: ADR-2

## Supporting Evidence

Cache TTL study STU-2026-01-15-cache-ttl-comparison validated the caching approach.
