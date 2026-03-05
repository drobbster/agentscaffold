"""Tree-sitter S-expression queries for extracting definitions per language.

Each language has queries for functions, classes, methods, and interfaces.
Queries use tree-sitter's pattern matching syntax.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Python queries
# ---------------------------------------------------------------------------

PYTHON_FUNCTION_QUERY = """
(function_definition
  name: (identifier) @name
  parameters: (parameters) @params
) @definition
"""

PYTHON_CLASS_QUERY = """
(class_definition
  name: (identifier) @name
  superclasses: (argument_list)? @bases
) @definition
"""

PYTHON_METHOD_QUERY = """
(class_definition
  name: (identifier) @class_name
  body: (block
    (function_definition
      name: (identifier) @method_name
      parameters: (parameters) @params
    ) @method
  )
)
"""

PYTHON_IMPORT_QUERY = """
[
  (import_statement
    name: (dotted_name) @module
  )
  (import_from_statement
    module_name: (dotted_name) @module
    name: [
      (dotted_name) @name
      (aliased_import name: (dotted_name) @name)
    ]
  )
] @import
"""

PYTHON_CALL_QUERY = """
(call
  function: [
    (identifier) @func_name
    (attribute
      object: (_) @object
      attribute: (identifier) @method_name
    )
  ]
  arguments: (argument_list) @args
) @call
"""

# ---------------------------------------------------------------------------
# TypeScript / JavaScript queries
# ---------------------------------------------------------------------------

TS_FUNCTION_QUERY = """
[
  (function_declaration
    name: (identifier) @name
    parameters: (formal_parameters) @params
  ) @definition

  (lexical_declaration
    (variable_declarator
      name: (identifier) @name
      value: (arrow_function
        parameters: (formal_parameters) @params
      )
    )
  ) @definition

  (export_statement
    (function_declaration
      name: (identifier) @name
      parameters: (formal_parameters) @params
    )
  ) @definition

  (export_statement
    (lexical_declaration
      (variable_declarator
        name: (identifier) @name
        value: (arrow_function
          parameters: (formal_parameters) @params
        )
      )
    )
  ) @definition
]
"""

TS_CLASS_QUERY = """
[
  (class_declaration
    name: (type_identifier) @name
  ) @definition

  (export_statement
    (class_declaration
      name: (type_identifier) @name
    )
  ) @definition
]
"""

TS_METHOD_QUERY = """
(class_declaration
  name: (type_identifier) @class_name
  body: (class_body
    (method_definition
      name: (property_identifier) @method_name
      parameters: (formal_parameters) @params
    ) @method
  )
)
"""

TS_INTERFACE_QUERY = """
[
  (interface_declaration
    name: (type_identifier) @name
  ) @definition

  (export_statement
    (interface_declaration
      name: (type_identifier) @name
    )
  ) @definition
]
"""

TS_IMPORT_QUERY = """
(import_statement
  source: (string) @source
) @import
"""

TS_CALL_QUERY = """
(call_expression
  function: [
    (identifier) @func_name
    (member_expression
      object: (_) @object
      property: (property_identifier) @method_name
    )
  ]
  arguments: (arguments) @args
) @call
"""

# ---------------------------------------------------------------------------
# Query registry
# ---------------------------------------------------------------------------

QUERIES: dict[str, dict[str, str]] = {
    "python": {
        "functions": PYTHON_FUNCTION_QUERY,
        "classes": PYTHON_CLASS_QUERY,
        "methods": PYTHON_METHOD_QUERY,
        "imports": PYTHON_IMPORT_QUERY,
        "calls": PYTHON_CALL_QUERY,
    },
    "typescript": {
        "functions": TS_FUNCTION_QUERY,
        "classes": TS_CLASS_QUERY,
        "methods": TS_METHOD_QUERY,
        "interfaces": TS_INTERFACE_QUERY,
        "imports": TS_IMPORT_QUERY,
        "calls": TS_CALL_QUERY,
    },
    "javascript": {
        "functions": TS_FUNCTION_QUERY,
        "classes": TS_CLASS_QUERY,
        "methods": TS_METHOD_QUERY,
        "imports": TS_IMPORT_QUERY,
        "calls": TS_CALL_QUERY,
    },
}


def get_queries(language: str) -> dict[str, str] | None:
    """Return query dict for a language, or None if unsupported."""
    return QUERIES.get(language)


def supported_languages() -> list[str]:
    """Return list of languages with tree-sitter query support."""
    return list(QUERIES.keys())
