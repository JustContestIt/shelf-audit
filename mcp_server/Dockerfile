FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY shelf_audit_mcp shelf_audit_mcp
RUN pip install .
EXPOSE 8765
CMD ["shelf-audit-mcp", "--transport", "http", "--port", "8765"]
