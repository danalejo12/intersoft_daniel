# Estado del desarrollo ERP

## Implementado y verificado

- **Punto de venta (POS) y facturación**:
  - Apertura y cierre de caja, pagos mixtos, idempotencia por clave de operación (`operacion_pos`), validación estricta de cantidades y límites monetarios (`DecimalField(14, 2)`), control de inventario acumulador por producto y recibo con instantánea inmutable para papel de 80 mm.
  - Análisis técnico del POS en `auditoria/2026-11-10-analisis-pos-recibo.md`.
- **Roles, permisos granulares (RBAC) y gestión de equipo (`/panel/equipo/`)**:
  - Catálogo centralizado de 31 permisos y plantillas de roles por defecto (`core/permisos.py`, comando `sincronizar_permisos` y migración `0014_catalogo_permisos.py`).
  - CRUD de roles y miembros del equipo con reglas anti-bloqueo del último administrador activo y visibilidad dinámica del menú y del dashboard.
- **Operación y selector multi-negocio**:
  - Configuración de correo SMTP por entorno con respaldo en consola (`settings.py` y `.env.example`), `STATIC_ROOT` para producción y selector visual de negocio activo en `/panel/negocio/cambiar/`.
- **Módulos ERP completos (`/panel/erp/`)**:
  - **Financieros y abastecimiento**: `proveedores`, `compras` (con recepción, Kardex y generación de cuenta por pagar), `cartera` (integrada con `Factura`, `Pago` de Wompi y `PagoCaja` de POS para impedir cobros duplicados), `cuentas` (cajas y bancos) y `tesoreria` (ingresos, egresos y abonos idempotentes por clave `operacion`).
  - **Contabilidad**: `plan-contable` y `contabilidad` con validación de línea (débito o crédito exclusivo), partida doble al confirmar y eliminación segura de comprobantes en borrador.
  - **Talento humano y nómina manual**: `empleados` y `nomina` con cálculo automático de neto, validación de períodos solapados por empleado y generación de cuenta por pagar al aprobar.
  - **Producción**: `produccion` con validación de insumos activos, prohibición de auto-insumo, verificación de stock y movimientos de salida/entrada en Kardex.
  - **Servicios y agenda**: `servicios` y `agenda` con cálculo de duración e IVA, bloqueo de cruces de horario por profesional y generación de cuenta por cobrar al marcar la cita como atendida.
  - **Reportes operativos (`/panel/erp/reportes/`)**: saldos pendientes de cartera, saldos por caja/banco y balance de comprobación contable filtrados según los permisos de cada rol.

## Alcance funcional actual

- La nómina opera con importes revisados e ingresados manualmente (base, adicionales y deducciones); no realiza liquidación automática de aportes parafiscales ni seguridad social.
- La contabilidad registra comprobantes de diario con validación de partida doble manual.
- La numeración de facturación es interna por empresa (no incluye envío electrónico a la DIAN).
