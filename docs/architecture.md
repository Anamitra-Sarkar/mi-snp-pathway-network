# Architecture — SNP-gene-pathway network for MI/CAD risk prioritization

## Overview
This system prioritizes candidate genes/variants for myocardial infarction (MI) / coronary artery disease (CAD) by:
1. Anchoring on a curated set of well-replicated GWAS risk genes (seed set).
2. Building a gene-level PPI network from STRING (confidence ≥700) plus pathway membership from Reactome/KEGG.
3. Propagating relevance via Random Walk with Restart (RWR) from seeds.
4. Fusing RWR with topology (degree, PageRank) and pathway-overlap features in a supervised model.
5. Evaluating via leave-one-seed-out / k-fold cross-validation with recall@k and AUPRC vs. degree baseline.

## Components

### data_pipeline/
- `seed_genes.py` — hardcoded cited MI/CAD seed list (≈27 genes/loci). Production source of truth: GWAS Catalog REST API.
- `string_parser.py` — parses STRING `9606.protein.links.v12.0.txt.gz` (tab-separated: protein1, protein2, combined_score). Maps ENSP→gene symbol via STRING alias file `9606.protein.aliases.v12.0.txt.gz` or, for gene-level network, accepts pre-mapped gene-symbol edge list.
- `pathway_parser.py` — parses Reactome `ReactomePathways.gmt` (GMT format) or KEGG pathway REST responses (`https://rest.kegg.jp/link/genes/pathway` and `https://rest.kegg.jp/list/pathway/hsa`). Produces gene→pathway and pathway→genes mappings; supports GMT file or KEGG API.
- `network.py` — builds sparse adjacency matrix (scipy.sparse CSR/CSC), column-normalizes to stochastic matrix W, node indexing.
- `rwr.py` — iterative RWR: `p_{t+1} = (1-r)*W*p_t + r*p_0`, power iteration until L1 < tol or max_iter. Sparse implementation.
- `features.py` — degree, PageRank (power iteration), pathway-overlap (binary + count: shares ≥1 pathway with any seed; count of shared pathways).
- `fusion.py` — logistic regression (sklearn) and optional GBDT, training + CV evaluation, metrics: recall@k, AUPRC, AP.
- CLI entrypoints: `data_pipeline/__main__.py` and per-module `python -m data_pipeline.*` with `--string-path`, `--pathway-path`, `--seed-genes`, `--outdir` flags.

### backend/
- FastAPI app (`backend/app.py` + `backend/main.py`).
- **Release gate (fail-closed):** Model artifacts (ranked gene list, scores, explanations) are NOT loaded unless `MODEL_RELEASE_APPROVED=true` AND `APPROVED_ARTIFACT_REVISION` is set to a non-empty value. Health endpoints honestly reflect load state.
  - `GET /health` → `{status, model_loaded, revision}` — `model_loaded=false` when gate fails.
  - `GET /ready` → 200 only if model loaded, else 503.
  - `GET /rankings`, `GET /explain/{gene}` → 503 with `{"detail":"model not released"}` when not loaded.
- **Auth stub (Firebase-shaped):** `backend/auth.py` — reads `FIREBASE_SERVICE_ACCOUNT_JSON` env var path; if present, verifies Bearer JWT via `firebase_admin` (optional dep); if absent, stub logs warning and either allows unauthenticated in dev or rejects depending on `REQUIRE_AUTH`. Unit-tested with mocked verifier.
- Endpoints:
  - `GET /genes/search?q=` — prefix/substring search over gene symbols.
  - `GET /genes/{symbol}` — gene detail + scores.
  - `GET /rankings?limit=&offset=&q=` — paginated ranked list.
  - `GET /explain/{gene}` — which seed genes/pathways drove score (top contributing seeds by RWR proximity, shared pathways).
  - `GET /seeds` — seed gene list with citations.
  - `GET /health`, `GET /ready`.

### frontend/
- React 18 + Vite 5 + TypeScript.
- Pages: Search + ranked table + gene drawer/detail with explanation (seed neighbors, shared pathways).
- Honest abstention banner: polls `GET /health`; if `model_loaded===false`, shows "Model not yet released — rankings are placeholder/synthetic and not for clinical use" and disables ranking table (or shows empty state).
- Cardiovascular-appropriate design: deep navy/crimson palette, clean table, score bars.
- API client in `src/api.ts` handles 503 gracefully.

### tests/
- `tests/fixtures/` — synthetic graphs (10-50 nodes), synthetic pathway GMT.
- Tests cover RWR convergence, column-stochastic invariants, seed ranking, feature correctness, fusion training, backend release gate, auth stub.

## Data Flow
```
GWAS Catalog / curated seeds → seed_genes.py
STRING downloads ───────────→ string_parser.py ─┐
Reactome/KEGG ──────────────→ pathway_parser.py ─┤
                                              network.py → features.py → fusion.py → artifacts/*.json|pkl
                                                                                          ↕
                                                                      backend (release gate) ↔ frontend
```

## Real-run procedure
1. Download STRING: `wget https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz`
2. Download Reactome GMT: `wget https://reactome.org/download/current/ReactomePathways.gmt` or KEGG: `curl https://rest.kegg.jp/link/genes/pathway`
3. `python -m data_pipeline --string-path <local> --pathway-path <local> --outdir artifacts/`
4. Set env: `MODEL_RELEASE_APPROVED=true APPROVED_ARTIFACT_REVISION=v1 uvicorn backend.main:app`
5. Frontend: `npm run dev` / `npm run build`

## Evaluation
- Leave-one-seed-out: for each seed gene s, hold it out, run RWR from remaining seeds, rank all non-seed + held-out gene, compute recall@k (k=10,25,50,100), AUPRC.
- Baseline: degree-only ranking (higher degree = higher rank).
- Reported in `fusion.py: evaluate_loso` and `evaluate_kfold`.

## Security / Honesty
- No fabricated data sources; all endpoints cited and documented in `docs/data_sources.md`.
- Backend never claims model is loaded when gate not satisfied.
- Frontend mirrors honest state; no mock scores shown as real.
