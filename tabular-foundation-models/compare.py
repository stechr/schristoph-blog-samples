"""Small personal comparison: XGBoost (default and lightly tuned) vs TabPFN v2 (default).

CPU only, four small public datasets (<= 1,000 rows), 5 repeated stratified 80/20 splits.
This is NOT a benchmark. It is one person's sanity check on a laptop-class CPU box.

Run:
    pip install -r requirements.txt
    python compare.py            # writes results.csv and prints a summary table
"""
from __future__ import annotations

import csv
import time
import warnings

import numpy as np
import pandas as pd
from scipy.stats import loguniform, randint, uniform
from sklearn.datasets import fetch_openml, load_breast_cancer
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, train_test_split
from tabpfn import TabPFNClassifier
from tabpfn.constants import ModelVersion
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

SEEDS = [0, 1, 2, 3, 4]
TUNING_ITERS = 30  # random-search configurations for the "tuned" XGBoost


def load_datasets() -> dict[str, tuple[pd.DataFrame, np.ndarray]]:
    out = {}
    X, y = load_breast_cancer(return_X_y=True, as_frame=True)
    out["breast-cancer (569x30)"] = (X, np.asarray(y))
    # OpenML datasets (public): credit-g = German Credit (id 31), diabetes = Pima (id 37),
    # blood-transfusion-service-center (id 1464)
    for name, did in [("credit-g", 31), ("diabetes", 37), ("blood-transfusion", 1464)]:
        bunch = fetch_openml(data_id=did, as_frame=True, parser="auto")
        X = bunch.data
        y = pd.factorize(bunch.target)[0]
        out[f"{name} ({X.shape[0]}x{X.shape[1]})"] = (X, y)
    return out


def encode(X: pd.DataFrame) -> tuple[np.ndarray, list[int]]:
    """Ordinal-encode categorical columns; return matrix + categorical column indices."""
    X = X.copy()
    cat_idx = []
    for i, col in enumerate(X.columns):
        if not pd.api.types.is_numeric_dtype(X[col]):
            X[col] = pd.factorize(X[col])[0]
            cat_idx.append(i)
    return X.to_numpy(dtype=float), cat_idx


def xgb_default(Xtr, ytr, Xte, seed):
    m = XGBClassifier(n_jobs=4, random_state=seed, eval_metric="logloss")
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def xgb_tuned(Xtr, ytr, Xte, seed):
    space = {
        "n_estimators": randint(50, 600),
        "max_depth": randint(2, 9),
        "learning_rate": loguniform(0.01, 0.3),
        "subsample": uniform(0.5, 0.5),
        "colsample_bytree": uniform(0.5, 0.5),
        "min_child_weight": loguniform(0.5, 20),
        "reg_lambda": loguniform(0.1, 10),
    }
    search = RandomizedSearchCV(
        XGBClassifier(n_jobs=4, random_state=seed, eval_metric="logloss"),
        space, n_iter=TUNING_ITERS, scoring="roc_auc",
        cv=StratifiedKFold(3, shuffle=True, random_state=seed), random_state=seed, n_jobs=1,
    )
    search.fit(Xtr, ytr)
    return search.predict_proba(Xte)[:, 1]


def tabpfn_v2(Xtr, ytr, Xte, seed, cat_idx):
    m = TabPFNClassifier.create_default_for_version(
        ModelVersion.V2, device="cpu", random_state=seed, categorical_features_indices=cat_idx or None
    )
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def main() -> None:
    rows = []
    for ds_name, (Xdf, y) in load_datasets().items():
        X, cat_idx = encode(Xdf)
        for seed in SEEDS:
            Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=seed)
            for model_name, fn in [
                ("XGBoost default", lambda: xgb_default(Xtr, ytr, Xte, seed)),
                (f"XGBoost tuned ({TUNING_ITERS}x3-fold)", lambda: xgb_tuned(Xtr, ytr, Xte, seed)),
                ("TabPFN v2 default", lambda: tabpfn_v2(Xtr, ytr, Xte, seed, cat_idx)),
            ]:
                t0 = time.perf_counter()
                proba = fn()
                secs = time.perf_counter() - t0
                auc = roc_auc_score(yte, proba)
                rows.append({"dataset": ds_name, "seed": seed, "model": model_name,
                             "roc_auc": round(auc, 4), "seconds": round(secs, 2)})
                print(f"{ds_name:28s} seed={seed} {model_name:28s} AUC={auc:.4f} {secs:6.1f}s", flush=True)

    with open("results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    df = pd.DataFrame(rows)
    summary = df.groupby(["dataset", "model"]).agg(
        auc_mean=("roc_auc", "mean"), auc_std=("roc_auc", "std"), sec_mean=("seconds", "mean")
    ).round(3)
    print("\n", summary.to_string())


if __name__ == "__main__":
    main()
