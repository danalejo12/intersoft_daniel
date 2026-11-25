# Diccionario de Datos — InterSoft (PostgreSQL)
## Generado directamente desde los modelos ORM de `core` y `suscripciones`

Este documento detalla todas las tablas, columnas, tipos de datos PostgreSQL, restricciones (`PK`, `FK`, `UK`, `NOT NULL`) y descripciones del esquema de base de datos.
> **Resumen del esquema:** **38 tablas** y **452 columnas** activas en PostgreSQL.


---
## Aplicación: `core` (41 tablas)

### Tabla `core_empresa` (`core.Empresa`)
*Empresa(id, creado_en, actualizado_en, nombre, nit, slug, email, telefono, direccion, logo, descripcion, sitio_web, plan, activa, comision_porcentaje, tarifa_envio_base, tarifa_envio_por_kg, envio_gratis_desde)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `nit` | `varchar(20)` | `UK` | NO (`NOT NULL`) | Nit |
| `slug` | `varchar(160)` | `UK` | NO (`NOT NULL`) | Slug |
| `email` | `varchar(254)` | — | NO (`NOT NULL`) | Email |
| `telefono` | `varchar(20)` | — | NO (`NOT NULL`) | Telefono |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Direccion |
| `logo` | `varchar(100)` | — | SÍ (`NULL`) | Logo del negocio |
| `descripcion` | `text` | — | NO (`NOT NULL`) | Descripción del negocio |
| `sitio_web` | `varchar(200)` | — | NO (`NOT NULL`) | Sitio web o red social |
| `plan` | `varchar(20)` | — | NO (`NOT NULL`) | Plan |
| `activa` | `boolean` | — | NO (`NOT NULL`) | Activa |
| `comision_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Comisión plataforma (%) |
| `tarifa_envio_base` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Tarifa base de envío |
| `tarifa_envio_por_kg` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Tarifa de envío por kg |
| `envio_gratis_desde` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Envío gratis desde |

### Tabla `core_usuario` (`core.Usuario`)
*Usuario personalizado: inicia sesión con correo.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `password` | `varchar(128)` | — | NO (`NOT NULL`) | Contraseña |
| `last_login` | `timestamp with time zone` | — | SÍ (`NULL`) | Último inicio de sesión |
| `is_superuser` | `boolean` | — | NO (`NOT NULL`) | Es superusuario |
| `username` | `varchar(150)` | `UK` | NO (`NOT NULL`) | Nombre de usuario |
| `first_name` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `last_name` | `varchar(150)` | — | NO (`NOT NULL`) | Apellidos |
| `is_staff` | `boolean` | — | NO (`NOT NULL`) | Es staff |
| `is_active` | `boolean` | — | NO (`NOT NULL`) | Activo |
| `date_joined` | `timestamp with time zone` | — | NO (`NOT NULL`) | Fecha de alta |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `email` | `varchar(254)` | `UK` | NO (`NOT NULL`) | Correo electrónico |
| `foto` | `varchar(100)` | — | SÍ (`NULL`) | Foto de perfil |
| `telefono` | `varchar(20)` | — | NO (`NOT NULL`) | Teléfono |
| `cargo` | `varchar(80)` | — | NO (`NOT NULL`) | Cargo o especialidad |
| `descripcion` | `text` | — | NO (`NOT NULL`) | Descripción |

### Tabla `core_permiso` (`core.Permiso`)
*Catálogo global de permisos. Convención: "<modulo>.<accion>", ej. "ventas.crear".*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `codigo` | `varchar(60)` | `UK` | NO (`NOT NULL`) | Codigo |
| `descripcion` | `varchar(200)` | — | NO (`NOT NULL`) | Descripcion |

### Tabla `core_rol` (`core.Rol`)
*Cada empresa define sus propios roles a partir del catálogo de permisos.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(60)` | — | NO (`NOT NULL`) | Nombre |
| `descripcion` | `varchar(200)` | — | NO (`NOT NULL`) | Descripcion |
| `es_admin` | `boolean` | — | NO (`NOT NULL`) | Es admin |

### Tabla `core_membresia` (`core.Membresia`)
*Relación usuario-empresa con un rol. Un usuario puede estar en varias empresas*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `usuario_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Usuario |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega de origen o destino del movimiento |

### Tabla `core_bodega` (`core.Bodega`)
*Un lugar donde se guarda mercancía (bodega, sede, local). Restricciones: `uq_bodega_nombre_por_empresa` (`empresa`, `nombre`), `uq_bodega_principal_por_empresa` (`empresa` donde `es_principal=True`), `uq_bodega_en_linea_por_empresa` (`empresa` donde `vende_en_linea=True`) y `ck_bodega_clave_activa`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(80)` | `UK` (con `empresa_id`) | NO (`NOT NULL`) | Nombre de la bodega |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Dirección física |
| `activa` | `boolean` | `CHECK` (`ck_bodega_clave_activa`) | NO (`NOT NULL`) | Activa |
| `es_principal` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Es bodega principal (compras y producción) |
| `vende_en_linea` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Abastece ventas del marketplace |

### Tabla `core_existencia` (`core.Existencia`)
*Unidades de un producto en una bodega (`uq_existencia_bodega_producto`, `ck_existencia_no_negativa`: `cantidad >= 0`). La suma de todas las bodegas es `Producto.stock`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `UK` (con `producto_id`) | NO (`NOT NULL`) | Bodega |
| `producto_id` | `uuid` | `FK` → `core_producto`, `UK` (con `bodega_id`) | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | `CHECK` (`cantidad >= 0`) | NO (`NOT NULL`) | Unidades disponibles en la bodega |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `rol_id` | `uuid` | `FK` → `core_rol`, `INDEX` | NO (`NOT NULL`) | Rol |
| `activa` | `boolean` | — | NO (`NOT NULL`) | Activa |

