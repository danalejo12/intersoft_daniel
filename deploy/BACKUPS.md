# Operación de Copias de Seguridad de PostgreSQL (InterSoft)

Este documento describe el procedimiento operativo para realizar respaldos automáticos de PostgreSQL con `pg_dump` y verificar periódicamente que pueden restaurarse sin errores en una base de datos temporal.

## 1. Script incluido

- Script: [`deploy/backup_postgres.sh`](./backup_postgres.sh)
- Formato: `pg_dump --format=custom --compress=6 --no-owner --no-privileges` (`.dump`)
- Retención por defecto: `14` días (`RETENTION_DAYS`)

### Variables de entorno

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `DB_NAME` | `intersoft` | Base de datos a respaldar |
| `DB_USER` | `postgres` | Usuario con permisos de lectura y creación/borrado de BD temporal |
| `DB_PASSWORD` / `PGPASSWORD` | *(requerido en prod)* | Contraseña de PostgreSQL (puede cargarse desde `.env`) |
| `DB_HOST` | `localhost` | Host de PostgreSQL |
| `DB_PORT` | `5432` | Puerto de PostgreSQL |
| `BACKUP_DIR` | `./backups/postgres` | Carpeta destino de los archivos `.dump` |
| `RETENTION_DAYS` | `14` | Días tras los cuales se eliminan copias antiguas |
| `VERIFY_RESTORE` | `false` | Si es `true` (o si se pasa `--verify`), restaura en una BD temporal |

## 2. Ejecución manual

### En servidor con PostgreSQL accesible

```bash
chmod +x deploy/backup_postgres.sh
set -a && source .env && set +a
./deploy/backup_postgres.sh --verify
```

### Con Docker Compose (`compose.prod.yml`)

```bash
docker compose -f compose.prod.yml exec -T db \
  pg_dump -U "${DB_USER:-intersoft}" -Fc "${DB_NAME:-intersoft}" > "backups/intersoft_$(date -u +%Y%m%dT%H%M%SZ).dump"
```

## 3. Programación periódica (Cron)

Ejemplo para respaldo diario a las 02:00 UTC y verificación semanal de restauración los domingos a las 03:00 UTC:

```cron
# Respaldo diario (02:00 UTC)
0 2 * * * cd /srv/intersoft && set -a && . ./.env && set +a && /srv/intersoft/deploy/backup_postgres.sh >> /var/log/intersoft-backup.log 2>&1

# Verificación semanal de restauración en base temporal (domingos 03:00 UTC)
0 3 * * 0 cd /srv/intersoft && set -a && . ./.env && set +a && /srv/intersoft/deploy/backup_postgres.sh --verify >> /var/log/intersoft-backup.log 2>&1
```

## 4. Qué valida `--verify`

1. Crea una base de datos temporal `${DB_NAME}_verify_<timestamp>`.
2. Ejecuta `pg_restore --exit-on-error` sobre el `.dump` recién creado.
3. Consulta `SELECT COUNT(*) FROM django_migrations;` para comprobar integridad de tablas.
4. Elimina la base temporal automáticamente mediante `trap ... EXIT`, incluso si falla algún paso.

## 5. Procedimiento de restauración ante desastre

1. Detener el tráfico web / worker (`docker compose -f compose.prod.yml stop web scheduler`).
2. Restaurar sobre una base limpia:
   ```bash
   dropdb -h "$DB_HOST" -U "$DB_USER" "$DB_NAME"
   createdb -h "$DB_HOST" -U "$DB_USER" "$DB_NAME"
   pg_restore --no-owner --no-privileges --exit-on-error -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" backups/postgres/<archivo>.dump
   ```
3. Levantar servicios y verificar `/salud/`.
