"""
FastAPI app with fail-closed release gate.

Model artifacts are NOT loaded unless:
  MODEL_RELEASE_APPROVED == "true" (case-insensitive) AND APPROVED_ARTIFACT_REVISION is non-empty.

Health/readiness honestly reflect load state. Rankings endpoints return 503 when not loaded.
"""
import os
import json
import glob
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import get_current_user

APP_DIR = Path(__file__).parent
DEFAULT_ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", str(APP_DIR.parent / "artifacts")))

# Global state for release gate
_model_loaded = False
_model_revision: Optional[str] = None
_rankings: List[dict] = []
_gene_index: dict = {}
_seed_records: List[dict] = []
_feature_meta: dict = {}
_evaluation: dict = {}


def is_release_approved():
    approved = os.environ.get("MODEL_RELEASE_APPROVED", "false").lower() in ("true", "1", "yes")
    revision = os.environ.get("APPROVED_ARTIFACT_REVISION", "").strip()
    return approved and len(revision) > 0, revision


def load_artifacts():
    global _model_loaded, _model_revision, _rankings, _gene_index, _seed_records, _feature_meta, _evaluation
    approved, revision = is_release_approved()
    if not approved:
        _model_loaded = False
        _model_revision = None
        _rankings = []
        _gene_index = {}
        return False

    # Look for artifacts
    artifact_dir = Path(os.environ.get("ARTIFACT_DIR", str(DEFAULT_ARTIFACT_DIR)))
    rankings_path = artifact_dir / "rankings.json"
    # Also allow revisioned path: artifacts/<revision>/rankings.json
    if not rankings_path.exists() and revision:
        alt = artifact_dir / revision / "rankings.json"
        if alt.exists():
            rankings_path = alt

    if not rankings_path.exists():
        # Fail-closed: approved but artifacts missing -> still not loaded, honest state
        _model_loaded = False
        _model_revision = revision
        return False

    try:
        with open(rankings_path) as f:
            _rankings = json.load(f)
        _gene_index = {r["gene"]: r for r in _rankings}
        _model_revision = revision
        # Load optional files
        feats = artifact_dir / "features.json"
        if feats.exists():
            with open(feats) as f:
                _feature_meta = json.load(f)
        eval_path = artifact_dir / "evaluation.json"
        if eval_path.exists():
            with open(eval_path) as f:
                _evaluation = json.load(f)
        # Seed records from data_pipeline
        try:
            from data_pipeline.seed_genes import get_seed_records
            _seed_records = get_seed_records()
        except Exception:
            _seed_records = []
        _model_loaded = True
        return True
    except Exception as e:
        print(f"Failed to load artifacts: {e}")
        _model_loaded = False
        return False


