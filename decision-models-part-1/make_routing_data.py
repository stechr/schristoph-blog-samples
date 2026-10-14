"""Generate a small synthetic routing dataset in the typed-decisions format.

The task: an agent receives a request and has to decide which skill handles it,
whether a human should look at it first, and how urgent it is. Every request is
built from templates, so the data contains no real requests, names or customers.

Each output line has the columns Unsloth's FastDecisionModel.build_dataset and
evaluate.py read: id, workflow, state, questions (JSON string), gold (JSON string).

The gold labels here come from the templates, which makes the task easier than
real traffic. Treat a model trained only on this as a smoke test, then add
labelled examples from your own logs.
"""
import argparse
import json
import random

SKILLS = {
    "research": "Answer a question by reading documentation or the web.",
    "calendar": "Find, create or move meetings and time blocks.",
    "writing": "Draft or edit a document, post or message.",
    "expenses": "Collect receipts and prepare an expense report.",
    "other": "Anything the other skills do not cover.",
}

REQUESTS = {
    "research": [
        "What is the maximum payload size for {thing}?",
        "Can you find out whether {thing} supports cross-region replication?",
        "Look up the current limits for {thing} and summarise them.",
        "Is there an official guide for migrating to {thing}?",
    ],
    "calendar": [
        "Move my {when} sync with the platform team to {later}.",
        "Block two hours of focus time {when}.",
        "Find a slot {when} where the whole design group is free.",
        "Cancel the {when} review, the presenter is out.",
    ],
    "writing": [
        "Draft a short note to the team about the {thing} rollout.",
        "Tighten the intro of my post about {thing}.",
        "Write a two-line summary of yesterday's {thing} discussion.",
        "Turn these bullet points about {thing} into a paragraph.",
    ],
    "expenses": [
        "I have three taxi receipts from {when}, please file them.",
        "Prepare the expense report for the {thing} conference trip.",
        "The hotel invoice from {when} is in my inbox, add it to the report.",
    ],
    "other": [
        "What's a good name for a houseplant?",
        "Tell me a joke about {thing}.",
        "How tall is the tallest tree in the world?",
    ],
}

THINGS = ["the event bus", "object storage", "the build pipeline", "the search index",
          "the vector store", "the billing export", "the login service"]
WHEN = ["Monday", "tomorrow morning", "Thursday afternoon", "next week", "today"]
LATER = ["Friday", "next Tuesday", "after lunch", "the week after"]
URGENT_MARKERS = ["", "", "", " This is blocking a customer demo today.", " No rush."]
RISKY_MARKERS = ["", "", "", " Send it to the whole company list.", " Approve it on my behalf."]

QUESTIONS = {
    "skill": {
        "type": "choice",
        "instructions": "Which skill should handle this request?",
        "criteria": SKILLS,
    },
    "needs_human": {
        "type": "noul",
        "instructions": "Should a human confirm before the agent acts?",
        "criteria": {
            "false": "The agent can act without a confirmation.",
            "true": "The action is broad, irreversible or acts on someone's behalf.",
        },
    },
    "urgency": {
        "type": "score",
        "instructions": "How urgent is this request?",
        "criteria": ["Can wait.", "Should happen this week.", "Needs to happen today."],
    },
}


def soft(options, target, mass, rng):
    """Put `mass` on the target option and spread the rest at random."""
    rest = [o for o in options if o != target]
    weights = [rng.random() + 0.1 for _ in rest]
    total = sum(weights)
    probs = {o: (1 - mass) * w / total for o, w in zip(rest, weights)}
    probs[target] = mass
    return {o: round(probs[o], 6) for o in options}


def answer(qtype, options, target, mass, rng):
    probs = soft(options, target, mass, rng)
    label = max(probs, key=probs.get)
    # "confidence" here is simply the top probability; the typed-decisions card
    # uses its own formula for that field. evaluate.py does not read it.
    out = {"type": qtype, "label": label, "probabilities": probs, "confidence": probs[label]}
    if qtype == "noul":
        out["noul"] = probs["true"]
    if qtype == "score":
        out["score"] = round(sum(int(k) * v for k, v in probs.items()), 6)
    return out


def make_row(i, rng, split):
    skill = rng.choice(list(SKILLS))
    template = rng.choice(REQUESTS[skill])
    text = template.format(thing=rng.choice(THINGS), when=rng.choice(WHEN), later=rng.choice(LATER))
    urgent_marker = rng.choice(URGENT_MARKERS)
    risky_marker = rng.choice(RISKY_MARKERS) if skill in ("writing", "expenses") else ""
    text += urgent_marker + risky_marker

    urgency = "2" if "today" in urgent_marker else ("0" if "No rush" in urgent_marker else "1")
    needs_human = "true" if risky_marker else "false"
    # Ambiguous templates get softer gold; "other" is the least certain class.
    skill_mass = 0.7 if skill == "other" else rng.uniform(0.8, 0.95)

    gold = {
        "skill": answer("choice", list(SKILLS), skill, skill_mass, rng),
        "needs_human": answer("noul", ["false", "true"], needs_human, rng.uniform(0.8, 0.95), rng),
        "urgency": answer("score", ["0", "1", "2"], urgency, rng.uniform(0.7, 0.9), rng),
    }
    return {
        "id": f"routing-{split}-{i:04d}",
        "workflow": "agent_skill_routing",
        "split": split,
        "state": json.dumps({"request": text}),
        "questions": json.dumps(QUESTIONS),
        "gold": json.dumps(gold),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--train", type=int, default=400)
    ap.add_argument("--test", type=int, default=100)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--out-prefix", default="routing")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    for split, n in (("train", args.train), ("test", args.test)):
        path = f"{args.out_prefix}-{split}.jsonl"
        with open(path, "w") as fh:
            for i in range(n):
                fh.write(json.dumps(make_row(i, rng, split)) + "\n")
        print(f"wrote {n} rows to {path}")


if __name__ == "__main__":
    main()
