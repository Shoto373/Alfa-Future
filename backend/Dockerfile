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

# Исходный код и синтетический набор данных (реальные данные кейса монтируются через DATA_DIR)
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/app /app/app
COPY data/synthetic /app/data/synthetic

RUN mkdir -p /app/runtime
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
