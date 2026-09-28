# ============================================================================
# NEXUS-ASTRA Go Router — Multi-stage Dockerfile
# Final image target: < 20 MB (statically linked binary on scratch)
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build
# ---------------------------------------------------------------------------
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache ca-certificates git

WORKDIR /build

# Cache dependency downloads before copying source.
COPY go.mod go.sum ./
RUN go mod download

# Copy source and build a fully static binary.
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -trimpath -o /go-router .

# ---------------------------------------------------------------------------
# Stage 2: Runtime (scratch for minimal attack surface and size)
# ---------------------------------------------------------------------------
FROM scratch

# Import CA certificates so outbound TLS (wss://) works.
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Copy the compiled binary.
COPY --from=builder /go-router /go-router

EXPOSE 9090

ENTRYPOINT ["/go-router"]
