# MI SNP-Gene-Pathway Network — MI/CAD Risk Gene Prioritization

Prioritizes candidate genes/variants for myocardial infarction (MI) / coronary artery disease (CAD) by mapping GWAS loci onto genes and propagating relevance over a gene–pathway/PPI network (RWR + fusion model).

## Quick start (synthetic test run)
```bash
pip install -r requirements.txt
pytest -q
# Frontend
npm install --prefix frontend
npm run build --prefix frontend
# Backend (release gate closed by default — honest 503)
uvicorn backend.main:app --reload
```

## Real run (STRING + Reactome/KEGG)
```bash
# 1. Download STRING PPI (high-confidence ≥700)
wget https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz
wget https://stringdb-downloads.org/download/protein.aliases.v12.0/9606.protein.aliases.v12.0.txt.gz  # for ENSP→symbol

# 2. Download Reactome GMT or KEGG
wget https://reactome.org/download/current/ReactomePathways.gmt
# or: curl https://rest.kegg.jp/link/genes/pathway -o kegg_link.txt

# 3. Run pipeline
python -m data_pipeline --string-path 9606.protein.links.v12.0.txt.gz \
  --aliases-path 9606.protein.aliases.v12.0.txt.gz \
  --pathway-path ReactomePathways.gmt --outdir artifacts/

# 4. Release gate (fail-closed)
MODEL_RELEASE_APPROVED=true APPROVED_ARTIFACT_REVISION=v1 ARTIFACT_DIR=artifacts uvicorn backend.main:app
# Frontend
VITE_API_URL=http://localhost:8000 npm run dev --prefix frontend
```

## Architecture
See `docs/architecture.md` and `docs/data_sources.md`.

## Data sources (real endpoints, no fabrications)
- GWAS Catalog REST: https://www.ebi.ac.uk/gwas/rest/api/ (EFO_0000612 myocardial infarction, EFO_0000378 coronary artery disease)
- STRING v12: https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz
- Reactome GMT: https://reactome.org/download/current/ReactomePathways.gmt
- KEGG REST: https://rest.kegg.jp/ (e.g. /link/genes/pathway)

## Evaluation
Leave-one-seed-out and k-fold over seed genes — `recall@10,25,50,100` and AUPRC vs degree-only baseline (`data_pipeline/fusion.py`).

## Security
- Backend release gate: `MODEL_RELEASE_APPROVED=true` + `APPROVED_ARTIFACT_REVISION` required, else 503 — never fabricates.
- Firebase auth stub: reads `FIREBASE_SERVICE_ACCOUNT_JSON` path; mocked in tests.
