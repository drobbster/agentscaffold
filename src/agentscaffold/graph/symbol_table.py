"""In-memory symbol table for cross-file resolution.

The symbol table maps symbol names to their defining locations, supporting
import and call resolution with confidence scoring.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SymbolEntry:
    """A symbol definition in the codebase."""

    name: str
    qualified_name: str
    file_path: str
    file_id: str
    node_id: str
    node_type: str  # "function", "class", "method", "interface"
    is_exported: bool = False
    class_name: str | None = None
    start_line: int = 0


class SymbolTable:
    """Bidirectional symbol index for resolution.

    Supports lookup by:
    - Simple name (e.g., "fetch") -> may return multiple matches
    - Qualified name (e.g., "libs.data.router.DataRouter.fetch") -> unique
    - File path + name -> symbols defined in a specific file
    """

    def __init__(self) -> None:
        self._by_name: dict[str, list[SymbolEntry]] = {}
        self._by_qualified: dict[str, SymbolEntry] = {}
        self._by_file: dict[str, list[SymbolEntry]] = {}
        self._module_exports: dict[str, list[str]] = {}

    def add(self, entry: SymbolEntry) -> None:
        """Register a symbol."""
        self._by_name.setdefault(entry.name, []).append(entry)
        self._by_qualified[entry.qualified_name] = entry
        self._by_file.setdefault(entry.file_path, []).append(entry)

    def register_module_exports(self, file_path: str, names: list[str]) -> None:
        """Register names exported by a module (from __all__ or export statements)."""
        self._module_exports[file_path] = names

    def lookup_name(self, name: str) -> list[SymbolEntry]:
        """Find all symbols with a given simple name."""
        return self._by_name.get(name, [])

    def lookup_qualified(self, qualified_name: str) -> SymbolEntry | None:
        """Find a symbol by its fully qualified name."""
        return self._by_qualified.get(qualified_name)

    def lookup_in_file(self, file_path: str) -> list[SymbolEntry]:
        """Find all symbols defined in a file."""
        return self._by_file.get(file_path, [])

    def lookup_class_method(self, class_name: str, method_name: str) -> list[SymbolEntry]:
        """Find methods of a given class name."""
        results = []
        for entry in self._by_name.get(method_name, []):
            if entry.class_name == class_name:
                results.append(entry)
        return results

    def get_module_exports(self, file_path: str) -> list[str] | None:
        """Return explicit exports for a module, or None if unknown."""
        return self._module_exports.get(file_path)

    def all_files(self) -> set[str]:
        """Return set of all file paths with registered symbols."""
        return set(self._by_file.keys())

    @property
    def total_symbols(self) -> int:
        return len(self._by_qualified)

    def __len__(self) -> int:
        return self.total_symbols
