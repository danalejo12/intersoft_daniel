# Estado del desarrollo ERP

## Implementado en esta rama

- Punto de venta: apertura y cierre de caja, pagos mixtos, control de inventario y recibo con diseño para papel de 80 mm.
- Análisis técnico del POS en `auditoria/2026-11-10-analisis-pos-recibo.md`.

## En desarrollo

Se agregaron modelos, migración y código inicial de servicios, formularios y vistas para proveedores, compras, cartera, tesorería, contabilidad, empleados, nómina manual, producción y agenda de servicios.

Estos módulos nuevos **todavía no están terminados ni disponibles en la navegación**. Faltan plantillas, rutas, integración con ventas y pagos, revisión de las transiciones y pruebas específicas. La migración permite reconstruir el esquema de esta versión del código, pero no implica que los módulos estén listos para operar.

La nómina propuesta usa importes ingresados manualmente. No implementa liquidación legal automática. La contabilidad inicial contempla comprobantes manuales y no contabilización automática de todas las operaciones. No se incluye integración de facturación electrónica.

## Próximos pasos

1. Completar pantallas y navegación de los módulos.
2. Integrar cartera con los cobros actuales para evitar cobrar dos veces una factura.
3. Revisar validación de cantidades, límites monetarios y reintentos del POS.
4. Probar los nuevos flujos, permisos, aislamiento por empresa y concurrencia.
5. Validar los procesos de tiendas, peluquerías, supermercados y comercios con datos de ejemplo.

La publicación de esta rama es un respaldo del trabajo en curso, no una entrega de un ERP completo.
