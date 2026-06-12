# Tool Design — companion code

Runnable companion code for the blog post **"MCP Tool Design, in Code"**, part 2
of the *MCP Strategies on AWS* series. It turns the tool-design pillar of the AWS
Prescriptive Guidance paper [*Model Context Protocol strategies on AWS*](https://docs.aws.amazon.com/prescriptive-guidance/latest/mcp-strategies/mcp-strategies.pdf)
into code you can run.

## What's here

| File | Demonstrates |
|------|--------------|
| `token_tax.py` | Measures the real token cost of N MCP tool definitions — minimal vs the paper's enriched (best-practice) form. Reproduces the paper's "250-500 tokens/tool, 20 tools = 5-10k" claim. |
| `github_tools.py` | Granular (tool-per-API) vs coarse-grained (workflow-driven) tools, using the GitHub-issue example. Shows model round-trips dropping from 3 to 1. |
| `naming_and_params.py` | A dependency-free linter for the paper's hard rules: `<= 8` params, `domain-noun-verb` naming, read/write separation, `<= 50` tools per server. |
| `run_demo.py` | Runs all three in sequence. |

## Quickstart

```bash
# everything (tiktoken required for the token measurement; strands optional)
uv run --with tiktoken --with strands-agents python run_demo.py

# just the token measurement
uv run --with tiktoken python token_tax.py

# the granular-vs-coarse comparison (runs without the SDK too)
python github_tools.py

# lint a toolset against the paper's rules
python naming_and_params.py
```

(If you don't use [`uv`](https://docs.astral.sh/uv/): `pip install -r requirements.txt`
then `python run_demo.py`.)

## The measured result

`token_tax.py` builds a realistic 20-tool GitHub-style MCP server and counts the
tokens each definition costs (tiktoken `cl100k_base` as a portable proxy):

- **Minimal** definitions: ~92 tokens/tool, ~1,800 tokens for 20 tools.
- **Best-practice** definitions (output schema + concrete examples + prompt-style
  descriptions, all of which the paper recommends): **~346 tokens/tool, ~6,900
  tokens for 20 tools** — squarely in the paper's 250-500/tool, 5-10k band.

The takeaway: the paper's range is the cost of *following the guidance*. Every
token you spend helping the model choose and fill a tool is sent on **every**
model invocation, before any user input. That is the budget tool design spends.

## Notes

- The tokenizer is a proxy; absolute counts vary by model family. The
  order of magnitude and the relative comparison are the point.
- `github_tools.py` uses a mock backend so it runs offline and makes no network
  calls. No credentials, no real GitHub access.
- All examples use fictional repositories (`octo/demo`).
