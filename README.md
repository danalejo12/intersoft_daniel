# Intersoft

Plataforma web multiempresa (SaaS + Marketplace + Punto de Venta POS + ERP) desarrollada en **Django 6.1** y **PostgreSQL 16**.

---

## Funcionalidades principales

- **Multiempresa (Multi-tenancy) con aislamiento estricto**:
  - Cada negocio opera sobre su propio inventario, clientes, facturación y turnos de caja mediante `TenantMiddleware` y `TenantQuerySet`.
  - Selector rápido de negocio activo en la barra superior (`/panel/negocio/cambiar/`) cuando un usuario pertenece a más de una empresa.
- **Roles, permisos granulares (RBAC) y gestión de equipo (`/panel/equipo/`)**:
  - Catálogo centralizado de 31 permisos agrupados por módulo (`core/permisos.py`) y comando idempotente `sincronizar_permisos`.
  - Plantillas de roles iniciales creadas automáticamente al registrar cada negocio: **Administrador**, **Cajero POS**, **Asesor comercial**, **Bodega e inventario**, **Contador** y **Empleado**.
  - Gestión de miembros del equipo (creación de usuarios nuevos o vinculación por correo de cuentas existentes) con reglas anti-bloqueo que impiden desactivar o degradar al último administrador activo.
  - Navegación lateral (dock) y métricas financieras del dashboard adaptadas según los permisos del rol activo.
- **Punto de Venta (POS) y arqueo de caja (`/panel/pos/`)**:
  - Apertura y cierre de turnos de caja con cálculo de arqueo y diferencias.
  - Cobros combinados (efectivo, tarjeta, transferencia), validación estricta de cantidades y límites monetarios (`DecimalField(14, 2)`).
  - Idempotencia por clave de operación (`clave_operacion` UUID) para evitar ventas duplicadas ante reintentos de red.
  - Ticket de venta con instantánea inmutable de datos del emisor, receptor y líneas vendidas.
- **Marketplace público, carrito y reservas de stock (`/`, `/carrito/`, `/pedidos/`)**:
  - Catálogo público por negocio (`/tienda/<slug>/`), opiniones con insignia de compra verificada y cumplimiento del art. 53 de la Ley 1480 (datos legales del vendedor).
  - Reserva temporal de stock al confirmar pedido con bloqueo de filas (`select_for_update`), renovación controlada y liberación automática de pedidos vencidos (`liberar_pedidos_vencidos`).
  - Compra unificada (`/comprar/`): un checkout con los datos de envío una sola vez para varios negocios; cada negocio se paga por separado desde `/compras/<id>/`, porque cobra con su propia cuenta de Wompi.
  - Orden «Más vendidos» (unidades pagadas en los últimos 90 días) y relevancia que combina ventas con opiniones.
- **Bodegas o sedes (`/panel/bodegas/`)**:
  - Stock por bodega (`Existencia`); `Producto.stock` es siempre la suma de todas las bodegas (`core/bodegas.py`).
  - La bodega **Principal** recibe compras y producción; la marcada **En línea** abastece el marketplace; cada caja POS vende desde la bodega elegida al abrir el turno. Anulaciones y reservas vencidas devuelven a la bodega de origen.
  - Traslados entre bodegas desde el kardex. Más de una bodega requiere un plan con «Gestión multisede» (Pro).
- **Planes de Intersoft (`/panel/suscripcion/`)**:
  - Los planes pagos se cobran con la cuenta de Wompi de Intersoft (`SUSCRIPCIONES_WOMPI_*`) y solo se activan cuando Wompi confirma el pago; renovar suma los días al vencimiento actual.
- **Pasarela de pagos Wompi y simulador local**:
  - Cada negocio conecta sus propias llaves cifradas en **Panel → Negocio → Pagos**, con tarifas, verificación y auditoría. [Configuración y transición](docs/PAGOS-POR-NEGOCIO.md).
  - Firma de integridad SHA-256, webhook con verificación `hmac.compare_digest`, idempotencia en pagos y alertas `CRITICAL` a `ADMINS` ante discrepancias de monto/moneda o reembolsos requeridos.
