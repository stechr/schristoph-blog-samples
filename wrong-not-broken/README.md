# wrong-not-broken: one refund run, three evaluators

A small, offline simulation for the blog post "Wrong, Not Broken". It reproduces the shape of the
refund example from Matt Wood's AWS Insights post "Wrong, not broken": an agent answers quickly,
without errors, and quotes a refund from last quarter's policy.

There is **no model call and no AWS call**. The "agent" is a stub that answers from whatever document
retrieval returns. The point is the trace and the evaluators, not the generation.

## What it shows

The run is traced with the OpenTelemetry SDK (three spans: agent, retrieval, generation). Then three
local checks score the trace:

| check | reads | result on the stale run |
|---|---|---|
| `context_check` | the answer and the retrieved document | 1 (pass) |
| `reference_check` | the answer and an expected answer | 0 (fail) |
| `freshness_check` | the retrieval span's document version and the current version | 0 (fail) |

The operational signals are all healthy: root status OK, zero error spans, sub-millisecond latency.

`context_check` is a stand-in for a context-grounded check. It is NOT an implementation of any
managed evaluator. In Amazon CloudWatch Omni the equivalent ideas are a built-in evaluator with a
ground-truth `expectedResponse` (reference) and a custom code-based evaluator (freshness); see the
post for links to the documentation.

## Live version

`live/` runs the same scenario with a real agent (Strands Agents SDK on Amazon Bedrock) and scores it with the
managed AgentCore Evaluations `Evaluate` API. See `live/README.md`. The blog post reports the live results.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python refund_sim.py
```

Tested with Python 3.9 and opentelemetry-sdk 1.x.

## Expected output (abridged)

```json
{
  "answer": "You are owed $40, and we will cover return shipping.",
  "root_status": "OK",
  "error_spans": 0,
  "retrieved_version": "2026-Q2",
  "scores": {"context_check": 1, "reference_check": 0, "freshness_check": 0}
}
```

## Adapting it

- Record the document id and version on your real retrieval spans (any span attribute names work;
  the ones used here are illustrative, not a standard convention).
- Point the freshness check at your real source of truth (a policy table, a document store's
  version API).
- Keep the expected answers for your known-bad runs; they become a regression dataset.

License: MIT-0.
