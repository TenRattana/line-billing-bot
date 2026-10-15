FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Thai font for the generated rich menu image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-tlwg-loma-ttf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen

COPY . .

EXPOSE 8500

# Migrate first, so a new image never runs against an old schema. One process only:
# sessions and per-user locks live in memory (no --workers).
ENTRYPOINT ["sh", "-c", "uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8500 \"$@\"", "--"]