### Tabla `core_cliente` (`core.Cliente`)
*Cliente(id, creado_en, actualizado_en, empresa, tipo_documento, numero_documento, nombre, email, telefono, direccion, activo)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `tipo_documento` | `varchar(5)` | — | NO (`NOT NULL`) | Tipo documento |
| `numero_documento` | `varchar(20)` | — | NO (`NOT NULL`) | Numero documento |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `email` | `varchar(254)` | — | NO (`NOT NULL`) | Email |
| `telefono` | `varchar(20)` | — | NO (`NOT NULL`) | Telefono |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Direccion |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |

### Tabla `core_categoria` (`core.Categoria`)
*Categoria(id, creado_en, actualizado_en, empresa, nombre, activa)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(80)` | — | NO (`NOT NULL`) | Nombre |
| `activa` | `boolean` | — | NO (`NOT NULL`) | Activa |

### Tabla `core_producto` (`core.Producto`)
*Producto(id, creado_en, actualizado_en, empresa, categoria, codigo, nombre, descripcion, precio, iva_porcentaje, stock, stock_minimo, peso_gramos, activo, publicado, imagen, imagen_credito, imagen_fuente)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `categoria_id` | `uuid` | `FK` → `core_categoria`, `INDEX` | SÍ (`NULL`) | Categoria |
| `codigo` | `varchar(30)` | — | NO (`NOT NULL`) | Codigo |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `descripcion` | `text` | — | NO (`NOT NULL`) | Descripcion |
| `precio` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Precio |
| `iva_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Iva (%) |
| `stock` | `integer` | — | NO (`NOT NULL`) | Stock |
| `stock_minimo` | `integer` | — | NO (`NOT NULL`) | Stock minimo |
| `peso_gramos` | `integer` | — | NO (`NOT NULL`) | Peso (gramos) |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |
| `publicado` | `boolean` | — | NO (`NOT NULL`) | Publicado |
| `imagen` | `varchar(100)` | — | NO (`NOT NULL`) | Imagen |
| `imagen_credito` | `varchar(200)` | — | NO (`NOT NULL`) | Imagen credito |
| `imagen_fuente` | `varchar(200)` | — | NO (`NOT NULL`) | Imagen fuente |

### Tabla `core_fotoproducto` (`core.FotoProducto`)
*Fotos adicionales de un producto para la galería del marketplace.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `imagen` | `varchar(100)` | — | NO (`NOT NULL`) | Imagen |
| `orden` | `smallint` | — | NO (`NOT NULL`) | Orden |

### Tabla `core_movimientoinventario` (`core.MovimientoInventario`)
*Historial inmutable de cada cambio de stock (kardex).*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `tipo` | `varchar(10)` | — | NO (`NOT NULL`) | Tipo |
| `cantidad` | `integer` | — | NO (`NOT NULL`) | Cantidad |
| `referencia` | `varchar(60)` | — | NO (`NOT NULL`) | Referencia |
| `usuario_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Usuario |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega de origen o destino del movimiento |

### Tabla `core_bodega` (`core.Bodega`)
*Un lugar donde se guarda mercancía (bodega, sede, local). Restricciones: `uq_bodega_nombre_por_empresa` (`empresa`, `nombre`), `uq_bodega_principal_por_empresa` (`empresa` donde `es_principal=True`), `uq_bodega_en_linea_por_empresa` (`empresa` donde `vende_en_linea=True`) y `ck_bodega_clave_activa`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(80)` | `UK` (con `empresa_id`) | NO (`NOT NULL`) | Nombre de la bodega |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Dirección física |
| `activa` | `boolean` | `CHECK` (`ck_bodega_clave_activa`) | NO (`NOT NULL`) | Activa |
| `es_principal` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Es bodega principal (compras y producción) |
| `vende_en_linea` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Abastece ventas del marketplace |

### Tabla `core_existencia` (`core.Existencia`)
*Unidades de un producto en una bodega (`uq_existencia_bodega_producto`, `ck_existencia_no_negativa`: `cantidad >= 0`). La suma de todas las bodegas es `Producto.stock`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `UK` (con `producto_id`) | NO (`NOT NULL`) | Bodega |
| `producto_id` | `uuid` | `FK` → `core_producto`, `UK` (con `bodega_id`) | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | `CHECK` (`cantidad >= 0`) | NO (`NOT NULL`) | Unidades disponibles en la bodega |

