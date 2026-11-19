# ==============================================================================
# Multi-Stage Production Dockerfile for PayLap
# ==============================================================================

# Stage 1: Build Frontend Assets
FROM node:20-alpine AS frontend-builder
WORKDIR /build

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Application
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    APP_HOME=/app

# Create unprivileged system group and user
RUN groupadd -g 10001 paylap && \
    useradd -u 10001 -g paylap -m -s /bin/bash paylap

WORKDIR $APP_HOME

# Install OS security updates and curl for healthchecks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ app/
COPY alembic.ini .
COPY alembic/ alembic/
COPY pyproject.toml .

# Copy built frontend assets from Stage 1
COPY --from=frontend-builder /build/dist /app/frontend/dist

# Secure ownership
RUN chown -R paylap:paylap $APP_HOME

USER paylap

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
