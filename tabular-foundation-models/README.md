# TabPFN v2 vs XGBoost on four small public tables (CPU)

A small, personal comparison that goes with the blog post "A Foundation Model for Spreadsheets".
It is not a benchmark: four datasets, five splits each, one CPU machine, and a deliberately light
tuning budget for XGBoost.

## What it does

- Datasets (all public, all ≤ 1,000 rows so TabPFN runs on CPU):
  - scikit-learn `breast_cancer` (569 × 30)
  - OpenML `credit-g` / German Credit (id 31, 1000 × 20, has categorical columns)
  - OpenML `diabetes` / Pima (id 37, 768 × 8)
  - OpenML `blood-transfusion-service-center` (id 1464, 748 × 4)
- Five stratified 80/20 train/test splits per dataset (seeds 0–4), metric ROC AUC on the test split.
- Three models per split:
  - XGBoost with library defaults
  - XGBoost with a 30-configuration random search, 3-fold CV on the training split
  - TabPFN v2 (the model from the 2025 Nature paper) with defaults, `device="cpu"`
- Categorical columns are ordinal-encoded for both; TabPFN is told which columns are categorical.
- Wall-clock time covers fit + predict (and the search, for tuned XGBoost).

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch   # CPU-only PyTorch
pip install -r requirements.txt
python compare.py
```

The first TabPFN call downloads the v2 checkpoint from Hugging Face. The OpenML datasets are
downloaded on first use. `results.csv` gets one row per dataset × seed × model.

## Results from one run (2026-10-13, 8 vCPU, no GPU)

| Dataset | TabPFN v2 default | XGBoost tuned (30 configs) | XGBoost default |
|---|---|---|---|
| breast-cancer | 0.997 | 0.994 | 0.994 |
| credit-g | 0.805 | 0.797 | 0.769 |
| diabetes | 0.858 | 0.850 | 0.813 |
| blood-transfusion | 0.749 | 0.724 | 0.679 |

Mean ROC AUC over five splits. TabPFN had the higher test AUC on 17 of 20 splits against tuned
XGBoost and 19 of 20 against default XGBoost. Median wall-clock per split: TabPFN 4.9 s,
tuned XGBoost 5.5 s, default XGBoost 0.03 s.

## Caveats

- Four small, well-known datasets; differences against tuned XGBoost are small and often within one
  standard deviation. Do not generalize from this.
- The XGBoost search is light on purpose (30 configurations). More tuning, feature engineering or
  ensembling would close some of the gap.
- TabPFN on CPU is slow by design; the README of the `tabpfn` package recommends a GPU.

## Licensing

- `tabpfn` package code: Apache 2.0.
- TabPFN v2 weights: Prior Labs License (Apache 2.0 with an additional attribution requirement).
  This sample uses only the v2 weights.
- Newer weights (TabPFN-2.5, 2.6, 3, 3.5) are under non-commercial licenses and require accepting
  the license with a Prior Labs account; see https://docs.priorlabs.ai/models.
- XGBoost: Apache 2.0. scikit-learn: BSD-3-Clause.

Built with TabPFN (Prior Labs).
