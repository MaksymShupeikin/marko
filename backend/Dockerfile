# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

FROM python:3.13-slim AS runtime

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

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN groupadd --gid 10001 marko \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin marko

EXPOSE 8000

FROM runtime AS test

RUN uv sync --frozen --group dev --no-editable
COPY tests ./tests
CMD ["pytest", "-q"]

FROM runtime AS production

USER 10001:10001

CMD ["uvicorn", "marko.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
