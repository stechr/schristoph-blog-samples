#!/usr/bin/env python3
"""
agent.py — a tiny agent that walks the full terms-in-the-402 flow against server.py:

  1. GET the gated article, declaring its intended use (CoMP function/sub-function).
  2. Receive HTTP 402 — read BOTH the price (x402 accepts[]) AND the license terms
     (Link: rel=license header + the CoMP usage doc).
  3. Fetch the license, decide whether the declared use is permitted.
  4. "Pay" (construct a simulated signed-payment authorization — no keys, no chain).
  5. Re-request with X-Payment, receive 200 + the content, under a declared license.

Standard library only. No network beyond localhost, no funds move.

Usage:
  python3 agent.py                       # default: ai-input/rag
  python3 agent.py ai-index agent-actions
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8402"
ARTICLE = "/articles/meridian-fx-outlook"


def _get(path: str, headers: dict | None = None):
    req = urllib.request.Request(BASE + path, headers=headers or {}, method="GET")
    try:
        resp = urllib.request.urlopen(req)  # noqa: S310 (localhost only)
        return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:  # 402 arrives here
        return e.code, dict(e.headers), e.read().decode()


def _make_payment(offer: dict) -> str:
    """Build a SIMULATED payment authorization for the first accepted offer.

    A real x402 client signs a payment authorization the facilitator verifies on-chain.
    Here we simply echo the quoted amount/network back in a base64 JSON blob so the demo
    server can accept it deterministically. This stands in for the signed payload.
    """
    accept = offer["accepts"][0]
    payload = {
        "x402Version": 2,
        "scheme": accept["scheme"],
        "network": accept["network"],
        "asset": accept["asset"],
        "amount": accept["amount"],
        "resource": accept["resource"],
        "paymentIdentifier": "sim-0001",  # idempotency key (avoids double-settle on retry)
        "signature": "SIMULATED-NO-KEYS",
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def main():
    function = sys.argv[1] if len(sys.argv) > 1 else "ai-input"
    subfunction = sys.argv[2] if len(sys.argv) > 2 else "rag"
    use_headers = {
        "X-Intended-Function": function,
        "X-Intended-Subfunction": subfunction,
    }

    print(f"[agent] declaring intended use: {function}/{subfunction}")
    print(f"[agent] GET {ARTICLE}")
    status, headers, body = _get(ARTICLE, use_headers)
    print(f"[agent] <- {status}")

    if status == 402:
        offer = json.loads(body)
        accept = offer["accepts"][0]
        terms = offer["terms"]
        print(f"[agent] 402 price   : {accept['amount']} {accept['asset']} ({accept['unit']})")
        print(f"[agent] 402 Link    : {headers.get('Link')}")
        print(f"[agent] 402 terms   : license={terms['licenseUrl']}")
        print(f"[agent]               usage={terms['usageUrl']} function={terms['function']}/{terms['subFunction']}")

        # Read the license the purchase would be made under.
        lstatus, _lh, license_xml = _get(terms["licenseUrl"].replace(BASE, ""))
        permits = [line.strip() for line in license_xml.splitlines() if "permits" in line]
        prohibits = [line.strip() for line in license_xml.splitlines() if "prohibits" in line]
        print(f"[agent] fetched license ({lstatus}): permits={len(permits)} prohibits={len(prohibits)}")
        if any(function in p for p in prohibits):
            print(f"[agent] STOP: license PROHIBITS {function}; not paying.")
            return

        # Pay (simulated) and re-request.
        payment = _make_payment(offer)
        print("[agent] paying (simulated signed authorization) and re-requesting...")
        paid_headers = dict(use_headers)
        paid_headers["X-Payment"] = payment
        status, headers, body = _get(ARTICLE, paid_headers)
        print(f"[agent] <- {status}  X-Licensed-Use={headers.get('X-Licensed-Use')}")

    if status == 200:
        first_line = body.splitlines()[0] if body else ""
        print(f"[agent] got content: {first_line!r} ... ({len(body)} bytes)")
        print("[agent] done — paid once, know exactly what we're licensed to do.")
    else:
        print(f"[agent] unexpected final status {status}: {body[:200]}")


if __name__ == "__main__":
    main()
