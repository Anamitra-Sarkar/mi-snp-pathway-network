"""
Fusion model: combine RWR + topology + pathway features.

Simple logistic regression (sklearn) and optional GBDT.
Evaluation: LOSO and k-fold, recall@k, AUPRC.
"""
import numpy as np
import json
from collections import defaultdict

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, KFold
from sklearn.metrics import average_precision_score, precision_recall_curve, auc

from .seed_genes import SEED_SET
from .network import build_network, column_normalize
from .rwr import rwr
from .features import build_feature_matrix


def train_logistic(X, y, C=1.0, max_iter=1000, class_weight="balanced"):
    clf = LogisticRegression(C=C, max_iter=max_iter, class_weight=class_weight, solver="lbfgs")
    clf.fit(X, y)
    return clf


def train_gbdt(X, y):
    clf = GradientBoostingClassifier(random_state=42)
    clf.fit(X, y)
    return clf


def recall_at_k(y_true, y_score, k):
    """
    Recall @ k: fraction of positives ranked in top k.
    y_true binary, y_score continuous.
    """
    n = len(y_true)
    k = min(k, n)
    # rank descending by score
    order = np.argsort(-y_score)
    topk = order[:k]
    positives = np.where(y_true == 1)[0]
    if len(positives) == 0:
        return 0.0
    hits = len(set(topk) & set(positives))
    return hits / len(positives)


def evaluate_metrics(y_true, y_score, ks=(10, 25, 50, 100)):
    """
    Returns dict with recall@k, auprc, ap
    """
    # AUPRC via average_precision (weighted)
    try:
        ap = average_precision_score(y_true, y_score)
    except Exception:
        ap = float("nan")
    # compute PR curve auc as alternative AUPRC
    try:
        precision, recall, _ = precision_recall_curve(y_true, y_score)
        auprc = auc(recall, precision)
    except Exception:
        auprc = ap
    out = {"auprc": float(auprc), "ap": float(ap)}
    for k in ks:
        out[f"recall@{k}"] = float(recall_at_k(y_true, y_score, k))
    return out


def evaluate_loso(gene_list, adj, W, gene_to_pathways, seed_symbols, model_fn=train_logistic, ks=(10, 25, 50, 100)):
    """
    Leave-One-Seed-Out: for each seed gene held out, train features based on remaining seeds,
    then rank held-out gene among all non-seed genes + held-out.

    To avoid data leakage, for each LOSO split:
      - p0 built from seeds \ {held_out}
      - RWR computed from that p0
      - pathway overlap uses seeds \ {held_out}
      - For training labels: positive = remaining seeds, negative = non-seed genes (subsample? use all)
        But we cannot train a model that has never seen held_out; we do CV over the training set.
        Simpler: we train fusion model via cross-validation inside LOSO (or just use raw RWR ranking for LOSO).
    Here we implement honest LOSO for RWR ranking evaluation (fusion evaluated in kfold).
    For fusion LOSO: we train logistic on remaining seeds vs negatives (non-seeds), then score held_out.
    This will be computationally more expensive but correct for small seed sets.

    Returns aggregated metrics and per-seed results.
    """
    gene_to_idx = {g: i for i, g in enumerate(gene_list)}
    seed_in_graph = [s for s in seed_symbols if s in gene_to_idx]
    if len(seed_in_graph) < 3:
        raise ValueError("Need at least 3 seeds in graph for LOSO")
    non_seed_idx = [i for i, g in enumerate(gene_list) if g not in seed_in_graph]

    per_seed = []
    # For aggregated recall, we compute per-split recall@k and average
    # We'll also pool scores: for each split, we create a ranking over (non_seeds + held_out)
    recalls = defaultdict(list)
    auprcs = []

    for held_out in seed_in_graph:
        train_seeds = [s for s in seed_in_graph if s != held_out]
        # build p0
        from .seed_genes import load_seed_p0
        p0 = load_seed_p0(gene_list, train_seeds)
        p, _, _ = rwr(W, p0, restart_prob=0.3, tol=1e-6)
        # pathway overlap using train_seeds
        from .features import build_feature_matrix
        X, fnames, _ = build_feature_matrix(gene_list, adj, W, p, gene_to_pathways, train_seeds)
        # labels: 1 for train_seeds, 0 for non-seeds (held_out is test positive)
        y = np.zeros(len(gene_list), dtype=int)
        for s in train_seeds:
            y[gene_to_idx[s]] = 1
        # train model on train_seeds vs non-seeds (exclude held_out from training)
        # simple: logistic
        train_idx = [gene_to_idx[s] for s in train_seeds] + non_seed_idx
        X_train = X[train_idx]
        y_train = y[train_idx]
        # need at least 2 classes
        if len(set(y_train)) < 2:
            continue
        clf = model_fn(X_train, y_train)
        # score all genes
        scores = clf.predict_proba(X)[:, 1] if hasattr(clf, "predict_proba") else clf.decision_function(X)
        # evaluation ranking: consider candidates = non_seeds + held_out
        held_idx = gene_to_idx[held_out]
        candidate_idx = non_seed_idx + [held_idx]
        y_true_cand = np.zeros(len(candidate_idx), dtype=int)
        y_true_cand[-1] = 1  # held_out is positive at last position
        # align scores
        y_score_cand = scores[candidate_idx]
        metrics = evaluate_metrics(y_true_cand, y_score_cand, ks=ks)
        # also compute RWR-only baseline metrics for same split
        rwr_scores_cand = p[candidate_idx]
        metrics_rwr = evaluate_metrics(y_true_cand, rwr_scores_cand, ks=ks)
        # degree baseline
        deg = np.array(adj.sum(axis=1)).flatten()
        deg_cand = deg[candidate_idx]
        metrics_deg = evaluate_metrics(y_true_cand, deg_cand, ks=ks)

        per_seed.append({
            "held_out": held_out,
            "metrics_fusion": metrics,
            "metrics_rwr": metrics_rwr,
            "metrics_degree": metrics_deg,
        })
        for k in ks:
            recalls[f"fusion_recall@{k}"].append(metrics[f"recall@{k}"])
            recalls[f"rwr_recall@{k}"].append(metrics_rwr[f"recall@{k}"])
            recalls[f"degree_recall@{k}"].append(metrics_deg[f"recall@{k}"])
        auprcs.append((metrics["auprc"], metrics_rwr["auprc"], metrics_deg["auprc"]))

    # aggregate
    agg = {}
    for key, vals in recalls.items():
        agg[key + "_mean"] = float(np.mean(vals)) if vals else 0.0
    if auprcs:
        agg["fusion_auprc_mean"] = float(np.mean([x[0] for x in auprcs]))
        agg["rwr_auprc_mean"] = float(np.mean([x[1] for x in auprcs]))
        agg["degree_auprc_mean"] = float(np.mean([x[2] for x in auprcs]))

    return {"per_seed": per_seed, "aggregate": agg}


