# syntax=docker/dockerfile:1
# MI/CAD SNP-gene-pathway backend — multi-stage, fail-closed release gate preserved
# Build & run:
#   docker build -f backend/Dockerfile -t mi-snp-backend .
#   docker run -p 8000:8000 mi-snp-backend
# Release-gated run (requires artifacts):
#   docker run -p 8000:8000 -e MODEL_RELEASE_APPROVED=true -e APPROVED_ARTIFACT_REVISION=v1 -v $(pwd)/artifacts:/app/artifacts mi-snp-backend

FROM python:3.11-slim AS builder
WORKDIR /app

# System deps for building scipy/scikit-learn wheels if needed (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --- runtime stage ---
FROM python:3.11-slim AS runtime
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code — backend depends on data_pipeline (seed genes) so include it
COPY backend/ ./backend/
COPY data_pipeline/ ./data_pipeline/
COPY requirements.txt ./requirements.txt

# Artifacts directory (may be mounted or empty — backend fail-closed handles missing)
RUN mkdir -p /app/artifacts && chown appuser:appuser /app/artifacts

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARTIFACT_DIR=/app/artifacts \
    MODEL_RELEASE_APPROVED=false \
    APPROVED_ARTIFACT_REVISION=""

EXPOSE 8000

USER appuser

# Healthcheck hits the honest /health endpoint (always 200)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4); sys.exit(0 if r.status==200 else 1)"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
