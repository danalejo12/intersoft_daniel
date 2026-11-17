FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias del sistema para PostgreSQL y fuentes básicas
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copiar código del proyecto y entrypoint
COPY intersoft /app/intersoft
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Usuario no privilegiado por seguridad
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/intersoft/media /app/intersoft/staticfiles /app/intersoft/logs \
    && chown -R appuser:appuser /app

USER appuser
WORKDIR /app/intersoft

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
