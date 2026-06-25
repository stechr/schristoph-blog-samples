"""Offline unit tests — no AWS, no network. Run: uv run pytest -q"""
from __future__ import annotations

import json

from factchecker import grounding, mock, verify as verify_mod
from factchecker.models import Context, Source, Verdict


def _src(snippet: str) -> Source:
    return Source(url="https://example.org/x", title="fictional source",
                  published_date="2026-01-01", snippet=snippet)


def test_extract_picks_numeric_sentences():
    text = "Hello everyone. Inflation was 211% last year. I feel great about it."
    claims = verify_mod.extract_claims(text, Context(), extract_fn=mock.mock_extract)
    assert len(claims) == 1
    assert "211%" in claims[0].claim


def test_verify_true_when_numbers_agree():
    res = verify_mod.verify_claim(
        "Inflation was about 211%.", Context(),
        search_fn=lambda q, n: [_src("Official inflation was 211%.")],
        verdict_fn=mock.mock_verdict,
    )
    assert res.verdict is Verdict.TRUE
    assert res.sources and res.queries_used == 1


def test_verify_false_when_numbers_differ():
    res = verify_mod.verify_claim(
        "Poverty reached 60%.", Context(),
        search_fn=lambda q, n: [_src("Official poverty rate was 42%.")],
        verdict_fn=mock.mock_verdict,
    )
    assert res.verdict is Verdict.FALSE


def test_self_consistency_downgrades_true_to_uncertain():
    # verdict_fn lies (says TRUE) but the explanation cites contradicting data.
    def lying_verdict(claim, summary, ctx, evidence):
        return {"verdict": "TRUE", "confidence": 0.9,
                "explanation": "Claim says 60. Evidence shows a different figure of 42."}
    res = verify_mod.verify_claim(
        "Poverty reached 60%.", Context(),
        search_fn=lambda q, n: [_src("42%")], verdict_fn=lying_verdict,
    )
    assert res.verdict is Verdict.UNCERTAIN
    assert res.confidence <= 0.5


def test_grounding_mock_and_evidence_block():
    sources = grounding._mock_search("inflation", 5)
    assert sources
    block = grounding.evidence_block(sources)
    assert "URL:" in block and "211%" in block


def test_verify_result_json_shape():
    res = verify_mod.verify_claim(
        "x is 211.", Context(),
        search_fn=lambda q, n: [_src("211")], verdict_fn=mock.mock_verdict,
    )
    j = res.to_json()
    assert j["verdict"] in {"TRUE", "FALSE", "UNCERTAIN"}
    assert set(["id", "verdict", "confidence", "explanation", "sources", "grounding"]) <= j.keys()


def test_verify_handler_envelope(monkeypatch):
    from factchecker import handlers
    monkeypatch.setattr("factchecker.grounding.web_search", lambda q, n=None: [_src("211%")])
    monkeypatch.setattr("factchecker.bedrock.reason_verdict", mock.mock_verdict)
    event = {"body": json.dumps({"claim": "Inflation was 211%."})}
    resp = handlers.verify_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["verdict"] == "TRUE"
    assert "requestId" in body


def test_verify_handler_missing_claim_is_400():
    from factchecker import handlers
    resp = handlers.verify_handler({"body": "{}"}, None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"]["code"] == "INVALID_INPUT"
