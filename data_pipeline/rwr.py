"""
Random Walk with Restart (RWR) implementation.

p_{t+1} = (1-r) * W * p_t + r * p_0
W column-normalized transition matrix (csc), p vectors shape (n,).
"""
import numpy as np
import scipy.sparse as sp


def rwr(W, p0, restart_prob=0.3, tol=1e-6, max_iter=1000, verbose=False):
    """
    Power iteration for RWR.
    W: scipy.sparse csc/csr column-stochastic matrix (n x n)
    p0: np.array (n,) summing to 1, restart distribution
    restart_prob: r in [0,1]
    Returns:
      p: stationary distribution (n,) summing to ~1
      n_iter: iterations
      converged: bool
    """
    if not 0 <= restart_prob <= 1:
        raise ValueError(f"restart_prob must be in [0,1], got {restart_prob}")
    if tol <= 0:
        raise ValueError(f"tol must be >0, got {tol}")
    if max_iter <= 0:
        raise ValueError(f"max_iter must be >0, got {max_iter}")
    n = W.shape[0]
    if W.shape[0] != W.shape[1]:
        raise ValueError(f"W must be square, got shape {W.shape}")
    if len(p0) != n:
        raise ValueError(f"p0 length {len(p0)} != W shape {n}")
    # normalize p0
    p0 = np.asarray(p0, dtype=float)
    s = p0.sum()
    if s == 0:
        raise ValueError("p0 sums to 0")
    p0 = p0 / s

    p = p0.copy()
    r = restart_prob
    for it in range(max_iter):
        p_next = (1 - r) * (W @ p) + r * p0
        # renormalize to handle numeric drift (should already sum to 1)
        p_next = p_next / p_next.sum() if p_next.sum() != 0 else p_next
        diff = np.linalg.norm(p_next - p, ord=1)
        if verbose and it % 10 == 0:
            print(f"iter {it} diff {diff:.3e}")
        if diff < tol:
            return p_next, it + 1, True
        p = p_next
    return p, max_iter, False


def pagerank(W, alpha=0.85, tol=1e-6, max_iter=1000):
    """
    PageRank: same as RWR with uniform p0.
    W column-stochastic. Returns pr vector.
    """
    n = W.shape[0]
    p0 = np.ones(n) / n
    return rwr(W, p0, restart_prob=1 - alpha, tol=tol, max_iter=max_iter)
