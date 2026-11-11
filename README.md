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
- **Pasarela de pagos Wompi y simulador local**:
  - Firma de integridad SHA-256, webhook con verificación `hmac.compare_digest`, idempotencia en pagos y alertas `CRITICAL` a `ADMINS` ante discrepancias de monto/moneda o reembolsos requeridos.
- **Seguridad y operación**:
  - Configuración por variables de entorno con `python-decouple`.
  - Protección contra fuerza bruta en inicio de sesión con `django-axes` (bloqueo por combinación correo + IP tras 5 intentos fallidos durante 15 minutos).
  - Registro rotativo en archivo (`logs/intersoft.log`) y envío de alertas críticas por correo (`SMTP` en producción o consola en desarrollo).

---

## Requisitos

- **Python** 3.12+ (compatible con Python 3.14)
- **PostgreSQL** 16+
- Dependencias listadas en `requirements.txt` (`Django`, `psycopg2-binary`, `Pillow`, `python-decouple`, `django-axes`)

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

4. **Ejecutar migraciones y sincronizar catálogo de permisos:**

   ```bash
   python intersoft/manage.py migrate
   python intersoft/manage.py sincronizar_permisos
   ```

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

# 3. Ejecutar la suite completa de pruebas
python intersoft/manage.py test core --noinput
```

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

### 3. Tarea programada: liberación de pedidos vencidos

Los pedidos del marketplace reservan stock por `PEDIDO_MINUTOS_RESERVA` minutos (por defecto 30). El comando `liberar_pedidos_vencidos` es idempotente y devuelve el stock de los pedidos cuyo plazo expiró sin pago confirmado.

- **En Linux (cron, cada 5 minutos):**
  ```cron
  */5 * * * * cd /ruta/a/intersoft_daniel-main && /ruta/a/venv/bin/python intersoft/manage.py liberar_pedidos_vencidos >> /ruta/a/intersoft_daniel-main/intersoft/logs/cron_reservas.log 2>&1
  ```

- **En Windows (Programador de tareas / PowerShell, cada 5 minutos):**
  ```powershell
  $accion = New-ScheduledTaskAction -Execute "C:\Python314\python.exe" `
    -Argument "intersoft\manage.py liberar_pedidos_vencidos" `
    -WorkingDirectory "C:\intersoft_daniel-main"
  $disparador = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
  Register-ScheduledTask -TaskName "IntersoftLiberarPedidos" `
    -Action $accion -Trigger $disparador -Description "Libera stock de pedidos vencidos cada 5 minutos"
  ```

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