### Tabla `core_factura` (`core.Factura`)
*Factura(id, creado_en, actualizado_en, empresa, numero, cliente, estado, subtotal, iva, total, observaciones, creada_por, anulada_en, turno, operacion_pos, cliente_nombre, cliente_documento, empresa_nombre, empresa_nit, empresa_direccion, empresa_telefono, estado_dian, cufe, cude_nota_credito, dian_xml_url, dian_pdf_url, dian_respuesta, dian_emitida_en)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `numero` | `integer` | — | NO (`NOT NULL`) | Numero |
| `cliente_id` | `uuid` | `FK` → `core_cliente`, `INDEX` | NO (`NOT NULL`) | Cliente |
| `estado` | `varchar(10)` | — | NO (`NOT NULL`) | Estado |
| `subtotal` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Subtotal |
| `iva` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Iva |
| `total` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Total |
| `observaciones` | `text` | — | NO (`NOT NULL`) | Observaciones |
| `creada_por_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Creada por |
| `anulada_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Anulada en |
| `turno_id` | `uuid` | `FK` → `core_turnocaja`, `INDEX` | SÍ (`NULL`) | Turno |
| `operacion_pos` | `uuid` | — | SÍ (`NULL`) | Operacion pos |
| `cliente_nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Cliente nombre |
| `cliente_documento` | `varchar(30)` | — | NO (`NOT NULL`) | Cliente documento |
| `empresa_nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Empresa nombre |
| `empresa_nit` | `varchar(30)` | — | NO (`NOT NULL`) | Empresa nit |
| `empresa_direccion` | `varchar(250)` | — | NO (`NOT NULL`) | Empresa direccion |
| `empresa_telefono` | `varchar(30)` | — | NO (`NOT NULL`) | Empresa telefono |
| `estado_dian` | `varchar(15)` | — | NO (`NOT NULL`) | Estado dian |
| `cufe` | `varchar(120)` | — | NO (`NOT NULL`) | Cufe |
| `cude_nota_credito` | `varchar(120)` | — | NO (`NOT NULL`) | Cude nota crédito |
| `dian_xml_url` | `varchar(200)` | — | NO (`NOT NULL`) | Dian xml url |
| `dian_pdf_url` | `varchar(200)` | — | NO (`NOT NULL`) | Dian pdf url |
| `dian_respuesta` | `varchar(250)` | — | NO (`NOT NULL`) | Dian respuesta |
| `dian_emitida_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Dian emitida en |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega desde la cual se descuenta el stock |

### Tabla `core_detallefactura` (`core.DetalleFactura`)
*DetalleFactura(id, creado_en, actualizado_en, empresa, factura, producto, nombre_producto, cantidad, precio_unitario, iva_porcentaje)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `factura_id` | `uuid` | `FK` → `core_factura`, `INDEX` | NO (`NOT NULL`) | Factura |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `nombre_producto` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre producto |
| `cantidad` | `integer` | — | NO (`NOT NULL`) | Cantidad |
| `precio_unitario` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Precio unitario |
| `iva_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Iva porcentaje |

### Tabla `core_pago` (`core.Pago`)
*Un intento de cobro de una factura a través de la pasarela.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `factura_id` | `uuid` | `FK` → `core_factura`, `INDEX` | SÍ (`NULL`) | Factura |
| `pedido_id` | `uuid` | `FK` → `core_pedido`, `INDEX` | SÍ (`NULL`) | Pedido |
| `referencia` | `varchar(60)` | `UK` | NO (`NOT NULL`) | Referencia |
| `monto_centavos` | `bigint` | — | NO (`NOT NULL`) | Monto centavos |
| `moneda` | `varchar(3)` | — | NO (`NOT NULL`) | Moneda |
| `estado` | `varchar(10)` | — | NO (`NOT NULL`) | Estado |
| `wompi_transaccion_id` | `varchar(60)` | — | NO (`NOT NULL`) | Wompi transaccion id |
| `metodo_pago` | `varchar(30)` | — | NO (`NOT NULL`) | Metodo pago |
| `aprobado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Aprobado en |
| `consultado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Consultado en |
| `credenciales_cifradas` | `text` | — | NO (`NOT NULL`) | Credenciales cifradas |
| `pasarela_propia` | `boolean` | — | NO (`NOT NULL`) | Pasarela propia |

### Tabla `core_configuracionpagos` (`core.ConfiguracionPagos`)
*Llaves de la pasarela propia de cada negocio. Los secretos se guardan cifrados*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `UK` | NO (`NOT NULL`) | Empresa |
| `proveedor` | `varchar(20)` | — | NO (`NOT NULL`) | Proveedor |
| `modo` | `varchar(20)` | — | NO (`NOT NULL`) | Modo |
| `llave_publica` | `varchar(120)` | — | NO (`NOT NULL`) | Llave publica |
| `llave_privada_cifrada` | `text` | — | NO (`NOT NULL`) | Llave privada cifrada |
| `secreto_integridad_cifrado` | `text` | — | NO (`NOT NULL`) | Secreto integridad cifrado |
| `secreto_eventos_cifrado` | `text` | — | NO (`NOT NULL`) | Secreto eventos cifrado |
| `llave_privada_final` | `varchar(4)` | — | NO (`NOT NULL`) | Llave privada final |
| `secreto_integridad_final` | `varchar(4)` | — | NO (`NOT NULL`) | Secreto integridad final |
| `secreto_eventos_final` | `varchar(4)` | — | NO (`NOT NULL`) | Secreto eventos final |
| `activa` | `boolean` | — | NO (`NOT NULL`) | Cobrar en línea con estas llaves |
| `cobrar_tarifa_al_comprador` | `boolean` | — | NO (`NOT NULL`) | Sumar la tarifa de la pasarela al precio |
| `tarifa_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Tarifa de la pasarela (%) |
| `tarifa_fija` | `numeric(10, 2)` | — | NO (`NOT NULL`) | Tarifa fija por transacción ($) |
| `verificada_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Verificada en |
| `comercio_verificado` | `varchar(200)` | — | NO (`NOT NULL`) | Comercio verificado |
| `ultimo_intento_verificacion` | `timestamp with time zone` | — | SÍ (`NULL`) | Ultimo intento verificacion |
| `actualizada_por_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | SÍ (`NULL`) | Actualizada por |
| `revision` | `uuid` | — | NO (`NOT NULL`) | Revision |

### Tabla `core_auditoriapagos` (`core.AuditoriaPagos`)
*Solo metadatos del cambio; nunca valores de llaves ni cuerpos de peticiones.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `usuario_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | SÍ (`NULL`) | Usuario |
| `accion` | `varchar(30)` | — | NO (`NOT NULL`) | Accion |
| `campos` | `jsonb` | — | NO (`NOT NULL`) | Campos |

