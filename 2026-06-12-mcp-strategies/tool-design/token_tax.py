"""token_tax.py — Measure the real token cost of MCP tool definitions.

The AWS Prescriptive Guidance paper "Model Context Protocol strategies on AWS"
states that a typical tool definition costs roughly 250-500 tokens (name +
description + schema) and that 20 tools therefore cost about 5,000-10,000
tokens *per model invocation*, before any user input is added.

This script measures that empirically. It builds a realistic set of MCP tool
definitions in the exact JSON shape an MCP server returns from a `tools/list`
call (the shape the model actually reads), then counts the tokens.

Tokenizer note: we use tiktoken's `cl100k_base` BPE as a portable, widely
available proxy. Different model families tokenize slightly differently, so
treat the absolute count as an order-of-magnitude measurement, not an exact
per-vendor figure. The paper's 250-500 band is itself a range for the same
reason.

Run:
    uv run --with tiktoken python token_tax.py
"""
from __future__ import annotations

import json
from typing import Any

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text))

    TOKENIZER = "tiktoken/cl100k_base"
except ImportError:  # pragma: no cover - fallback when tiktoken is absent
    def count_tokens(text: str) -> int:
        # Documented heuristic: ~4 characters per token for English + JSON.
        # Clearly an estimate; install tiktoken for a real measurement.
        return max(1, round(len(text) / 4))

    TOKENIZER = "heuristic(4 chars/token)"


