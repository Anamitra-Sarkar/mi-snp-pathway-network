"""
Hardening tests: edge-case handling for parsers, RWR validation, backend error paths.
Covers documented gaps: real file quirks, missing optional columns, comment lines,
header variants, malformed inputs should yield clean 4xx not 500.
"""
import os
import json
import gzip
import tempfile
import pathlib

import numpy as np
import scipy.sparse as sp
import pytest
from fastapi.testclient import TestClient


# --- STRING parser edge cases ---

from data_pipeline.string_parser import parse_string_links, load_aliases, edges_to_adjacency_inputs
from data_pipeline.pathway_parser import parse_gmt, parse_kegg_link, parse_pathways
from data_pipeline.network import build_network, column_normalize
from data_pipeline.rwr import rwr


def test_string_parser_comment_and_header_variants():
    # Header variant with tab + comment lines + empty lines
    content = "# STRING PPI\n# comment\nprotein1\tprotein2\tcombined_score\n9606.ENSP001\t9606.ENSP002\t700\n\n# another comment\n9606.ENSP001\t9606.ENSP003\t900\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        edges, genes = parse_string_links(path, min_score=700)
        assert len(edges) == 2
        assert "ENSP001" in genes
    finally:
        os.unlink(path)


def test_string_parser_float_scores_and_trailing_comments():
    content = "protein1 protein2 combined_score\nGENE_A GENE_B 700.0\nGENE_A GENE_C 800 # inline comment\nGENE_B GENE_C 699\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        edges, genes = parse_string_links(path, min_score=700)
        # GENE_B-GENE_C score 699 should be filtered, but 700.0 and 800 kept
        assert len(edges) == 2
        # check both edges present
        edge_genes = {(a, b) for a, b, _ in edges}
        assert ("GENE_A", "GENE_B") in edge_genes or ("GENE_B", "GENE_A") in edge_genes
    finally:
        os.unlink(path)


def test_string_parser_mixed_delimiter_and_extra_columns():
    content = "protein1 protein2 combined_score extra_col\nGENE_A GENE_B 900 foo\nGENE_B\tGENE_C\t800\tbar\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        edges, genes = parse_string_links(path, min_score=700)
        assert len(edges) == 2
    finally:
        os.unlink(path)


def test_string_parser_empty_after_filter():
    content = "protein1 protein2 combined_score\nGENE_A GENE_B 100\nGENE_B GENE_C 200\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        edges, genes = parse_string_links(path, min_score=700)
        assert len(edges) == 0
        assert len(genes) == 0
    finally:
        os.unlink(path)


def test_string_parser_alias_mapping_with_header_and_bom():
    # aliases with BOM, header, comment, multiple sources
    aliases_content = "\ufeff#string_protein_id\talias\tsource\nstring_protein_id\talias\tsource\n9606.ENSP001\tGENE_A\tEnsembl_HGNC\n9606.ENSP001\tOLD_A\tEnsembl_gene\n9606.ENSP002\tGENE_B\tUnknown\n9606.ENSP003\tGENE_C\tEnsembl_gene_name\n"
    links_content = "protein1 protein2 combined_score\n9606.ENSP001 9606.ENSP002 800\n9606.ENSP002 9606.ENSP003 750\n9606.ENSP001 9606.ENSP003 700\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as af:
        af.write(aliases_content)
        apath = af.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as lf:
        lf.write(links_content)
        lpath = lf.name
    try:
        amap = load_aliases(apath)
        assert amap["9606.ENSP001"] == "GENE_A"  # HGNC priority wins
        assert amap["9606.ENSP002"] == "GENE_B"
        edges, genes = parse_string_links(lpath, min_score=700, aliases_path=apath)
        assert len(edges) == 3
        assert "GENE_A" in genes and "GENE_B" in genes
    finally:
        os.unlink(apath)
        os.unlink(lpath)


def test_string_parser_gzipped_with_comments():
    content = "# comment\nprotein1 protein2 combined_score\nGENE_X GENE_Y 800\nGENE_Y GENE_Z 750\n"
    with tempfile.NamedTemporaryFile(suffix=".tsv.gz", delete=False) as tmp:
        tpath = tmp.name
    try:
        with gzip.open(tpath, "wt") as gz:
            gz.write(content)
        edges, genes = parse_string_links(tpath, min_score=700)
        assert len(edges) == 2
        assert "GENE_X" in genes
    finally:
        os.unlink(tpath)


def test_string_parser_invalid_min_score():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as tmp:
        tmp.write("protein1 protein2 combined_score\nGENE_A GENE_B 800\n")
        path = tmp.name
    try:
        with pytest.raises(ValueError):
            parse_string_links(path, min_score=2000)
    finally:
        os.unlink(path)


def test_edges_dedup_keeps_max():
    edges = [("A", "B", 700), ("B", "A", 900), ("A", "B", 800)]
    dedup = edges_to_adjacency_inputs(edges)
    assert len(dedup) == 1
    assert dedup[0][2] == 900


