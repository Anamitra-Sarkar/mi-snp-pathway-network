"""Run mi-snp-pathway-network's own data_pipeline on real STRING + Reactome data.

Real, public, no-auth endpoints exactly as docs/data_sources.md and the README specify:
  - STRING v12 protein links + aliases (9606, confidence 700 default)
  - Reactome pathway GMT

GWAS Catalog is documented as the SNP source but the repo's CLI takes STRING +
pathway files and its own MI/CAD seed gene list (data_pipeline/seed_genes.py) --
GWAS lookups are informational/for extending seeds, not a required CLI input.

Run: modal run train_mspn.py
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "numpy==1.26.4", "scipy==1.14.1", "scikit-learn==1.5.2",
        "networkx==3.3", "pandas==2.2.3", "requests==2.32.3",
    )
)

app = modal.App("mspn-real-run", image=image)
vol = modal.Volume.from_name("mspn-artifacts", create_if_missing=True)

REPO = "https://github.com/Anamitra-Sarkar/mi-snp-pathway-network.git"
STRING_LINKS = "https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz"
STRING_ALIASES = "https://stringdb-downloads.org/download/protein.aliases.v12.0/9606.protein.aliases.v12.0.txt.gz"
REACTOME_GMT = "https://reactome.org/download/current/ReactomePathways.gmt"


@app.function(timeout=7200, cpu=8.0, memory=32768, volumes={"/art": vol})
def train() -> dict:
    import json
    import subprocess
    import sys
    from pathlib import Path
    import requests

    subprocess.run(["git", "clone", "--depth", "1", REPO, "/repo"], check=True)
    sys.path.insert(0, "/repo")

    data = Path("/data"); data.mkdir(exist_ok=True)
    files = {}
    for url, name in ((STRING_LINKS, "links.txt.gz"), (STRING_ALIASES, "aliases.txt.gz"), (REACTOME_GMT, "reactome.gmt")):
        dest = data / name
        print(f"downloading {url}", flush=True)
        with requests.get(url, stream=True, timeout=1800) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        print(f"  {dest} {dest.stat().st_size} bytes", flush=True)
        files[name] = dest

    from data_pipeline.__main__ import main as pipeline_main

    outdir = "/art/run1"
    Path(outdir).mkdir(parents=True, exist_ok=True)
    argv = [
        "data_pipeline",
        "--string-path", str(files["links.txt.gz"]),
        "--aliases-path", str(files["aliases.txt.gz"]),
        "--pathway-path", str(files["reactome.gmt"]),
        "--pathway-format", "gmt",
        "--outdir", outdir,
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        pipeline_main()
    finally:
        sys.argv = old_argv

    vol.commit()
    produced = sorted(str(p.relative_to("/art")) for p in Path("/art").rglob("*") if p.is_file())
    print("ARTIFACTS:", produced, flush=True)

    result = {}
    for p in Path(outdir).rglob("*.json"):
        try:
            result[p.name] = json.loads(p.read_text())
        except Exception:
            pass
    print("RESULT:", json.dumps(result, indent=2, default=str)[:3500], flush=True)
    return {"artifacts": produced, "metrics": result}


@app.local_entrypoint()
def main():
    import json
    print(json.dumps(train.remote(), indent=2, default=str))
