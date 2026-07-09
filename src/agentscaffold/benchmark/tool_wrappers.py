"""Container-local AgentScaffold tool wrapper scripts."""

from __future__ import annotations

SCAFFOLD_TOOL_SCRIPTS: dict[str, str] = {
    "scaffold-search": """#!/bin/bash
set -euo pipefail
query="${1:-}"
if [ -z "$query" ]; then
  echo "Usage: scaffold-search <query>" >&2
  exit 2
fi
cd /testbed
scaffold graph search "$query"
""",
    "scaffold-review": """#!/bin/bash
set -euo pipefail
plan="${1:-}"
if [ -z "$plan" ]; then
  echo "Usage: scaffold-review <plan-number-or-file>" >&2
  exit 2
fi
cd /testbed
scaffold review brief "$plan"
""",
    "scaffold-impact": """#!/bin/bash
set -euo pipefail
target="${1:-}"
if [ -z "$target" ]; then
  echo "Usage: scaffold-impact <symbol-or-path>" >&2
  exit 2
fi
cd /testbed
scaffold graph search "$target" --kind code --top 10
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
