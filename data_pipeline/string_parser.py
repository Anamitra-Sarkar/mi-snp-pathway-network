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
        return gzip.open(path, mode, encoding="utf-8" if "t" in mode else None)
    return open(path, mode, encoding="utf-8", errors="replace")


def load_aliases(aliases_path):
    """
    Load STRING protein alias file into dict: ENSP id (e.g. 9606.ENSP000...) -> gene symbol.
    Prefers Ensembl_HGNC source if present, else first alias.
    Handles real file quirks: comment lines (#), header row, tab/space mixed,
    UTF-8 BOM, extra trailing columns, missing source field, gzipped.
    """
    mapping = {}
    # track source priority: Ensembl_HGNC > Ensembl_gene > others
    priority = {"Ensembl_HGNC": 3, "Ensembl_gene_name": 2, "Ensembl_gene": 2}
    best_score = {}
    # Also handle BOM
    with _open_maybe_gz(aliases_path) as f:
        for raw in f:
            line = raw.lstrip("\ufeff").strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            # header detection: STRING aliases header is "#string_protein_id\talias\tsource"
            # but after lstrip it may be "string_protein_id alias source"
            lower = line.lower()
            if lower.startswith("string_protein_id") or (lower.startswith("string") and "alias" in lower and "source" in lower):
                continue
            parts = line.split("\t")
            # fallback to whitespace split if tabs not present but line has 3 fields
            if len(parts) < 3:
                parts = line.split()
            if len(parts) < 3:
                continue
            prot, alias, source = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not prot or not alias:
                continue
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

    Hardened for real file quirks:
      - gzipped or plain, UTF-8 BOM, comment lines (#), header variants
      - tab or space delimited, extra columns, missing optional cols, empty lines
      - float scores like "700.0", trailing whitespace, inline comments
    """
    if not 0 <= min_score <= 1000:
        raise ValueError(f"min_score must be 0-1000, got {min_score}")
    if aliases_path and gene_alias_map is None:
        gene_alias_map = load_aliases(aliases_path)

    edges = []
    genes = set()

    with _open_maybe_gz(string_path) as f:
        raw_lines = f.readlines()

    # Strip BOM from first line
    if raw_lines and raw_lines[0].startswith("\ufeff"):
        raw_lines[0] = raw_lines[0].lstrip("\ufeff")

    # Filter: skip comment lines and handle header detection
    data_lines = []
    header_skipped = False
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        lower = stripped.lower()
        # header variants: "protein1 protein2 combined_score", "protein1\tprotein2\tcombined_score", "string_protein_id ..."
        if not header_skipped and ("protein" in lower or "combined_score" in lower):
            # Heuristic: header line contains non-gene token 'protein' and 'score' but no numeric score
            # If first two fields look like headers and third is header, skip
            parts_h = stripped.split()
            if len(parts_h) >= 3:
                # header tokens contain letters without ENSP-like dots and are not numeric
                if any(t.lower() in ("protein1", "protein2", "combined_score", "score") for t in parts_h):
                    header_skipped = True
                    continue
                # also tab-split check
                parts_tab = stripped.split("\t")
                if any("protein" in t.lower() or "combined" in t.lower() for t in parts_tab):
                    header_skipped = True
                    continue
        data_lines.append(line)

    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Remove inline comments after '#' if present but keep ENSP ids (they don't contain #)
        if "#" in stripped:
            # only treat as comment if '#' is preceded by whitespace or is at start of extra column
            # STRING files don't have # inside ENSP ids, safe to split
            stripped = stripped.split("#", 1)[0].strip()
            if not stripped:
                continue
        # Try tab split first (real STRING uses space but some use tab)
        parts = stripped.split("\t")
        # If tab split yields 1 but space split yields 3, use space split
        if len(parts) < 3:
            parts = stripped.split()
        if len(parts) < 3:
            continue
        p1, p2, score_str = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not p1 or not p2:
            continue
        # score may have trailing non-numeric (e.g., "700;") — handle via float conversion
        score_str = score_str.rstrip(",;")
        try:
            score = int(score_str)
        except ValueError:
            try:
                score = int(float(score_str))
            except Exception:
                continue
        if not 0 <= score <= 1000:
            # clamped scores beyond 1000 are likely malformed; skip
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
        # sanitize gene symbols: strip whitespace, skip empty or overly long (likely parse error)
        g1 = g1.strip()
        g2 = g2.strip()
        if not g1 or not g2:
            continue
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
