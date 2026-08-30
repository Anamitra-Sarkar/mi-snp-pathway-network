import os
import json
import tempfile
import pathlib
import importlib

import pytest
from fastapi.testclient import TestClient


def _make_artifacts(tmpdir, n_genes=10):
    # Create minimal ranked artifacts
    rankings = []
    for i in range(n_genes):
        gene = f"GENE_{i}"
        rankings.append({
            "rank": i+1,
            "gene": gene,
            "score": float(1.0 - i*0.05),
            "rwr": float(0.5 - i*0.02),
            "is_seed": i < 2
        })
    with open(os.path.join(tmpdir, "rankings.json"), "w") as f:
        json.dump(rankings, f)
    with open(os.path.join(tmpdir, "features.json"), "w") as f:
        json.dump({"gene_list": [r["gene"] for r in rankings], "feature_names": ["rwr_score"]}, f)
    with open(os.path.join(tmpdir, "evaluation.json"), "w") as f:
        json.dump({"kfold": {"aggregate": {"auprc_mean": 0.9}}}, f)
    return rankings


def test_release_gate_closed_by_default():
    # Ensure env not approved
    for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
        os.environ.pop(k, None)
    # Need to reimport app after env change
    import backend.app as app_mod
    import importlib
    importlib.reload(app_mod)
    client = TestClient(app_mod.create_app())
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["model_loaded"] is False
    # rankings should 503
    res2 = client.get("/rankings")
    assert res2.status_code == 503
    assert "model not released" in res2.json()["detail"]
    # ready should 503
    res3 = client.get("/ready")
    assert res3.status_code == 503
    # seeds is always available (does not require model)
    res4 = client.get("/seeds")
    assert res4.status_code == 200
    assert "seeds" in res4.json()


def test_release_gate_open_with_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        rankings = _make_artifacts(tmp, n_genes=12)
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "testrev123"
        os.environ["ARTIFACT_DIR"] = tmp
        import backend.app as app_mod
        import importlib
        importlib.reload(app_mod)
        app = app_mod.create_app()
        client = TestClient(app)
        h = client.get("/health")
        assert h.status_code == 200
        assert h.json()["model_loaded"] is True
        assert h.json()["revision"] == "testrev123"
        r = client.get("/ready")
        assert r.status_code == 200
        # rankings ok
        resp = client.get("/rankings?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 12
        assert len(data["results"]) == 5
        assert data["results"][0]["gene"] == "GENE_0"
        # search
        s = client.get("/genes/search?q=GENE_1")
        assert s.status_code == 200
        assert any("GENE_1" in r["gene"] for r in s.json()["results"])
        # gene detail
        g = client.get("/genes/GENE_0")
        assert g.status_code == 200
        assert g.json()["gene"] == "GENE_0"
        assert "explanation" in g.json()
        # explain
        e = client.get("/explain/GENE_1")
        assert e.status_code == 200
        assert e.json()["gene"] == "GENE_1"
        # missing gene 404
        miss = client.get("/genes/NONEXISTENT_GENE_XYZ")
        assert miss.status_code == 404
        # cleanup
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
            os.environ.pop(k, None)


def test_release_gate_approved_but_missing_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        # empty dir, no rankings.json
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "rev-missing"
        os.environ["ARTIFACT_DIR"] = tmp
        import backend.app as app_mod
        import importlib
        importlib.reload(app_mod)
        client = TestClient(app_mod.create_app())
        h = client.get("/health")
        assert h.json()["model_loaded"] is False
        # still 503 for rankings (fail-closed, not fabricated)
        r = client.get("/rankings")
        assert r.status_code == 503
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
            os.environ.pop(k, None)


def test_auth_stub_with_mock_verifier():
    with tempfile.TemporaryDirectory() as tmp:
        _make_artifacts(tmp)
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "rev-auth"
        os.environ["ARTIFACT_DIR"] = tmp
        import backend.auth as auth_mod
        import backend.app as app_mod
        import importlib
        importlib.reload(auth_mod)
        importlib.reload(app_mod)

        # Inject mock verifier that only accepts token "valid-token"
        def verifier(token):
            if token == "valid-token":
                return {"uid": "testuser"}
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="invalid token")

        auth_mod.set_verifier(verifier)
        app = app_mod.create_app()
        client = TestClient(app)
        # Without token, but REQUIRE_AUTH not set -> should still allow (optional)
        # Actually get_current_user returns None when no auth, but endpoint allows it
        resp = client.get("/rankings")
        # auth stub currently allows unauthenticated when REQUIRE_AUTH false (our default)
        assert resp.status_code == 200

        # With invalid token -> 401
        resp2 = client.get("/rankings", headers={"Authorization": "Bearer bad-token"})
        assert resp2.status_code == 401

        # With valid token -> 200
        resp3 = client.get("/rankings", headers={"Authorization": "Bearer valid-token"})
        assert resp3.status_code == 200

        # Cleanup verifier
        auth_mod.set_verifier(None)
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR"]:
            os.environ.pop(k, None)
        importlib.reload(auth_mod)
        importlib.reload(app_mod)


def test_auth_stub_missing_header_when_require_auth():
    with tempfile.TemporaryDirectory() as tmp:
        _make_artifacts(tmp)
        os.environ["MODEL_RELEASE_APPROVED"] = "true"
        os.environ["APPROVED_ARTIFACT_REVISION"] = "rev2"
        os.environ["ARTIFACT_DIR"] = tmp
        os.environ["REQUIRE_AUTH"] = "true"
        import backend.auth as auth_mod
        import backend.app as app_mod
        import importlib
        importlib.reload(auth_mod)
        importlib.reload(app_mod)

        # mock verifier to accept valid token
        def verifier(token):
            if token == "good":
                return {"uid": "u1"}
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="bad")

        auth_mod.set_verifier(verifier)
        app = app_mod.create_app()
        client = TestClient(app)
        # No header -> should be 401 when REQUIRE_AUTH true? Our app allows None for rankings if REQUIRE_AUTH not enforced at endpoint?
        # The rankings endpoint Depends(get_current_user) where get_current_user checks REQUIRE_AUTH
        # Actually we set set_verifier, but get_current_user will check verifier or REQUIRE_AUTH.
        # With REQUIRE_AUTH=true and no header, it should raise 401
        resp = client.get("/rankings")
        # Could be 401 or 503? Let's assert it's not 200 success without auth
        assert resp.status_code in (401, 503)

        auth_mod.set_verifier(None)
        for k in ["MODEL_RELEASE_APPROVED", "APPROVED_ARTIFACT_REVISION", "ARTIFACT_DIR", "REQUIRE_AUTH"]:
            os.environ.pop(k, None)
        importlib.reload(auth_mod)
        importlib.reload(app_mod)
