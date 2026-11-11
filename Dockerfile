FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY intersoft /app/intersoft

WORKDIR /app/intersoft

RUN adduser --disabled-password --gecos "" intersoft \
    && mkdir -p /app/intersoft/staticfiles /app/intersoft/media /app/intersoft/logs \
    && chown -R intersoft:intersoft /app/intersoft

USER intersoft

EXPOSE 8000

CMD ["gunicorn", "intersoft.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
