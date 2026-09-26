# ---- frontend build ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- backend + built frontend ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EMBEDDING_CACHE_DIR=/models STORAGE_DIR=/data/files
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Bake the local embedding model into the image so the first request is fast.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')"

COPY backend/app ./app
COPY backend/alembic.ini ./
COPY --from=web /web/dist ./static

# /data/files holds original resumes (STORAGE_PROVIDER=local); compose mounts a volume there.
RUN useradd --create-home talentflow && mkdir -p /data/files && chown -R talentflow /app /models /data/files
USER talentflow

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
# Migrations run once here, before the API workers start. The worker service overrides CMD.
ENV AUTO_MIGRATE=false WEB_CONCURRENCY=2
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
