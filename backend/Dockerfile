FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend/src

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock /app/backend/

RUN pip install --no-cache-dir uv \
    && uv sync --project /app/backend --frozen --no-dev --no-install-project

COPY backend/src /app/backend/src
COPY projects /app/projects
COPY frontend/dist /app/frontend/dist

WORKDIR /app/backend
EXPOSE 8100
CMD ["uv", "run", "--project", "/app/backend", "--no-dev", "uvicorn", "symbiot.sidecar:app", "--host", "0.0.0.0", "--port", "8100"]