- **Protección de datos personales — Ley 1581 de 2012 (`intersoft/datos_personales/`)**:
  - Autorización previa, expresa e informada en el registro (casillas sin marcar) con prueba guardada: versión de la política, finalidades, fecha, IP y navegador.
  - Si cambia la política (`VERSION_POLITICA`), se vuelve a pedir la autorización al ingresar.
  - Política completa en `/privacidad/` (Decreto 1377, art. 13) y avisos de privacidad en registro, pago y PQRS.
  - «Mis datos personales» (`/mis-datos/`): descarga de todos los datos en JSON, historial de autorizaciones y solicitudes con radicado y plazos legales en días hábiles (consultas 10, reclamos 15).
  - Consola `/plataforma/datos-personales/`: responder, rechazar o suprimir; la supresión anonimiza al titular y conserva las facturas por obligación legal.
  - Lo que debe hacer la empresa (RNBD, oficial de datos, contratos, revisión legal): [docs/calidad/ley-1581-cumplimiento.md](docs/calidad/ley-1581-cumplimiento.md).
- **Validación de datos de entrada** (`intersoft/core/validadores.py`, aplicada en los modelos):
  - Nombres y apellidos de personas: obligatorios (not null y not blank, también en la base de datos) y solo letras y espacios.
  - Nombre de negocio y de producto con al menos una letra o número; NIT, código de producto y dirección con formato válido; correo con máximo 64 caracteres antes de la @.
  - Contraseñas: además de las reglas de Django, rechaza las comunes en español, los caracteres repetidos y las secuencias.
  - Límite de largo en todos los textos libres (por ejemplo, 5.000 caracteres en la descripción del producto) para que pegar un texto gigante no congele el navegador.
- **Consola de plataforma (`/plataforma/`)**: negocios, planes y cobros, PQRS, datos personales, comentarios, ideas, errores, operación y auditoría, con roles internos y verificación en dos pasos (TOTP).
- **Seguridad y operación**:
  - Configuración por variables de entorno con `python-decouple`.
  - Protección contra fuerza bruta en inicio de sesión con `django-axes` (bloqueo por combinación correo + IP tras 5 intentos fallidos durante 15 minutos).
  - Registro rotativo en archivo (`logs/intersoft.log`) y envío de alertas críticas por correo (`SMTP` en producción o consola en desarrollo).

---

## Requisitos

- **Python** 3.14 (versión estándar en `Dockerfile` y `.github/workflows/pruebas.yml`)
- **PostgreSQL** 16+
- Dependencias listadas en `requirements.txt` (entre otras `Django`, `psycopg2-binary`, `Pillow`, `python-decouple`, `django-axes`)

---

## Instalación y puesta en marcha local

1. **Crear y activar entorno virtual (opcional pero recomendado):**

   ```bash
   python -m venv .venv
   # En Windows (PowerShell):
   .\.venv\Scripts\Activate.ps1
   # En Linux / macOS:
   source .venv/bin/activate
   ```

2. **Instalar dependencias desde la raíz del repositorio:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar variables de entorno:**

   Copia `intersoft/.env.example` como `intersoft/.env` y ajusta las credenciales de tu base de datos PostgreSQL y una clave secreta:

   ```bash
   cp intersoft/.env.example intersoft/.env
   ```

   Para desarrollo local asegúrate de definir en `intersoft/.env`:
   - `DJANGO_SECRET_KEY` (clave aleatoria de 50+ caracteres)
   - `DEBUG=True`
   - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`

   Antes de producción define también los datos del responsable de los datos personales (`DATOS_RESPONSABLE_RAZON_SOCIAL`, `DATOS_RESPONSABLE_NIT`, `DATOS_RESPONSABLE_DIRECCION`, `DATOS_RESPONSABLE_CORREO`, `DATOS_RESPONSABLE_TELEFONO`). Mientras falten, la política de `/privacidad/` los muestra en rojo.

4. **Ejecutar migraciones y sincronizar catálogo de permisos:**

   ```bash
   python intersoft/manage.py migrate
   python intersoft/manage.py sincronizar_permisos
   ```

   Corre `migrate` cada vez que bajes cambios del repositorio. La migración `core.0034_nombres_obligatorios` completa con «Pendiente» los nombres o apellidos vacíos de usuarios existentes, antes de exigirlos en la base de datos; esas personas deben corregirlos en «Mi perfil».

5. **Iniciar el servidor de desarrollo:**

   ```bash
   python intersoft/manage.py runserver
   ```

---

## Verificación y pruebas automatizadas

Desde la raíz del repositorio:

```bash
# 1. Revisión de configuración de Django
python intersoft/manage.py check

