# Manual Técnico y de Usuario — InterSoft
## Proyecto ADSO — SENA

---

## Parte 1: Manual Técnico (Para Desarrolladores y Despliegue)

### 1. Stack Tecnológico y Requisitos
- **Lenguaje / Framework**: Python 3.12+ / Django 6.1.2 / Django REST Framework 3.18.3 / `drf-spectacular` 0.30.0
- **Base de datos**: PostgreSQL 16+
- **Seguridad y cifrado**: `django-axes` 9.0.0, `cryptography` 50.0.2 (Fernet), `python-decouple` 3.8
- **Zona horaria y moneda**: `America/Bogota` (`USE_TZ=True`), `DecimalField` en COP

### 2. Estructura Principal del Proyecto
- `intersoft/intersoft/`: Configuración central (`settings.py`, `urls.py`, `wsgi.py`, `asgi.py`).
- `intersoft/core/`: Núcleo multi-tenant (`Empresa`, `Usuario`, `Rol`, `Permiso`, `Membresia`), Inventario, POS, Facturación, DIAN, ERP, Marketplace y Pagos Wompi.
- `intersoft/suscripciones/`: Planes SaaS, límites JSON, features, periodos de prueba, comisiones, descuento fundador, API DRF (`/api/docs/`) y vista `/panel/suscripcion/`.
- `docs/diagramas/`: Documentación visual UML, MER, Casos de Uso y Diagramas de Secuencia en `.md`, `.pdf` y `.docx`.

### 3. Variables de Entorno Clave (`.env`)
| Variable | Descripción |
| :--- | :--- |
| `DJANGO_SECRET_KEY` | Llave secreta obligatoria de Django. |
| `DEBUG` | `False` en producción, `True` solo en desarrollo local. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Conexión a PostgreSQL. |
| `PAGOS_CLAVES_CIFRADO` | Llave Fernet para cifrar credenciales de pasarela por negocio. |
| `WOMPI_PUBLIC_KEY`, `WOMPI_INTEGRITY_SECRET`, `WOMPI_EVENTS_SECRET` | Credenciales base de Wompi (o `PASARELA_SIMULADA=True` en local). |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Servidor SMTP para recuperación de contraseña y alertas `ADMINS`. |

### 4. Comandos de Operación y Mantenimiento
```bash
# Aplicar migraciones (incluye catálogo de permisos y 4 planes iniciales)
python manage.py migrate

# Sincronizar catálogo de permisos y roles base
python manage.py sincronizar_permisos

# Cron cada 5 min: liberar reservas web vencidas y alertar stock mínimo
python manage.py procesar_reservas_y_alertas

# Cron diario: vencer Trials y suscripciones expiradas pasando a plan Gratis
python manage.py verificar_suscripciones
```

---

## Parte 2: Manual de Usuario por Roles

### 1. Acceso y Perfil Personal
1. Ingresa en `/login/` con tu **correo electrónico** y **contraseña**. Si olvidaste tu clave, usa **`¿Olvidaste tu contraseña?`**.
2. En la esquina superior derecha (o en **Mi cuenta → Mi perfil** del Marketplace) puedes abrir `/perfil/` para ver tu rol, empresa y actualizar tu foto, nombre, cargo, teléfono y descripción.

### 2. Guía Operativa por Rol
| Rol | Módulos Disponibles | Acciones Principales |
| :--- | :--- | :--- |
| **Administrador** | Todo el panel | Configura **Perfil del negocio** (`/panel/negocio/`), **Plan y suscripción** (`/panel/suscripcion/`), **Equipo y roles** (`/panel/equipo/`) y **Pagos en línea**. |
| **Cajero POS** | POS, Clientes, Productos | Abre caja en `/panel/pos/`, escanea o busca productos, cobra en efectivo/tarjeta/transferencia, imprime ticket y cierra arqueo a ciegas. |
| **Asesor Comercial** | Clientes, Facturas, Agenda | Crea clientes y facturas, genera links de cobro Wompi, emite factura electrónica DIAN y gestiona citas de servicios. |
| **Bodega e Inventario** | Productos, Categorías, Compras, Producción, Pedidos Web | Administra catálogo y kardex, recibe compras de proveedores, ejecuta órdenes de producción y registra guías de despacho en `/panel/pedidos/`. |
| **Contador** | Cartera, Tesorería, Contabilidad PUC, Nómina, Reportes | Lleva facturas a cartera, registra recaudos, genera comprobantes contables en 1 clic, liquida nómina con aportes de ley y traslada cierres POS. |
| **Empleado** | Catálogo, Clientes, Agenda | Consulta disponibilidad de inventario, directorio y citas en modo lectura. |
| **Comprador Web** | Marketplace (`/`) | Busca productos, agrega al carrito, confirma envío (reserva 30 min), paga en Wompi y rastrea su guía en `/pedidos/`. |
