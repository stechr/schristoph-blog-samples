"""run_demo.py — Run both governance demos.

    python run_demo.py
"""
from __future__ import annotations


def main() -> None:
    print("=" * 64)
    print("1) TOKEN ISOLATION — hallucinated DELETE fails safely under a")
    print("   scoped token; would delete prod under admin creds")
    print("=" * 64)
    import token_isolation
    token_isolation._demo()

    print("\n" + "=" * 64)
    print("2) RATE LIMITING — per-tool limits + standard headers + load shed")
    print("=" * 64)
    import rate_limit
    rate_limit._demo()


if __name__ == "__main__":
    main()
