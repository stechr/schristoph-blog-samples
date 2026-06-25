"""Local CLI demo:  python -m factchecker.demo "<claim or text>" [--extract]

In mock mode (GROUNDING_PROVIDER=mock) it runs fully offline using mock grounding AND mock
Bedrock, so you can exercise the contract with no AWS credentials. Otherwise it calls real
AgentCore Web Search + Bedrock.
"""
from __future__ import annotations

import json
import sys

from . import config, verify as verify_mod
from .models import Context

_MOCK = config.GROUNDING_PROVIDER == "mock"
if _MOCK:
    from . import mock
    _EXTRACT_FN = mock.mock_extract
    _VERDICT_FN = mock.mock_verdict
else:
    _EXTRACT_FN = None
    _VERDICT_FN = None


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    do_extract = "--extract" in argv
    if not args:
        print('usage: python -m factchecker.demo "<claim or text>" [--extract]', file=sys.stderr)
        return 2
    text = args[0]
    ctx = Context(language="en")

    if do_extract:
        claims = verify_mod.extract_claims(text, ctx, extract_fn=_EXTRACT_FN)
        results = []
        for c in claims:
            res = verify_mod.verify_claim(
                c.claim, ctx, summary=c.summary, verdict_fn=_VERDICT_FN,
            )
            results.append(res.to_json())
        print(json.dumps({"claims": [c.to_json() for c in claims], "results": results}, indent=2))
    else:
        res = verify_mod.verify_claim(text, ctx, verdict_fn=_VERDICT_FN)
        print(json.dumps(res.to_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
