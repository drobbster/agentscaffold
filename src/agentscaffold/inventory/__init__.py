"""System inventory and component lifecycle (Plan 282, ADR-029).

Implements ``docs/ai/contracts/system_inventory_interface.md`` v1: the declared
list of what a project runs, collectors that list what its repository files
declare, the INV-001..INV-010 checks, and the optional health snapshot.
"""

from __future__ import annotations

from agentscaffold.inventory.schema import (
    KINDS,
    LIFECYCLES,
    Component,
    Inventory,
    InventoryError,
    load_inventory,
)

__all__ = [
    "KINDS",
    "LIFECYCLES",
    "Component",
    "Inventory",
    "InventoryError",
    "load_inventory",
]
