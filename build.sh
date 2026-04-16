#!/usr/bin/env bash
# Salir si hay algún error
set -o errexit

echo "Instalando dependencias..."
pip install -r requirements.txt

echo "Recolectando archivos estáticos (CSS/JS)..."
python manage.py collectstatic --no-input

echo "Aplicando migraciones a la Base de Datos en Neon..."
python manage.py migrate