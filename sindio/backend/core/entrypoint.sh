#!/bin/bash
set -euo pipefail

MODEL_DIR="${MODEL_PATH:-/workspace/models/trained}"
EMBEDDING_DIR="${EMBEDDINGS_PATH:-/workspace/models/embeddings}"
S3_BUCKET="s3://sindio-${ENVIRONMENT:-production}-models"

REQUIRED_MODELS=(
    urban_stress_v1.pth
    mobility_v2.pth
    water_demand_v1.pth
)

models_missing() {
    for f in "${REQUIRED_MODELS[@]}"; do
        [ -f "$MODEL_DIR/$f" ] || return 0
    done
    return 1
}

embeddings_missing() {
    [ ! -f "$EMBEDDING_DIR/all-MiniLM-L6-v2/config.json" ]
}

s3_sync_with_retry() {
    local src="$1"
    local dst="$2"
    local label="$3"
    local max_attempts=3
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "[entrypoint] S3 sync $label (attempt $attempt/$max_attempts): $src -> $dst"
        if aws s3 sync "$src" "$dst" 2>&1; then
            echo "[entrypoint] S3 sync $label succeeded"
            return 0
        fi
        if [ $attempt -lt $max_attempts ]; then
            local delay=$((10 * attempt))
            echo "[entrypoint] S3 sync $label failed — retrying in ${delay}s"
            sleep "$delay"
        fi
        attempt=$((attempt + 1))
    done
    echo "[entrypoint] S3 sync $label failed after $max_attempts attempts"
    return 1
}

if models_missing; then
    echo "[entrypoint] Trained model weights missing at $MODEL_DIR"
    echo "[entrypoint] Attempting S3 download from $S3_BUCKET ..."

    if command -v aws &>/dev/null; then
        s3_sync_with_retry "$S3_BUCKET/trained/" "$MODEL_DIR/" "trained models" || true
    else
        echo "[entrypoint] AWS CLI not found in \$PATH — cannot download models"
    fi

    if models_missing; then
        echo "[entrypoint] FATAL: Model weights are missing and S3 download failed or is unavailable."
        echo "[entrypoint] Ensure MODEL_PATH points to a directory with .pth checkpoints"
        echo "[entrypoint] or configure AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY to pull from $S3_BUCKET."
        exit 1
    fi

    echo "[entrypoint] Trained model download complete — all ${#REQUIRED_MODELS[@]} checkpoints present."
fi

if embeddings_missing; then
    echo "[entrypoint] Embedding model config missing at $EMBEDDING_DIR"

    if command -v aws &>/dev/null; then
        s3_sync_with_retry "$S3_BUCKET/embeddings/" "$EMBEDDING_DIR/" "embeddings" || true
    fi

    if embeddings_missing; then
        echo "[entrypoint] WARNING: Embedding weights not available from S3."
        echo "[entrypoint] The service will attempt to download all-MiniLM-L6-v2 from HuggingFace at runtime."
        echo "[entrypoint] Ensure HF_HUB_TOKEN is set if the model is gated, and that outbound internet is allowed."
    else
        echo "[entrypoint] Embedding model download complete."
    fi
fi

PORT="${PORT:-${CORE_PORT:-8081}}"
echo "[entrypoint] Starting Sindio Core on port $PORT"
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
