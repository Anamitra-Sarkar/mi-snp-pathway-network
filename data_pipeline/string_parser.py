"""
Parser for STRING PPI data.

Real endpoint: https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz
Format (tab-separated, header):
  protein1 protein2 combined_score
  9606.ENSP00000000233 9606.ENSP00000003084 700

Aliases for ENSP->gene symbol mapping:
  https://stringdb-downloads.org/download/protein.aliases.v12.0/9606.protein.aliases.v12.0.txt.gz
  columns: #string_protein_id alias source
(filtered where source == "Ensembl_HGNC" etc, or we accept all and deduplicate).

Real-run CLI:
  python -m data_pipeline.string_parser --string-path 9606.protein.links.v12.0.txt.gz \
    --aliases-path 9606.protein.aliases.v12.0.txt.gz --min-score 700 --out edges.tsv

In tests, we use small synthetic gene-symbol edge lists (no ENSP mapping needed).
"""
import argparse
import gzip
import os
from collections import defaultdict


def _open_maybe_gz(path, mode="rt"):
    if path.endswith(".gz"):
        return gzip.open(path, mode)
    return open(path, mode)


def load_aliases(aliases_path):
    """
    Load STRING protein alias file into dict: ENSP id (e.g. 9606.ENSP000...) -> gene symbol.
    Prefers Ensembl_HGNC source if present, else first alias.
    """
    mapping = {}
    # track source priority: Ensembl_HGNC > Ensembl_gene > others
    priority = {"Ensembl_HGNC": 3, "Ensembl_gene_name": 2, "Ensembl_gene": 2}
    best_score = {}
    with _open_maybe_gz(aliases_path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            prot, alias, source = parts[0], parts[1], parts[2]
            # alias is gene symbol for HGNC sources
            score = priority.get(source, 1)
            if prot not in mapping or score > best_score.get(prot, 0):
                mapping[prot] = alias
                best_score[prot] = score
    return mapping


def parse_string_links(string_path, min_score=700, aliases_path=None, gene_alias_map=None):
    """
    Parse STRING links file. Returns list of (gene1, gene2, score) and set of genes.
    If aliases_path provided, maps ENSP ids to gene symbols via aliases file.
    If gene_alias_map already provided, use it.
    If neither, strips '9606.' prefix and uses ENSP id as node id (for synthetic gene-symbol files,
    this keeps symbols intact if they lack prefix).
    """
    if aliases_path and gene_alias_map is None:
        gene_alias_map = load_aliases(aliases_path)

    edges = []
    genes = set()

    with _open_maybe_gz(string_path) as f:
        header = f.readline()
        # detect header by checking if it contains 'protein1' or 'combined_score'
        is_header = "protein" in header.lower() or "combined" in header.lower()
        lines = [] if is_header else [header]
        # read rest
        lines.extend(f.readlines())

        for line in lines:
            if not line.strip():
                continue
            parts = line.strip().split()
            if len(parts) < 3:
                # try tab
                parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            p1, p2, score_str = parts[0], parts[1], parts[2]
            try:
                score = int(score_str)
            except ValueError:
                try:
                    score = int(float(score_str))
                except Exception:
                    continue
            if score < min_score:
                continue
            if gene_alias_map is not None:
                g1 = gene_alias_map.get(p1)
                g2 = gene_alias_map.get(p2)
                if g1 is None or g2 is None:
                    continue
            else:
                # strip 9606. prefix if present; synthetic gene symbols pass through
                g1 = p1.split(".", 1)[-1] if "." in p1 and p1.startswith("9606.") else p1
                g2 = p2.split(".", 1)[-1] if "." in p2 and p2.startswith("9606.") else p2
            if g1 == g2:
                continue
            edges.append((g1, g2, score))
            genes.add(g1)
            genes.add(g2)
    return edges, genes


def edges_to_adjacency_inputs(edges):
    """
    Deduplicate edges, keep max score if duplicate, return list.
    Undirected: each edge counts once but will be added symmetrically later.
    """
    best = {}
    for g1, g2, score in edges:
        key = tuple(sorted((g1, g2)))
        if key not in best or score > best[key]:
            best[key] = score
    return [(k[0], k[1], v) for k, v in best.items()]


def main():
    parser = argparse.ArgumentParser(description="Parse STRING PPI links")
    parser.add_argument("--string-path", required=True, help="Path to 9606.protein.links file (or .gz)")
    parser.add_argument("--aliases-path", default=None, help="Path to 9606.protein.aliases file (or .gz)")
    parser.add_argument("--min-score", type=int, default=700, help="Minimum combined_score (0-1000)")
    parser.add_argument("--out", required=True, help="Output edge TSV path")
    args = parser.parse_args()

    if not os.path.exists(args.string_path):
        raise SystemExit(f"STRING file not found: {args.string_path}. Download from https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz")
    if args.aliases_path and not os.path.exists(args.aliases_path):
        raise SystemExit(f"Aliases file not found: {args.aliases_path}")

    edges, genes = parse_string_links(args.string_path, min_score=args.min_score, aliases_path=args.aliases_path)
    dedup = edges_to_adjacency_inputs(edges)
    with open(args.out, "w") as out:
        out.write("gene1\tgene2\tcombined_score\n")
        for g1, g2, s in sorted(dedup):
            out.write(f"{g1}\t{g2}\t{s}\n")
    print(f"Wrote {len(dedup)} edges, {len(genes)} genes to {args.out}")


if __name__ == "__main__":
    main()
