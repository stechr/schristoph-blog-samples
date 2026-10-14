"""Write baseline predictions for a typed-decisions split.

prior:   every case gets each question's mean gold distribution from the train
         split (it ignores the input).
uniform: every option gets the same probability.

Use these to check that evaluate.py reproduces the reference rows of the
typed-decisions dataset card before you trust it on your own model.
"""
import argparse
import json
from collections import defaultdict

import pandas as pd


def rows(path):
    if path.endswith(".parquet"):
        return pd.read_parquet(path).to_dict("records")
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--kind", choices=["prior", "uniform"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # Summed gold probabilities per (workflow, question, option) over the train split.
    mass = defaultdict(lambda: defaultdict(float))
    for row in rows(args.train):
        for name, g in json.loads(row["gold"]).items():
            for option, p in g["probabilities"].items():
                mass[(row["workflow"], name)][option] += p

    with open(args.out, "w") as fh:
        for row in rows(args.test):
            answers = {}
            for name, g in json.loads(row["gold"]).items():
                options = list(g["probabilities"].keys())
                if args.kind == "uniform":
                    probs = {o: 1 / len(options) for o in options}
                else:
                    m = mass[(row["workflow"], name)]
                    total = sum(m[o] for o in options)
                    probs = {o: m[o] / total for o in options}
                answers[name] = {"probabilities": probs}
            fh.write(json.dumps({"id": row["id"], "answers": answers}) + "\n")


if __name__ == "__main__":
    main()
