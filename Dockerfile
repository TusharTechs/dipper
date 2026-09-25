# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
# Behind a TLS-inspecting proxy, pass the proxy's CA bundle as a build secret. It is used only for this
# step and is not stored in the image. docker-compose.yml wires it from $DIPPER_EXTRA_CA (default: empty file).
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca.pem && export SSL_CERT_FILE=/tmp/ca.pem; \
    fi; \
    uv sync --frozen --no-dev && rm -f /tmp/ca.pem
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "--no-sync", "uvicorn", "dipper_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