# 2. Verificar que no falten migraciones por generar
python intersoft/manage.py makemigrations --check --dry-run

# 3. Revisión de estilo con las reglas de intersoft/ruff.toml (debe decir «All checks passed!»)
pip install ruff   # una sola vez; no está en requirements.txt porque no se usa en producción
cd intersoft && ruff check . && cd ..

# 4. Ejecutar la suite completa de pruebas (706 pruebas, todas las aplicaciones)
python intersoft/manage.py test --noinput
```

Pruebas de caja negra por técnica (partición de equivalencia, valores límite, flujos positivo y negativo) de los casos de uso registrar usuario, iniciar sesión, registrar empresa y registrar producto:

```bash
python intersoft/manage.py test core.tests_caja_negra --noinput
```

Informes de calidad en [`docs/calidad/`](docs/calidad/):

| Documento | Contenido |
|---|---|
| [2026-11-26-pruebas-caja-negra-tecnicas.md](docs/calidad/2026-11-26-pruebas-caja-negra-tecnicas.md) | 169 casos de caja negra por técnica y 2 defectos corregidos |
| [2026-11-24-informe-pruebas-caja-negra-y-blanca.md](docs/calidad/2026-11-24-informe-pruebas-caja-negra-y-blanca.md) | Pruebas de caja negra y blanca de principio a fin |
| [ISO-25010-calidad-del-codigo.md](docs/calidad/ISO-25010-calidad-del-codigo.md) | Las 8 características de ISO/IEC 25010 y las normas de código del equipo |
| [ley-1581-cumplimiento.md](docs/calidad/ley-1581-cumplimiento.md) | Cumplimiento de la Ley 1581: lo que hace el software y lo que hace la empresa |

Las correcciones al informe de validación de datos de entrada de los evaluadores (25 de noviembre de 2026, casos CP-02, 04, 08, 09, 12, 13, 14 y 15) tienen su prueba de regresión en `intersoft/core/tests_validacion_entradas.py`.

---

## Operación y despliegue en producción (`DEBUG=False`)

### 1. Variables de entorno obligatorias en producción

En `intersoft/.env` (o variables del sistema):

- `DEBUG=False`
- `DJANGO_SECRET_KEY`: cadena aleatoria de al menos 50 caracteres.
- `ALLOWED_HOSTS`: dominios separados por coma (ej. `tienda.tudominio.co,www.tienda.tudominio.co`).
- `CSRF_TRUSTED_ORIGINS`: orígenes con `https://` separados por coma (ej. `https://tienda.tudominio.co`).
- **Correo SMTP** (para alertas críticas de pagos/reembolsos a `ADMINS`):
  - `ADMINS=finanzas@tudominio.co,operaciones@tudominio.co`
  - `EMAIL_HOST`, `EMAIL_PORT` (por defecto `587`), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS=True`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`.
  - Si `EMAIL_HOST` se deja vacío, Django usa `console.EmailBackend` como respaldo.

Verifica la configuración antes de exponer el servidor con:

```bash
python intersoft/manage.py check --deploy
```

### 2. Archivos estáticos (`STATIC_ROOT`) y multimedia (`MEDIA_ROOT`)

Cuando `DEBUG=False`, Django **no** sirve archivos estáticos ni las fotos subidas por los negocios (`MEDIA_ROOT`):

1. Recolecta los archivos estáticos en `intersoft/staticfiles/`:
   ```bash
   python intersoft/manage.py collectstatic --noinput
   ```
2. En tu proxy inverso (por ejemplo **Nginx** o **Caddy**) o servicio de almacenamiento:
   - Sirve `/static/` apuntando a `<ruta-repo>/intersoft/staticfiles/`.
   - Sirve `/media/` apuntando a `<ruta-repo>/intersoft/media/` con cabeceras `X-Content-Type-Options: nosniff` y sin ejecución de scripts.

