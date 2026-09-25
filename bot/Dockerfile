FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY shelf_bot shelf_bot
RUN pip install .
CMD ["shelf-audit-bot"]
