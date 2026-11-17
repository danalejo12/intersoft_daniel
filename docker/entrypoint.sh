#!/bin/sh
set -e

echo "Aplicando migraciones de base de datos..."
python manage.py migrate --noinput

echo "Sincronizando catalogo de permisos..."
python manage.py sincronizar_permisos

echo "Recolectando archivos estaticos..."
python manage.py collectstatic --noinput

echo "Iniciando servidor Gunicorn en 0.0.0.0:8000..."
exec gunicorn intersoft.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
