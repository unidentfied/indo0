FROM golang:1.22-alpine AS builder

WORKDIR /workspace

COPY sindio/backend/api/go.mod sindio/backend/api/go.sum ./
RUN go mod download

COPY sindio/backend/api/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /api ./cmd/api/

FROM alpine:3.19
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /api /usr/local/bin/api

EXPOSE 8080
USER nobody
CMD ["api"]
