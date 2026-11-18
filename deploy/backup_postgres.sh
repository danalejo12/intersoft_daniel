#!/usr/bin/env bash
# Copia de seguridad automática de PostgreSQL (pg_dump) y verificación de restauración.
# Uso:
#   ./deploy/backup_postgres.sh [--verify]
#
# Variables de entorno opcionales:
#   BACKUP_DIR      Directorio destino (por defecto: ./backups/postgres)
#   RETENTION_DAYS  Días de retención de respaldos (por defecto: 14)
#   DB_NAME         Nombre de la base de datos (por defecto: intersoft)
#   DB_USER         Usuario de PostgreSQL (por defecto: postgres)
#   DB_HOST         Host de PostgreSQL (por defecto: localhost)
#   DB_PORT         Puerto de PostgreSQL (por defecto: 5432)
#   PGPASSWORD / DB_PASSWORD  Contraseña de PostgreSQL
#   VERIFY_RESTORE  "true" para verificar restauración en base temporal

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_NAME="${DB_NAME:-intersoft}"
DB_USER="${DB_USER:-postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
export PGPASSWORD="${PGPASSWORD:-${DB_PASSWORD:-}}"

VERIFY_RESTORE="${VERIFY_RESTORE:-false}"
if [[ "${1:-}" == "--verify" ]]; then
  VERIFY_RESTORE="true"
fi

mkdir -p "${BACKUP_DIR}"
FECHA="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVO="${BACKUP_DIR}/${DB_NAME}_${FECHA}.dump"
TEMP_DB=""

limpiar_temp_db() {
  if [[ -n "${TEMP_DB}" ]]; then
    dropdb --if-exists -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "${TEMP_DB}" >/dev/null 2>&1 || true
  fi
}
trap limpiar_temp_db EXIT

echo "[$(date -u +%FT%TZ)] Generando respaldo en ${ARCHIVO}..."
pg_dump \
  --format=custom \
  --compress=6 \
  --no-owner \
  --no-privileges \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -f "${ARCHIVO}" \
  "${DB_NAME}"

if [[ ! -s "${ARCHIVO}" ]]; then
  echo "ERROR: El archivo de respaldo está vacío: ${ARCHIVO}" >&2
  exit 1
fi

echo "[$(date -u +%FT%TZ)] Respaldo generado: $(du -h "${ARCHIVO}" | cut -f1)"

if [[ "${VERIFY_RESTORE}" == "true" ]]; then
  TEMP_DB="${DB_NAME}_verify_${FECHA}"
  echo "[$(date -u +%FT%TZ)] Verificando restauración en base temporal ${TEMP_DB}..."
  createdb -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "${TEMP_DB}"
  pg_restore \
    --no-owner \
    --no-privileges \
    --exit-on-error \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    -d "${TEMP_DB}" \
    "${ARCHIVO}"

  MIGRACIONES="$(psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${TEMP_DB}" -Atc "SELECT COUNT(*) FROM django_migrations;")"
  echo "[$(date -u +%FT%TZ)] Restauración verificada OK (${MIGRACIONES} migraciones registradas)."
  dropdb -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "${TEMP_DB}"
  TEMP_DB=""
fi

echo "[$(date -u +%FT%TZ)] Eliminando respaldos con más de ${RETENTION_DAYS} días..."
find "${BACKUP_DIR}" -type f -name "${DB_NAME}_*.dump" -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date -u +%FT%TZ)] Proceso finalizado correctamente."
