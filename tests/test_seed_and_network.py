from data_pipeline.seed_genes import SEED_GENES, SEED_SET, get_seed_symbols, load_seed_p0
from data_pipeline.network import build_network, column_normalize
import numpy as np


def test_seed_list_cited():
    assert len(SEED_GENES) >= 20
    # Check required seeds present
    required = ["LDLR", "PCSK9", "APOB", "LPA", "SORT1", "APOE", "ABO", "CXCL12", "PHACTR1"]
    symbols = get_seed_symbols()
    for r in required:
        assert r in symbols, f"Missing required seed {r}"
    # Each entry has pmid and citation
    for g in SEED_GENES:
        assert "symbol" in g and "pmid" in g and "citation" in g
        assert g["pmid"].isdigit() or g["pmid"].startswith("1")


def test_load_seed_p0():
    genes = ["LDLR", "PCSK9", "GENE_X", "ABO"]
    p0 = load_seed_p0(genes, ["LDLR", "PCSK9"])
    assert abs(p0.sum() - 1.0) < 1e-9
    assert p0[genes.index("LDLR")] == 0.5
    assert p0[genes.index("GENE_X")] == 0.0
    # Unknown seeds raise
    import pytest
    with pytest.raises(ValueError):
        load_seed_p0(genes, ["NOT_IN_GRAPH"])


def test_network_build_and_normalize():
    edges = [("A","B",800), ("B","C",700), ("A","C",900)]
    adj, mapping, gl = build_network(edges)
    assert adj.shape == (3,3)
    # symmetric
    assert (adj != adj.T).nnz == 0
    W = column_normalize(adj)
    col_sums = np.array(W.sum(axis=0)).flatten()
    assert np.allclose(col_sums, 1.0)
