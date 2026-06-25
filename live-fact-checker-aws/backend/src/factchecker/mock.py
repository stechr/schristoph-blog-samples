"""Offline mock providers — deterministic, no AWS. Used by the demo (mock mode) and tests.

The fake verdict logic is intentionally tiny: it just compares a number in the claim against a
number in the evidence so the end-to-end flow (ground -> reason -> self-consistency) is exercised
without a model. All numbers here are fictional.
"""
from __future__ import annotations

import re

from .models import Claim, Context


def mock_extract(text: str, ctx: Context, max_claims: int) -> list[Claim]:
    """One naive 'claim per sentence that contains a number', capped at max_claims."""
    claims: list[Claim] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\d", sentence) and sentence.strip():
            s = sentence.strip()
            claims.append(Claim(claim=s, summary=s, search_query=s[:200]))
        if len(claims) >= max_claims:
            break
    return claims


def mock_verdict(claim: str, summary: str, ctx: Context, evidence_block: str) -> dict:
    """Compare the headline figure in the claim with the headline figure in the evidence.

    Prefers a percentage token (these fact-check claims are percentages); falls back to the first
    plain number once index markers, dates and URLs are stripped out.
    """
    claim_num = _figure(summary or claim)
    ev_num = _figure(evidence_block)
    if claim_num is None or ev_num is None:
        return {
            "verdict": "UNCERTAIN", "confidence": 0.4,
            "explanation": "No comparable figure found in the evidence.",
            "claimNormalized": summary or claim,
        }
    # Within ~15% -> TRUE, else FALSE.
    close = abs(claim_num - ev_num) <= 0.15 * max(abs(ev_num), 1.0)
    if close:
        return {
            "verdict": "TRUE", "confidence": 0.8,
            "explanation": f"Claim says {claim_num:g}. Evidence shows {ev_num:g}. They agree.",
            "claimNormalized": summary or claim,
        }
    return {
        "verdict": "FALSE", "confidence": 0.85,
        "explanation": f"Claim says {claim_num:g}. Evidence shows {ev_num:g}. They differ materially.",
        "claimNormalized": summary or claim,
    }


def _clean(text: str) -> str:
    """Drop index markers, date and URL tokens so they aren't mistaken for the figure."""
    text = re.sub(r"\[\d+\]", " ", text or "")          # evidence index markers [1], [2]
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)        # ISO dates
    text = re.sub(r"https?://\S+", " ", text)             # URLs
    return text


def _figure(text: str) -> float | None:
    text = _clean(text)
    pct = re.search(r"(-?\d[\d,]*\.?\d*)\s*%", text)       # prefer a percentage
    token = pct.group(1) if pct else None
    if token is None:
        num = re.search(r"-?\d[\d,]*\.?\d*", text)
        token = num.group(0) if num else None
    if token is None:
        return None
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None
