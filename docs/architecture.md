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
- `string_parser.py` — parses STRING `9606.protein.links.v12.0.txt.gz` (tab- or space-separated: protein1, protein2, combined_score, with possible extra columns). Maps ENSP→gene symbol via STRING alias file `9606.protein.aliases.v12.0.txt.gz` or, for gene-level network, accepts pre-mapped gene-symbol edge list. Hardened for real-file quirks: comment lines (`#`), blank lines, UTF-8 BOM, header variants (`protein1/protein2/combined_score`), tab/space mixed delimiters, inline comments, gzipped input, float scores (`700.0`), missing optional columns, deduplication (keeps max score), and strict `min_score` validation (0–1000).
- `pathway_parser.py` — parses Reactome `ReactomePathways.gmt` (GMT format) or KEGG pathway REST responses (`https://rest.kegg.jp/link/genes/pathway` and `https://rest.kegg.jp/list/pathway/hsa`). Produces gene→pathway and pathway→genes mappings; supports GMT file or KEGG API. Hardened for: comment/blank lines, UTF-8 BOM, gzipped or `.zip`, missing/empty description, duplicate pathway IDs (merged), tab/space/comma mixed delimiters, KEGG reversed columns (`hsa:xxx` vs `path:xxx`), extra trailing columns, and auto-format detection tolerant of gzipped reads.
- `network.py` — builds sparse adjacency matrix (scipy.sparse CSR/CSC), column-normalizes to stochastic matrix W (dangling columns filled uniform `1/n`), node indexing.
- `rwr.py` — iterative RWR: `p_{t+1} = (1-r)*W*p_t + r*p_0`, power iteration until L1 < tol or max_iter. Sparse implementation. Validates `restart_prob ∈ [0,1]`, `tol>0`, `max_iter>0`, `W` square, `p0` length matches `W`.
- `features.py` — degree, PageRank (power iteration), pathway-overlap (binary + count: shares ≥1 pathway with any seed; count of shared pathways; max Jaccard).
- `fusion.py` — logistic regression (sklearn) and optional GBDT, training + CV evaluation, metrics: recall@k, AUPRC, AP.
- CLI entrypoints: `data_pipeline/__main__.py` and per-module `python -m data_pipeline.*` with `--string-path`, `--pathway-path`, `--seed-genes`, `--outdir` flags.

### backend/
- FastAPI app (`backend/app.py` + `backend/main.py`).
- **Release gate (fail-closed):** Model artifacts (ranked gene list, scores, explanations) are NOT loaded unless `MODEL_RELEASE_APPROVED=true` AND `APPROVED_ARTIFACT_REVISION` is set to a non-empty value. Health endpoints honestly reflect load state.
  - `GET /health` → `{status, model_loaded, revision}` — `model_loaded=false` when gate fails.
  - `GET /ready` → 200 only if model loaded, else 503.
  - `GET /rankings`, `GET /explain/{gene}` → 503 with `{"detail":"model not released"}` when not loaded.
- **Auth stub (Firebase-shaped):** `backend/auth.py` — reads `FIREBASE_SERVICE_ACCOUNT_JSON` env var path; if present, verifies Bearer JWT via `firebase_admin` (optional dep); if absent, stub logs warning and either allows unauthenticated in dev or rejects depending on `REQUIRE_AUTH`. Unit-tested with mocked verifier.
 - Endpoints (with strict validation — malformed inputs return `400`/`422`, never raw `500`):
  - `GET /genes/search?q=&limit=` — prefix/substring search over gene symbols (`q` 1–100 chars, `limit` 1–50; 422 on overflow, 400 on empty after trim).
  - `GET /genes/{symbol}` — gene detail + scores (`symbol` regex `^[A-Za-z0-9._\-]+$`, max 50 chars; 400 on invalid, 404 on not found).
  - `GET /rankings?limit=&offset=&q=` — paginated ranked list (`limit` 1–500 default 25, `offset` ≥0, `q` ≤100; offset beyond total returns empty page 200, not 500).
  - `GET /explain/{gene}?top_n=` — which seed genes/pathways drove score (top contributing seeds by RWR proximity, shared pathways; `top_n` 1–20).
  - `GET /evaluation` — k-fold + LOSO metrics (returns honest empty note when artifacts lack evaluation, not 500).
  - `GET /seeds` — seed gene list with citations (public, always 200).
  - `GET /health`, `GET /ready`.

### frontend/
- React 18 + Vite 5 + TypeScript.
- Pages: Search + ranked table (paginated, 25/page, Prev/Next) + gene drawer/detail with explanation (seed neighbors, shared pathways).
- Honest abstention banner: polls `GET /health`; if `model_loaded===false`, shows "Model not yet released — rankings are placeholder/synthetic and not for clinical use" and disables ranking table (or shows empty state) with retry button.
- Accessibility: labeled search input (`label` + `aria-label`), `aria-live` for results, `table caption` sr-only, `scope="col"` headers, focus-visible outlines, `role="alert"` for errors, disabled state handling, explain loading state, keyboard-friendly pagination (`role="navigation"`).
- Responsive: stacked search row, header wrapping, table font scaling at ≤640px, pagination wraps.
- Cardiovascular-appropriate design: deep navy/crimson palette, clean table, score bars.
- API client in `src/api.ts` handles 503/400/422 gracefully (user-friendly messages).

### tests/
- `tests/fixtures/` — synthetic graphs (10-50 nodes), synthetic pathway GMT.
- Tests cover RWR convergence, column-stochastic invariants, seed ranking, feature correctness, fusion training, backend release gate, auth stub, plus hardening suite (`tests/test_hardening.py`): parser edge cases (comment/header/BOM variants, mixed delimiters, float scores, extra columns, alias priority, gzipped inputs), pathway edge cases (missing desc, duplicate pathways, comma/whitespace genes, KEGG reversed columns, auto-detect, gzipped GMT), RWR validation (invalid restart_prob/p0), backend error paths (400 on bad symbol, 422 on limit/offset overflow, empty query, offset clamping, evaluation missing → 200 not 500).

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