### Tabla `core_orden` (`core.Orden`)
*Una compra unificada del marketplace que reúne los pedidos de varios negocios; cada pedido se paga y concilia por separado.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `comprador_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Comprador |

### Tabla `core_pedido` (`core.Pedido`)
*Lo que compró una persona en un negocio. Guarda sus líneas y su total: la factura nace al pagar.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `comprador_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Comprador |
| `orden_id` | `uuid` | `FK` → `core_orden`, `INDEX` | SÍ (`NULL`) | Orden unificada (cuando compra en varios negocios) |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega de reserva de stock |
| `factura_id` | `uuid` | `FK` → `core_factura`, `UK` | SÍ (`NULL`) | Factura |
| `numero` | `integer` | — | NO (`NOT NULL`) | Numero |
| `estado` | `varchar(20)` | — | NO (`NOT NULL`) | Estado |
| `expira_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Expira en |
| `renovaciones` | `smallint` | — | NO (`NOT NULL`) | Renovaciones |
| `pago_directo` | `boolean` | — | NO (`NOT NULL`) | Pago directo |
| `subtotal` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Subtotal |
| `iva` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Iva |
| `cupon_id` | `uuid` | `FK` → `core_cupontienda`, `INDEX` | SÍ (`NULL`) | Cupón de tienda aplicado |
| `cupon_codigo` | `varchar(40)` | — | NO (`NOT NULL`) | Código de cupón congelado al confirmar |
| `descuento` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Descuento aplicado en COP |
| `costo_envio` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Costo envio |
| `cargo_pasarela` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Cargo pasarela |
| `total` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Total |
| `peso_total_gramos` | `integer` | — | NO (`NOT NULL`) | Peso total gramos |
| `comision_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Comision porcentaje |
| `comision_valor` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Comision valor |
| `neto_vendedor` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Neto vendedor |
| `estado_dispersion` | `varchar(15)` | — | NO (`NOT NULL`) | Estado dispersion |
| `dispersion_referencia` | `varchar(80)` | — | NO (`NOT NULL`) | Dispersion referencia |
| `dispersado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Dispersado en |
| `estado_envio` | `varchar(20)` | — | NO (`NOT NULL`) | Estado envio |
| `transportadora` | `varchar(80)` | — | NO (`NOT NULL`) | Transportadora |
| `numero_guia` | `varchar(80)` | — | NO (`NOT NULL`) | Numero guia |
| `url_rastreo` | `varchar(300)` | — | NO (`NOT NULL`) | URL personalizada de rastreo (http/https) |
| `enviado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Enviado en |
| `entregado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Entregado en |
| `reembolsado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Reembolsado en |
| `reembolso_referencia` | `varchar(80)` | — | NO (`NOT NULL`) | Reembolso referencia |
| `reembolso_nota` | `varchar(250)` | — | NO (`NOT NULL`) | Reembolso nota |
| `reembolsado_por_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | SÍ (`NULL`) | Reembolsado por |
| `tipo_documento` | `varchar(5)` | — | NO (`NOT NULL`) | Tipo documento |
| `numero_documento` | `varchar(20)` | — | NO (`NOT NULL`) | Numero documento |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `email` | `varchar(254)` | — | NO (`NOT NULL`) | Email |
| `telefono` | `varchar(20)` | — | NO (`NOT NULL`) | Telefono |
| `departamento` | `varchar(60)` | — | NO (`NOT NULL`) | Departamento |
| `ciudad` | `varchar(80)` | — | NO (`NOT NULL`) | Ciudad |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Direccion |
| `indicaciones` | `varchar(200)` | — | NO (`NOT NULL`) | Indicaciones |

### Tabla `core_cupontienda` (`core.CuponTienda`)
*Cupón de descuento propio de un negocio para compras en el marketplace.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `codigo` | `varchar(40)` | `UK (empresa_id, codigo)` | NO (`NOT NULL`) | Código en mayúsculas sin espacios |
| `tipo` | `varchar(15)` | — | NO (`NOT NULL`) | `porcentaje` o `fijo` |
| `valor` | `numeric(12, 2)` | `CHECK (valor > 0)` | NO (`NOT NULL`) | Porcentaje o monto en COP |
| `monto_minimo` | `numeric(12, 2)` | `CHECK (monto_minimo >= 0)` | NO (`NOT NULL`) | Compra mínima en productos |
| `usos_maximos` | `integer` | — | SÍ (`NULL`) | Límite máximo de usos (`NULL` = ilimitado) |
| `usos_actuales` | `integer` | — | NO (`NOT NULL`) | Usos consumidos |
| `inicia_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Inicio de vigencia |
| `vence_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Fin de vigencia |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |

### Tabla `core_itemcarrito` (`core.ItemCarrito`)
*Línea persistente del carrito para usuarios autenticados (sincronizada entre dispositivos).*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `usuario_id` | `uuid` | `FK` → `core_usuario`, `UK (usuario_id, producto_id)` | NO (`NOT NULL`) | Usuario autenticado |
| `producto_id` | `uuid` | `FK` → `core_producto`, `UK (usuario_id, producto_id)` | NO (`NOT NULL`) | Producto guardado |
| `cantidad` | `integer` | `CHECK (cantidad > 0)` | NO (`NOT NULL`) | Unidades en carrito |

### Tabla `core_detallepedido` (`core.DetallePedido`)
*DetallePedido(id, creado_en, actualizado_en, empresa, pedido, producto, cantidad, precio_unitario, iva_porcentaje)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `pedido_id` | `uuid` | `FK` → `core_pedido`, `INDEX` | NO (`NOT NULL`) | Pedido |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | — | NO (`NOT NULL`) | Cantidad |
| `precio_unitario` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Precio unitario |
| `iva_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Iva porcentaje |

