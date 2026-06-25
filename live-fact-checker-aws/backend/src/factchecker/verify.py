"""Orchestration — the public seam.

``extract_claims`` : text -> [Claim]
``verify_claim``   : claim text -> VerifyResult (ground -> reason -> self-consistency check)

Both accept injectable dependencies (``search_fn``, ``extract_fn``, ``verdict_fn``) so they can
run fully offline in tests with mock providers, and against real AWS in production.
"""
from __future__ import annotations

import re
import time
import uuid

from . import bedrock, config, grounding
from .models import Claim, Context, Source, Verdict, VerifyResult

# Words that signal the explanation contradicts a TRUE verdict. Deliberately does NOT match a
# bare number — the verdict prompt REQUIRES stating "Evidence shows [Y]", so a digit alone is not
# a contradiction; only explicit mismatch language is.
_CONTRADICTION = re.compile(
    r"\b(different|differs?|contradicts?|does not match|do not match|mismatch|"
    r"distinto|distinta|no coincide|sin embargo)\b",
    re.IGNORECASE,
)


def extract_claims(text: str, context: Context | None = None, *, extract_fn=None,
                   max_claims: int | None = None) -> list[Claim]:
    context = context or Context()
    max_claims = max_claims or config.MAX_CLAIMS_PER_EXTRACT
    extract_fn = extract_fn or bedrock.extract_claims
    text = (text or "").strip()[: config.MAX_TEXT_CHARS]
    if not text:
        return []
    return extract_fn(text, context, max_claims)


def verify_claim(claim: str, context: Context | None = None, *, search_fn=None, verdict_fn=None,
                 summary: str = "", max_results: int | None = None) -> VerifyResult:
    context = context or Context()
    search_fn = search_fn or grounding.web_search
    verdict_fn = verdict_fn or bedrock.reason_verdict
    claim = (claim or "").strip()[: config.MAX_CLAIM_CHARS]
    started = time.monotonic()

    # 1) Ground
    query = (summary or claim)[: config.WEB_QUERY_MAX_CHARS]
    sources: list[Source] = search_fn(query, max_results)

    # 2) Reason
    data = verdict_fn(claim, summary, context, grounding.evidence_block(sources))
    verdict = Verdict(str(data.get("verdict", "UNCERTAIN")).upper())
    confidence = float(data.get("confidence", 0.5))
    explanation = data.get("explanation", "")
    normalized = data.get("claimNormalized") or summary or claim

    # 3) Self-consistency: a TRUE verdict whose explanation cites contradicting data is downgraded.
    if verdict is Verdict.TRUE and _CONTRADICTION.search(explanation):
        verdict = Verdict.UNCERTAIN
        confidence = min(confidence, 0.5)

    return VerifyResult(
        id="c-" + uuid.uuid4().hex[:8],
        claim_normalized=normalized,
        verdict=verdict,
        confidence=confidence,
        explanation=explanation,
        sources=sources,
        queries_used=1 if query else 0,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
