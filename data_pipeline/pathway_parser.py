"""
Parser for pathway membership data.

Real endpoints:
 - Reactome GMT: https://reactome.org/download/current/ReactomePathways.gmt (or .gmt.zip)
   Format: TSV lines: pathway_id<TAB>description<TAB>gene1<TAB>gene2...
 - KEGG API: https://rest.kegg.jp/link/genes/pathway and https://rest.kegg.jp/list/pathway/hsa
   KEGG link file format: tab-separated "path:map04110\thsa:10458" (pathway<->gene)
   Genes are like "hsa:10458" (Entrez prefixed), pathways like "path:hsa04110"

Real-run:
  python -m data_pipeline.pathway_parser --pathway-path ReactomePathways.gmt --format gmt --out pathways.json
  python -m data_pipeline.pathway_parser --pathway-path kegg_link.txt --format kegg --out pathways.json

Fallback: if --pathway-path not provided, raises informative error.
Tests use synthetic small GMT fixture.
"""
import argparse
import json
import os
import gzip
from collections import defaultdict


def _open_maybe_gz(path, mode="rt"):
    if path.endswith(".gz"):
        return gzip.open(path, mode)
    return open(path, mode)


def parse_gmt(pathway_path):
    """
    Parse Reactome GMT file.
    Returns:
      gene_to_pathways: dict gene -> set(pathway_id)
      pathway_to_genes: dict pathway_id -> set(genes)
      pathway_names: dict pathway_id -> description
    """
    gene_to_pathways = defaultdict(set)
    pathway_to_genes = {}
    pathway_names = {}
    with _open_maybe_gz(pathway_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            pathway_id = parts[0].strip()
            description = parts[1].strip()
            genes = [g.strip() for g in parts[2:] if g.strip()]
            # Reactome GMT sometimes has gene symbols; normalize uppercase
            pathway_to_genes[pathway_id] = set(genes)
            pathway_names[pathway_id] = description
            for g in genes:
                gene_to_pathways[g].add(pathway_id)
    return dict(gene_to_pathways), pathway_to_genes, pathway_names


def parse_kegg_link(link_path):
    """
    Parse KEGG link file (from https://rest.kegg.jp/link/genes/pathway or similar).
    Each line: pathway_id<tab>gene_id  where gene_id may be "hsa:10458" and pathway "path:hsa04110".
    Map gene Entrez to symbol if possible? Here we keep raw ids, but strip prefixes for simplicity.
    For hsa genes, strip "hsa:" prefix.
    """
    gene_to_pathways = defaultdict(set)
    pathway_to_genes = defaultdict(set)
    with _open_maybe_gz(link_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                parts = line.split()
            if len(parts) < 2:
                continue
            a, b = parts[0].strip(), parts[1].strip()
            # detect which is pathway vs gene: pathway contains "path:"
            if a.startswith("path:"):
                pathway_id, gene_id = a, b
            elif b.startswith("path:"):
                pathway_id, gene_id = b, a
            else:
                # assume first is pathway
                pathway_id, gene_id = a, b
            # normalize: strip "path:" and "hsa:" prefixes
            if ":" in pathway_id:
                pathway_id = pathway_id.split(":", 1)[-1]
            if ":" in gene_id:
                gene_id = gene_id.split(":", 1)[-1]
            gene_to_pathways[gene_id].add(pathway_id)
            pathway_to_genes[pathway_id].add(gene_id)
    return dict(gene_to_pathways), dict(pathway_to_genes), {}


def parse_pathways(pathway_path, fmt="auto"):
    """
    Auto-detect or use explicit format.
    fmt in {"auto","gmt","kegg"}
    """
    if fmt == "auto":
        # heuristic: if file contains "path:" it's KEGG link, else GMT
        with _open_maybe_gz(pathway_path) as f:
            sample = f.read(5000)
            if "path:" in sample or "\thsa:" in sample:
                fmt = "kegg"
            else:
                fmt = "gmt"
    if fmt == "gmt":
        return parse_gmt(pathway_path)
    elif fmt == "kegg":
        return parse_kegg_link(pathway_path)
    else:
        raise ValueError(f"Unknown format {fmt}")


def save_pathway_artifacts(gene_to_pathways, pathway_to_genes, pathway_names, out_path):
    data = {
        "gene_to_pathways": {k: sorted(list(v)) for k, v in gene_to_pathways.items()},
        "pathway_to_genes": {k: sorted(list(v)) for k, v in pathway_to_genes.items()},
        "pathway_names": pathway_names,
    }
    with open(out_path, "w") as out:
        json.dump(data, out, indent=2)
    print(f"Saved {len(pathway_to_genes)} pathways, {len(gene_to_pathways)} genes to {out_path}")


def load_pathway_artifacts(path):
    with open(path) as f:
        data = json.load(f)
    gene_to_pathways = {k: set(v) for k, v in data["gene_to_pathways"].items()}
    pathway_to_genes = {k: set(v) for k, v in data["pathway_to_genes"].items()}
    return gene_to_pathways, pathway_to_genes, data.get("pathway_names", {})


def main():
    parser = argparse.ArgumentParser(description="Parse pathway membership (Reactome GMT or KEGG link)")
    parser.add_argument("--pathway-path", required=True, help="Local pathway file (GMT or KEGG link)")
    parser.add_argument("--format", choices=["auto", "gmt", "kegg"], default="auto")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    if not os.path.exists(args.pathway_path):
        raise SystemExit(f"Pathway file not found: {args.pathway_path}. "
                         f"Download Reactome GMT from https://reactome.org/download/current/ReactomePathways.gmt "
                         f"or KEGG via https://rest.kegg.jp/link/genes/pathway")

    g2p, p2g, names = parse_pathways(args.pathway_path, fmt=args.format)
    save_pathway_artifacts(g2p, p2g, names, args.out)


if __name__ == "__main__":
    main()