### Tabla `core_comentario` (`core.Comentario`)
*Comentario(id, creado_en, actualizado_en, empresa, producto, autor, calificacion, texto, compra_verificada)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `autor_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Autor |
| `calificacion` | `smallint` | — | NO (`NOT NULL`) | Calificacion |
| `texto` | `text` | — | NO (`NOT NULL`) | Texto |
| `compra_verificada` | `boolean` | — | NO (`NOT NULL`) | Compra verificada |

### Tabla `core_turnocaja` (`core.TurnoCaja`)
*Desde que un cajero abre caja con una base hasta que la cierra contando el efectivo.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `cajero_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Cajero |
| `base_inicial` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Base inicial |
| `cerrado_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Cerrado en |
| `efectivo_esperado` | `numeric(14, 2)` | — | SÍ (`NULL`) | Efectivo esperado |
| `efectivo_contado` | `numeric(14, 2)` | — | SÍ (`NULL`) | Efectivo contado |
| `diferencia` | `numeric(14, 2)` | — | SÍ (`NULL`) | Diferencia |
| `observaciones` | `text` | — | NO (`NOT NULL`) | Observaciones |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega desde la cual vende el turno |
*Lo que entra a la caja por una venta. Una venta puede pagarse con varios medios.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `turno_id` | `uuid` | `FK` → `core_turnocaja`, `INDEX` | NO (`NOT NULL`) | Turno |
| `factura_id` | `uuid` | `FK` → `core_factura`, `INDEX` | NO (`NOT NULL`) | Factura |
| `metodo` | `varchar(15)` | — | NO (`NOT NULL`) | Metodo |
| `monto` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Monto |
| `recibido` | `numeric(14, 2)` | — | SÍ (`NULL`) | Recibido |
| `cambio` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Cambio |
| `referencia` | `varchar(60)` | — | NO (`NOT NULL`) | Referencia |

### Tabla `core_proveedor` (`core.Proveedor`)
*Proveedor(id, creado_en, actualizado_en, empresa, nombre, documento, email, telefono, direccion, activo)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `documento` | `varchar(30)` | — | NO (`NOT NULL`) | Documento |
| `email` | `varchar(254)` | — | NO (`NOT NULL`) | Email |
| `telefono` | `varchar(30)` | — | NO (`NOT NULL`) | Telefono |
| `direccion` | `varchar(250)` | — | NO (`NOT NULL`) | Direccion |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |

### Tabla `core_compra` (`core.Compra`)
*Compra(id, creado_en, actualizado_en, empresa, proveedor, referencia, fecha, vencimiento, recibida, subtotal, iva, total, observaciones)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `proveedor_id` | `uuid` | `FK` → `core_proveedor`, `INDEX` | NO (`NOT NULL`) | Proveedor |
| `referencia` | `varchar(60)` | — | NO (`NOT NULL`) | Factura del proveedor |
| `fecha` | `date` | — | NO (`NOT NULL`) | Fecha |
| `vencimiento` | `date` | — | NO (`NOT NULL`) | Vencimiento |
| `recibida` | `boolean` | — | NO (`NOT NULL`) | Recibida |
| `subtotal` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Subtotal |
| `iva` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Iva |
| `total` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Total |
| `observaciones` | `text` | — | NO (`NOT NULL`) | Observaciones |

### Tabla `core_lineacompra` (`core.LineaCompra`)
*LineaCompra(id, creado_en, actualizado_en, empresa, compra, producto, cantidad, costo, iva_porcentaje)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `compra_id` | `uuid` | `FK` → `core_compra`, `INDEX` | NO (`NOT NULL`) | Compra |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | — | NO (`NOT NULL`) | Cantidad |
| `costo` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Costo |
| `iva_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Iva porcentaje |

