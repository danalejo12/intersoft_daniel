# Especificación de Requisitos de Software (SRS — Estándar IEEE 830)
## Proyecto: InterSoft (ERP + POS + Marketplace Multi-tenant + Suscripciones)

---

## 1. Introducción

### 1.1 Propósito
Definir los requisitos funcionales, no funcionales, reglas de negocio y restricciones técnicas de la plataforma **InterSoft**, desarrollada bajo la metodología del programa **ADSO (Análisis y Desarrollo de Software) — SENA**.

### 1.2 Alcance del Sistema
**InterSoft** es una aplicación web SaaS multiempresa (B2B2C) que integra en un solo ecosistema:
- **Módulo Multi-tenant y RBAC**: Gestión de empresas, roles personalizados y membresías por usuario.
- **Gestión de Inventario y Catálogo**: Categorías, productos, imágenes, alertas de stock mínimo y kardex atómico.
- **Punto de Venta (POS)**: Apertura y cierre de turnos de caja (arqueo a ciegas), múltiples medios de pago, idempotencia y tickets.
- **ERP Administrativo y Fiscal**: Compras, proveedores, cartera (CxC/CxP), tesorería, contabilidad PUC en partida doble, nómina colombiana, producción, agenda de servicios y facturación electrónica DIAN (`CUFE` / `CUDE`).
- **Marketplace Público y Pagos**: Catálogo público, carrito, reserva temporal de stock, pasarela Wompi con firma SHA-256 y webhooks idempotentes.
- **Suscripciones SaaS (API DRF + Panel)**: Planes (`Gratis`, `Emprendedor`, `Negocio`, `Pro`), periodo de prueba (`TRIAL` 14 días), límites por plan, comisiones diferenciadas y beneficio de fundador.

---

## 2. Descripción General y Actores

| Actor / Rol | Responsabilidad Principal |
| :--- | :--- |
| **Administrador** | Control total de la empresa, perfil del negocio, equipo/roles, suscripción SaaS, pagos Wompi y reportes. |
| **Cajero POS** | Apertura de caja, ventas de mostrador, cobros combinados, tickets y cierre con arqueo a ciegas. |
| **Asesor Comercial** | Gestión de clientes, facturación directa, cobros en línea, agenda de citas y emisión DIAN. |
| **Bodega e Inventario** | Catálogo de productos/categorías, kardex, recepción de compras, órdenes de producción y despacho de pedidos web. |
| **Contador** | Cartera, tesorería, asientos contables PUC (manuales o en 1 clic), nómina y reportes financieros. |
| **Empleado** | Consulta en solo lectura de productos, clientes y agenda asignada. |
| **Comprador Web** | Exploración del Marketplace, carrito, checkout con reserva de stock, seguimiento de pedidos y reseñas. |

---

## 3. Requisitos Funcionales (RF)

| Código | Módulo | Requisito Funcional | Prioridad |
| :--- | :--- | :--- | :--- |
| **RF-01** | Autenticación | El sistema debe permitir registro, inicio de sesión por correo electrónico y recuperación de contraseña por enlace seguro. | Alta |
| **RF-02** | Multi-tenant | Cada usuario puede pertenecer a una o más empresas mediante membresías y cambiar su empresa activa en sesión sin acceder a datos de terceros. | Alta |
| **RF-03** | RBAC y Equipo | El administrador debe poder crear roles con permisos granulares por módulo y vincular/desactivar miembros del equipo (impidiendo quitar al último administrador). | Alta |
| **RF-04** | Perfiles | Todo usuario debe poder consultar y editar su perfil (foto, nombres, cargo, teléfono, descripción); el administrador debe poder gestionar el perfil público del negocio (logo, descripción, sitio web, dirección y teléfono). | Media |
| **RF-05** | Inventario | El sistema debe permitir CRUD de categorías y productos (con borrado lógico) y registrar entradas, salidas y ajustes en kardex garantizando que el stock nunca sea negativo. | Alta |
| **RF-06** | POS | El cajero debe poder abrir turno con base inicial, vender múltiples productos con efectivo/tarjeta/transferencia, imprimir ticket y cerrar turno con arqueo a ciegas y traslado a tesorería. | Alta |
| **RF-07** | Facturación y DIAN | El sistema debe emitir facturas con consecutivo único por empresa, generar `CUFE` mediante adaptador DIAN, y al anular revertir stock, asiento contable (`ANUL-FACT-n`) y emitir Nota Crédito (`CUDE`). | Alta |
| **RF-08** | ERP y Contabilidad | El sistema debe gestionar compras, cartera, tesorería, nómina con aportes de ley colombiana (4% salud + 4% pensión trabajador; aportes empleador y parafiscales) y asientos contables PUC en partida doble. | Alta |
| **RF-09** | Marketplace y Wompi | Los compradores deben poder buscar productos, reservar stock por 30 minutos al confirmar pedido y pagar por Wompi validando checksum HMAC, monto y moneda exactos. | Alta |
| **RF-10** | Suscripciones SaaS | Toda empresa nueva debe iniciar en `TRIAL` del plan `Negocio` por 14 días; debe poder consultar planes (`GET /api/planes/`), ver su uso frente a límites (`GET /api/suscripcion/`) y cambiar de plan validando downgrades y beneficio fundador. | Alta |

---

## 4. Requisitos No Funcionales (RNF)

| Código | Categoría | Requisito No Funcional | Criterio de Verificación |
| :--- | :--- | :--- | :--- |
| **RNF-01** | Seguridad (Fuerza bruta) | Bloqueo temporal tras 5 intentos fallidos de login por combinación correo + IP durante 15 minutos (`django-axes`), insensible a mayúsculas. | Pruebas `LimiteDeIntentosTests` (HTTP `429`). |
| **RNF-02** | Seguridad (Multi-tenant) | Aislamiento estricto por `empresa_id` mediante `TenantMiddleware` y `TenantMixin`, devolviendo `404`/`403` ante intentos de acceso cruzado. | Pruebas en `tests.py`, `tests_pos.py`, `suscripciones/tests.py`. |
| **RNF-03** | Concurrencia e Integridad | Operaciones críticas de stock, consecutivos, pagos y cambio de plan deben usar `@transaction.atomic` y bloqueo de fila `select_for_update()`. | Pruebas `ConcurrenciaPosTests` y `ConcurrenciaPedidosTests`. |
| **RNF-04** | Exactitud Financiera | Todos los cálculos monetarios deben emplear `Decimal` (`DecimalField`) con redondeo `ROUND_HALF_UP` a 2 decimales, prohibiendo `float`. | Pruebas en `tests_erp.py` y `suscripciones/tests.py`. |
| **RNF-05** | Disponibilidad y Cron | Procesos periódicos (`verificar_suscripciones`, `procesar_reservas_y_alertas`) deben ser idempotentes para ejecutarse de forma segura en cron. | Pruebas de doble ejecución en `tests_pedidos.py` y `suscripciones/tests.py`. |
| **RNF-06** | Documentación API | Los endpoints REST deben exponerse bajo estándar OpenAPI 3.0 con interfaz Swagger UI (`/api/docs/`). | Pruebas `test_documentacion_openapi_y_swagger_disponibles`. |
