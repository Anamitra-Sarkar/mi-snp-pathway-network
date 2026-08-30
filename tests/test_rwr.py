import numpy as np
import scipy.sparse as sp
import pathlib
import tempfile
import os

from data_pipeline.network import build_network, column_normalize
from data_pipeline.rwr import rwr, pagerank
from data_pipeline.string_parser import parse_string_links


def _synthetic_network():
    # 10-node chain + extras
    edges = [
        ("A","B",900), ("A","C",800), ("B","C",850), ("B","D",750),
        ("C","E",700), ("D","E",900), ("E","F",800), ("F","G",900),
        ("G","H",850), ("H","I",700), ("I","J",750), ("A","J",700),
        ("B","F",720), ("C","G",710),
    ]
    adj, _, genes = build_network(edges)
    W = column_normalize(adj)
    return adj, W, genes


def test_rwr_converges_and_sums_to_one():
    adj, W, genes = _synthetic_network()
    # column sums should be 1
    col_sums = np.array(W.sum(axis=0)).flatten()
    np.testing.assert_allclose(col_sums, np.ones(len(genes)), atol=1e-9)
    p0 = np.zeros(len(genes))
    p0[genes.index("A")] = 1.0
    p, n_iter, conv = rwr(W, p0, restart_prob=0.3, tol=1e-9, max_iter=1000)
    assert conv, "RWR should converge"
    assert n_iter < 1000
    # sums to 1
    assert abs(p.sum() - 1.0) < 1e-9
    # all non-negative
    assert (p >= -1e-12).all()


def test_rwr_seed_ranks_high():
    adj, W, genes = _synthetic_network()
    # seeds A, B -> candidates near them should rank higher than distant I,J? But with RWR they should.
    seed_idx = [genes.index("A"), genes.index("B")]
    p0 = np.zeros(len(genes))
    for i in seed_idx: p0[i] = 0.5
    p, _, _ = rwr(W, p0, restart_prob=0.3)
    # seed genes themselves should be top 2-3? Check that A and B are in top 4
    order = np.argsort(-p)
    top4 = [genes[i] for i in order[:4]]
    assert "A" in top4
    assert "B" in top4
    # neighbors C,F should outrank far I
    assert p[genes.index("C")] > p[genes.index("I")]
    assert p[genes.index("B")] > p[genes.index("J")]


def test_pagerank_sums():
    adj, W, genes = _synthetic_network()
    pr, _, conv = pagerank(W)
    assert conv
    assert abs(pr.sum() - 1.0) < 1e-9


def test_dangling_node_handling():
    # isolated node
    edges = [("A","B",900), ("B","C",900)]
    # genes will be A,B,C; add isolated D via gene_list
    adj, _, genes = build_network(edges, gene_list=["A","B","C","D"])
    W = column_normalize(adj)
    col_sums = np.array(W.sum(axis=0)).flatten()
    np.testing.assert_allclose(col_sums, np.ones(4), atol=1e-9)
    # dangling column D should be uniform 0.25
    # W is csc
    d_col = np.array(W[:,3].todense()).flatten()
    np.testing.assert_allclose(d_col, np.ones(4)/4, atol=1e-9)
    p0 = np.zeros(4); p0[0]=1
    p, _, conv = rwr(W, p0)
    assert conv
    assert abs(p.sum()-1.0)<1e-9


def test_parse_string_links_synthetic():
    path = pathlib.Path(__file__).parent / "fixtures" / "synthetic_edges.tsv"
    edges, genes = parse_string_links(str(path), min_score=700)
    assert len(edges) > 0
    assert len(genes) == 10
    # filter higher min_score
    edges2, _ = parse_string_links(str(path), min_score=900)
    assert len(edges2) < len(edges)
    # test gzipped reading
    import gzip, tempfile
    with tempfile.NamedTemporaryFile(suffix=".tsv.gz", delete=False) as tmp:
        tmp_path = tmp.name
    # copy content gzip
    import shutil
    with open(path, "rb") as f_in, gzip.open(tmp_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    try:
        edges_gz, genes_gz = parse_string_links(tmp_path, min_score=700)
        assert len(edges_gz) == len(edges)
    finally:
        os.unlink(tmp_path)