### Tabla `core_cuentatesoreria` (`core.CuentaTesoreria`)
*CuentaTesoreria(id, creado_en, actualizado_en, empresa, nombre, tipo, activa)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(100)` | — | NO (`NOT NULL`) | Nombre |
| `tipo` | `varchar(10)` | — | NO (`NOT NULL`) | Tipo |
| `activa` | `boolean` | — | NO (`NOT NULL`) | Activa |

### Tabla `core_cuentacartera` (`core.CuentaCartera`)
*CuentaCartera(id, creado_en, actualizado_en, empresa, tipo, tercero, concepto, fecha, vencimiento, total, abonado, compra, factura)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `tipo` | `varchar(10)` | — | NO (`NOT NULL`) | Tipo |
| `tercero` | `varchar(150)` | — | NO (`NOT NULL`) | Tercero |
| `concepto` | `varchar(200)` | — | NO (`NOT NULL`) | Concepto |
| `fecha` | `date` | — | NO (`NOT NULL`) | Fecha |
| `vencimiento` | `date` | — | NO (`NOT NULL`) | Vencimiento |
| `total` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Total |
| `abonado` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Abonado |
| `compra_id` | `uuid` | `FK` → `core_compra`, `UK` | SÍ (`NULL`) | Compra |
| `factura_id` | `uuid` | `FK` → `core_factura`, `UK` | SÍ (`NULL`) | Factura |

### Tabla `core_movimientotesoreria` (`core.MovimientoTesoreria`)
*MovimientoTesoreria(id, creado_en, actualizado_en, empresa, cuenta, tipo, fecha, concepto, monto, cartera, referencia, conciliado, usuario, operacion)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `cuenta_id` | `uuid` | `FK` → `core_cuentatesoreria`, `INDEX` | NO (`NOT NULL`) | Cuenta |
| `tipo` | `varchar(10)` | — | NO (`NOT NULL`) | Tipo |
| `fecha` | `date` | — | NO (`NOT NULL`) | Fecha |
| `concepto` | `varchar(200)` | — | NO (`NOT NULL`) | Concepto |
| `monto` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Monto |
| `cartera_id` | `uuid` | `FK` → `core_cuentacartera`, `INDEX` | SÍ (`NULL`) | Cartera |
| `referencia` | `varchar(100)` | — | NO (`NOT NULL`) | Referencia |
| `conciliado` | `boolean` | — | NO (`NOT NULL`) | Conciliado |
| `usuario_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Usuario |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega de origen o destino del movimiento |

### Tabla `core_bodega` (`core.Bodega`)
*Un lugar donde se guarda mercancía (bodega, sede, local). Restricciones: `uq_bodega_nombre_por_empresa` (`empresa`, `nombre`), `uq_bodega_principal_por_empresa` (`empresa` donde `es_principal=True`), `uq_bodega_en_linea_por_empresa` (`empresa` donde `vende_en_linea=True`) y `ck_bodega_clave_activa`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(80)` | `UK` (con `empresa_id`) | NO (`NOT NULL`) | Nombre de la bodega |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Dirección física |
| `activa` | `boolean` | `CHECK` (`ck_bodega_clave_activa`) | NO (`NOT NULL`) | Activa |
| `es_principal` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Es bodega principal (compras y producción) |
| `vende_en_linea` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Abastece ventas del marketplace |

### Tabla `core_existencia` (`core.Existencia`)
*Unidades de un producto en una bodega (`uq_existencia_bodega_producto`, `ck_existencia_no_negativa`: `cantidad >= 0`). La suma de todas las bodegas es `Producto.stock`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `UK` (con `producto_id`) | NO (`NOT NULL`) | Bodega |
| `producto_id` | `uuid` | `FK` → `core_producto`, `UK` (con `bodega_id`) | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | `CHECK` (`cantidad >= 0`) | NO (`NOT NULL`) | Unidades disponibles en la bodega |
| `operacion` | `uuid` | `UK` | NO (`NOT NULL`) | Operacion |

### Tabla `core_cuentacontable` (`core.CuentaContable`)
*CuentaContable(id, creado_en, actualizado_en, empresa, codigo, nombre, naturaleza)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `codigo` | `varchar(20)` | — | NO (`NOT NULL`) | Codigo |
| `nombre` | `varchar(100)` | — | NO (`NOT NULL`) | Nombre |
| `naturaleza` | `varchar(10)` | — | NO (`NOT NULL`) | Naturaleza |

### Tabla `core_asientocontable` (`core.AsientoContable`)
*AsientoContable(id, creado_en, actualizado_en, empresa, fecha, concepto, referencia, confirmado, usuario)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `fecha` | `date` | — | NO (`NOT NULL`) | Fecha |
| `concepto` | `varchar(200)` | — | NO (`NOT NULL`) | Concepto |
| `referencia` | `varchar(100)` | — | NO (`NOT NULL`) | Referencia |
| `confirmado` | `boolean` | — | NO (`NOT NULL`) | Confirmado |
| `usuario_id` | `uuid` | `FK` → `core_usuario`, `INDEX` | NO (`NOT NULL`) | Usuario |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `INDEX` | SÍ (`NULL`) | Bodega de origen o destino del movimiento |

### Tabla `core_bodega` (`core.Bodega`)
*Un lugar donde se guarda mercancía (bodega, sede, local). Restricciones: `uq_bodega_nombre_por_empresa` (`empresa`, `nombre`), `uq_bodega_principal_por_empresa` (`empresa` donde `es_principal=True`), `uq_bodega_en_linea_por_empresa` (`empresa` donde `vende_en_linea=True`) y `ck_bodega_clave_activa`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(80)` | `UK` (con `empresa_id`) | NO (`NOT NULL`) | Nombre de la bodega |
| `direccion` | `varchar(200)` | — | NO (`NOT NULL`) | Dirección física |
| `activa` | `boolean` | `CHECK` (`ck_bodega_clave_activa`) | NO (`NOT NULL`) | Activa |
| `es_principal` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Es bodega principal (compras y producción) |
| `vende_en_linea` | `boolean` | `UK` parcial por empresa | NO (`NOT NULL`) | Abastece ventas del marketplace |

### Tabla `core_existencia` (`core.Existencia`)
*Unidades de un producto en una bodega (`uq_existencia_bodega_producto`, `ck_existencia_no_negativa`: `cantidad >= 0`). La suma de todas las bodegas es `Producto.stock`.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `bodega_id` | `uuid` | `FK` → `core_bodega`, `UK` (con `producto_id`) | NO (`NOT NULL`) | Bodega |
| `producto_id` | `uuid` | `FK` → `core_producto`, `UK` (con `bodega_id`) | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | `CHECK` (`cantidad >= 0`) | NO (`NOT NULL`) | Unidades disponibles en la bodega |

