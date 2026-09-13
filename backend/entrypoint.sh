#!/bin/sh
# Downloads the approved artifacts from HF Hub before starting the server,
# if MODEL_RELEASE_APPROVED + APPROVED_ARTIFACT_REVISION are set. If not
# approved, starts anyway -- backend/app.py correctly fails closed.
set -e

if [ "$MODEL_RELEASE_APPROVED" = "true" ] && [ -n "$APPROVED_ARTIFACT_REVISION" ]; then
  echo "[entrypoint] Downloading approved artifact revision $APPROVED_ARTIFACT_REVISION"
  python3 -c "
import os
import shutil
from huggingface_hub import hf_hub_download

rev = os.environ['APPROVED_ARTIFACT_REVISION']
token = os.environ.get('HF_TOKEN')
repo_id = 'bhumika-tewari-282006/mi-snp-pathway-network'
artifact_dir = os.environ.get('ARTIFACT_DIR', '/app/artifacts')
os.makedirs(artifact_dir, exist_ok=True)

for fname in ('rankings.json', 'features.json', 'model.pkl', 'evaluation.json'):
    p = hf_hub_download(repo_id=repo_id, filename=fname, repo_type='model', revision=rev, token=token)
    shutil.copy(p, os.path.join(artifact_dir, fname))
    print(f'[entrypoint] {fname} -> {artifact_dir}/{fname}')
"
else
  echo "[entrypoint] No approved release configured; starting in fail-closed abstention mode."
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