### 3. Tareas periódicas (`tareas_periodicas`)

Un solo comando ejecuta todas las tareas automáticas, cada una con su propio intervalo:

| Tarea | Cada | Qué hace |
|---|---|---|
| `liberar_reservas` | 5 min | Vence pedidos sin pagar (`PEDIDO_MINUTOS_RESERVA`) y devuelve su stock |
| `conciliar_cobros_suscripcion` | 15 min | Consulta en Wompi los cobros de planes pendientes y anula los abandonados (48 h) |
| `verificar_suscripciones` | 1 h | Pasa a Gratis las suscripciones y pruebas vencidas |
| `alertas_stock` | 1 día | Envía las alertas de stock mínimo |

Cada tarea guarda en la base cuándo corrió (`EjecucionTarea`, visible en `/admin/`): un reinicio no la repite antes de tiempo y dos programadores a la vez no la ejecutan dos veces. Tres fallos seguidos generan una alerta `CRITICAL` a `ADMINS`.

- **Docker:** el contenedor `scheduler` ya ejecuta `tareas_periodicas --bucle`.
- **Linux (cron, cada 5 minutos):**
  ```cron
  */5 * * * * cd /ruta/a/intersoft_daniel && /ruta/a/venv/bin/python intersoft/manage.py tareas_periodicas >> /ruta/a/intersoft_daniel/intersoft/logs/tareas.log 2>&1
  ```
- **Windows (Programador de tareas, cada 5 minutos):**
  ```powershell
  $accion = New-ScheduledTaskAction -Execute "C:\ruta\a\intersoft_daniel\env\Scripts\python.exe" `
    -Argument "intersoft\manage.py tareas_periodicas" `
    -WorkingDirectory "C:\ruta\a\intersoft_daniel"
  $disparador = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
  Register-ScheduledTask -TaskName "IntersoftTareasPeriodicas" `
    -Action $accion -Trigger $disparador -Description "Tareas periódicas de Intersoft"
  ```

Opciones: `--forzar` ejecuta aunque no les toque, `--solo alertas_stock liberar_reservas` limita la pasada.

### 4. Despliegue reproducible con Docker Compose (`compose.dev.yml` y `compose.prod.yml`)

El repositorio usa **Python 3.14** (`Dockerfile` y `.github/workflows/pruebas.yml`) y separa claramente desarrollo y producción sin secretos por defecto (`DJANGO_SECRET_KEY` y `DB_PASSWORD` son obligatorios en `intersoft/.env`):

- **Desarrollo (`compose.dev.yml`):** levanta `db`, `web` (`DEBUG=True`, `PASARELA_SIMULADA=True`, puerto `8000`, sin Nginx) y `scheduler`:
  ```bash
  docker compose -f compose.dev.yml --env-file intersoft/.env up -d --build
  ```
- **Producción (`compose.prod.yml`):** levanta **PostgreSQL 16 + Redis 7 + Gunicorn + Scheduler (`tareas_periodicas`) + Nginx** (`REDIS_URL` comparte los contadores de *rate limiting* y *throttling* entre workers):
  1. Crea `intersoft/.env` a partir de `intersoft/.env.example` con `DEBUG=False`, `DJANGO_SECRET_KEY`, `DB_PASSWORD`, `EMAIL_HOST`, `PAGOS_CLAVES_CIFRADO`, `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`.
  2. Levanta los servicios desde la raíz del proyecto:
     ```bash
     docker compose -f compose.prod.yml --env-file intersoft/.env up -d --build
     ```
     Solo el contenedor `web` ejecuta `migrate --noinput`, `sincronizar_permisos`, `collectstatic --noinput` e inicia `gunicorn`. El contenedor `scheduler` ejecuta únicamente `tareas_periodicas --bucle`.
- **Healthcheck HTTP (`/salud/`):** responde `200 OK` si PostgreSQL responde (`503` en caso contrario) y es usado por el `healthcheck` de Docker Compose.
- **Documentación OpenAPI / Swagger (`/api/docs/` y `/api/schema/`):** en desarrollo (`DEBUG=True`) es pública; en producción (`DEBUG=False`) queda restringida a usuarios `is_staff` mediante `SERVE_PERMISSIONS`.
- **Verificación de despliegue (`python intersoft/manage.py check --deploy`):** con variables de producción (`DEBUG=False`, `ALLOWED_HOSTS`, `DJANGO_SECRET_KEY`, `EMAIL_HOST`) pasa con **0 errores**. Las advertencias esperadas si no se definen explícitamente son:
  - `core.W001`: definir `PAGOS_CLAVES_CIFRADO` con una clave Fernet dedicada en producción.
  - `security.W005` y `security.W021`: `SECURE_HSTS_INCLUDE_SUBDOMAINS` y `SECURE_HSTS_PRELOAD` (opcionales según la política de subdominios y preload HSTS del dominio).

### 5. Copias de seguridad de PostgreSQL 16 y verificación de webhook Wompi

- **Respaldo comprimido (`pg_dump`):**
  ```bash
  pg_dump -Fc -h localhost -U postgres -d intersoft -f backup_intersoft_$(date +%F).dump
  ```
- **Restauración (`pg_restore`):**
  ```bash
  pg_restore -h localhost -U postgres -d intersoft --clean --if-exists backup_intersoft_YYYY-MM-DD.dump
  ```
- **Webhook de Wompi en producción:**
  - Cada negocio configura la URL pública `https://<tu-dominio>/webhooks/wompi/<uuid-del-negocio>/` y sus propios secretos desde el panel.
  - La vista `WompiWebhookNegocioView` valida firma, negocio y transacción, y aplica el resultado de forma idempotente. La URL antigua queda solo para conciliar intentos históricos.
