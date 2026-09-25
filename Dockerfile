# syntax=docker/dockerfile:1
# One image serves the web app at / and the API at /api (dipper_api.main:site).
# Optional build secret `extra_ca`: an extra CA bundle for networks with a TLS-inspecting proxy. It is used only
# during the download steps and is never stored in the image.

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem && export SSL_CERT_FILE=/tmp/ca.pem; \
    fi; \
    uv sync --frozen --no-dev && rm -f /tmp/ca.pem
COPY --from=web /web/dist ./web/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Run as an unprivileged user. Everything that changes at runtime (event store, redacted photos) lives in
# /app/state, which docker-compose.yml mounts as a volume.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin dipper \
    && mkdir -p /app/state && chown dipper:dipper /app/state
ENV DIPPER_DB=/app/state/dipper.sqlite3 DIPPER_MEDIA=/app/state/media DIPPER_CACHE=/app/state/cache PORT=8000 PATH="/app/.venv/bin:$PATH"
USER dipper
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/ready', timeout=4)"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn dipper_api.main:site --host 0.0.0.0 --port ${PORT}"]