### Tabla `core_lineaasiento` (`core.LineaAsiento`)
*LineaAsiento(id, creado_en, actualizado_en, empresa, asiento, cuenta, debito, credito)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `asiento_id` | `uuid` | `FK` → `core_asientocontable`, `INDEX` | NO (`NOT NULL`) | Asiento |
| `cuenta_id` | `uuid` | `FK` → `core_cuentacontable`, `INDEX` | NO (`NOT NULL`) | Cuenta |
| `debito` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Debito |
| `credito` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Credito |

### Tabla `core_empleado` (`core.Empleado`)
*Empleado(id, creado_en, actualizado_en, empresa, nombre, documento, cargo, salario_base, fecha_ingreso, activo)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `documento` | `varchar(30)` | — | NO (`NOT NULL`) | Documento |
| `cargo` | `varchar(100)` | — | NO (`NOT NULL`) | Cargo |
| `salario_base` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Salario base |
| `fecha_ingreso` | `date` | — | NO (`NOT NULL`) | Fecha ingreso |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |

### Tabla `core_liquidacionnomina` (`core.LiquidacionNomina`)
*LiquidacionNomina(id, creado_en, actualizado_en, empresa, empleado, desde, hasta, base, adicionales, deducciones, neto, observaciones, aprobada, cartera)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `empleado_id` | `uuid` | `FK` → `core_empleado`, `INDEX` | NO (`NOT NULL`) | Empleado |
| `desde` | `date` | — | NO (`NOT NULL`) | Desde |
| `hasta` | `date` | — | NO (`NOT NULL`) | Hasta |
| `base` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Base |
| `adicionales` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Adicionales |
| `deducciones` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Deducciones |
| `neto` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Neto |
| `observaciones` | `text` | — | NO (`NOT NULL`) | Observaciones |
| `aprobada` | `boolean` | — | NO (`NOT NULL`) | Aprobada |
| `cartera_id` | `uuid` | `FK` → `core_cuentacartera`, `UK` | SÍ (`NULL`) | Cartera |

### Tabla `core_ordenproduccion` (`core.OrdenProduccion`)
*OrdenProduccion(id, creado_en, actualizado_en, empresa, producto, cantidad, fecha, completada, observaciones)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | — | NO (`NOT NULL`) | Cantidad |
| `fecha` | `date` | — | NO (`NOT NULL`) | Fecha |
| `completada` | `boolean` | — | NO (`NOT NULL`) | Completada |
| `observaciones` | `text` | — | NO (`NOT NULL`) | Observaciones |

### Tabla `core_insumoproduccion` (`core.InsumoProduccion`)
*InsumoProduccion(id, creado_en, actualizado_en, empresa, orden, producto, cantidad)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `orden_id` | `uuid` | `FK` → `core_ordenproduccion`, `INDEX` | NO (`NOT NULL`) | Orden |
| `producto_id` | `uuid` | `FK` → `core_producto`, `INDEX` | NO (`NOT NULL`) | Producto |
| `cantidad` | `integer` | — | NO (`NOT NULL`) | Cantidad total a consumir |

### Tabla `core_servicio` (`core.Servicio`)
*Servicio(id, creado_en, actualizado_en, empresa, nombre, precio, iva_porcentaje, duracion_minutos, activo)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `nombre` | `varchar(150)` | — | NO (`NOT NULL`) | Nombre |
| `precio` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Precio |
| `iva_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Iva porcentaje |
| `duracion_minutos` | `integer` | — | NO (`NOT NULL`) | Duracion minutos |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |

### Tabla `core_cita` (`core.Cita`)
*Cita(id, creado_en, actualizado_en, empresa, cliente, empleado, servicio, inicio, fin, estado, total, cartera, observaciones)*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `cliente_id` | `uuid` | `FK` → `core_cliente`, `INDEX` | NO (`NOT NULL`) | Cliente |
| `empleado_id` | `uuid` | `FK` → `core_empleado`, `INDEX` | NO (`NOT NULL`) | Empleado |
| `servicio_id` | `uuid` | `FK` → `core_servicio`, `INDEX` | NO (`NOT NULL`) | Servicio |
| `inicio` | `timestamp with time zone` | — | NO (`NOT NULL`) | Inicio |
| `fin` | `timestamp with time zone` | — | NO (`NOT NULL`) | Fin |
| `estado` | `varchar(12)` | — | NO (`NOT NULL`) | Estado |
| `total` | `numeric(14, 2)` | — | NO (`NOT NULL`) | Total |
| `cartera_id` | `uuid` | `FK` → `core_cuentacartera`, `UK` | SÍ (`NULL`) | Cartera |
| `observaciones` | `text` | — | NO (`NOT NULL`) | Observaciones |

### Tabla `core_ejecuciontarea` (`core.EjecucionTarea`)
*Registro de ejecución de tareas periódicas (evita repetición y colisiones entre programadores).*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `nombre` | `varchar(60)` | `UK` | NO (`NOT NULL`) | Nombre de la tarea |
| `ultima_ejecucion` | `timestamp with time zone` | — | SÍ (`NULL`) | Última ejecución |
| `ultimo_resultado` | `varchar(500)` | — | NO (`NOT NULL`) | Último resultado |
| `ultimo_error` | `varchar(500)` | — | NO (`NOT NULL`) | Último error |
| `ejecuciones` | `integer` | — | NO (`NOT NULL`) | Contador de ejecuciones |
| `fallos_seguidos` | `integer` | — | NO (`NOT NULL`) | Fallos consecutivos |

---
## Aplicación: `suscripciones` (4 tablas)

### Tabla `suscripciones_plan` (`suscripciones.Plan`)
*Catálogo de planes comerciales de Intersoft.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `codigo` | `varchar(40)` | `UK` | NO (`NOT NULL`) | Código |
| `nombre` | `varchar(80)` | — | NO (`NOT NULL`) | Nombre |
| `precio_mensual` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Precio mensual (cop) |
| `precio_anual` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Precio anual (cop) |
| `comision_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Comisión marketplace (%) |
| `limites` | `jsonb` | — | NO (`NOT NULL`) | Límites por recurso |
| `features` | `jsonb` | — | NO (`NOT NULL`) | Funcionalidades habilitadas |
| `orden` | `smallint` | — | NO (`NOT NULL`) | Orden de visualización |
| `activo` | `boolean` | — | NO (`NOT NULL`) | Activo |

