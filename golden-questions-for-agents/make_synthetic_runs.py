"""Generate the synthetic run files used by gate.py.

All numbers are invented for illustration. Nothing here comes from a real agent.
Each run file holds one row per golden question with pass/fail and a safety flag.
"""
from __future__ import annotations

import json
from pathlib import Path

# category -> number of questions in the suite (50 total)
SUITE = {
    "single_table_aggregation": 10,
    "multi_fact_join": 10,
    "time_comparison": 8,
    "ranking": 6,
    "ambiguous": 8,
    "out_of_scope": 4,
    "permission_boundary": 4,
}
SAFETY_CATEGORIES = {"permission_boundary"}


def make_run(passes: dict, flaky: dict | None = None, violations: set | None = None) -> list:
    """passes: category -> how many questions pass; flaky: category -> extra failures in this run."""
    flaky = flaky or {}
    violations = violations or set()
    rows = []
    for cat, n in SUITE.items():
        ok = passes[cat] - flaky.get(cat, 0)
        for i in range(n):
            qid = f"{cat[:4].upper()}-{i + 1:02d}"
            rows.append({
                "question_id": qid,
                "category": cat,
                "passed": i < ok,
                "safety_violation": qid in violations,
            })
    return rows


BASELINE = {"single_table_aggregation": 9, "multi_fact_join": 8, "time_comparison": 7,
            "ranking": 5, "ambiguous": 6, "out_of_scope": 4, "permission_boundary": 4}
# Candidate A: a model upgrade. Most categories improve, multi-fact joins collapse.
CAND_A = {"single_table_aggregation": 10, "multi_fact_join": 5, "time_comparison": 8,
          "ranking": 6, "ambiguous": 8, "out_of_scope": 4, "permission_boundary": 4}
# Candidate B: a prompt change. One more ambiguous question passes, and a time-comparison
# question still gets the right number, but the agent wrote a scratch table while doing it
# (a write during a read-only task). Correct answer, safety violation.
CAND_B = dict(BASELINE, ambiguous=7)


def main() -> None:
    out = Path(__file__).parent / "runs"
    out.mkdir(exist_ok=True)
    plans = {
        "baseline": (BASELINE, None),
        "candidate-a": (CAND_A, None),
        "candidate-b": (CAND_B, {"TIME-03"}),
    }
    for name, (passes, viol) in plans.items():
        # three repeats per change; repeat 2 has one flaky ambiguous question
        repeats = [make_run(passes, violations=viol),
                   make_run(passes, flaky={"ambiguous": 1}, violations=viol),
                   make_run(passes, violations=viol)]
        (out / f"{name}.json").write_text(json.dumps({"change": name, "repeats": repeats}, indent=1))
    print("wrote", ", ".join(sorted(p.name for p in out.glob("*.json"))))


if __name__ == "__main__":
    main()
