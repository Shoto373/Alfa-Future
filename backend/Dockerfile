FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_DIR=/app/data/synthetic \
    FALLBACK_DATA_DIR=/app/data/synthetic \
    RUNTIME_DIR=/app/runtime

WORKDIR /app

# Установка зависимостей backend
COPY backend/requirements.txt /app/requirements.txt
COPY backend/constraints.txt /app/constraints.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Локальная embedding-модель (не генеративная, ~220 МБ) скачивается при сборке,
# чтобы в работе сервису не нужна была сеть. EMBEDDINGS_ENABLED=0 — работа только на словарях.
ENV EMBEDDINGS_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2     EMBEDDINGS_CACHE_DIR=/app/models
RUN python -c "import os; from fastembed import TextEmbedding; TextEmbedding(os.environ['EMBEDDINGS_MODEL'], cache_dir=os.environ['EMBEDDINGS_CACHE_DIR'])"
ENV HF_HUB_OFFLINE=1

# Исходный код и синтетический набор данных (реальные данные кейса монтируются через DATA_DIR)
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/app /app/app
# Отрасли, темы и действия как данные (SPR4-00): исходная доменная конфигурация.
COPY backend/config /app/config
COPY data/synthetic /app/data/synthetic

RUN mkdir -p /app/runtime
EXPOSE 8000

# ROLE=api (по умолчанию) — HTTP API на 8000, ROLE=worker — фоновый воркер (app/run.py).
CMD ["python", "-m", "app.run"]
