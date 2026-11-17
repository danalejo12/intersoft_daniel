#!/bin/sh
set -e

# Si el contenedor recibe un comando (por ejemplo el "scheduler" de compose.prod.yml con
# `python manage.py tareas_periodicas --bucle`), se ejecuta ese comando tal cual. Sin esto,
# todos los contenedores arrancarían gunicorn y las tareas periódicas nunca correrían.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "Aplicando migraciones de base de datos..."
python manage.py migrate --noinput

echo "Sincronizando catalogo de permisos..."
python manage.py sincronizar_permisos

echo "Recolectando archivos estaticos..."
python manage.py collectstatic --noinput

echo "Iniciando servidor Gunicorn en 0.0.0.0:8000..."
exec gunicorn intersoft.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