# --- Pathway parser edge cases ---

def test_gmt_comment_blank_and_missing_desc():
    content = "# Reactome GMT\n\nR-HSA-1\tPathway one\tGENE_A\tGENE_B\nR-HSA-2\t\tGENE_C\tGENE_D\nR-HSA-3\tDesc with spaces\tGENE_E\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gmt", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        g2p, p2g, names = parse_gmt(path)
        assert "R-HSA-1" in p2g
        assert "R-HSA-2" in p2g  # missing desc allowed
        assert "R-HSA-3" in p2g
        assert names["R-HSA-2"] == ""
        assert "GENE_A" in g2p
    finally:
        os.unlink(path)


def test_gmt_duplicate_pathway_merge():
    content = "R-HSA-1\tDesc1\tGENE_A\tGENE_B\nR-HSA-1\tDesc1\tGENE_C\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gmt", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        g2p, p2g, _ = parse_gmt(path)
        assert p2g["R-HSA-1"] == {"GENE_A", "GENE_B", "GENE_C"}
        assert g2p["GENE_C"] == {"R-HSA-1"}
    finally:
        os.unlink(path)


def test_gmt_comma_separated_and_whitespace():
    content = "R-HSA-1\tDesc\tGENE_A,GENE_B GENE_C\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gmt", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        g2p, p2g, _ = parse_gmt(path)
        # Should parse at least GENE_A and GENE_B etc.
        assert "R-HSA-1" in p2g
        assert len(p2g["R-HSA-1"]) >= 2
    finally:
        os.unlink(path)


def test_kegg_reversed_columns_and_mixed_delim():
    content = "# KEGG link\n hsa:10458 \t path:hsa04110 \npath:hsa00010\thsa:2318\n  path:map00010   hsa:9999 \n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        g2p, p2g, _ = parse_kegg_link(path)
        assert "10458" in g2p
        assert "hsa04110" in g2p["10458"]
        assert "2318" in g2p
        assert "9999" in g2p
    finally:
        os.unlink(path)


def test_kegg_extra_columns_and_empty_lines():
    content = "path:hsa04110\thsa:10458\textra\n\npath:hsa04110\thsa:2318\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        g2p, p2g, _ = parse_kegg_link(path)
        assert "10458" in g2p
        assert len(p2g["hsa04110"]) == 2
    finally:
        os.unlink(path)


def test_parse_pathways_auto_detect():
    # GMT content should be detected as gmt
    gmt_content = "R-HSA-1\tDesc\tGENE_A\tGENE_B\n"
    kegg_content = "path:hsa04110\thsa:10458\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gmt", delete=False) as fg:
        fg.write(gmt_content)
        gpath = fg.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fk:
        fk.write(kegg_content)
        kpath = fk.name
    try:
        g2p, p2g, _ = parse_pathways(gpath, fmt="auto")
        assert "R-HSA-1" in p2g
        g2p2, p2g2, _ = parse_pathways(kpath, fmt="auto")
        assert "10458" in g2p2
    finally:
        os.unlink(gpath)
        os.unlink(kpath)


def test_parse_pathways_gzipped_gmt():
    content = "R-HSA-1\tDesc\tGENE_A\tGENE_B\n"
    with tempfile.NamedTemporaryFile(suffix=".gmt.gz", delete=False) as tmp:
        tpath = tmp.name
    try:
        with gzip.open(tpath, "wt") as gz:
            gz.write(content)
        g2p, p2g, _ = parse_pathways(tpath, fmt="gmt")
        assert "R-HSA-1" in p2g
    finally:
        os.unlink(tpath)


# --- RWR validation ---

def test_rwr_invalid_restart_prob():
    adj, _, genes = build_network([("A", "B", 900)], gene_list=["A", "B"])
    W = column_normalize(adj)
    p0 = np.array([0.5, 0.5])
    with pytest.raises(ValueError):
        rwr(W, p0, restart_prob=1.5)
    with pytest.raises(ValueError):
        rwr(W, p0, restart_prob=-0.1)


def test_rwr_invalid_p0_length():
    adj, _, genes = build_network([("A", "B", 900)], gene_list=["A", "B"])
    W = column_normalize(adj)
    with pytest.raises(ValueError):
        rwr(W, np.array([0.5]), restart_prob=0.3)


def test_rwr_zero_sum_p0():
    adj, _, genes = build_network([("A", "B", 900)], gene_list=["A", "B"])
    W = column_normalize(adj)
    with pytest.raises(ValueError):
        rwr(W, np.array([0.0, 0.0]), restart_prob=0.3)


# --- Backend error handling (4xx not 500) ---

