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

---

### 3. Nuevas Funcionalidades Operativas (Bodegas, Comprar todo, Pagar un plan y Más vendidos)

#### A. Bodegas o sedes (`/panel/bodegas/`)
1. Cada negocio cuenta automáticamente con una bodega **Principal** (donde ingresan compras y producción) y una marcada **En línea** (que abastece el Marketplace). Ambas pueden ser la misma sede o sedes distintas.
2. En **Panel → Bodegas** puedes crear nuevas sedes (disponible en planes con funcionalidad `multisede`), editar sus datos o desactivar sedes secundarias sin existencias.
3. Para mover mercancía entre sedes, ingresa a **Productos → Kardex / Trasladar** (`/panel/productos/<id>/trasladar/`), selecciona bodega origen, bodega destino y cantidad. El sistema descuenta en origen, suma en destino y conserva el stock total consolidado.
4. Al abrir caja en **Punto de venta** (`/panel/pos/abrir/`), el cajero elige la **bodega** desde la cual descontará las ventas de ese turno.

#### B. Comprar todo en varios negocios (`/comprar/`)
1. Si agregas al carrito productos de **dos o más negocios**, puedes usar el botón **«Comprar todo»** en `/carrito/`.
2. El sistema solicita tus datos de envío **una sola vez** y crea una `Orden` unificada junto con un `Pedido` independiente por cada negocio (reservando el inventario en la bodega en línea de cada comercio).
3. En la pantalla de la orden (`/compras/<id>/`) podrás pagar cada pedido por separado con la cuenta de Wompi del negocio correspondiente.

#### C. Pagar un plan de suscripción (`/panel/suscripcion/`)
1. El Administrador ingresa a **Plan y suscripción** en el menú lateral del panel.
2. Al seleccionar un plan pago (**Emprendedor**, **Negocio** o **Pro**) y ciclo (**Mensual** o **Anual**), el sistema valida límites de uso, aplica el descuento de fundador si corresponde y genera un cobro (`CobroSuscripcion`) redirigiendo al checkout seguro de Wompi.
3. El plan se activa únicamente cuando el servidor confirma el pago en Wompi (por retorno, webhook firmado o conciliación periódica); si renuevas un plan vigente, los días se suman a la fecha de vencimiento actual.

#### D. Orden «Más vendidos» en el Marketplace (`/`)
1. En el catálogo público del Marketplace y en las tiendas por negocio (`/tienda/<slug>/`), puedes ordenar los resultados por **«Más vendidos»**.
2. Este criterio prioriza los productos con mayor número de unidades pagadas en pedidos web durante los últimos **90 días**, facilitando a los compradores descubrir los artículos más populares.
