# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.10.1 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY core ./core
COPY main.py ./

RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

# OAuth browser callback; it is published only by docker-compose.yml.
EXPOSE 8765

CMD ["python", "-m", "core.pipeline", "--selfcheck"]
