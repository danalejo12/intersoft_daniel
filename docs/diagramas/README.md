# Diagramas de Arquitectura y Diseño — InterSoft

Documentación visual de la arquitectura multi-tenant, base de datos PostgreSQL, casos de uso y flujos de secuencia de **InterSoft**.

## Estructura de carpetas

- **[UML — Diagrama de Clases](uml/diagrama-clases.md)**: Modelos de dominio, herencia (`ModeloBase` / `ModeloTenant`), RBAC, suscripciones, inventario, POS, Marketplace, cupones de tienda (`CuponTienda`) y carrito persistente (`ItemCarrito`).
- **[MER — Modelo Entidad-Relación](mer/modelo-entidad-relacion.md)**: Tablas de PostgreSQL, llaves primarias (`PK`), llaves foráneas (`FK`) y cardinalidades (incluyendo `CORE_CUPONTIENDA`, `CORE_ITEMCARRITO` y tablas de Ley 1581).
- **[Casos de Uso](casos-de-uso/casos-de-uso.md)**: Actores por rol, casos de uso por subsistema (`CU-01` a `CU-25`) y flujos principales/excepcionales.
- **[Diagramas de Secuencia](secuencia/diagramas-secuencia.md)**:
  1. Compra en Marketplace, reserva de stock y webhook Wompi
  2. Cambio de plan de suscripción y validación multi-tenant
  3. Punto de Venta (POS), idempotencia y traslado a Tesorería
  4. Facturación electrónica DIAN (`CUFE`), contabilidad PUC y anulación con Nota Crédito (`CUDE`)
  5. Compra unificada en varios negocios (`Orden` + `Pedido`)
  6. Pago de un plan con Wompi (retorno, webhook y conciliación)
  7. Traslado entre bodegas
  8. Venta POS desde una bodega
  9. Tareas periódicas (`core/tareas.py` + `EjecucionTarea`)
  10. Carrito multi-dispositivo, cupón de tienda y rastreo de envío
