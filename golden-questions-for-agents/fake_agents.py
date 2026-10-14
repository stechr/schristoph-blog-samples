"""Simulated agents for the demo.

These are NOT real models. Each one replays the golden answers and injects a
fixed set of mistakes, so the gate mechanics can be shown without paying for
model calls. Replace them with an adapter around your own agent:

    class MyAgent:
        config = {"model": "...", "system_prompt": "...", "tools": [...]}
        def ask(self, question_id, phrasing, repeat):
            # call the agent with `phrasing` only (never the expected answer!)
            return {"behavior": "answer" | "clarify" | "refuse" | "cannot_answer",
                    "answer": <value or None>}
"""
from __future__ import annotations

import json
import random
from pathlib import Path

_GOLDEN = {q["id"]: q for q in json.loads((Path(__file__).parent / "golden_set.json").read_text())["questions"]}


class SimulatedAgent:
    def __init__(self, config: dict, wrong_answer=(), wrong_behavior=(), flaky=()):
        self.config = config
        self.wrong_answer = set(wrong_answer)      # answers, but with a wrong value
        self.wrong_behavior = dict(wrong_behavior)  # question_id -> behaviour it shows instead
        self.flaky = set(flaky)                     # fails on the 2nd of 3 repeats
        self._rng = random.Random(42)

    def ask(self, question_id: str, phrasing: str, repeat: int) -> dict:
        q = _GOLDEN[question_id]
        if question_id in self.wrong_behavior:
            return {"behavior": self.wrong_behavior[question_id], "answer": "plausible-looking answer"}
        if q["expected_behavior"] != "answer":
            return {"behavior": q["expected_behavior"], "answer": None}
        answer = q["expected_answer"]
        if question_id in self.wrong_answer or (question_id in self.flaky and repeat == 1):
            answer = answer * 1.1 if isinstance(answer, float) else ("yes" if answer == "no" else "no")
        return {"behavior": "answer", "answer": answer}


AGENTS = {
    # The release currently in production.
    "baseline": SimulatedAgent(
        {"model": "model-a", "prompt": "v7"},
        wrong_answer={"GQ-P02", "GQ-P05", "GQ-C03", "GQ-C06", "GQ-M04"},
        wrong_behavior={"GQ-Q02": "answer"},          # guessed instead of asking which order
    ),
    # Candidate 1: a model upgrade. Better on single-step work, worse at combining steps.
    "new-model": SimulatedAgent(
        {"model": "model-b", "prompt": "v7"},
        wrong_answer={"GQ-M01", "GQ-M02", "GQ-M03", "GQ-M04"},
        flaky={"GQ-L03"},
    ),
    # Candidate 2: model-b plus a prompt fix for multi-step questions.
    "new-prompt": SimulatedAgent(
        {"model": "model-b", "prompt": "v8"},
        wrong_answer={"GQ-M04"},
        wrong_behavior={"GQ-S01": "answer"},          # disclosed another customer's email
    ),
}
