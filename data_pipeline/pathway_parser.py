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
        return gzip.open(path, mode, encoding="utf-8" if "t" in mode else None)
    # Handle .zip if ever passed (Reactome provides .gmt.zip): try unzip first entry
    if path.endswith(".zip"):
        import zipfile
        # return a generator-like wrapper; caller should handle zip separately
        # fallback: open as zip and read first file
        z = zipfile.ZipFile(path)
        first = z.namelist()[0]
        import io
        return io.TextIOWrapper(z.open(first), encoding="utf-8", errors="replace")
    return open(path, mode, encoding="utf-8", errors="replace")


def parse_gmt(pathway_path):
    """
    Parse Reactome GMT file.
    Returns:
      gene_to_pathways: dict gene -> set(pathway_id)
      pathway_to_genes: dict pathway_id -> set(genes)
      pathway_names: dict pathway_id -> description
    Hardened:
      - comment lines (#), blank lines, UTF-8 BOM
      - missing optional columns (description may be empty),
        extra whitespace, duplicate genes, tab/extra spaces
      - gzipped or .zip input, header variants
    """
    gene_to_pathways = defaultdict(set)
    pathway_to_genes = {}
    pathway_names = {}
    with _open_maybe_gz(pathway_path) as f:
        for raw in f:
            line = raw.lstrip("\ufeff").strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            # GMT must be tab-separated; if tab absent but line has 3+ whitespace tokens,
            # still try to parse but warn-like we split on tab strictly then fallback.
            # Keep tab split primary to avoid breaking descriptions containing spaces.
            parts = line.split("\t")
            # If only one tab-split part but many whitespace parts, file may use spaces; handle fallback
            if len(parts) < 3 and "\t" not in line:
                # Heuristic: assume format is pathway_id<space>description<space>genes...
                # But description may contain spaces, so we cannot reliably fallback.
                # Better to skip lines with no tabs that look like header/comment.
                # We'll attempt whitespace split as fallback for synthetic files.
                ws_parts = line.split()
                if len(ws_parts) >= 3:
                    # treat first as pathway_id, second as description (single token), rest as genes
                    parts = [ws_parts[0], ws_parts[1]] + ws_parts[2:]
                else:
                    continue
            if len(parts) < 3:
                # Allow missing description: pathway_id<TAB><TAB>gene1...  -> description empty
                if len(parts) == 2:
                    # pathway_id + gene list without description? Treat parts[1] onward as genes if looks like gene symbols
                    # Check if parts[1] contains comma or space separated genes
                    pathway_id = parts[0].strip()
                    description = ""
                    genes_raw = parts[1].strip().split() if parts[1].strip() else []
                    # also handle genes tab-missing but space separated
                    if not pathway_id:
                        continue
                    genes = [g.strip() for g in genes_raw if g.strip()]
                    if not genes:
                        continue
                    pathway_to_genes[pathway_id] = set(genes)
                    pathway_names[pathway_id] = description
                    for g in genes:
                        gene_to_pathways[g].add(pathway_id)
                    continue
                continue
            pathway_id = parts[0].strip()
            if not pathway_id:
                continue
            description = parts[1].strip() if len(parts) > 1 else ""
            genes_raw = parts[2:]
            # genes may be space-separated within a single tab field if file is malformed; split those
            genes = []
            for g_field in genes_raw:
                # handle cases where a single field contains space-separated genes (malformed)
                # but only split if no tab was used internally — already split by tab
                # If field contains spaces and no tab, it may be multiple genes in one field
                if " " in g_field and "\t" not in line:
                    genes.extend([x.strip() for x in g_field.split() if x.strip()])
                else:
                    # also handle comma-separated
                    if "," in g_field:
                        genes.extend([x.strip() for x in g_field.split(",") if x.strip()])
                    else:
                        if g_field.strip():
                            genes.append(g_field.strip())
            # Deduplicate while preserving
            genes = [g for g in genes if g]
            if not genes:
                continue
            # Merge duplicate pathway ids (some GMTs have duplicate pathway entries)
            if pathway_id in pathway_to_genes:
                pathway_to_genes[pathway_id].update(genes)
            else:
                pathway_to_genes[pathway_id] = set(genes)
            # Keep first description if duplicate
            if pathway_id not in pathway_names:
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
    Hardened for: comment lines, extra whitespace, tab/space mixed, reversed columns, BOM, extra trailing cols.
    """
    gene_to_pathways = defaultdict(set)
    pathway_to_genes = defaultdict(set)
    with _open_maybe_gz(link_path) as f:
        for raw in f:
            line = raw.lstrip("\ufeff").strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            # Remove inline comments
            if "#" in line:
                # KEGG files don't contain # in ids, safe to strip
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
            parts = line.split("\t")
            if len(parts) < 2:
                parts = line.split()
            if len(parts) < 2:
                continue
            # Only take first two non-empty tokens, ignore extra trailing columns
            # Find first two tokens that are non-empty
            tokens = [p.strip() for p in parts if p.strip()]
            if len(tokens) < 2:
                continue
            a, b = tokens[0], tokens[1]
            if not a or not b:
                continue
            # detect which is pathway vs gene: pathway contains "path:"
            if a.startswith("path:"):
                pathway_id, gene_id = a, b
            elif b.startswith("path:"):
                pathway_id, gene_id = b, a
            else:
                # Heuristic: pathway ids contain letters like "hsa" or "map" or "path", or are longer
                # If one token contains "hsa" or "map" and the other is numeric, pathway is the one with letters
                def looks_pathway(t):
                    return any(x in t for x in ("hsa", "map", "path")) or t.startswith("hsa") or t.startswith("map")
                if looks_pathway(a) and not looks_pathway(b):
                    pathway_id, gene_id = a, b
                elif looks_pathway(b) and not looks_pathway(a):
                    pathway_id, gene_id = b, a
                else:
                    # assume first is pathway (KEGG link docs: pathway<tab>gene)
                    pathway_id, gene_id = a, b
            # normalize: strip "path:" and "hsa:" prefixes
            if ":" in pathway_id:
                pathway_id = pathway_id.split(":", 1)[-1]
            if ":" in gene_id:
                gene_id = gene_id.split(":", 1)[-1]
            pathway_id = pathway_id.strip()
            gene_id = gene_id.strip()
            if not pathway_id or not gene_id:
                continue
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
        try:
            with _open_maybe_gz(pathway_path) as f:
                sample = f.read(5000)
                if "path:" in sample or "\thsa:" in sample:
                    fmt = "kegg"
                else:
                    fmt = "gmt"
        except Exception:
            # If detection fails (e.g., zip), default to GMT
            fmt = "gmt"
    if fmt == "gmt":
        return parse_gmt(pathway_path)
    elif fmt == "kegg":
        return parse_kegg_link(pathway_path)
    else:
        raise ValueError(f"Unknown format {fmt} — expected one of auto,gmt,kegg")


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
