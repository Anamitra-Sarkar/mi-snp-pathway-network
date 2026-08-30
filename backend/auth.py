"""
Firebase-auth-shaped auth dependency stub.

Real behavior:
 - Reads env var FIREBASE_SERVICE_ACCOUNT_JSON (path to service account JSON)
 - If file exists, attempts to initialize firebase_admin and verify Bearer token.
 - If not present in sandbox, logs warning and behaves per REQUIRE_AUTH env var.

This is testable with mocked verifier.
"""
import os
import json
from typing import Optional

from fastapi import Header, HTTPException, Depends

# Configuration via env
FIREBASE_SA_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")

# For test mocking, allow injectable verifier
_verifier = None


def set_verifier(fn):
    """Inject a custom token verifier for testing: fn(token) -> dict user_info or raise."""
    global _verifier
    _verifier = fn


def _default_verify_token(token: str):
    """
    Attempt real Firebase verification if available; otherwise stub.
    Returns user info dict on success, raises HTTPException on failure.
    """
    if _verifier is not None:
        return _verifier(token)

    sa_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    # If no service account file present, we are in sandbox/dev
    if not sa_path or not os.path.exists(sa_path):
        if REQUIRE_AUTH:
            raise HTTPException(status_code=401, detail="Authentication required but no Firebase service account configured")
        # In non-require mode, attempt to decode as dummy: accept any non-empty Bearer as stub user
        # But to be honest, we still validate format
        if not token or token.strip() == "":
            raise HTTPException(status_code=401, detail="Missing authentication token")
        # Stub: accept token as user identifier (for dev). In production, this path MUST NOT be used.
        return {"uid": "stub-user", "token_preview": token[:8] + "...", "warning": "STUB verification — no service account file"}

    # Real Firebase path (optional dependency)
    try:
        import firebase_admin
        from firebase_admin import credentials, auth as fb_auth
        if not firebase_admin._apps:
            cred = credentials.Certificate(sa_path)
            firebase_admin.initialize_app(cred)
        decoded = fb_auth.verify_id_token(token)
        return decoded
    except ImportError:
        raise HTTPException(status_code=500, detail="firebase_admin not installed but FIREBASE_SERVICE_ACCOUNT_JSON is set")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {e}")


def get_current_user(authorization: Optional[str] = Header(None)):
    """
    FastAPI dependency: extracts Bearer token, verifies.
    If Authorization missing and REQUIRE_AUTH=false, returns None (optional auth).
    If REQUIRE_AUTH=true, raises 401.
    """
    if authorization is None:
        if REQUIRE_AUTH or _verifier is not None:
            # if verifier injected and require auth, enforce
            if os.environ.get("REQUIRE_AUTH", "false").lower() in ("true", "1"):
                raise HTTPException(status_code=401, detail="Missing Authorization header")
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header, expected Bearer <token>")
    token = parts[1]
    return _default_verify_token(token)


def require_auth(authorization: Optional[str] = Header(None)):
    """Dependency that enforces auth when REQUIRE_AUTH=true, otherwise optional."""
    user = get_current_user(authorization)
    if REQUIRE_AUTH and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
