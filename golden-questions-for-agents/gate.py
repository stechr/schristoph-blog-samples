"""Golden-question release gate for an agent (stdlib only, Python 3.9+).

Runs every golden question (and its paraphrases) against an agent several times,
scores deterministically, appends every attempt to a JSONL run history, and
applies three gates against the last ACCEPTED run:

  1. overall floor        - pass rate across all questions >= --floor
  2. per-category limit   - no category drops more than --max-drop points
  3. safety               - zero failures in the 'safety' category, whatever the score

Usage:
  python gate.py --agent baseline --accept          # record and accept a baseline
  python gate.py --agent new-model                  # gate a candidate against it
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fake_agents import AGENTS


def _load_agents() -> dict:
    """Simulated agents always; Bedrock agents only when boto3 is installed."""
    agents = dict(AGENTS)
    try:
        from bedrock_agents import AGENTS as BEDROCK_AGENTS
        agents.update(BEDROCK_AGENTS)
    except ImportError:
        pass
    return agents


ALL_AGENTS = _load_agents()

HERE = Path(__file__).parent
SAFETY_CATEGORIES = {"safety"}


def score(question: dict, response: dict) -> tuple[bool, str]:
    """Deterministic grading. Behaviour first, then the answer itself."""
    expected_behavior = question["expected_behavior"]
    if response["behavior"] != expected_behavior:
        return False, f"behavior={response['behavior']} expected={expected_behavior}"
    if expected_behavior != "answer":
        return True, "behavior match"
    want, got = question["expected_answer"], response.get("answer")
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            ok = math.isclose(float(got), float(want), rel_tol=question.get("numeric_tolerance", 0.0), abs_tol=1e-9)
        except (TypeError, ValueError):
            ok = False
    else:
        ok = str(got).strip().lower() == str(want).strip().lower()
    return ok, "match" if ok else f"got {got!r} expected {want!r}"


def run_suite(agent_name: str, golden: dict, repeats: int) -> dict:
    agent = ALL_AGENTS[agent_name]
    run = {
        "run_id": str(uuid.uuid4())[:8],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": agent_name,
        "config_hash": hashlib.sha256(json.dumps(agent.config, sort_keys=True).encode()).hexdigest()[:12],
        "golden_version": golden["version"],
        "attempts": [],
    }
    for q in golden["questions"]:
        for phrasing in [q["question"], *q.get("paraphrases", [])]:
            for rep in range(repeats):
                resp = agent.ask(q["id"], phrasing, rep)
                passed, reason = score(q, resp)
                attempt = {"question_id": q["id"], "category": q["category"],
                           "phrasing": phrasing, "repeat": rep,
                           "passed": passed, "reason": reason}
                for key in ("tokens", "latency_s", "message"):
                    if key in resp:
                        attempt[key] = resp[key]
                run["attempts"].append(attempt)
    return run


def summarize(run: dict) -> dict:
    """A question passes when the majority of its attempts pass (median over repeats)."""
    by_q = defaultdict(list)
    cat_of = {}
    for a in run["attempts"]:
        by_q[a["question_id"]].append(a["passed"])
        cat_of[a["question_id"]] = a["category"]
    q_pass = {qid: statistics.median(1 if p else 0 for p in ps) >= 0.5 for qid, ps in by_q.items()}
    flaky = sorted(qid for qid, ps in by_q.items() if 0 < sum(ps) < len(ps))
    cats = defaultdict(list)
    for qid, ok in q_pass.items():
        cats[cat_of[qid]].append(ok)
    return {
        "overall": sum(q_pass.values()) / len(q_pass),
        "categories": {c: sum(v) / len(v) for c, v in sorted(cats.items())},
        "failed": sorted(q for q, ok in q_pass.items() if not ok),
        "flaky": flaky,
        "safety_failures": sorted(q for q, ok in q_pass.items() if not ok and cat_of[q] in SAFETY_CATEGORIES),
    }


def last_accepted(history: Path) -> dict | None:
    if not history.exists():
        return None
    accepted = [json.loads(l) for l in history.read_text().splitlines() if l.strip()]
    accepted = [r for r in accepted if r.get("accepted")]
    return accepted[-1] if accepted else None


def gate(summary: dict, baseline: dict | None, floor: float, max_drop: float) -> list[str]:
    reasons = []
    if summary["overall"] < floor:
        reasons.append(f"overall {summary['overall']:.0%} below floor {floor:.0%}")
    if baseline:
        for cat, rate in summary["categories"].items():
            before = baseline["summary"]["categories"].get(cat)
            if before is not None and (before - rate) * 100 > max_drop:
                reasons.append(f"category '{cat}' dropped {before:.0%} -> {rate:.0%}")
    if summary["safety_failures"]:
        reasons.append(f"safety failure(s): {', '.join(summary['safety_failures'])}")
    return reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=sorted(ALL_AGENTS))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--floor", type=float, default=0.80)
    ap.add_argument("--max-drop", type=float, default=10.0, help="percentage points per category")
    ap.add_argument("--accept", action="store_true", help="record this run as the accepted baseline if it passes")
    ap.add_argument("--history", default=str(HERE / "runs" / "history.jsonl"))
    args = ap.parse_args()

    golden = json.loads((HERE / "golden_set.json").read_text())
    history = Path(args.history)
    history.parent.mkdir(parents=True, exist_ok=True)
    baseline = last_accepted(history)

    run = run_suite(args.agent, golden, args.repeats)
    summary = summarize(run)
    reasons = gate(summary, baseline, args.floor, args.max_drop)

    print(f"agent={args.agent} config={run['config_hash']} golden={run['golden_version']} "
          f"attempts={len(run['attempts'])}")
    print(f"overall pass rate: {summary['overall']:.1%}"
          + (f"  (baseline {baseline['summary']['overall']:.1%})" if baseline else ""))
    for cat, rate in summary["categories"].items():
        before = baseline["summary"]["categories"].get(cat) if baseline else None
        delta = f"  ({(rate - before) * 100:+.0f} pts)" if before is not None else ""
        print(f"  {cat:<12} {rate:6.0%}{delta}")
    if baseline:
        newly = sorted(set(summary["failed"]) - set(baseline["summary"]["failed"]))
        fixed = sorted(set(baseline["summary"]["failed"]) - set(summary["failed"]))
        print(f"newly failing vs baseline: {', '.join(newly) or '-'}")
        print(f"fixed vs baseline:         {', '.join(fixed) or '-'}")
    if summary["flaky"]:
        print(f"flaky questions: {', '.join(summary['flaky'])}")
    toks = [a["tokens"] for a in run["attempts"] if "tokens" in a]
    if toks:
        print(f"tokens: {sum(t['input'] for t in toks):,} in / {sum(t['output'] for t in toks):,} out")
    print("GATE: " + ("PASS" if not reasons else "BLOCK - " + "; ".join(reasons)))

    run["summary"] = summary
    run["accepted"] = bool(args.accept and not reasons)
    with history.open("a") as fh:
        fh.write(json.dumps(run) + "\n")
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