def _make_artifacts(tmpdir, n_genes=10):
    rankings = []
    for i in range(n_genes):
        gene = f"GENE_{i}"
        rankings.append({"rank": i+1, "gene": gene, "score": float(1.0 - i*0.05), "rwr": float(0.5 - i*0.02), "is_seed": i < 2})
    with open(os.path.join(tmpdir, "rankings.json"), "w") as f:
        json.dump(rankings, f)
    with open(os.path.join(tmpdir, "features.json"), "w") as f:
        json.dump({"gene_list": [r["gene"] for r in rankings], "feature_names": []}, f)
    with open(os.path.join(tmpdir, "evaluation.json"), "w") as f:
        json.dump({"kfold": {"aggregate": {"auprc_mean": 0.9}}}, f)
    return rankings


def test_backend_invalid_gene_symbol_returns_400():
    with tempfile.TemporaryDirectory() as tmp:
        _make_artifacts(tmp)
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "rev-400"
        os.environ["ARTIFACT_DIR"] = tmp
        import backend.app as app_mod, backend.auth as auth_mod
        import importlib
        importlib.reload(auth_mod)
        importlib.reload(app_mod)
        auth_mod.set_verifier(None)
        app = app_mod.create_app()
        client = TestClient(app)
        # invalid symbol with special chars should be 400, not 500
        r = client.get("/genes/INVALID!SYMBOL")
        assert r.status_code == 400
        r2 = client.get("/explain/BAD*GENE")
        assert r2.status_code == 400
        # valid but not found should be 404
        r3 = client.get("/genes/GENE_NOTEXIST999")
        assert r3.status_code == 404
        # too long
        r4 = client.get("/genes/" + "A"*100)
        assert r4.status_code in (400, 422)
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
            os.environ.pop(k, None)
        importlib.reload(auth_mod)
        importlib.reload(app_mod)


def test_backend_rankings_invalid_query_len():
    with tempfile.TemporaryDirectory() as tmp:
        _make_artifacts(tmp)
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "rev-qlen"
        os.environ["ARTIFACT_DIR"] = tmp
        import backend.app as app_mod, backend.auth as auth_mod
        import importlib
        importlib.reload(auth_mod)
        importlib.reload(app_mod)
        auth_mod.set_verifier(None)
        app = app_mod.create_app()
        client = TestClient(app)
        long_q = "A"*200
        r = client.get(f"/rankings?q={long_q}")
        assert r.status_code in (400, 422)
        # offset beyond total should return 200 empty, not 500
        r2 = client.get("/rankings?offset=9999&limit=10")
        assert r2.status_code == 200
        assert r2.json()["results"] == []
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
            os.environ.pop(k, None)
        importlib.reload(auth_mod)
        importlib.reload(app_mod)


def test_backend_search_empty_query_400_or_422():
    with tempfile.TemporaryDirectory() as tmp:
        _make_artifacts(tmp)
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "rev-search"
        os.environ["ARTIFACT_DIR"] = tmp
        import backend.app as app_mod, backend.auth as auth_mod
        import importlib
        importlib.reload(auth_mod)
        importlib.reload(app_mod)
        auth_mod.set_verifier(None)
        app = app_mod.create_app()
        client = TestClient(app)
        # empty q param fails pydantic min_length
        r = client.get("/genes/search?q=")
        assert r.status_code in (400, 422)
        # limit out of range should be 422
        r2 = client.get("/genes/search?q=GENE&limit=999")
        assert r2.status_code == 422
        # rankings limit invalid
        r3 = client.get("/rankings?limit=9999")
        assert r3.status_code == 422
        # rankings offset negative
        r4 = client.get("/rankings?offset=-5")
        assert r4.status_code == 422
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
            os.environ.pop(k, None)
        importlib.reload(auth_mod)
        importlib.reload(app_mod)


def test_backend_evaluation_when_missing_still_200():
    with tempfile.TemporaryDirectory() as tmp:
        rankings = [{"rank":1,"gene":"GENE_0","score":0.9,"rwr":0.5,"is_seed":True}]
        with open(os.path.join(tmp, "rankings.json"),"w") as f:
            json.dump(rankings,f)
        # no evaluation.json
        os.environ["MODEL_RELEASE_APPROVED"]="true"
        os.environ["APPROVED_ARTIFACT_REVISION"]="rev-eval"
        os.environ["ARTIFACT_DIR"]=tmp
        import backend.app as app_mod, backend.auth as auth_mod
        import importlib
        importlib.reload(auth_mod)
        importlib.reload(app_mod)
        auth_mod.set_verifier(None)
        app = app_mod.create_app()
        client = TestClient(app)
        r = client.get("/evaluation")
        # should not 500; either 200 with empty note or 200
        assert r.status_code == 200
        for k in ["MODEL_RELEASE_APPROVED","APPROVED_ARTIFACT_REVISION","ARTIFACT_DIR"]:
            os.environ.pop(k,None)
        importlib.reload(auth_mod)
        importlib.reload(app_mod)
