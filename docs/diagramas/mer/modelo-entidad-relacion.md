# Modelo Entidad–Relación (MER) — InterSoft

Estructura relacional de las tablas principales en PostgreSQL, incluyendo llaves primarias (`PK`), llaves foráneas (`FK`), llaves únicas (`UK`) y cardinalidades.

```mermaid
erDiagram
    CORE_EMPRESA {
        uuid id PK
        varchar nombre
        varchar nit UK
        slug slug UK
        varchar direccion
        varchar telefono
        varchar email
        varchar logo
        text descripcion
        url sitio_web
        boolean activa
        decimal comision_porcentaje
    }

    CORE_USUARIO {
        uuid id PK
        varchar email UK
        varchar username
        varchar first_name
        varchar last_name
        varchar foto
        varchar telefono
        varchar cargo
        text descripcion
        boolean is_active
    }

    CORE_PERMISO {
        uuid id PK
        varchar codigo UK
        varchar descripcion
    }

    CORE_ROL {
        uuid id PK
        uuid empresa_id FK
        varchar nombre
        boolean es_admin
    }

    CORE_ROL_PERMISOS {
        bigint id PK
        uuid rol_id FK
        uuid permiso_id FK
    }

    CORE_MEMBRESIA {
        uuid id PK
        uuid usuario_id FK
        uuid empresa_id FK
        uuid rol_id FK
        boolean activa
    }

    SUSCRIPCIONES_PLAN {
        uuid id PK
        slug codigo UK
        varchar nombre
        decimal precio_mensual
        decimal precio_anual
        decimal comision_porcentaje
        jsonb limites
        jsonb features
        smallint orden
        boolean activo
    }

    SUSCRIPCIONES_SUSCRIPCION {
        uuid id PK
        uuid empresa_id FK
        uuid plan_id FK
        varchar estado
        varchar ciclo
        datetime inicia_en
        datetime vence_en
        boolean es_fundador
        decimal descuento_porcentaje
    }

    SUSCRIPCIONES_HISTORIALSUSCRIPCION {
        uuid id PK
        uuid suscripcion_id FK
        uuid plan_anterior_id FK
        uuid plan_nuevo_id FK
        varchar estado_anterior
        varchar estado_nuevo
        varchar motivo
        datetime fecha
    }

    CORE_CATEGORIA {
        uuid id PK
        uuid empresa_id FK
        varchar nombre
        boolean activa
    }

    CORE_PRODUCTO {
        uuid id PK
        uuid empresa_id FK
        uuid categoria_id FK
        varchar codigo
        varchar nombre
        decimal precio
        decimal iva_porcentaje
        int stock
        int stock_minimo
        boolean activo
        boolean publicado
    }

    CORE_MOVIMIENTOINVENTARIO {
        uuid id PK
        uuid empresa_id FK
        uuid producto_id FK
        uuid usuario_id FK
        varchar tipo
        int cantidad
        varchar referencia
    }

    CORE_CLIENTE {
        uuid id PK
        uuid empresa_id FK
        varchar tipo_documento
        varchar numero_documento
        varchar nombre
        varchar email
        boolean activo
    }

    CORE_TURNOCAJA {
        uuid id PK
        uuid empresa_id FK
        uuid cajero_id FK
        decimal base_inicial
        datetime cerrado_en
        decimal efectivo_esperado
        decimal efectivo_contado
        decimal diferencia
    }

    CORE_FACTURA {
        uuid id PK
        uuid empresa_id FK
        uuid cliente_id FK
        uuid creada_por_id FK
        uuid turno_id FK
        int numero
        varchar estado
        decimal subtotal
        decimal iva
        decimal total
        varchar estado_dian
        varchar cufe
        varchar cude_nota_credito
    }

    CORE_DETALLEFACTURA {
        uuid id PK
        uuid empresa_id FK
        uuid factura_id FK
        uuid producto_id FK
        int cantidad
        decimal precio_unitario
        decimal iva_porcentaje
    }

    CORE_PAGOCAJA {
        uuid id PK
        uuid empresa_id FK
        uuid turno_id FK
        uuid factura_id FK
        varchar metodo
        decimal monto
        decimal recibido
        decimal cambio
    }

    CORE_PEDIDO {
        uuid id PK
        uuid empresa_id FK
        uuid comprador_id FK
        uuid orden_id FK
        uuid bodega_id FK
        uuid factura_id FK
        uuid cupon_id FK
        int numero
        varchar estado
        varchar estado_envio
        varchar cupon_codigo
        decimal descuento
        varchar transportadora
        varchar numero_guia
        url url_rastreo
        decimal total
        datetime expira_en
    }

    CORE_CUPONTIENDA {
        uuid id PK
        uuid empresa_id FK
        varchar codigo UK
        varchar tipo
        decimal valor
        decimal monto_minimo
        int usos_maximos
        int usos_actuales
        datetime inicia_en
        datetime vence_en
        boolean activo
    }

    CORE_ITEMCARRITO {
        uuid id PK
        uuid usuario_id FK
        uuid producto_id FK
        int cantidad
        datetime actualizado_en
    }

    DATOS_PERSONALES_AUTORIZACIONDATOS {
        uuid id PK
        uuid usuario_id FK
        varchar version_politica
        datetime aceptada_en
        datetime revocada_en
        varchar ip
    }

    DATOS_PERSONALES_SOLICITUDDATOS {
        uuid id PK
        uuid usuario_id FK
        varchar tipo
        varchar estado
        text detalle
        datetime vence_en
    }

    CORE_ORDEN {
        uuid id PK
        uuid comprador_id FK
        datetime creado_en
    }

    CORE_BODEGA {
        uuid id PK
        uuid empresa_id FK
        varchar nombre UK
        varchar direccion
        boolean activa
        boolean es_principal
        boolean vende_en_linea
    }

    CORE_EXISTENCIA {
        uuid id PK
        uuid empresa_id FK
        uuid bodega_id FK
        uuid producto_id FK
        int cantidad
    }

    CORE_EJECUCIONTAREA {
        uuid id PK
        varchar nombre UK
        datetime ultima_ejecucion
        varchar ultimo_resultado
        varchar ultimo_error
        int ejecuciones
        int fallos_seguidos
    }

    SUSCRIPCIONES_COBROSUSCRIPCION {
        uuid id PK
        uuid empresa_id FK
        uuid plan_id FK
        uuid creado_por_id FK
        varchar ciclo
        varchar referencia UK
        decimal precio_lista
        decimal descuento_porcentaje
        decimal monto
        varchar moneda
        varchar estado
        varchar transaccion_id
        varchar metodo_pago
        datetime resuelto_en
    }

    CORE_PAGO {
        uuid id PK
        uuid empresa_id FK
        uuid factura_id FK
        uuid pedido_id FK
        varchar referencia UK
        int monto_centavos
        varchar moneda
        varchar estado
    }

    CORE_EMPRESA ||--o{ CORE_MEMBRESIA : "tiene"
    CORE_USUARIO ||--o{ CORE_MEMBRESIA : "pertenece"
    CORE_ROL ||--o{ CORE_MEMBRESIA : "asigna"
    CORE_EMPRESA ||--o{ CORE_ROL : "define"
    CORE_ROL ||--o{ CORE_ROL_PERMISOS : "posee"
    CORE_PERMISO ||--o{ CORE_ROL_PERMISOS : "autoriza"

    CORE_EMPRESA ||--|| SUSCRIPCIONES_SUSCRIPCION : "contrata"
    SUSCRIPCIONES_PLAN ||--o{ SUSCRIPCIONES_SUSCRIPCION : "rige"
    SUSCRIPCIONES_SUSCRIPCION ||--o{ SUSCRIPCIONES_HISTORIALSUSCRIPCION : "registra"
    SUSCRIPCIONES_PLAN |o--o{ SUSCRIPCIONES_HISTORIALSUSCRIPCION : "plan_anterior"
    SUSCRIPCIONES_PLAN ||--o{ SUSCRIPCIONES_HISTORIALSUSCRIPCION : "plan_nuevo"

    CORE_EMPRESA ||--o{ CORE_CATEGORIA : "organiza"
    CORE_EMPRESA ||--o{ CORE_PRODUCTO : "almacena"
    CORE_CATEGORIA |o--o{ CORE_PRODUCTO : "clasifica"
    CORE_PRODUCTO ||--o{ CORE_MOVIMIENTOINVENTARIO : "mueve"
    CORE_USUARIO ||--o{ CORE_MOVIMIENTOINVENTARIO : "ejecuta"

    CORE_EMPRESA ||--o{ CORE_CLIENTE : "atiende"
    CORE_EMPRESA ||--o{ CORE_TURNOCAJA : "opera"
    CORE_USUARIO ||--o{ CORE_TURNOCAJA : "cajero"

    CORE_EMPRESA ||--o{ CORE_FACTURA : "emite"
    CORE_CLIENTE ||--o{ CORE_FACTURA : "compra"
    CORE_TURNOCAJA |o--o{ CORE_FACTURA : "cobra_en"
    CORE_FACTURA ||--|{ CORE_DETALLEFACTURA : "contiene"
    CORE_PRODUCTO ||--o{ CORE_DETALLEFACTURA : "vendido_en"
    CORE_TURNOCAJA ||--o{ CORE_PAGOCAJA : "recibe"
    CORE_FACTURA ||--o{ CORE_PAGOCAJA : "paga"

    CORE_EMPRESA ||--o{ CORE_PEDIDO : "despacha"
    CORE_USUARIO ||--o{ CORE_PEDIDO : "comprador"
    CORE_USUARIO ||--o{ CORE_ORDEN : "compra_unificada"
    CORE_ORDEN |o--o{ CORE_PEDIDO : "agrupa"
    CORE_EMPRESA ||--o{ CORE_BODEGA : "opera_sede"
    CORE_BODEGA ||--o{ CORE_EXISTENCIA : "almacena"
    CORE_PRODUCTO ||--o{ CORE_EXISTENCIA : "ubicado_en"
    CORE_BODEGA |o--o{ CORE_MOVIMIENTOINVENTARIO : "bodega_mov"
    CORE_BODEGA |o--o{ CORE_TURNOCAJA : "bodega_pos"
    CORE_BODEGA |o--o{ CORE_FACTURA : "bodega_fac"
    CORE_BODEGA |o--o{ CORE_PEDIDO : "bodega_ped"
    CORE_EMPRESA ||--o{ SUSCRIPCIONES_COBROSUSCRIPCION : "paga_plan"
    SUSCRIPCIONES_PLAN ||--o{ SUSCRIPCIONES_COBROSUSCRIPCION : "cobrado_en"
    CORE_FACTURA |o--o| CORE_PEDIDO : "factura"
    CORE_FACTURA |o--o{ CORE_PAGO : "cobra"
    CORE_PEDIDO |o--o{ CORE_PAGO : "cobra"
    CORE_EMPRESA ||--o{ CORE_CUPONTIENDA : "ofrece"
    CORE_CUPONTIENDA |o--o{ CORE_PEDIDO : "aplica_descuento"
    CORE_USUARIO ||--o{ CORE_ITEMCARRITO : "guarda"
    CORE_PRODUCTO ||--o{ CORE_ITEMCARRITO : "en_carrito"
    CORE_USUARIO ||--o{ DATOS_PERSONALES_AUTORIZACIONDATOS : "autoriza_ley1581"
    CORE_USUARIO ||--o{ DATOS_PERSONALES_SOLICITUDDATOS : "radica_habeas_data"
```