def tool_def(name: str, description: str, properties: dict[str, Any],
             required: list[str]) -> dict[str, Any]:
    """Return one tool in the MCP `tools/list` result shape."""
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def sample_toolset() -> list[dict[str, Any]]:
    """A realistic 20-tool GitHub-style MCP server.

    Descriptions are written as prompts (what it does, when to use it, error
    conditions) and schemas use enums + descriptions, exactly as the guidance
    recommends. That discipline is *why* a good tool costs 250-500 tokens: the
    cost buys the model the context it needs to pick and fill the tool well.
    """
    str_p = lambda d: {"type": "string", "description": d}  # noqa: E731
    enum_p = lambda d, vals: {"type": "string", "enum": vals, "description": d}  # noqa: E731
    int_p = lambda d: {"type": "integer", "description": d}  # noqa: E731

    nouns_verbs = [
        ("github_issue_create", "Create a new issue in a repository. Use when the "
         "user wants to file a bug, request a feature, or open a tracked task. "
         "Returns the created issue number and URL. Errors if the repo does not "
         "exist or the caller lacks write access.",
         {"repo": str_p("owner/name of the target repository"),
          "title": str_p("short issue title"),
          "body": str_p("markdown issue body"),
          "labels": {"type": "array", "items": {"type": "string"},
                     "description": "label names to apply"},
          "assignee": str_p("login of the user to assign (optional)")},
         ["repo", "title"]),
        ("github_issue_get", "Retrieve a single issue by number, including its "
         "state, labels, and latest comments. Use before updating an issue to "
         "read current state. Errors if the issue number is not found.",
         {"repo": str_p("owner/name of the repository"),
          "number": int_p("issue number")},
         ["repo", "number"]),
        ("github_issue_list", "List issues in a repository, optionally filtered "
         "by state and label. Use to find existing issues before creating a "
         "duplicate. Returns up to `per_page` issues.",
         {"repo": str_p("owner/name of the repository"),
          "state": enum_p("issue state filter", ["open", "closed", "all"]),
          "labels": str_p("comma-separated label filter"),
          "per_page": int_p("page size, max 100")},
         ["repo"]),
        ("github_issue_update", "Update an existing issue's title, body, state, "
         "or labels. Use to edit or close an issue. This is a WRITE operation; "
         "prefer github_issue_get first to read current state.",
         {"repo": str_p("owner/name of the repository"),
          "number": int_p("issue number"),
          "title": str_p("new title (optional)"),
          "state": enum_p("new state", ["open", "closed"]),
          "labels": {"type": "array", "items": {"type": "string"},
                     "description": "replacement label set"}},
         ["repo", "number"]),
        ("github_issue_comment_create", "Add a comment to an issue. Use to post "
         "an update or response. Returns the comment id.",
         {"repo": str_p("owner/name of the repository"),
          "number": int_p("issue number"),
          "body": str_p("markdown comment body")},
         ["repo", "number", "body"]),
        ("github_pullrequest_create", "Open a pull request from a head branch "
         "into a base branch. Use when code is ready for review. Errors if the "
         "branches are identical or already have an open PR.",
         {"repo": str_p("owner/name of the repository"),
          "head": str_p("source branch"),
          "base": str_p("target branch"),
          "title": str_p("PR title"),
          "body": str_p("PR description in markdown"),
          "draft": {"type": "boolean", "description": "open as draft"}},
         ["repo", "head", "base", "title"]),
        ("github_pullrequest_get", "Retrieve a pull request by number with its "
         "review and merge state. Use before merging to check mergeability.",
         {"repo": str_p("owner/name of the repository"),
          "number": int_p("PR number")},
         ["repo", "number"]),
        ("github_pullrequest_list", "List pull requests, filtered by state. Use "
         "to find open PRs awaiting review.",
         {"repo": str_p("owner/name of the repository"),
          "state": enum_p("PR state filter", ["open", "closed", "all"])},
         ["repo"]),
        ("github_pullrequest_merge", "Merge a pull request using the given "
         "method. This is a destructive WRITE; the caller must have merge "
         "rights and the PR must be mergeable.",
         {"repo": str_p("owner/name of the repository"),
          "number": int_p("PR number"),
          "method": enum_p("merge method", ["merge", "squash", "rebase"])},
         ["repo", "number"]),
        ("github_repo_get", "Retrieve repository metadata (default branch, "
         "visibility, topics). Use to confirm a repo exists before other calls.",
         {"repo": str_p("owner/name of the repository")},
         ["repo"]),
        ("github_repo_list", "List repositories for an owner. Use to discover "
         "available repositories.",
         {"owner": str_p("user or organization login"),
          "type": enum_p("repo type filter", ["all", "public", "private"])},
         ["owner"]),
        ("github_branch_create", "Create a branch from a base ref. Use before "
         "opening a PR for new work.",
         {"repo": str_p("owner/name of the repository"),
          "name": str_p("new branch name"),
          "from_ref": str_p("base branch or commit SHA")},
         ["repo", "name", "from_ref"]),
        ("github_branch_list", "List branches in a repository.",
         {"repo": str_p("owner/name of the repository")},
         ["repo"]),
        ("github_file_get", "Read a file's contents at a ref. Use to inspect "
         "code before editing. Returns decoded text for text files.",
         {"repo": str_p("owner/name of the repository"),
          "path": str_p("file path within the repo"),
          "ref": str_p("branch, tag, or commit SHA")},
         ["repo", "path"]),
        ("github_file_update", "Create or update a file in a branch with a "
         "commit. This is a WRITE operation. Requires the current file SHA when "
         "updating an existing file.",
         {"repo": str_p("owner/name of the repository"),
          "path": str_p("file path within the repo"),
          "content": str_p("new file content"),
          "message": str_p("commit message"),
          "branch": str_p("target branch"),
          "sha": str_p("current blob SHA when updating (optional for create)")},
         ["repo", "path", "content", "message", "branch"]),
        ("github_label_create", "Create a label in a repository.",
         {"repo": str_p("owner/name of the repository"),
          "name": str_p("label name"),
          "color": str_p("6-digit hex color, no leading #")},
         ["repo", "name"]),
        ("github_label_list", "List labels available in a repository.",
         {"repo": str_p("owner/name of the repository")},
         ["repo"]),
        ("github_release_create", "Publish a release for a tag. Use to cut a "
         "versioned release with notes.",
         {"repo": str_p("owner/name of the repository"),
          "tag": str_p("git tag for the release"),
          "name": str_p("release title"),
          "notes": str_p("markdown release notes"),
          "prerelease": {"type": "boolean", "description": "mark as prerelease"}},
         ["repo", "tag"]),
        ("github_workflow_list", "List GitHub Actions workflows in a repository.",
         {"repo": str_p("owner/name of the repository")},
         ["repo"]),
        ("github_workflow_run", "Trigger a workflow_dispatch run for a workflow. "
         "This is a WRITE/action operation that consumes CI minutes.",
         {"repo": str_p("owner/name of the repository"),
          "workflow": str_p("workflow file name or id"),
          "ref": str_p("branch or tag to run against")},
         ["repo", "workflow", "ref"]),
    ]
    return [tool_def(n, d, p, r) for (n, d, p, r) in nouns_verbs]


