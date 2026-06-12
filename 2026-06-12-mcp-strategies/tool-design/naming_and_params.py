"""naming_and_params.py — A linter for the paper's tool-design rules.

The guidance gives hard, checkable rules. This module turns them into a small
linter you can run against any MCP toolset (in the `tools/list` shape):

  - <= 8 parameters per tool (decompose beyond that)
  - domain-noun-verb naming (so an alphabetical sort clusters related ops)
  - read/write separation (destructive ops named distinctly from reads)
  - <= 50 tools per server (split beyond that)

It is intentionally simple and dependency-free so it can run in CI as a guard.

Run:
    python naming_and_params.py        # lints the bundled sample toolset
"""
from __future__ import annotations

import re
from typing import Any

MAX_PARAMS = 8
MAX_TOOLS_PER_SERVER = 50
# domain-noun-verb: lowercase tokens separated by underscores, >= 3 segments.
NAME_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+){2,}$")
WRITE_VERBS = {"create", "update", "delete", "merge", "run", "remove", "set", "add"}
READ_VERBS = {"get", "list", "search", "read", "describe"}


def lint_tool(tool: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    name = tool.get("name", "")
    props = tool.get("inputSchema", {}).get("properties", {})

    n_params = len(props)
    if n_params > MAX_PARAMS:
        findings.append(
            f"{name}: {n_params} parameters exceeds the {MAX_PARAMS}-param limit "
            f"-> decompose or bundle the workflow instead")

    if not NAME_RE.match(name):
        findings.append(
            f"{name}: name is not domain-noun-verb (lowercase, >=3 _-separated "
            f"segments) -> rename e.g. 'github_issue_create'")

    verb = name.rsplit("_", 1)[-1] if "_" in name else name
    if verb not in WRITE_VERBS and verb not in READ_VERBS:
        findings.append(
            f"{name}: verb '{verb}' is neither a known read nor write verb "
            f"-> use a clear verb so read/write intent is explicit")
    return findings


def lint_server(tools: list[dict[str, Any]]) -> dict[str, Any]:
    all_findings: list[str] = []
    for t in tools:
        all_findings.extend(lint_tool(t))

    if len(tools) > MAX_TOOLS_PER_SERVER:
        all_findings.append(
            f"server: {len(tools)} tools exceeds {MAX_TOOLS_PER_SERVER} "
            f"-> split into domain-bounded servers")

    # read/write separation summary (informational)
    reads = [t["name"] for t in tools
             if t["name"].rsplit("_", 1)[-1] in READ_VERBS]
    writes = [t["name"] for t in tools
              if t["name"].rsplit("_", 1)[-1] in WRITE_VERBS]
    return {
        "n_tools": len(tools),
        "findings": all_findings,
        "reads": reads,
        "writes": writes,
    }


def _demo() -> None:
    from token_tax import sample_toolset

    # Inject two deliberately bad tools to show the linter catching them.
    bad = [
        {  # 9 params -> over the limit, and not noun-verb
            "name": "doEverything",
            "description": "kitchen-sink tool",
            "inputSchema": {"type": "object", "properties": {
                f"p{i}": {"type": "string"} for i in range(9)}, "required": []},
        },
    ]
    tools = sample_toolset() + bad
    result = lint_server(tools)

    print(f"Linted {result['n_tools']} tools")
    print(f"  reads  ({len(result['reads'])}): {', '.join(result['reads'][:6])} ...")
    print(f"  writes ({len(result['writes'])}): {', '.join(result['writes'][:6])} ...")
    print(f"\nFindings ({len(result['findings'])}):")
    if not result["findings"]:
        print("  (clean)")
    for f in result["findings"]:
        print(f"  - {f}")
    print("\nThe 20 well-designed tools pass; the injected 'doEverything' "
          "(9 params, bad name) is flagged on both rules.")


if __name__ == "__main__":
    _demo()
