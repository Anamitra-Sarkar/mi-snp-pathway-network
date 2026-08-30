"""
Network construction utilities: build sparse adjacency / transition matrix.
"""
import numpy as np
import scipy.sparse as sp


def build_network(edges, gene_list=None, weighted=False):
    """
    Build sparse adjacency matrix from edge list.
    edges: iterable of (gene1, gene2, score)
    gene_list: optional ordered list of genes. If None, sorted unique genes.
    weighted: if True, use combined_score/1000 as weight, else binary (1)
    Returns:
      adj: scipy.sparse.csr_matrix shape (n,n), symmetric
      gene_to_idx: dict
      idx_to_gene: list
    """
    if gene_list is None:
        genes = set()
        for g1, g2, _ in edges:
            genes.add(g1)
            genes.add(g2)
        gene_list = sorted(genes)
    gene_to_idx = {g: i for i, g in enumerate(gene_list)}
    n = len(gene_list)
    rows, cols, data = [], [], []
    for g1, g2, score in edges:
        if g1 not in gene_to_idx or g2 not in gene_to_idx:
            continue
        i, j = gene_to_idx[g1], gene_to_idx[g2]
        w = float(score) / 1000.0 if weighted else 1.0
        rows.extend([i, j])
        cols.extend([j, i])
        data.extend([w, w])
    adj = sp.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()
    # ensure diagonal zero (no self-loops)
    adj.setdiag(0)
    adj.eliminate_zeros()
    return adj, gene_to_idx, gene_list


def column_normalize(adj):
    """
    Column-normalize adjacency to get stochastic transition matrix W (column-stochastic).
    Dangling nodes (degree 0) get uniform? Here we leave column as 0 and handle in RWR via
    teleport; alternatively, we set dangling columns to uniform via small epsilon. We choose:
    dangling columns remain 0 (will be handled by RWR iteration: mass from dangling nodes is lost
    unless we add teleport; but we also keep p0 restart which ensures conservation).
    For more stable: set dangling columns to 1/n.

    Returns csc_matrix (efficient column slicing).
    """
    n = adj.shape[0]
    csc = adj.tocsc()
    col_sums = np.array(csc.sum(axis=0)).flatten()
    # avoid division by zero
    inv = np.zeros(n, dtype=float)
    nonzero = col_sums > 0
    inv[nonzero] = 1.0 / col_sums[nonzero]
    # scale columns
    Dinv = sp.diags(inv)
    W = csc @ Dinv  # column-normalized
    # dangling columns: fill uniform 1/n so column sums =1 for all (standard PageRank handling)
    dangling = np.where(col_sums == 0)[0]
    if len(dangling) > 0:
        # Use lil for assignment then convert back
        W = W.tolil()
        uniform = 1.0 / n
        for j in dangling:
            W[:, j] = uniform
        W = W.tocsc()
    return W


def get_degree(adj):
    """Degree per node (sum of adjacency row, equal to column sum for undirected)."""
    deg = np.array(adj.sum(axis=1)).flatten()
    return deg
