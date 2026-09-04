# Real training run — STRING v12 + Reactome (2026-09-03)

First real (non-synthetic) run of this repository's own `data_pipeline` package,
executed on Modal CPU against the exact endpoints `docs/data_sources.md` specifies.
Raw output: `evaluation.json`, `features.json`, `model.pkl`, `rankings.json`.
Reproduce with `run_real_training_modal.py`.

## Data — real, public, no auth

| Input | Source | Size |
|---|---|---|
| PPI edges | STRING v12, `9606.protein.links.v12.0.txt.gz` | 83,164,437 bytes |
| ID aliases | STRING v12, `9606.protein.aliases.v12.0.txt.gz` | 19,777,800 bytes |
| Pathways | Reactome, `ReactomePathways.gmt` | 298,479 bytes |

Confidence threshold 700 (default). Seed genes: the repo's own MI/CAD list
(`data_pipeline/seed_genes.py`, 26 genes).

## Result — two honest, different evaluations

**5-fold CV** (fusion model, aggregate over folds):

| Metric | Mean |
|---|---|
| Recall@10 | 0.080 |
| Recall@25 | 0.160 |
| Recall@50 | 0.227 |
| AUPRC | 0.025 |

**Leave-one-seed-out** (26 folds — one held-out MI/CAD gene per fold), comparing
the fusion model against its own two component signals:

| Model | Mean AUPRC | Mean Recall@10 |
|---|---|---|
| Fusion (logistic regression on RWR + topology + pathway features) | **0.0004** | **0.000** |
| RWR score alone | **0.032** | **0.154** |
| Degree baseline | 0.0004 | 0.000 |

## Honest reading — the fusion model is worse than its own RWR input

This is a real negative result about the fusion step specifically, not about RWR:
**in leave-one-seed-out, the plain RWR propagation score alone clearly
outperforms the logistic-regression fusion model that is supposed to improve on
it** (AUPRC 0.032 vs 0.0004 — RWR is ~80x better on this metric). The fusion
model performs essentially at the degree-baseline floor.

The mechanism is a small-n overfitting problem, not a flaw in the network or the
RWR signal itself: with only 26 seed genes, each LOSO fold trains the logistic
regression on ~25 positive examples against a ~16,000-gene universe. A linear
model over multiple correlated topology features (degree, PageRank, betweenness,
closeness, RWR score itself) has enough capacity to overfit that few positives,
while RWR alone is a single, well-behaved propagation score with no fold-specific
fitting at all.

The 5-fold CV numbers (recall@10 0.08, AUPRC 0.025) are for the same reason not
directly comparable to the LOSO numbers — 5-fold CV trains on ~20 of 26 seeds per
fold (more data per fit) and evaluates on a random held-out slice rather than a
single specific gene, which is a much easier setting than genuinely holding out
one gene's information entirely.

## What this means for the pipeline, stated plainly

On this data, at this seed-gene count, **the fusion step should not be presented
as an improvement over RWR alone**. If this pipeline is to prioritise novel
MI/CAD candidates, the RWR-based ranking is the trustworthy signal today, not the
fusion model's ranking. A regularised or lower-capacity fusion model (e.g. a
single-feature or heavily L2-penalised logistic regression, or simple rank
averaging instead of a learned classifier) would be the natural next experiment
if a data scientist wanted to try to recover fusion's advantage — not attempted
here, since it changes the model itself rather than reporting the result of the
one the repository already implements.