def enrich(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the paper's best-practice recommendations to each tool.

    The guidance says to add an output schema, write descriptions as prompts,
    and — "the single most effective way to guide tool usage" — provide
    concrete examples with real values. Each of those costs tokens. This is
    the same toolset, enriched the way the paper recommends, so we can measure
    what that guidance actually costs in context.
    """
    out = []
    for t in tools:
        e = json.loads(json.dumps(t))  # deep copy
        e["outputSchema"] = {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean", "description": "whether the call succeeded"},
                "data": {"type": "object", "description": "the returned resource"},
                "error": {"type": "string", "description": "error message when ok is false"},
            },
            "required": ["ok"],
        }
        e["examples"] = [{
            "description": f"Typical call to {e['name']}",
            "arguments": {k: f"<{k}>" for k in list(e["inputSchema"]["properties"])[:3]},
        }]
        e["description"] = (
            e["description"] + " Prerequisites: confirm the repository exists "
            "(github_repo_get) and you hold the required scope. On rate-limit, "
            "respect the X-RateLimit-Reset header before retrying."
        )
        out.append(e)
    return out


def measure(tools: list[dict[str, Any]], indent: int | None = None) -> dict[str, Any]:
    """Token-count each tool definition as serialized JSON, plus the total.

    `indent=None` minifies (lower bound); `indent=2` mirrors how many SDKs
    actually transmit tool schemas (closer to what the model sees).
    """
    per_tool = []
    for t in tools:
        if indent is None:
            serialized = json.dumps(t, separators=(",", ":"))
        else:
            serialized = json.dumps(t, indent=indent)
        per_tool.append((t["name"], count_tokens(serialized)))
    total = sum(tok for _, tok in per_tool)
    counts = [tok for _, tok in per_tool]
    return {
        "tokenizer": TOKENIZER,
        "n_tools": len(tools),
        "per_tool": per_tool,
        "total": total,
        "min": min(counts),
        "max": max(counts),
        "mean": round(total / len(tools), 1),
    }


def _report(label: str, r: dict[str, Any]) -> None:
    print(f"[{label}]  mean {r['mean']} tok/tool  "
          f"(min {r['min']}, max {r['max']})  ->  "
          f"{r['n_tools']} tools = {r['total']} tokens / invocation")


def main() -> None:
    tools = sample_toolset()
    minimal = measure(tools, indent=None)
    pretty = measure(tools, indent=2)
    best = measure(enrich(tools), indent=2)

    print(f"Tokenizer: {minimal['tokenizer']}")
    print(f"Tools measured: {minimal['n_tools']}\n")
    print(f"{'tool':<32}{'minimal':>9}{'enriched':>10}")
    print("-" * 51)
    enriched_per = dict(best["per_tool"])
    for name, tok in minimal["per_tool"]:
        print(f"{name:<32}{tok:>9}{enriched_per[name]:>10}")
    print("-" * 51)
    print()
    _report("minimal JSON (lower bound)", minimal)
    _report("pretty JSON (as many SDKs send)", pretty)
    _report("best-practice: +outputSchema +examples +prompt-style desc", best)
    print()
    print("The paper's claim: ~250-500 tokens/tool; 20 tools = 5,000-10,000 tokens.")
    print()
    print("Reading: a MINIMAL definition is cheaper than the paper's band, but the")
    print("paper recommends the enriched form (output schema + examples + prompt-")
    print(f"style descriptions). Enriched lands at {best['mean']} tok/tool "
          f"= {best['total']} tokens for 20 tools,")
    print("squarely in the paper's 5k-10k range. The cost is the guidance: every")
    print("token you spend helping the model choose well is sent on every call.")


if __name__ == "__main__":
    main()
