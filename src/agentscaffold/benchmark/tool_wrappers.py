"""Container-local AgentScaffold tool wrapper scripts.

These are CLI stand-ins for the equipped benchmark arm. The container has no
MCP client, so each wrapper runs from ``/testbed`` (the copied task repo) and
calls the current ``scaffold`` CLI. Cwd is how 0.10+ resolves the project.
"""

from __future__ import annotations

_PREAMBLE = "#!/bin/bash\nset -euo pipefail\ncd /testbed\n"

SCAFFOLD_TOOL_SCRIPTS: dict[str, str] = {
    "scaffold-orient": _PREAMBLE + "scaffold graph orient\n",
    "scaffold-search": _PREAMBLE
    + """query="${1:-}"
if [ -z "$query" ]; then
  echo "Usage: scaffold-search <query>" >&2
  exit 2
fi
scaffold graph search "$query"
""",
    "scaffold-review": _PREAMBLE
    + """plan="${1:-}"
if [ -z "$plan" ]; then
  echo "Usage: scaffold-review <plan-number>" >&2
  exit 2
fi
scaffold review prepare "$plan"
""",
    "scaffold-impact": _PREAMBLE
    + """target="${1:-}"
if [ -z "$target" ]; then
  echo "Usage: scaffold-impact <file-or-symbol>" >&2
  exit 2
fi
scaffold graph impact "$target"
""",
}


def render_install_command() -> str:
    """Render a shell command that installs all wrapper scripts in a container."""

    chunks: list[str] = []
    for name, script in SCAFFOLD_TOOL_SCRIPTS.items():
        chunks.append(
            "cat << 'AGENTSCAFFOLD_SCRIPT_EOF' "
            f"> /usr/local/bin/{name}\n"
            f"{script.strip()}\n"
            "AGENTSCAFFOLD_SCRIPT_EOF\n"
            f"chmod +x /usr/local/bin/{name}"
        )
    return "\n".join(chunks)