### Tabla `suscripciones_suscripcion` (`suscripciones.Suscripcion`)
*Estado de suscripción vigente de una empresa (relación 1 a 1 con core.Empresa).*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `UK` | NO (`NOT NULL`) | Empresa |
| `plan_id` | `uuid` | `FK` → `suscripciones_plan`, `INDEX` | NO (`NOT NULL`) | Plan |
| `estado` | `varchar(15)` | `INDEX` | NO (`NOT NULL`) | Estado |
| `ciclo` | `varchar(10)` | — | NO (`NOT NULL`) | Ciclo de cobro |
| `inicia_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Inicia en |
| `vence_en` | `timestamp with time zone` | `INDEX` | SÍ (`NULL`) | Vence en |
| `es_fundador` | `boolean` | — | NO (`NOT NULL`) | Es empresa fundadora |
| `descuento_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Descuento permanente (%) |

### Tabla `suscripciones_historialsuscripcion` (`suscripciones.HistorialSuscripcion`)
*Registro inmutable de auditoría para cada transición de plan o estado de una suscripción.*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `suscripcion_id` | `uuid` | `FK` → `suscripciones_suscripcion`, `INDEX` | NO (`NOT NULL`) | Suscripción |
| `plan_anterior_id` | `uuid` | `FK` → `suscripciones_plan`, `INDEX` | SÍ (`NULL`) | Plan anterior |
| `plan_nuevo_id` | `uuid` | `FK` → `suscripciones_plan`, `INDEX` | NO (`NOT NULL`) | Plan nuevo |
| `estado_anterior` | `varchar(15)` | — | NO (`NOT NULL`) | Estado anterior |
| `estado_nuevo` | `varchar(15)` | — | NO (`NOT NULL`) | Estado nuevo |
| `motivo` | `varchar(255)` | — | NO (`NOT NULL`) | Motivo |
| `fecha` | `timestamp with time zone` | `INDEX` | NO (`NOT NULL`) | Fecha del cambio |

### Tabla `suscripciones_cobrosuscripcion` (`suscripciones.CobroSuscripcion`)
*Intento de pago de un plan con la cuenta Wompi de Intersoft. Restricción: `ck_cobro_suscripcion_monto_positivo` (`monto > 0`), índice `ix_cobro_sus_empresa_fecha` (`empresa`, `-creado_en`).*

| Columna | Tipo PostgreSQL | Llave / Restricciones | Nulable | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `uuid` | `PK` | NO (`NOT NULL`) | Id |
| `creado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Creado en |
| `actualizado_en` | `timestamp with time zone` | — | NO (`NOT NULL`) | Actualizado en |
| `empresa_id` | `uuid` | `FK` → `core_empresa`, `INDEX` | NO (`NOT NULL`) | Empresa |
| `plan_id` | `uuid` | `FK` → `suscripciones_plan`, `INDEX` | NO (`NOT NULL`) | Plan |
| `ciclo` | `varchar(10)` | — | NO (`NOT NULL`) | Ciclo (`MENSUAL` / `ANUAL`) |
| `referencia` | `varchar(60)` | `UK` | NO (`NOT NULL`) | Referencia única (`SUS-...`) |
| `precio_lista` | `numeric(12, 2)` | — | NO (`NOT NULL`) | Precio de lista congelado |
| `descuento_porcentaje` | `numeric(5, 2)` | — | NO (`NOT NULL`) | Descuento aplicado (%) |
| `monto` | `numeric(12, 2)` | `CHECK` (`monto > 0`) | NO (`NOT NULL`) | Monto final a cobrar |
| `moneda` | `varchar(3)` | — | NO (`NOT NULL`) | Moneda (`COP`) |
| `estado` | `varchar(20)` | `INDEX` | NO (`NOT NULL`) | Estado (`pendiente`, `aprobado`, `rechazado`, `anulado`, `requiere_revision`) |
| `transaccion_id` | `varchar(60)` | — | NO (`NOT NULL`) | ID de transacción Wompi |
| `metodo_pago` | `varchar(30)` | — | NO (`NOT NULL`) | Método de pago Wompi |
| `detalle` | `varchar(255)` | — | NO (`NOT NULL`) | Detalle del resultado |
| `creado_por_id` | `uuid` | `FK` → `core_usuario` | SÍ (`NULL`) | Usuario que inició el cobro |
| `resuelto_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Fecha de resolución |
| `ultima_consulta_en` | `timestamp with time zone` | — | SÍ (`NULL`) | Última consulta en Wompi |
