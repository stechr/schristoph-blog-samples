"""Score typed decisions: accuracy, Brier, KL from gold, ECE, and an escalation sweep.

Input 1: a typed-decisions split (parquet from Hugging Face, or JSONL with the same
         columns: id, questions, gold).
Input 2: a predictions JSONL, one line per case:
         {"id": "...", "answers": {"<question>": {"probabilities": {"<option>": p, ...}}}}

Every decision is one (case, question) pair. Metric definitions are written out in
README.md so you can compare them with other reports.
"""
import argparse
import json
import math
import sys


def load_cases(path):
    if path.endswith(".parquet"):
        import pandas as pd  # only needed for parquet input

        rows = pd.read_parquet(path).to_dict("records")
    else:
        with open(path) as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    cases = {}
    for row in rows:
        gold = row["gold"]
        cases[row["id"]] = json.loads(gold) if isinstance(gold, str) else gold
    return cases


def load_predictions(path):
    preds = {}
    with open(path) as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                preds[rec["id"]] = rec["answers"]
    return preds


def decisions(cases, preds):
    """Yield (question_name, options, gold_probs, gold_label, pred_probs)."""
    for case_id, gold in cases.items():
        if case_id not in preds:
            raise SystemExit(f"missing prediction for case {case_id}")
        for name, g in gold.items():
            options = list(g["probabilities"].keys())
            p = preds[case_id][name]["probabilities"]
            total = sum(p.get(o, 0.0) for o in options)
            if total <= 0:
                raise SystemExit(f"case {case_id} question {name}: probabilities sum to 0")
            yield (
                name,
                options,
                [g["probabilities"][o] for o in options],
                g["label"],
                [p.get(o, 0.0) / total for o in options],
            )


def score(cases, preds, bins=10, eps=1e-12):
    n = correct = 0
    brier = kl = 0.0
    conf_hits = []  # (top-label confidence, was it the gold label?)
    for _, options, gp, glabel, pp in decisions(cases, preds):
        best = max(pp)
        tops = [i for i in range(len(options)) if pp[i] == best]
        # Ties share the credit, so a uniform guess scores 1/k instead of
        # depending on option order.
        hit = sum(options[i] == glabel for i in tops) / len(tops)
        n += 1
        correct += hit
        # Brier against the soft gold distribution, summed over options.
        brier += sum((pp[i] - gp[i]) ** 2 for i in range(len(options)))
        kl += sum(g * math.log(g / max(p, eps)) for g, p in zip(gp, pp) if g > 0)
        conf_hits.append((best, hit))
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [(c, h) for c, h in conf_hits if lo < c <= hi or (b == 0 and c == 0)]
        if bucket:
            avg_conf = sum(c for c, _ in bucket) / len(bucket)
            acc = sum(h for _, h in bucket) / len(bucket)
            ece += len(bucket) / n * abs(avg_conf - acc)
    return {
        "decisions": n,
        "accuracy": correct / n,
        "brier": brier / n,
        "kl_from_gold": kl / n,
        "ece": ece,
    }, conf_hits


def escalation_sweep(conf_hits, thresholds):
    """Answer locally when top-label confidence >= t, escalate the rest."""
    rows = []
    n = len(conf_hits)
    for t in thresholds:
        kept = [h for c, h in conf_hits if c >= t]
        rows.append(
            {
                "threshold": t,
                "answered_locally": len(kept) / n,
                "local_accuracy": (sum(kept) / len(kept)) if kept else None,
                "escalated": 1 - len(kept) / n,
            }
        )
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", required=True, help="typed-decisions split (.parquet or .jsonl)")
    ap.add_argument("--predictions", required=True, help="predictions JSONL")
    ap.add_argument("--thresholds", default="0.5,0.6,0.7,0.8,0.9")
    args = ap.parse_args()

    metrics, conf_hits = score(load_cases(args.cases), load_predictions(args.predictions))
    thresholds = [float(t) for t in args.thresholds.split(",")]
    out = {"metrics": metrics, "escalation": escalation_sweep(conf_hits, thresholds)}
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
