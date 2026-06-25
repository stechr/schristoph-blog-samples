"""API contract types — the shapes that cross the client/backend seam.

These mirror the JSON in docs/api-contract.md. Kept as plain dataclasses so the same models
serve the Lambda handlers and the local demo/tests.
"""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field


class Verdict(str, enum.Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class Context:
    """Optional grounding context — improves precision, never required."""
    speaker: str = ""
    event: str = ""
    language: str = ""        # ISO-639-1; "" = auto
    as_of_date: str = ""      # YYYY-MM-DD
    source_url: str = ""

    def to_prompt_block(self) -> str:
        parts = []
        if self.speaker:
            parts.append(f"Speaker/Source: {self.speaker}")
        if self.event:
            parts.append(f"Event/Topic: {self.event}")
        if self.as_of_date:
            parts.append(f"As-of date: {self.as_of_date}")
        if self.source_url:
            parts.append(f"Source URL: {self.source_url}")
        return "\n".join(parts) or "No additional context."

    @classmethod
    def from_dict(cls, d: dict | None) -> "Context":
        d = d or {}
        return cls(
            speaker=d.get("speaker", ""),
            event=d.get("event", ""),
            language=d.get("language", ""),
            as_of_date=d.get("asOfDate", ""),
            source_url=d.get("sourceUrl", ""),
        )


@dataclass
class Claim:
    """A verifiable claim extracted from text."""
    claim: str               # verbatim quote
    summary: str             # precise, testable assertion
    search_query: str        # tight (<=200 char) data-finding query

    def to_json(self) -> dict:
        return {"claim": self.claim, "summary": self.summary, "searchQuery": self.search_query}


@dataclass
class Source:
    url: str = ""
    title: str = ""
    published_date: str = ""
    snippet: str = ""

    def to_json(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "publishedDate": self.published_date,
            "snippet": self.snippet,
        }


@dataclass
class VerifyResult:
    id: str
    claim_normalized: str
    verdict: Verdict
    confidence: float
    explanation: str
    sources: list[Source] = field(default_factory=list)
    queries_used: int = 0
    latency_ms: int = 0

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "claimNormalized": self.claim_normalized,
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 2),
            "explanation": self.explanation,
            "sources": [s.to_json() for s in self.sources],
            "grounding": {"provider": "agentcore-web-search", "queriesUsed": self.queries_used},
            "latencyMs": self.latency_ms,
        }


def error_body(request_id: str, code: str, message: str, retry_after_ms: int | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if retry_after_ms is not None:
        err["retryAfterMs"] = retry_after_ms
    return {"requestId": request_id, "error": err}
