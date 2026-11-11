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

- **Facturación electrónica DIAN desacoplada (`core/facturacion_electronica.py`)**: interfaz de proveedor (`ProveedorFacturacionElectronica`), simulador determinístico con cálculo de CUFE SHA-384 (`ProveedorSimuladoDian`) y servicio transaccional idempotente (`emitir_factura_electronica`) integrable con proveedores tecnológicos autorizados.
- **Automatización contable y calculadora de aportes (`core/contabilidad_automatica.py`)**: creación idempotente de cuentas base PUC (`asegurar_cuentas_puc`), generación de asientos confirmados para facturas (`contabilizar_factura`), compras recibidas (`contabilizar_compra`), movimientos de tesorería (`contabilizar_movimiento_tesoreria`) y nóminas aprobadas (`contabilizar_nomina`), además de calculadora de aportes de seguridad social y parafiscales en Colombia (`calcular_aportes_nomina_colombia`).
- **Liquidación y dispersión de pagos en el marketplace**: control de estado de dispersión al comercio (`estado_dispersion`, `dispersion_referencia` y `dispersado_en` en `Pedido`) mediante `registrar_dispersion_pedido`.
