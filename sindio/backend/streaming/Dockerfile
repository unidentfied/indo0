# Build stage
FROM rust:1.75-slim AS builder

WORKDIR /workspace

# Install system deps for rdkafka / openssl
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev cmake \
    && rm -rf /var/lib/apt/lists/*

# Copy Cargo manifests first (layer caching)
COPY sindio/backend/streaming/Cargo.toml sindio/backend/streaming/Cargo.lock ./
COPY sindio/backend/streaming/src ./src

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

CMD exec /app/sindio-streaming --port ${PORT:-8082}