def create_app():
    app = FastAPI(
        title="MI/CAD SNP-gene-pathway Risk Prioritization API",
        description="Prioritizes candidate genes for myocardial infarction / coronary artery disease via PPI RWR + pathway fusion.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Attempt load on startup
    load_artifacts()

    class HealthResponse(BaseModel):
        model_config = {"protected_namespaces": ()}
        status: str
        model_loaded: bool
        revision: Optional[str]
        detail: Optional[str] = None

    @app.get("/health", response_model=HealthResponse)
    def health():
        approved, rev = is_release_approved()
        if _model_loaded:
            return HealthResponse(status="ok", model_loaded=True, revision=_model_revision)
        else:
            if not approved:
                return HealthResponse(status="ok", model_loaded=False, revision=None, detail="model not released — MODEL_RELEASE_APPROVED != true or APPROVED_ARTIFACT_REVISION not set")
            else:
                return HealthResponse(status="ok", model_loaded=False, revision=rev, detail="release approved but artifacts not found or failed to load")

    @app.get("/ready")
    def ready():
        if not _model_loaded:
            raise HTTPException(status_code=503, detail="model not loaded — release gate not satisfied or artifacts missing")
        return {"ready": True, "revision": _model_revision}

    @app.get("/seeds")
    def seeds():
        # Always available (seed list is public knowledge), even when model not loaded
        try:
            from data_pipeline.seed_genes import get_seed_records
            return {"seeds": get_seed_records(), "count": len(get_seed_records())}
        except Exception:
            return {"seeds": _seed_records, "count": len(_seed_records)}

    def require_model():
        if not _model_loaded:
            raise HTTPException(status_code=503, detail="model not released — rankings unavailable. Set MODEL_RELEASE_APPROVED=true and APPROVED_ARTIFACT_REVISION=<rev> with valid artifacts.")
        return True

    @app.get("/rankings")
    def rankings(
        limit: int = Query(25, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: Optional[str] = None,
        _ok=Depends(require_model),
        user=Depends(get_current_user),
    ):
        filtered = _rankings
        if q:
            ql = q.lower()
            filtered = [r for r in filtered if ql in r["gene"].lower()]
        total = len(filtered)
        paged = filtered[offset: offset + limit]
        return {"total": total, "limit": limit, "offset": offset, "results": paged, "revision": _model_revision}

    @app.get("/genes/search")
    def gene_search(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50), _ok=Depends(require_model), user=Depends(get_current_user)):
        ql = q.lower()
        # Search over ranked genes (all genes in network)
        matches = [r for r in _rankings if ql in r["gene"].lower()]
        # prioritize prefix matches
        matches.sort(key=lambda r: (0 if r["gene"].lower().startswith(ql) else 1, r.get("rank", 999)))
        return {"query": q, "results": matches[:limit]}

    @app.get("/genes/{symbol}")
    def gene_detail(symbol: str, _ok=Depends(require_model), user=Depends(get_current_user)):
        rec = _gene_index.get(symbol.upper()) or _gene_index.get(symbol)
        if not rec:
            # try case-insensitive
            for k, v in _gene_index.items():
                if k.lower() == symbol.lower():
                    rec = v
                    break
        if not rec:
            raise HTTPException(status_code=404, detail=f"gene {symbol} not found")
        # Add explanation stub: shared pathways, neighbor seeds (if pathway data available)
        explanation = _build_explanation(symbol, rec)
        return {**rec, "explanation": explanation}

    @app.get("/explain/{gene}")
    def explain(gene: str, top_n: int = Query(5, ge=1, le=20), _ok=Depends(require_model), user=Depends(get_current_user)):
        rec = _gene_index.get(gene.upper()) or _gene_index.get(gene)
        if not rec:
            for k, v in _gene_index.items():
                if k.lower() == gene.lower():
                    rec = v
                    break
        if not rec:
            raise HTTPException(status_code=404, detail=f"gene {gene} not found")
        explanation = _build_explanation(gene, rec, top_n=top_n)
        return {"gene": gene, "ranking": rec, "explanation": explanation}

    @app.get("/evaluation")
    def evaluation(_ok=Depends(require_model), user=Depends(get_current_user)):
        return _evaluation

    return app


def _build_explanation(gene_symbol, ranking_rec, top_n=5):
    """
    Build honest explanation: which seeds/pathways drove the score.
    When artifacts lack pathway attribution, return RWR score and is_seed flag plus disclaimer.
    Attempts to load pathway artifacts if available.
    """
    gene = ranking_rec.get("gene", gene_symbol)
    # Try to load pathway membership for explanation
    artifact_dir = Path(os.environ.get("ARTIFACT_DIR", str(DEFAULT_ARTIFACT_DIR)))
    # Look for pathway artifacts
    g2p = {}
    try:
        import json
        # Check for pathway file
        for cand in [artifact_dir / "pathways.json", artifact_dir / "gene_to_pathways.json"]:
            if cand.exists():
                with open(cand) as f:
                    data = json.load(f)
                    if "gene_to_pathways" in data:
                        g2p = {k: set(v) for k, v in data["gene_to_pathways"].items()}
                    break
    except Exception:
        pass

    # If no pathway data, return simple explanation
    if not g2p:
        return {
            "rwr_score": ranking_rec.get("rwr"),
            "fusion_score": ranking_rec.get("score"),
            "is_seed": ranking_rec.get("is_seed", False),
            "contributing_seeds": "pathway attribution unavailable — provide pathway artifacts for detailed explanation",
            "shared_pathways": [],
            "note": "Score reflects network proximity to seed MI/CAD genes via RWR (restart 0.3) + topology & pathway fusion." + (" This gene is itself a known MI/CAD GWAS seed." if ranking_rec.get("is_seed") else ""),
        }

    # With pathway data: find shared pathways with seeds
    try:
        from data_pipeline.seed_genes import SEED_SET
        seeds = SEED_SET
    except Exception:
        seeds = set()

    g_pws = g2p.get(gene, set()) or g2p.get(gene.upper(), set())
    shared = []
    for seed in seeds:
        s_pws = g2p.get(seed, set())
        inter = g_pws & s_pws
        for pw in inter:
            shared.append({"pathway": pw, "shared_with_seed": seed})

    # Deduplicate and limit
    seen = set()
    unique_shared = []
    for s in shared:
        key = (s["pathway"], s["shared_with_seed"])
        if key not in seen:
            seen.add(key)
            unique_shared.append(s)
    unique_shared = unique_shared[: top_n * 2]

    return {
        "rwr_score": ranking_rec.get("rwr"),
        "fusion_score": ranking_rec.get("score"),
        "is_seed": ranking_rec.get("is_seed", False),
        "shared_pathways": unique_shared,
        "pathway_overlap_count": len(unique_shared),
        "note": "Shared pathway indicates the candidate gene co-occurs in Reactome/KEGG pathway with a known MI/CAD seed gene.",
    }


# Singleton for uvicorn
app = create_app()