- **Monitoreo opcional de errores (Sentry):**
  - Si defines `SENTRY_DSN` en `intersoft/.env` e instalas `sentry-sdk`, `settings.py` lo inicializa automáticamente con `send_default_pii=False`.

---

## Estructura principal del proyecto

- `requirements.txt` — Dependencias del proyecto.
- `intersoft/manage.py` — Utilidad de administración de Django.
- `intersoft/intersoft/settings.py` — Configuración central por variables de entorno.
- `intersoft/core/` — Aplicación principal:
  - `models/` — Modelos multi-tenant (`empresas`, `usuarios`, `clientes`, `inventario`, `ventas`, `caja`, `pagos`, `pedidos`, `erp`).
  - `permisos.py`, `forms_equipo.py`, `views_equipo.py` — Catálogo RBAC, plantillas de roles y gestión de equipo.
  - `caja.py`, `views_pos.py` — Punto de venta (POS), turnos de caja y recibos.
  - `compras.py`, `reservas.py`, `pagos.py`, `views_tienda.py`, `views_compra.py` — Marketplace, reservas y pasarela Wompi.
  - `erp_services.py`, `erp_forms.py`, `views_erp.py` — Módulos ERP (compras, cartera, tesorería, contabilidad, nómina, producción y agenda).
  - `validadores.py` — Reglas de datos de entrada compartidas (nombres, NIT, código, dirección, correo y contraseñas).
- `intersoft/suscripciones/` — Planes de Intersoft, cobros con Wompi y API REST.
- `intersoft/plataforma/` — Consola interna del equipo de Intersoft con roles, 2FA y bitácora de auditoría.
- `intersoft/pqrs/` — Sistema de Peticiones, Quejas, Reclamos y Sugerencias (flujo A: negocio → Intersoft; flujo B: comprador → negocio con escalamiento automático).
- `intersoft/soporte/` — Reporte de problemas, comentarios, encuesta NPS, ideas y registro de errores.
- `intersoft/datos_personales/` — Protección de datos personales (Ley 1581): autorizaciones, solicitudes del titular y supresión.
- `docs/calidad/` — Informes de pruebas y de calidad.

---

## Nota legal sobre plazos de PQRS

El plazo de respuesta configurado en `PQRS_DIAS_RESPUESTA` (por defecto **15 días hábiles** en `intersoft/intersoft/settings.py`) y el calendario de festivos de Colombia en `intersoft/pqrs/dias_habiles.py` **deben validarse con un abogado** antes de operar en producción para confirmar su adecuación a la normativa colombiana vigente (Ley 1755 de 2015, Ley 1480 de 2011 / Estatuto del Consumidor y regulaciones aplicables según el tipo de solicitud).

