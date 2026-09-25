# API + graph + RAG (context: repo root, see docker-compose.yml)
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install uv
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN uv pip install --system -e backend
COPY evals /app/evals
# data/ (photos, refs, models) is mounted at runtime: customer data is never baked into an image
VOLUME ["/app/data"]
EXPOSE 8000
WORKDIR /app/backend
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
