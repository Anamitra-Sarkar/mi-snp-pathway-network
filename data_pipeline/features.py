"""
Feature computation: degree, PageRank, pathway-overlap.
"""
import numpy as np
import scipy.sparse as sp
from collections import defaultdict

from .network import get_degree
from .rwr import pagerank


def compute_topology_features(adj, W=None):
    """
    Compute degree and PageRank.
    adj: csr adjacency
    W: column-normalized (if None, compute)
    Returns dict: gene_idx -> {degree, pagerank}
    """
    from .network import column_normalize
    n = adj.shape[0]
    degrees = get_degree(adj)
    if W is None:
        W = column_normalize(adj)
    pr, _, _ = pagerank(W)
    # also degree normalized
    max_deg = degrees.max() if degrees.max() > 0 else 1
    return {
        "degree": degrees,
        "degree_norm": degrees / max_deg,
        "pagerank": pr,
        "log_degree": np.log1p(degrees),
    }


def compute_pathway_overlap_features(gene_list, gene_to_pathways, seed_symbols):
    """
    Compute pathway overlap between each gene and the seed set.
    For each candidate gene g:
      - pathway_overlap_binary: 1 if shares >=1 pathway with any seed, else 0
      - pathway_overlap_count: number of pathways shared with any seed (union)
      - pathway_jaccard: max Jaccard between g's pathways and any seed's pathways (or 0 if none)
    Returns dict of arrays shape (n,).
    """
    seed_set = set(seed_symbols)
    # collect all pathways that any seed belongs to
    seed_pathways_union = set()
    for s in seed_set:
        if s in gene_to_pathways:
            seed_pathways_union.update(gene_to_pathways[s])

    n = len(gene_list)
    binary = np.zeros(n, dtype=int)
    count = np.zeros(n, dtype=int)
    jaccard_max = np.zeros(n, dtype=float)

    # optional: precompute seed pathway sets
    seed_pws = {s: gene_to_pathways.get(s, set()) for s in seed_set}

    for i, g in enumerate(gene_list):
        g_pws = gene_to_pathways.get(g, set())
        if not g_pws:
            continue
        inter_union = g_pws & seed_pathways_union
        if inter_union:
            binary[i] = 1
            count[i] = len(inter_union)
        # max Jaccard with any seed
        best = 0.0
        for s, s_pws in seed_pws.items():
            if not s_pws:
                continue
            inter = len(g_pws & s_pws)
            union = len(g_pws | s_pws)
            if union == 0:
                continue
            j = inter / union
            if j > best:
                best = j
        jaccard_max[i] = best

    return {
        "pathway_overlap_binary": binary,
        "pathway_overlap_count": count,
        "pathway_jaccard_max": jaccard_max,
    }


def build_feature_matrix(gene_list, adj, W, rwr_scores, gene_to_pathways, seed_symbols):
    """
    Build feature matrix for fusion model.
    Features: rwr_score, degree, degree_norm, log_degree, pagerank, pathway_binary, pathway_count, pathway_jaccard
    Returns: X shape (n, d), feature_names, feature_dict
    """
    n = len(gene_list)
    topo = compute_topology_features(adj, W)
    pw = compute_pathway_overlap_features(gene_list, gene_to_pathways, seed_symbols)

    # rwr_scores should be array shape (n,)
    rwr_scores = np.asarray(rwr_scores, dtype=float)

    # stack
    feature_names = ["rwr_score", "degree_norm", "log_degree", "pagerank", "pathway_overlap_binary", "pathway_overlap_count", "pathway_jaccard_max"]
    # normalize rwr and pagerank already somewhat, but z-score not needed for logistic regression? We'll keep raw + log
    X = np.column_stack([
        rwr_scores,
        topo["degree_norm"],
        topo["log_degree"],
        topo["pagerank"],
        pw["pathway_overlap_binary"].astype(float),
        pw["pathway_overlap_count"].astype(float),
        pw["pathway_jaccard_max"],
    ])
    feature_dict = {**topo, **pw, "rwr_score": rwr_scores}
    return X, feature_names, feature_dict
