# terms-in-the-402 — license terms carried inside the HTTP 402

Companion code for the blog post **"Terms in the 402"** (part of the x402 / agentic-web
monetization series).

An HTTP `402 Payment Required` can do more than quote a price. It can also tell an AI agent
**what it is licensed to do** with the content once it pays. This repo is a tiny, self-contained,
public-safe server that unites two layers on one origin:

- **Layer 4 — payment:** an x402-style challenge (price + accepted networks + a signed-payment
  re-request), the pattern the AWS WAF AI-traffic-monetization feature enforces at the edge.
- **Layer 3 — licensing/terms:** the same 402 points at an **RSL-style** license declaration
  (`Link: rel="license"`) and a **CoMP-style** usage/offer document at a well-known URI.

> The agent pays **once** and knows **exactly** what it is licensed to do — train vs RAG vs
> agent-actions — because the terms travelled with the payment challenge.

This is a **local / simulated** server, not a live WAF deployment. It mirrors the *contract* of
an edge 402 so you can read every byte. Payment verification is stubbed (no keys, no chain, no
funds). Publisher and figures are **fictional** ("The Meridian").

## What it does

- **`server.py`** — a stdlib HTTP server for a fictional publisher with one gated article:
  - `GET /articles/meridian-fx-outlook` — returns **402** unless a valid `X-Payment` is present.
    The 402 body is an x402-style `accepts[]` offer **plus** a `terms{}` block; the response also
    carries `Link: rel="license"`, a `License:` header, and `X-Usage-Declaration`.
  - `GET /license.xml` — an **RSL-style** license declaration: which usages are permitted
    (`ai-input`, `ai-index`) vs prohibited (`ai-train`), payment types, attribution.
  - `GET /.well-known/usage.json` — a **CoMP-style** offer/usage document: `licenseUrl`,
    `reportUrl`, pricing basis per intended-use, and `retrieval.type = HTML`.
  - `POST /usage-report` — a CoMP `reporturl` stub that acknowledges usage reports.
- **`agent.py`** — an agent that declares its intended use, receives the 402, reads the license,
  refuses to pay when the use is prohibited, otherwise "pays" (simulated) and gets the content.

Price is quoted **per intended use** — the same article costs a different amount depending on
what the agent declares it will do with it, mapped to the **CoMP function / sub-function**
vocabulary:

| Declared use (CoMP `function`/`subFunction`) | Price (fictional) | License verdict |
|---|---|---|
| `ai-input` / `rag` | 0.010 USDC per-use | permitted |
| `ai-input` / `grounding` | 0.010 USDC per-use | permitted |
| `ai-index` / `agent-actions` | 0.020 USDC per-query | permitted |
| `ai-train` / `training` | 0.250 USDC per-token-batch | **prohibited** by the license |

The interesting case is the last row: the 402 still quotes a training price, but the RSL license
**prohibits** `ai-train`, so a well-behaved agent reads the terms and declines to pay.

## Run it

No dependencies — Python 3 standard library only.

```bash
python3 server.py        # serves http://127.0.0.1:8402
# in another shell:
python3 agent.py                    # default: ai-input/rag  -> pays, gets content
python3 agent.py ai-index agent-actions   # -> pays, gets content
python3 agent.py ai-train training        # -> license prohibits; agent stops
```

See [`sample-402-transcript.txt`](sample-402-transcript.txt) for a full captured run (the 402
body with terms attached, the license, the usage doc, and the paid 200).

## How the layers map to the standards

- **x402** (Layer 4): the `402` + `accepts[]` + signed-payment re-request. Governed by the x402
  Foundation under the Linux Foundation. AWS WAF AI-traffic-monetization and Cloudflare's
  Monetization Gateway both verify this at the edge before the origin sees the request.
- **RSL — Really Simple Licensing** (Layer 3): per-URL license terms (permitted usages, payment
  types, attribution), associable via robots.txt `License:`, an HTTP `Link: rel="license"`
  header, HTML, or RSS. This demo uses the header association + a served `license.xml`.
- **IAB Tech Lab CoMP** (Layer 3): the offer/usage object model — `licenseurl`, `reporturl`,
  pricing basis, and the intended-use function vocabulary (`ai-train` / `ai-input`+`rag`/`grounding`
  / `ai-index`+`agent-actions`). CoMP declares payment and clearing **out of scope** — which is
  exactly why the payment half is carried by x402 here.

The point of the series' Part 4 ("Why doesn't the web just use HTTP?") is that these are
**complementary layers**, not competitors: HTTP + x402 handle delivery and payment; RSL/CoMP
handle terms. This repo puts both on one origin.

## What is real vs simulated

- **Real:** the HTTP flow, the header/JSON shapes, the per-use pricing, the license-driven refusal.
- **Simulated:** payment verification (any well-formed `X-Payment` with amount ≥ the quote is
  accepted). A production edge (WAF Monetize / an x402 facilitator) verifies a signed payment
  authorization on-chain. No keys, no network beyond localhost, no funds move.

## Safety

Fictional publisher and data only. No real brands, accounts, credentials, or wallet addresses
(the `payTo` field is a literal placeholder). See [`../LICENSE`](../LICENSE).
