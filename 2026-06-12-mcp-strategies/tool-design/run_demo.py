"""run_demo.py — Run all three tool-design demos in sequence.

    uv run --with tiktoken --with strands-agents python run_demo.py
    # tiktoken is required for a real token measurement; strands-agents is
    # optional (github_tools falls back to a no-op @tool decorator without it).
"""
from __future__ import annotations


def main() -> None:
    print("=" * 64)
    print("1) TOKEN TAX — what N tool definitions cost per model call")
    print("=" * 64)
    import token_tax
    token_tax.main()

    print("\n" + "=" * 64)
    print("2) GRANULAR vs COARSE-GRAINED — the GitHub-issue example")
    print("=" * 64)
    import github_tools
    github_tools._demo()

    print("\n" + "=" * 64)
    print("3) LINT — <=8 params, domain-noun-verb naming, <=50 tools")
    print("=" * 64)
    import naming_and_params
    naming_and_params._demo()


if __name__ == "__main__":
    main()
