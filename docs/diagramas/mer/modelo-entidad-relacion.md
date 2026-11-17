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
        uuid factura_id FK
        int numero
        varchar estado
        varchar estado_envio
        decimal total
        datetime expira_en
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
    CORE_FACTURA |o--o| CORE_PEDIDO : "factura"
    CORE_FACTURA |o--o{ CORE_PAGO : "cobra"
    CORE_PEDIDO |o--o{ CORE_PAGO : "cobra"
```
