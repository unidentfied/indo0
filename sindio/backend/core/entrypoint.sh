#!/bin/bash
set -euo pipefail

MODEL_DIR="${MODEL_PATH:-/workspace/models/trained}"
EMBEDDING_DIR="${EMBEDDINGS_PATH:-/workspace/models/embeddings}"

# List of required model checkpoints (placeholder names)
REQUIRED_MODELS=(
    urban_stress_v1.pth
    mobility_v2.pth
    water_demand_v1.pth
)

# Helper: create dummy files if they do not exist
create_dummy_models() {
    mkdir -p "$MODEL_DIR"
    for f in "${REQUIRED_MODELS[@]}"; do
        if [ ! -f "$MODEL_DIR/$f" ]; then
            echo "[entrypoint] Creating dummy model $f"
            touch "$MODEL_DIR/$f"
        fi
    done
}

# Helper: create a minimal embeddings placeholder
create_dummy_embeddings() {
    mkdir -p "$EMBEDDING_DIR"
    if [ ! -f "$EMBEDDING_DIR/all-MiniLM-L6-v2/config.json" ]; then
        echo "[entrypoint] Creating dummy embeddings placeholder"
        mkdir -p "$EMBEDDING_DIR/all-MiniLM-L6-v2"
        echo '{"model_type":"dummy"}' > "$EMBEDDING_DIR/all-MiniLM-L6-v2/config.json"
    fi
}

# Skip any AWS download – create placeholders instead
create_dummy_models
create_dummy_embeddings

PORT="${PORT:-${CORE_PORT:-8081}}"
echo "[entrypoint] Starting Sindio Core on port $PORT"
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
