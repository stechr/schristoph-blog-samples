#!/usr/bin/env python3
"""
terms-in-the-402 — a minimal, public-safe HTTP 402 server that carries LICENSE TERMS
inside the payment challenge.

The point: an HTTP 402 "Payment Required" response can do more than quote a price. It can
also tell an AI agent *what it is licensed to do* with the content once it pays, by pointing
at (a) an RSL-style license declaration and (b) a CoMP-style usage-declaration document at a
well-known URI. This unites the licensing/terms layer (Layer 3) and the payment layer
(Layer 4) on a single origin — the pattern the AWS WAF AI-traffic-monetization feature makes
real at the edge, here reproduced as a runnable local server so you can read every byte.

This is a LOCAL / SIMULATED server. It mirrors the *contract* of an edge 402 (price +
accepted networks + a signed-payment re-request), NOT a live WAF deployment. Payment
verification is stubbed: any well-formed X-Payment header whose decoded amount >= the quoted
price is accepted. No real money, no chain, no keys — the goal is to show terms travelling
with the 402.

Fictional publisher throughout ("The Meridian"). No real brands, accounts, or credentials.

Run:  python3 server.py           # serves on http://127.0.0.1:8402
Then: python3 agent.py            # drives the full 402 -> read terms -> pay -> 200 flow
"""
from __future__ import annotations

import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8402
BASE = f"http://{HOST}:{PORT}"

# --- Fictional publisher config -------------------------------------------------

PUBLISHER = "The Meridian"
LICENSE_PATH = "/license.xml"          # RSL-style license declaration
USAGE_PATH = "/.well-known/usage.json"  # CoMP-style usage / offer declaration
REPORT_PATH = "/usage-report"          # CoMP reporturl (accepts POST usage reports)

# One gated article. Price is quoted per intended use — the same content costs different
# amounts depending on what the agent declares it will DO with it (CoMP function vocabulary).
ARTICLE = {
    "id": "meridian-fx-outlook",
    "title": "The Meridian — Q3 FX Outlook",
    "body": (
        "# The Meridian — Q3 FX Outlook\n\n"
        "Fictional market commentary for demonstration only. The euro held its range "
        "against the dollar through the quarter while carry unwound in the yen. Nothing "
        "here is real, investable, or advice.\n"
    ),
}

# Price basis keyed by CoMP intended-use function/sub-function.
# function -> sub-function -> {price, currency, unit}
PRICE_TABLE = {
    "ai-train": {"training": {"amount": "0.250", "unit": "per-token-batch"}},
    "ai-input": {
        "rag": {"amount": "0.010", "unit": "per-use"},
        "grounding": {"amount": "0.010", "unit": "per-use"},
    },
    "ai-index": {"agent-actions": {"amount": "0.020", "unit": "per-query"}},
}
CURRENCY = "USDC"
# Simulated x402 network id (CAIP-2 style) — the *shape* of what an edge 402 advertises.
ACCEPTED_NETWORKS = ["eip155:8453"]  # Base mainnet id, used illustratively


def _price_for(function: str, subfunction: str):
    fn = PRICE_TABLE.get(function, {})
    return fn.get(subfunction)


def _payment_required_payload(function: str, subfunction: str, price: dict) -> dict:
    """The body of the 402 — the machine-readable challenge, WITH terms attached.

    Shape deliberately mirrors an x402 'payment-required' offer plus a terms pointer:
      - accepts[]: how to pay (network + asset + amount)  ← Layer 4 (payment)
      - terms{}:   what you're licensed to do             ← Layer 3 (licensing)
    """
    return {
        "x402Version": 2,
        "error": "payment required",
        "accepts": [
            {
                "scheme": "exact",
                "network": net,
                "asset": CURRENCY,
                "amount": price["amount"],
                "unit": price["unit"],
                "payTo": "0xPUBLISHER_WALLET_PLACEHOLDER",
                "resource": f"/articles/{ARTICLE['id']}",
                "maxTimeoutSeconds": 120,
            }
            for net in ACCEPTED_NETWORKS
        ],
        # The terms half — this is the part a bare 402 omits.
        "terms": {
            "publisher": PUBLISHER,
            "licenseUrl": f"{BASE}{LICENSE_PATH}",   # RSL declaration (Layer 3)
            "usageUrl": f"{BASE}{USAGE_PATH}",       # CoMP-style offer/usage doc
            "reportUrl": f"{BASE}{REPORT_PATH}",     # CoMP reporturl
            "function": function,                    # CoMP intended-use function
            "subFunction": subfunction,              # CoMP sub-function
            "citationRequired": True,
        },
    }


