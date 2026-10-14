# Golden-question release gate (sample)

A small sample (the simulated demo is dependency-free) for the blog post *"Golden Questions: Release Gates for Agents"*.
It shows the mechanics of treating every agent change as a release:

- a **golden set** of 30 questions with known-good answers or behaviours, grouped by category
  (`golden_set.json`)
- a **runner** that asks every question and paraphrase three times, scores deterministically and
  appends every attempt to a run history (`runs/history.jsonl`)
- **three gates** against the last accepted run: an overall floor, a per-category drop limit, and
  zero tolerance in the `safety` category

The agents in `fake_agents.py` are **simulated**. They replay the golden answers and inject a fixed
set of mistakes, so you can watch the gate decide without calling a model. To use the gate for real,
replace them with an adapter around your own agent (the interface is documented at the top of
`fake_agents.py`). The domain (order support for a demo shop) and all data are synthetic.

## Run it

Python 3.9+ and nothing else.

```bash
./run_demo.sh
```

It starts from an empty history and runs three releases:

| run | what changed | overall | gate |
|---|---|---|---|
| `baseline --accept` | the release in production | 80.0% | PASS, recorded as accepted |
| `new-model` | model upgrade | 86.7% | BLOCK: `multi_step` dropped 83% -> 33% |
| `new-prompt` | model upgrade + prompt fix | 93.3% | BLOCK: safety failure `GQ-S01` |

Both candidates beat the baseline average. Neither ships.

## Run it against real models on Amazon Bedrock

`bedrock_agents.py` is a small order-support agent built on the Bedrock Converse API with client-side tools:
`get_order`, `get_return_policy` (both read-only) and `final_answer`, whose `behavior` and `answer` fields are
what the gate scores. A release is a model ID, a prompt version and a tool-contract version (`c1`: `answer`
optional, `c2`: `answer` required). Shop data is synthetic and lives in the module.

Needs Python 3.9+, `boto3`, and AWS credentials allowed to call `bedrock:InvokeModel` (Converse) on the
EU cross-Region inference profiles for Amazon Nova Lite, Nova 2 Lite and Nova Micro. Region defaults to
`eu-central-1` (`AWS_REGION` overrides it; outside the EU, change the `eu.` prefix in the model IDs).
It creates no AWS resources; cost is the tokens of about 108 conversations per release.

```bash
pip install boto3
./run_bedrock_demo.sh            # writes runs/bedrock-history.jsonl
```

The output of the run used in the blog post is in `results/2026-10-13-bedrock-run.txt`. Model output is
non-deterministic, so your numbers will differ. Known issue kept on purpose: in `golden-2026-10`, GQ-C06
expects a refund amount for an order that GQ-M06 says cannot be returned yet. The real run surfaced it;
the fix belongs in the next golden-set version.

## Options

```bash
python3 gate.py --agent new-model --floor 0.85 --max-drop 10 --repeats 3
```

- `--floor` overall pass-rate floor (default 0.80)
- `--max-drop` maximum drop per category in percentage points vs the last accepted run (default 10)
- `--repeats` attempts per phrasing; a question passes when the majority of its attempts pass,
  and questions that both pass and fail are reported as flaky
- `--accept` records the run as the new baseline, but only if it passes all gates

## What the golden set records

Each question has an `id`, an `owner`, a `category`, the `question` plus optional `paraphrases`,
an `expected_behavior` (`answer`, `clarify`, `refuse`, `cannot_answer`), the `expected_answer` with a
`numeric_tolerance` where it is a number, and a one-line `rationale` explaining why the answer is
right. The record format follows the one described in Alex Merced's article
[How to Build a Golden-Question Benchmark for Your Data Agents](https://iceberglakehouse.com/posts/data-agent-golden-question-benchmark).

## Limits

- Deterministic grading only covers exact values and behaviour labels. Free-text answers need a
  judge, and a judge needs validating against human labels before you gate on it.
- The history is a local JSONL file to keep the sample self-contained. In a team you would put it
  where the rest of your release data lives.
- The safety category here is three questions. A real one is larger and owned by whoever owns the
  rule it tests.

## License

MIT-0. Synthetic data only. The simulated demo makes no network calls; the Bedrock demo calls only the Bedrock Converse API with your own credentials.
