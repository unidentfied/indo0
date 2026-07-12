# Build stage
FROM rust:latest AS builder

WORKDIR /workspace

# Install system deps for rdkafka / openssl
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev cmake \
    && rm -rf /var/lib/apt/lists/*

# Ensure we have a recent Rust/Cargo toolchain that understands newer Cargo.lock formats
# (This updates the stable toolchain inside the image.)
RUN rustup update stable && rustup default stable

# Show cargo version for debugging (will appear in build logs)
RUN cargo --version

# Copy Cargo manifests first (layer caching)
COPY streaming/Cargo.toml streaming/Cargo.lock ./
COPY streaming/src ./src

# Build release binary
RUN cargo build --release --bin sindio-streaming

# Runtime stage
FROM debian:bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /workspace/target/release/sindio-streaming /app/sindio-streaming

ENV RUST_LOG=sindio_streaming=info
ENV PORT=8082

EXPOSE 8082

CMD ["/app/sindio-streaming", "--port", "8082"]
