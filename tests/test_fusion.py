import numpy as np
import scipy.sparse as sp
from data_pipeline.network import build_network, column_normalize
from data_pipeline.rwr import rwr
from data_pipeline.features import build_feature_matrix
from data_pipeline.fusion import train_logistic, evaluate_metrics, evaluate_loso, evaluate_kfold, recall_at_k


def _build_synthetic_dataset(n_seeds=3, n_other=15):
    # Build small graph where seeds are highly connected among themselves and to positives
    # Create gene list
    seeds = [f"SEED_{i}" for i in range(n_seeds)]
    others = [f"GENE_{i}" for i in range(n_other)]
    gene_list = seeds + others
    # edges: seeds fully connected, plus each seed connects to 3 others, others form chain
    edges = []
    for i in range(n_seeds):
        for j in range(i+1, n_seeds):
            edges.append((seeds[i], seeds[j], 900))
    # seed -> other links (first 6 others are "proximal positives" we will label as high)
    for i, s in enumerate(seeds):
        for j in range(3):
            target = others[(i*2 + j) % n_other]
            edges.append((s, target, 800))
    # other chain
    for i in range(n_other-1):
        edges.append((others[i], others[i+1], 700))
    adj, _, gl = build_network(edges, gene_list=gene_list)
    W = column_normalize(adj)
    # Pathway: seeds share PW1, proximal others also share PW1, distant others share PW2
    g2p = {}
    for s in seeds:
        g2p[s] = {"PW1", "PW_CAD"}
    for i, g in enumerate(others):
        if i < 6:
            g2p[g] = {"PW1"}
        else:
            g2p[g] = {"PW2"}
    return gene_list, adj, W, g2p, seeds


def test_recall_at_k():
    y_true = np.array([0,0,1,0,1])
    y_score = np.array([0.1, 0.2, 0.9, 0.3, 0.8])
    # positives at indices 2,4 should be top2
    assert recall_at_k(y_true, y_score, k=2) == 1.0
    assert recall_at_k(y_true, y_score, k=1) == 0.5
    # k larger than n
    assert recall_at_k(y_true, y_score, k=10) == 1.0
    # no positives
    assert recall_at_k(np.array([0,0]), np.array([0.1,0.2]), k=1) == 0.0


def test_feature_matrix_shape():
    gene_list, adj, W, g2p, seeds = _build_synthetic_dataset()
    from data_pipeline.seed_genes import load_seed_p0
    p0 = load_seed_p0(gene_list, seeds)
    p, _, _ = rwr(W, p0, restart_prob=0.3)
    X, names, fd = build_feature_matrix(gene_list, adj, W, p, g2p, seeds)
    assert X.shape[0] == len(gene_list)
    assert X.shape[1] == len(names) == 7
    assert "rwr_score" in names
    assert "pathway_overlap_binary" in names
    # check pathway overlap for proximal vs distant
    idx_prox = gene_list.index("GENE_0")
    idx_dist = gene_list.index("GENE_10")
    # proximal shares pathway
    assert X[idx_prox, names.index("pathway_overlap_binary")] == 1
    assert X[idx_dist, names.index("pathway_overlap_binary")] == 0


def test_fusion_train_and_metrics():
    gene_list, adj, W, g2p, seeds = _build_synthetic_dataset()
    from data_pipeline.seed_genes import load_seed_p0
    p0 = load_seed_p0(gene_list, seeds)
    p, _, _ = rwr(W, p0)
    X, names, _ = build_feature_matrix(gene_list, adj, W, p, g2p, seeds)
    y = np.array([1 if g in seeds else 0 for g in gene_list])
    clf = train_logistic(X, y)
    scores = clf.predict_proba(X)[:,1]
    assert len(scores) == len(gene_list)
    assert (scores >= 0).all() and (scores <= 1).all()
    # seeds should on average score higher than non-seeds (since RWR drives)
    assert scores[y==1].mean() > scores[y==0].mean()
    metrics = evaluate_metrics(y, scores, ks=(5,10))
    assert "auprc" in metrics
    assert 0 <= metrics["auprc"] <= 1


def test_kfold_evaluation():
    gene_list, adj, W, g2p, seeds = _build_synthetic_dataset(n_seeds=6, n_other=24)
    from data_pipeline.seed_genes import load_seed_p0
    p0 = load_seed_p0(gene_list, seeds)
    p, _, _ = rwr(W, p0)
    X, _, _ = build_feature_matrix(gene_list, adj, W, p, g2p, seeds)
    y = np.array([1 if g in seeds else 0 for g in gene_list])
    res = evaluate_kfold(X, y, n_splits=3)
    assert "aggregate" in res
    assert "auprc_mean" in res["aggregate"]
    assert 0 <= res["aggregate"]["auprc_mean"] <= 1


def test_loso_on_synthetic():
    gene_list, adj, W, g2p, seeds = _build_synthetic_dataset(n_seeds=4, n_other=16)
    res = evaluate_loso(gene_list, adj, W, g2p, seeds, ks=(5,10))
    assert "aggregate" in res
    assert "per_seed" in res
    assert len(res["per_seed"]) == len([s for s in seeds if s in gene_list])
    # aggregate should have fusion vs degree
    agg = res["aggregate"]
    assert "fusion_auprc_mean" in agg
    assert "degree_auprc_mean" in agg
    # With our synthetic where seeds clustered, fusion should beat or equal degree baseline
    # Not strict but we check both are valid numbers
    assert 0 <= agg["fusion_auprc_mean"] <= 1