def evaluate_kfold(X, y, n_splits=5, model_fn=train_logistic, ks=(10, 25, 50, 100)):
    """
    Stratified KFold over labeled data (seeds vs non-seeds). Report mean metrics.
    """
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    all_metrics = []
    all_metrics_deg = []
    # degree baseline: we expect caller to pass degree as comparator; here we just evaluate model
    for train_idx, test_idx in skf.split(X, y):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        clf = model_fn(X_train, y_train)
        scores = clf.predict_proba(X_test)[:, 1] if hasattr(clf, "predict_proba") else clf.decision_function(X_test)
        m = evaluate_metrics(y_test, scores, ks=ks)
        all_metrics.append(m)
    agg = {}
    for k in ks:
        vals = [m[f"recall@{k}"] for m in all_metrics]
        agg[f"recall@{k}_mean"] = float(np.mean(vals))
    agg["auprc_mean"] = float(np.mean([m["auprc"] for m in all_metrics]))
    agg["ap_mean"] = float(np.mean([m["ap"] for m in all_metrics]))
    return {"per_fold": all_metrics, "aggregate": agg}


def run_full_pipeline(edges, gene_to_pathways, seed_symbols=None, min_score=700, outdir="artifacts", restart_prob=0.3):
    """
    End-to-end pipeline for real run: build network, run RWR, compute features, train fusion, evaluate.
    Saves artifacts to outdir.
    """
    import os
    os.makedirs(outdir, exist_ok=True)
    if seed_symbols is None:
        from .seed_genes import SEED_SYMBOLS
        seed_symbols = SEED_SYMBOLS

    from .network import build_network, column_normalize
    from .seed_genes import load_seed_p0
    from .rwr import rwr
    from .features import build_feature_matrix
    import json, pickle

    adj, gene_to_idx, gene_list = build_network(edges)
    W = column_normalize(adj)
    p0 = load_seed_p0(gene_list, seed_symbols)
    p, n_iter, conv = rwr(W, p0, restart_prob=restart_prob)

    X, fnames, fdict = build_feature_matrix(gene_list, adj, W, p, gene_to_pathways, seed_symbols)
    # labels: seed vs non-seed
    y = np.array([1 if g in set(seed_symbols) else 0 for g in gene_list], dtype=int)
    clf = train_logistic(X, y)

    # evaluation kfold
    kfold_res = evaluate_kfold(X, y, n_splits=5)
    # LOSO if enough seeds in graph
    seed_in_graph = [s for s in seed_symbols if s in gene_to_idx]
    loso_res = None
    if len(seed_in_graph) >= 3:
        loso_res = evaluate_loso(gene_list, adj, W, gene_to_pathways, seed_symbols)

    # save artifacts
    scores = clf.predict_proba(X)[:, 1]
    order = np.argsort(-scores)
    ranked = [{"rank": i+1, "gene": gene_list[idx], "score": float(scores[idx]),
               "rwr": float(p[idx]), "is_seed": bool(y[idx])} for i, idx in enumerate(order)]
    with open(os.path.join(outdir, "rankings.json"), "w") as f:
        json.dump(ranked, f, indent=2)
    with open(os.path.join(outdir, "features.json"), "w") as f:
        json.dump({"gene_list": gene_list, "feature_names": fnames}, f, indent=2)
    with open(os.path.join(outdir, "model.pkl"), "wb") as f:
        pickle.dump({"model": clf, "gene_list": gene_list, "feature_names": fnames}, f)
    with open(os.path.join(outdir, "evaluation.json"), "w") as f:
        json.dump({"kfold": kfold_res, "loso": loso_res, "n_iter": n_iter, "converged": conv}, f, indent=2)
    print(f"Pipeline done: {len(gene_list)} genes, converged={conv} in {n_iter} iters")
    print(f"Kfold AUPRC {kfold_res['aggregate']['auprc_mean']:.3f}, recall@50 {kfold_res['aggregate']['recall@50_mean']:.3f}")
    if loso_res:
        print(f"LOSO fusion AUPRC {loso_res['aggregate'].get('fusion_auprc_mean',0):.3f} vs degree {loso_res['aggregate'].get('degree_auprc_mean',0):.3f}")
    return ranked
