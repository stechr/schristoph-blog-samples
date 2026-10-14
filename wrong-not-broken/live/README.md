# live/: the same stale refund run, scored by the managed evaluators

This folder runs a real agent and real managed evaluators. It needs an AWS account with Amazon Bedrock
model access (Claude Haiku 4.5 through the US cross-Region inference profile, or set `MODEL_ID`) and
Amazon Bedrock AgentCore Evaluations in a supported Region. It uses us-east-1.

- `agent_run.py` builds a small Strands agent with one tool, `retrieve_policy`. The tool returns last
  quarter's refund policy ($40) because the index was never rebuilt; the current policy says $140. The tool
  span records `policy.doc_id`, `policy.version` and `policy.effective_date`. Spans are captured in memory
  with the OpenTelemetry SDK and written as JSON records shaped like the documents in the CloudWatch
  `aws/spans` log group.
- `evaluate.py` sends those spans to the on-demand `Evaluate` API with `Builtin.Faithfulness`,
  `Builtin.Helpfulness`, `Builtin.Correctness`, and `Builtin.Correctness` with an `expectedResponse`.

It creates no AWS resources. Each run costs a few cents (two model calls, four evaluations).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
AWS_REGION=us-east-1 .venv/bin/python agent_run.py spans.json
.venv/bin/python evaluate.py spans.json results.json
```

## Results from two runs (2026-10-13)

Both runs answered "you are owed a $40 credit ... return shipping" in about two seconds with zero error
spans. Scores were identical across the two runs:

| evaluator | expected response given | score | label |
|---|---|---|---|
| Builtin.Faithfulness | no | 1.0 | Completely Yes |
| Builtin.Helpfulness | no | 0.83 | Very Helpful |
| Builtin.Correctness | no | 1.0 | Perfectly Correct |
| Builtin.Correctness | yes ($140) | 0.0 | Incorrect |

Full explanations are in `results-run1.json` and `results-run2.json`. LLM-judge scores can vary between
runs; two runs is not a statistical sample.

The on-demand path normally downloads spans from CloudWatch Logs (see the AgentCore "Getting started with
on-demand evaluation" guide). Sending in-memory spans with the same record shape worked here; treat that as
a shortcut for experiments, and use the documented path in production.

License: MIT-0.
