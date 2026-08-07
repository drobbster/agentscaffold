import json

from tests.fixtures.multiproject import BETA


def test_inspect_failures(two_project_workspace):
    from agentscaffold.mcp.server import _dispatch_tool

    wp = str(two_project_workspace.source_file(BETA))

    print("\n##### prior_experiments from BETA, FOREIGN plan 101 #####")
    r = _dispatch_tool("scaffold_prior_experiments", {"plan_number": 101, "working_path": wp})
    print(json.dumps({k: v for k, v in r.items() if k != "meta"}, default=str, indent=2)[:900])

    print("\n##### prior_experiments from BETA, OWN plan 202 #####")
    r = _dispatch_tool("scaffold_prior_experiments", {"plan_number": 202, "working_path": wp})
    print(json.dumps({k: v for k, v in r.items() if k != "meta"}, default=str, indent=2)[:900])

    print("\n##### prepare_retro from BETA, OWN plan 202 #####")
    r = _dispatch_tool("scaffold_prepare_retro", {"plan_number": 202, "working_path": wp})
    text = json.dumps({k: v for k, v in r.items() if k != "meta"}, default=str)
    idx = text.lower().find("not found")
    print("contains 'not found' at", idx)
    print("context:", text[max(0, idx - 300) : idx + 200] if idx >= 0 else "n/a")
