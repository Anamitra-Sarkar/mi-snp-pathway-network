"""
CLI entrypoint for data_pipeline.
Usage:
  python -m data_pipeline --string-path <file> --pathway-path <file> --outdir artifacts/
"""
import argparse
import os
import json

from .string_parser import parse_string_links
from .pathway_parser import parse_pathways
from .fusion import run_full_pipeline
from .seed_genes import SEED_SYMBOLS


def main():
    parser = argparse.ArgumentParser(description="MI/CAD SNP-gene-pathway pipeline")
    parser.add_argument("--string-path", required=True, help="STRING links file (local path, .gz ok)")
    parser.add_argument("--aliases-path", default=None, help="STRING aliases file (optional)")
    parser.add_argument("--pathway-path", required=False, default=None, help="Pathway GMT or KEGG link file")
    parser.add_argument("--pathway-format", choices=["auto","gmt","kegg"], default="auto")
    parser.add_argument("--min-score", type=int, default=700)
    parser.add_argument("--restart-prob", type=float, default=0.3)
    parser.add_argument("--outdir", default="artifacts")
    parser.add_argument("--seed-genes", nargs="*", default=None, help="Override seed gene list")
    args = parser.parse_args()

    if not os.path.exists(args.string_path):
        raise SystemExit(f"STRING file not found: {args.string_path}\nDownload from https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz")

    seeds = args.seed_genes if args.seed_genes else SEED_SYMBOLS
    print(f"Using {len(seeds)} seed genes")

    edges, genes = parse_string_links(args.string_path, min_score=args.min_score, aliases_path=args.aliases_path)
    print(f"Parsed {len(edges)} edges, {len(genes)} genes from STRING")

    if args.pathway_path:
        if not os.path.exists(args.pathway_path):
            raise SystemExit(f"Pathway file not found: {args.pathway_path}\nDownload Reactome GMT from https://reactome.org/download/current/ReactomePathways.gmt")
        g2p, p2g, _ = parse_pathways(args.pathway_path, fmt=args.pathway_format)
        print(f"Parsed {len(p2g)} pathways, {len(g2p)} genes with pathway membership")
    else:
        print("WARNING: No pathway file provided — using synthetic/minimal pathway membership (pathway overlap features will be zero). "
              "Provide --pathway-path with Reactome GMT (https://reactome.org/download/current/ReactomePathways.gmt) for real pathway context.")
        g2p = {}

    run_full_pipeline(edges, g2p, seed_symbols=seeds, outdir=args.outdir, restart_prob=args.restart_prob)


if __name__ == "__main__":
    main()
