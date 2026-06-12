"""github_tools.py — Granular vs coarse-grained tools, the GitHub-issue example.

The AWS guidance frames the central tool-design tension as granularity. A
*granular* (tool-per-API) design exposes create_issue, add_label, and
assign_issue as three separate tools; the model must orchestrate all three,
paying a model round-trip for each. A *coarse-grained* (workflow-driven) design
exposes one tool that does the whole "file and triage an issue" workflow
deterministically inside the tool — one model call, the orchestration hidden.

The paper's rule: if a common workflow needs 3+ separate calls, bundle them
into one tool. This file implements both designs against a mock backend so you
can run it and SEE the difference in model-visible calls.

These functions are decorated with Strands Agents' `@tool` where available, so
the same code is a real MCP-style tool. The decorator import is guarded so the
demo runs even without the SDK installed.

Run (standalone demo):
    uv run --with strands-agents python github_tools.py
    # or, without the SDK (still runs the mock comparison):
    python github_tools.py
"""
from __future__ import annotations

from typing import Any

try:
    from strands import tool  # type: ignore
    HAVE_STRANDS = True
except ImportError:  # pragma: no cover
    HAVE_STRANDS = False

    def tool(fn=None, **_kwargs):  # minimal no-op fallback decorator
        def wrap(f):
            return f
        return wrap(fn) if callable(fn) else wrap


# --- Mock backend: counts the API calls a real GitHub server would make. -----
class MockGitHub:
    def __init__(self) -> None:
        self.api_calls: list[str] = []
        self._next_issue = 100

    def create_issue(self, repo: str, title: str, body: str = "") -> dict[str, Any]:
        self.api_calls.append("POST /issues")
        num = self._next_issue
        self._next_issue += 1
        return {"number": num, "title": title, "url": f"https://example/{repo}/issues/{num}"}

    def add_labels(self, repo: str, number: int, labels: list[str]) -> dict[str, Any]:
        self.api_calls.append("POST /issues/labels")
        return {"number": number, "labels": labels}

    def assign(self, repo: str, number: int, assignee: str) -> dict[str, Any]:
        self.api_calls.append("POST /issues/assignees")
        return {"number": number, "assignee": assignee}


BACKEND = MockGitHub()


# --- Granular design: three tools the MODEL must sequence itself. ------------
@tool
def github_issue_create(repo: str, title: str, body: str = "") -> dict[str, Any]:
    """Create an issue. Returns the new issue number. (Granular: model must
    then call github_issue_add_label and github_issue_assign separately.)"""
    return BACKEND.create_issue(repo, title, body)


@tool
def github_issue_add_label(repo: str, number: int, labels: list[str]) -> dict[str, Any]:
    """Add labels to an existing issue. (Granular.)"""
    return BACKEND.add_labels(repo, number, labels)


@tool
def github_issue_assign(repo: str, number: int, assignee: str) -> dict[str, Any]:
    """Assign an issue to a user. (Granular.)"""
    return BACKEND.assign(repo, number, assignee)


# --- Coarse-grained design: one tool, deterministic orchestration inside. ----
@tool
def github_issue_file_and_triage(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    assignee: str | None = None,
) -> dict[str, Any]:
    """File an issue and triage it in one step: create it, apply labels, and
    assign it. Use when a user reports a bug or requests work that should be
    tracked and routed immediately. The create -> label -> assign sequence runs
    deterministically inside the tool, so the model makes ONE call instead of
    three. Returns the created issue with its applied labels and assignee.

    This is the paper's recommendation in action: a workflow that needs 3+
    calls is bundled into a single tool. Note it stays within the 8-parameter
    limit (5 params)."""
    issue = BACKEND.create_issue(repo, title, body)
    if labels:
        BACKEND.add_labels(repo, issue["number"], labels)
        issue["labels"] = labels
    if assignee:
        BACKEND.assign(repo, issue["number"], assignee)
        issue["assignee"] = assignee
    return issue


def _demo() -> None:
    print(f"Strands SDK available: {HAVE_STRANDS}\n")

    # Granular: the model would emit three separate tool calls.
    BACKEND.api_calls.clear()
    issue = github_issue_create("octo/demo", "Login button is misaligned",
                                "On mobile the button overlaps the footer.")
    github_issue_add_label("octo/demo", issue["number"], ["bug", "ui"])
    github_issue_assign("octo/demo", issue["number"], "maintainer")
    granular_model_calls = 3  # the model issued 3 tool calls
    print("GRANULAR design")
    print(f"  model-visible tool calls : {granular_model_calls}")
    print(f"  backend API calls        : {len(BACKEND.api_calls)} {BACKEND.api_calls}")

    # Coarse-grained: one model call, same backend work, hidden orchestration.
    BACKEND.api_calls.clear()
    github_issue_file_and_triage(
        "octo/demo", "Login button is misaligned",
        "On mobile the button overlaps the footer.",
        labels=["bug", "ui"], assignee="maintainer")
    coarse_model_calls = 1
    print("\nCOARSE-GRAINED design (paper's recommendation)")
    print(f"  model-visible tool calls : {coarse_model_calls}")
    print(f"  backend API calls        : {len(BACKEND.api_calls)} {BACKEND.api_calls}")

    print("\nSame backend work; the coarse tool cuts model round-trips from "
          f"{granular_model_calls} to {coarse_model_calls}.")
    print("Fewer round-trips = lower latency, lower cost, and no chance for the "
          "model to drop a step (e.g. forget to assign).")


if __name__ == "__main__":
    _demo()