def _rsl_license_xml() -> str:
    """An RSL-style (Really Simple Licensing) license declaration for the article.

    RSL lets a publisher declare, per content URL, which usages are permitted and the
    payment type. It can be served via robots.txt `License:`, an HTTP `Link: rel=license`
    header, HTML, or RSS. Here we serve the XML directly and also advertise it via the
    Link header on the gated resource. Fictional terms only.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rsl xmlns="https://rslstandard.org/rsl">\n'
        f'  <content url="{BASE}/articles/{ARTICLE["id"]}">\n'
        '    <license>\n'
        '      <permits type="usage">ai-input</permits>\n'
        '      <permits type="usage">ai-index</permits>\n'
        '      <prohibits type="usage">ai-train</prohibits>\n'
        '      <payment type="pay-per-inference">\n'
        f'        <amount currency="{CURRENCY}">0.010</amount>\n'
        '      </payment>\n'
        '      <payment type="pay-per-crawl">\n'
        f'        <amount currency="{CURRENCY}">0.020</amount>\n'
        '      </payment>\n'
        '      <attribution required="true"/>\n'
        '    </license>\n'
        '  </content>\n'
        '</rsl>\n'
    )


def _usage_json() -> dict:
    """A CoMP-style offer / usage-declaration document at a well-known URI.

    CoMP (IAB Tech Lab Content Metadata Marketplace Supply Spec) models the machine-readable
    OFFER: a licenseurl, a reporturl, a pricing basis, and the intended-use functions the
    publisher recognises. CoMP itself declares payment and clearing OUT of scope — so the
    payment half is carried by x402 in the 402 above; this document is the terms half.
    Function / sub-function vocabulary here maps to CoMP: ai-train/training,
    ai-input/{rag,grounding}, ai-index/agent-actions.
    """
    packages = []
    for function, subs in PRICE_TABLE.items():
        for subfunction, price in subs.items():
            packages.append(
                {
                    "function": function,
                    "subFunction": subfunction,
                    "pricingBasis": price["unit"],
                    "amount": price["amount"],
                    "currency": CURRENCY,
                }
            )
    return {
        "publisher": PUBLISHER,
        "licenseUrl": f"{BASE}{LICENSE_PATH}",
        "reportUrl": f"{BASE}{REPORT_PATH}",
        "citationRequired": True,
        "retrieval": {"type": "HTML", "endpoint": f"{BASE}/articles/{ARTICLE['id']}"},
        "packages": packages,
        "_note": "CoMP declares payment/clearing out of scope; the 402 carries payment via x402.",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "terms-in-the-402/1.0"

    # --- helpers ---------------------------------------------------------------
    def _send_json(self, code: int, payload: dict, extra_headers: dict | None = None):
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, text: str, content_type: str, extra_headers=None):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _declared_use(self):
        """Read the agent's declared intended use from request headers (CoMP-style)."""
        function = self.headers.get("X-Intended-Function", "ai-input")
        subfunction = self.headers.get("X-Intended-Subfunction", "rag")
        return function, subfunction

    def _verify_payment(self, price: dict):
        """SIMULATED verification. Accept any X-Payment whose decoded amount >= quoted.

        Real edge verification (WAF Monetize / an x402 facilitator) checks a signed payment
        authorization on-chain. Here we only parse the shape so the flow is demonstrable and
        deterministic — no keys, no network, no funds move.
        """
        raw = self.headers.get("X-Payment")
        if not raw:
            return False, "no X-Payment header"
        try:
            decoded = json.loads(base64.b64decode(raw).decode())
        except Exception as exc:  # noqa: BLE001
            return False, f"malformed X-Payment: {exc}"
        try:
            paid = float(decoded.get("amount", "0"))
            quoted = float(price["amount"])
        except (TypeError, ValueError):
            return False, "unparseable amount"
        if paid + 1e-9 < quoted:
            return False, f"underpaid: {paid} < {quoted}"
        return True, "ok"

    # --- routes ----------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if self.path == LICENSE_PATH:
            self._send_text(200, _rsl_license_xml(), "application/rsl+xml")
            return
        if self.path == USAGE_PATH:
            self._send_json(200, _usage_json())
            return
        if self.path == f"/articles/{ARTICLE['id']}":
            self._serve_gated()
            return
        if self.path in ("/", "/index.html"):
            self._send_text(
                200,
                f"{PUBLISHER} — terms-in-the-402 demo. Try GET /articles/{ARTICLE['id']}\n",
                "text/plain",
            )
            return
        self._send_text(404, "not found\n", "text/plain")

    def do_POST(self):  # noqa: N802
        if self.path == REPORT_PATH:
            # CoMP reporturl: accept a usage report and acknowledge. We do not store it.
            length = int(self.headers.get("Content-Length", 0) or 0)
            _ = self.rfile.read(length) if length else b""
            self._send_json(202, {"status": "accepted", "note": "usage report received"})
            return
        self._send_text(404, "not found\n", "text/plain")

    def _serve_gated(self):
        function, subfunction = self._declared_use()
        price = _price_for(function, subfunction)
        if price is None:
            self._send_json(
                400,
                {"error": f"unknown intended use {function}/{subfunction}",
                 "seeUsage": f"{BASE}{USAGE_PATH}"},
            )
            return

        ok, _reason = self._verify_payment(price)
        if not ok:
            # 402 WITH TERMS ATTACHED. Note the Link: rel=license header (RSL association)
            # and the License header, alongside the JSON challenge body.
            headers = {
                "Link": f'<{BASE}{LICENSE_PATH}>; rel="license"',
                "License": f"{BASE}{LICENSE_PATH}",
                "X-Usage-Declaration": f"{BASE}{USAGE_PATH}",
                "Cache-Control": "no-store",
            }
            self._send_json(402, _payment_required_payload(function, subfunction, price), headers)
            return

        # Paid: deliver content, echo the license the purchase was made under.
        headers = {
            "Link": f'<{BASE}{LICENSE_PATH}>; rel="license"',
            "X-Licensed-Use": f"{function}/{subfunction}",
            "Cache-Control": "no-store",
        }
        self._send_text(200, ARTICLE["body"], "text/markdown", headers)

    def log_message(self, fmt, *args):  # quieter logs
        print("[server] " + (fmt % args))


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{PUBLISHER} terms-in-the-402 demo on {BASE}")
    print(f"  gated article : GET {BASE}/articles/{ARTICLE['id']}")
    print(f"  license (RSL) : GET {BASE}{LICENSE_PATH}")
    print(f"  usage (CoMP)  : GET {BASE}{USAGE_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
