# Governance — companion code

Runnable companion code for the blog post **"MCP Governance, in Code"**, part 4
of the *MCP Strategies on AWS* series. It turns the governance pillar of the AWS
Prescriptive Guidance paper [*Model Context Protocol strategies on AWS*](https://docs.aws.amazon.com/prescriptive-guidance/latest/mcp-strategies/mcp-strategies.pdf)
into runnable demos. **No real AWS resources** — everything is in-memory mocks.

## What's here

| File | Demonstrates |
|------|--------------|
| `token_isolation.py` | The paper's headline story, simulated: an agent clones a DB and hallucinates a "delete prod" cleanup. A scoped READ+CREATE token makes the DELETE fail safely; an admin token would delete prod. Also enforces the MCP `aud` (audience) claim. |
| `rate_limit.py` | Per-tool rate limiting with the standard `X-RateLimit-*` headers, plus a global load-shedding ceiling. |
| `run_demo.py` | Runs both. |

## Quickstart

```bash
python run_demo.py          # both demos, stdlib only — no deps, no AWS
# or individually:
python token_isolation.py
python rate_limit.py
```

## What you'll see

**Token isolation** runs the same hallucinated workflow under two tokens:

```text
[scoped-read-create]  scopes=['create', 'read']
    - read prod (ok)
    - create preprod (ok)
    - delete prod (DENIED — token lacks scope 'delete')
    => SAFE — prod still exists

[admin-all]  scopes=['create', 'delete', 'read']
    - delete prod (EXECUTED!)
    => DISASTER — prod was deleted
```

The scoped token contains the blast radius of a bad model step. Reusing the
user's admin credentials would have deleted production.

**Rate limiting** shows per-tool 429s with `X-RateLimit-Remaining=0`, and a
global ceiling that sheds load even when no single tool hit its own limit.

## Notes

- Pure stdlib; no AWS, no network, no credentials.
- The token model also enforces the MCP spec's audience (`aud`) check, so a
  token minted for one server can't be replayed against another.
- The rate limiter is a fixed-window in-memory implementation for illustration.
  In production you'd back it with a shared store (e.g. a distributed counter)
  and set per-tool limits to the lowest of the downstream APIs a tool calls.
