"""AWS Lambda handlers behind API Gateway (REST proxy integration).

Three entry points:
* ``extract_handler`` — POST /v1/extract
* ``verify_handler``  — POST /v1/verify
* ``batch_handler``   — POST /v1/verify/batch

Stateless: no persistence, each invocation is self-contained. Auth (Cognito JWT) is enforced by
the API Gateway authorizer, not here.
"""
from __future__ import annotations

import json
import uuid

from . import verify as verify_mod
from .models import Context, error_body

_CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": _CORS, "body": json.dumps(body)}


def _parse(event: dict) -> dict:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def extract_handler(event, _context=None):
    rid = "req-" + uuid.uuid4().hex[:12]
    try:
        data = _parse(event)
        text = data.get("text", "")
        if not text.strip():
            return _response(400, error_body(rid, "INVALID_INPUT", "Field 'text' is required."))
        ctx = Context.from_dict(data.get("context"))
        max_claims = int((data.get("options") or {}).get("maxClaims", 5))
        claims = verify_mod.extract_claims(text, ctx, max_claims=max_claims)
        return _response(200, {"requestId": rid, "claims": [c.to_json() for c in claims]})
    except Exception as exc:  # noqa: BLE001 — PoC: surface a clean error envelope
        return _response(500, error_body(rid, "INTERNAL", str(exc)[:200]))


def verify_handler(event, _context=None):
    rid = "req-" + uuid.uuid4().hex[:12]
    try:
        data = _parse(event)
        claim = data.get("claim", "")
        if not claim.strip():
            return _response(400, error_body(rid, "INVALID_INPUT", "Field 'claim' is required."))
        ctx = Context.from_dict(data.get("context"))
        opts = data.get("options") or {}
        result = verify_mod.verify_claim(
            claim, ctx, summary=data.get("summary", ""), max_results=opts.get("maxResults"),
        )
        out = result.to_json()
        out["requestId"] = rid
        return _response(200, out)
    except Exception as exc:  # noqa: BLE001
        return _response(500, error_body(rid, "INTERNAL", str(exc)[:200]))


def batch_handler(event, _context=None):
    rid = "req-" + uuid.uuid4().hex[:12]
    try:
        data = _parse(event)
        items = data.get("claims") or []
        if not isinstance(items, list) or not items:
            return _response(400, error_body(rid, "INVALID_INPUT", "Field 'claims' (array) is required."))
        results = []
        for item in items:
            ctx = Context.from_dict(item.get("context"))
            res = verify_mod.verify_claim(item.get("claim", ""), ctx, summary=item.get("summary", ""))
            results.append(res.to_json())
        return _response(200, {"requestId": rid, "results": results})
    except Exception as exc:  # noqa: BLE001
        return _response(500, error_body(rid, "INTERNAL", str(exc)[:200]))
