# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv

FROM python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

RUN apk upgrade --no-cache libcrypto3 libssl3 \
    && addgroup -S marko \
    && adduser -S -G marko -h /nonexistent marko

COPY --from=build /app/.venv ./.venv
COPY pyproject.toml uv.lock README.md ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN chown -R marko:marko /app

USER marko

EXPOSE 8000

FROM runtime AS test

USER root
COPY --from=uv /uv /uvx /bin/
RUN uv sync --frozen --group dev --no-editable
COPY tests ./tests
RUN chown -R marko:marko /app
USER marko
CMD ["pytest", "-q"]

FROM runtime AS production

CMD ["uvicorn", "marko.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--limit-concurrency", "100", "--timeout-keep-alive", "10"]
