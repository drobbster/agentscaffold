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
# Go queries
# ---------------------------------------------------------------------------

GO_FUNCTION_QUERY = """
(function_declaration
  name: (identifier) @name
  parameters: (parameter_list) @params
) @definition
"""

GO_METHOD_QUERY = """
(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: [
        (pointer_type (type_identifier) @class_name)
        (type_identifier) @class_name
      ]
    )
  )
  name: (field_identifier) @method_name
  parameters: (parameter_list) @params
) @method
"""

GO_STRUCT_QUERY = """
(type_declaration
  (type_spec
    name: (type_identifier) @name
    type: (struct_type)
  )
) @definition
"""

GO_INTERFACE_QUERY = """
(type_declaration
  (type_spec
    name: (type_identifier) @name
    type: (interface_type)
  )
) @definition
"""

GO_IMPORT_QUERY = """
[
  (import_declaration
    (import_spec
      path: (interpreted_string_literal) @source
    )
  )
  (import_declaration
    (import_spec_list
      (import_spec
        path: (interpreted_string_literal) @source
      )
    )
  )
] @import
"""

GO_CALL_QUERY = """
(call_expression
  function: [
    (identifier) @func_name
    (selector_expression
      operand: (_) @object
      field: (field_identifier) @method_name
    )
  ]
  arguments: (argument_list) @args
) @call
"""

# ---------------------------------------------------------------------------
# Rust queries
# ---------------------------------------------------------------------------

RUST_FUNCTION_QUERY = """
(function_item
  name: (identifier) @name
  parameters: (parameters) @params
) @definition
"""

RUST_STRUCT_QUERY = """
(struct_item
  name: (type_identifier) @name
) @definition
"""

RUST_IMPL_METHOD_QUERY = """
(impl_item
  type: (type_identifier) @class_name
  body: (declaration_list
    (function_item
      name: (identifier) @method_name
      parameters: (parameters) @params
    ) @method
  )
)
"""

RUST_TRAIT_QUERY = """
(trait_item
  name: (type_identifier) @name
) @definition
"""

RUST_CALL_QUERY = """
(call_expression
  function: [
    (identifier) @func_name
    (field_expression
      value: (_) @object
      field: (field_identifier) @method_name
    )
    (scoped_identifier
      name: (identifier) @func_name
    )
  ]
  arguments: (arguments) @args
) @call
"""

# ---------------------------------------------------------------------------
# Java queries
# ---------------------------------------------------------------------------

JAVA_METHOD_QUERY = """
(class_declaration
  name: (identifier) @class_name
  body: (class_body
    (method_declaration
      name: (identifier) @method_name
      parameters: (formal_parameters) @params
    ) @method
  )
)
"""

JAVA_CLASS_QUERY = """
(class_declaration
  name: (identifier) @name
) @definition
"""

JAVA_INTERFACE_QUERY = """
(interface_declaration
  name: (identifier) @name
) @definition
"""

JAVA_IMPORT_QUERY = """
(import_declaration
  (scoped_identifier) @source
) @import
"""

JAVA_CALL_QUERY = """
(method_invocation
  name: (identifier) @func_name
  arguments: (argument_list) @args
) @call
"""

# ---------------------------------------------------------------------------
# C queries
# ---------------------------------------------------------------------------

C_FUNCTION_QUERY = """
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name
    parameters: (parameter_list) @params
  )
) @definition
"""

C_STRUCT_QUERY = """
(struct_specifier
  name: (type_identifier) @name
) @definition
"""

C_CALL_QUERY = """
(call_expression
  function: (identifier) @func_name
  arguments: (argument_list) @args
) @call
"""

# ---------------------------------------------------------------------------
# C++ queries (extends C with classes/methods)
# ---------------------------------------------------------------------------

CPP_FUNCTION_QUERY = C_FUNCTION_QUERY

CPP_CLASS_QUERY = """
(class_specifier
  name: (type_identifier) @name
) @definition
"""

CPP_METHOD_QUERY = """
(class_specifier
  name: (type_identifier) @class_name
  body: (field_declaration_list
    (function_definition
      declarator: (function_declarator
        declarator: (field_identifier) @method_name
        parameters: (parameter_list) @params
      )
    ) @method
  )
)
"""

CPP_STRUCT_QUERY = C_STRUCT_QUERY

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
    "go": {
        "functions": GO_FUNCTION_QUERY,
        "classes": GO_STRUCT_QUERY,
        "methods": GO_METHOD_QUERY,
        "interfaces": GO_INTERFACE_QUERY,
        "imports": GO_IMPORT_QUERY,
        "calls": GO_CALL_QUERY,
    },
    "rust": {
        "functions": RUST_FUNCTION_QUERY,
        "classes": RUST_STRUCT_QUERY,
        "methods": RUST_IMPL_METHOD_QUERY,
        "interfaces": RUST_TRAIT_QUERY,
        "calls": RUST_CALL_QUERY,
    },
    "java": {
        "classes": JAVA_CLASS_QUERY,
        "methods": JAVA_METHOD_QUERY,
        "interfaces": JAVA_INTERFACE_QUERY,
        "imports": JAVA_IMPORT_QUERY,
        "calls": JAVA_CALL_QUERY,
    },
    "c": {
        "functions": C_FUNCTION_QUERY,
        "classes": C_STRUCT_QUERY,
        "calls": C_CALL_QUERY,
    },
    "cpp": {
        "functions": CPP_FUNCTION_QUERY,
        "classes": CPP_CLASS_QUERY,
        "methods": CPP_METHOD_QUERY,
        "calls": C_CALL_QUERY,
    },
}


def get_queries(language: str) -> dict[str, str] | None:
    """Return query dict for a language, or None if unsupported."""
    return QUERIES.get(language)


def supported_languages() -> list[str]:
    """Return list of languages with tree-sitter query support."""
    return list(QUERIES.keys())
