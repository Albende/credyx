FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy requirements first for layer caching.
COPY apps/api/requirements.txt /app/apps/api/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/apps/api/requirements.txt

# Copy the whole monorepo so `packages.*` imports resolve.
COPY apps /app/apps
COPY packages /app/packages

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
