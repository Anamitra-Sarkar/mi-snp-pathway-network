import pathlib
import tempfile
import os
from data_pipeline.pathway_parser import parse_gmt, parse_kegg_link, parse_pathways
from data_pipeline.features import compute_pathway_overlap_features


def test_parse_gmt_fixture():
    path = pathlib.Path(__file__).parent / "fixtures" / "synthetic_pathways.gmt"
    g2p, p2g, names = parse_gmt(str(path))
    assert len(p2g) == 5
    assert "R-HSA-1001" in p2g
    assert "GENE_A" in g2p
    assert "GENE_A" in p2g["R-HSA-1001"]
    assert names["R-HSA-1001"] == "Lipid metabolism"
    # gene to pathways correct
    assert "R-HSA-1001" in g2p["GENE_A"]
    assert "R-HSA-1002" in g2p["GENE_A"]


def test_parse_kegg_link():
    # Create synthetic KEGG link file
    content = "path:hsa04110\thsa:10458\npath:hsa04110\thsa:2318\npath:hsa00010\thsa:10458\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        g2p, p2g, _ = parse_kegg_link(tmp_path)
        assert "10458" in g2p
        assert "hsa04110" in g2p["10458"]  # stripped "path:" but keeps hsa04110? In code: path:hsa04110 -> hsa04110
        assert "hsa04110" in p2g
        assert "10458" in p2g["hsa04110"]
    finally:
        os.unlink(tmp_path)


def test_pathway_overlap_binary_and_count():
    # Build synthetic g2p
    g2p = {
        "GENE_A": {"R-HSA-1001", "R-HSA-1002"},
        "GENE_B": {"R-HSA-1001", "R-HSA-1005"},
        "GENE_C": {"R-HSA-1005"},
        "GENE_X": {"R-HSA-1003"},  # no overlap with seeds A,B
        "GENE_Y": {"R-HSA-1001"},  # shares with seed
    }
    seeds = ["GENE_A", "GENE_B"]
    genes = ["GENE_A", "GENE_B", "GENE_C", "GENE_X", "GENE_Y"]
    feats = compute_pathway_overlap_features(genes, g2p, seeds)
    # binary: A,B,C,Y should be 1 (A/B are seeds themselves share), X should be 0
    # Note: function marks seed genes as 1 because they share with union (includes themselves). That's intended.
    assert feats["pathway_overlap_binary"][0] == 1  # GENE_A
    assert feats["pathway_overlap_binary"][3] == 0  # GENE_X
    assert feats["pathway_overlap_binary"][4] == 1  # GENE_Y
    # count: GENE_C has 1 shared pathway (R-HSA-1005 with GENE_B)
    idx_c = genes.index("GENE_C")
    assert feats["pathway_overlap_count"][idx_c] == 1
    # GENE_Y shares R-HSA-1001 with seed union -> count 1
    assert feats["pathway_overlap_count"][4] == 1
    # jaccard: GENE_Y vs GENE_A: 1/2 =0.5, vs GENE_B: 1/2=0.5 -> max 0.5
    assert abs(feats["pathway_jaccard_max"][4] - 0.5) < 1e-9
    # GENE_X jaccard 0
    assert feats["pathway_jaccard_max"][3] == 0.0


def test_pathway_overlap_no_membership():
    g2p = {"GENE_A": {"PW1"}}
    feats = compute_pathway_overlap_features(["GENE_A", "GENE_Z"], g2p, ["GENE_A"])
    # GENE_Z has no pathways -> binary 0
    assert feats["pathway_overlap_binary"][1] == 0
    assert feats["pathway_overlap_count"][1] == 0
