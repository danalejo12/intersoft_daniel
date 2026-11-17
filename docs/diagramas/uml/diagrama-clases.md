# Diagrama de Clases UML — InterSoft

Representación orientada a objetos de los modelos principales del proyecto (`core` y `suscripciones`).

```mermaid
classDiagram
    direction TB

    class ModeloBase {
        <<abstract>>
        +UUID id
        +DateTime creado_en
        +DateTime actualizado_en
    }

    class ModeloTenant {
        <<abstract>>
        +Empresa empresa
    }

    class Usuario {
        +UUID id
        +Email email
        +String first_name
        +String last_name
        +Image foto
        +String telefono
        +String cargo
        +Text descripcion
    }

    class Empresa {
        +String nombre
        +String nit
        +Slug slug
        +String direccion
        +String telefono
        +String email
        +Image logo
        +Text descripcion
        +URL sitio_web
        +Boolean activa
        +Decimal comision_porcentaje
        +datos_completos() bool
    }

    class Permiso {
        +String codigo
        +String descripcion
    }

    class Rol {
        +String nombre
        +String descripcion
        +Boolean es_admin
    }

    class Membresia {
        +Boolean activa
        +tiene_permiso(codigo) bool
    }

    class Plan {
        +Slug codigo
        +String nombre
        +Decimal precio_mensual
        +Decimal precio_anual
        +Decimal comision_porcentaje
        +JSON limites
        +JSON features
        +Integer orden
        +Boolean activo
    }

    class Suscripcion {
        +String estado
        +String ciclo
        +DateTime inicia_en
        +DateTime vence_en
        +Boolean es_fundador
        +Decimal descuento_porcentaje
        +puede(feature) bool
        +dentro_del_limite(recurso, uso) bool
    }

    class HistorialSuscripcion {
        +String estado_anterior
        +String estado_nuevo
        +String motivo
        +DateTime fecha
    }

    class Categoria {
        +String nombre
        +Boolean activa
    }

    class Producto {
        +String codigo
        +String nombre
        +Decimal precio
        +Decimal iva_porcentaje
        +Integer stock
        +Integer stock_minimo
        +Boolean activo
        +Boolean publicado
    }

    class MovimientoInventario {
        +String tipo
        +Integer cantidad
        +String referencia
    }

    class Cliente {
        +String tipo_documento
        +String numero_documento
        +String nombre
        +String email
        +Boolean activo
    }

    class Factura {
        +Integer numero
        +String estado
        +Decimal subtotal
        +Decimal iva
        +Decimal total
        +String estado_dian
        +String cufe
        +String cude_nota_credito
    }

    class DetalleFactura {
        +Integer cantidad
        +Decimal precio_unitario
        +Decimal iva_porcentaje
    }

    class TurnoCaja {
        +Decimal base_inicial
        +DateTime cerrado_en
        +Decimal efectivo_esperado
        +Decimal efectivo_contado
        +Decimal diferencia
    }

    class Pedido {
        +Integer numero
        +String estado
        +String estado_envio
        +Decimal total
        +DateTime expira_en
    }

    class Pago {
        +String referencia
        +Integer monto_centavos
        +String moneda
        +String estado
    }

    ModeloBase <|-- ModeloTenant
    ModeloBase <|-- Empresa
    ModeloBase <|-- Permiso
    ModeloBase <|-- Membresia
    ModeloBase <|-- Plan
    ModeloBase <|-- Suscripcion
    ModeloBase <|-- HistorialSuscripcion

    ModeloTenant <|-- Rol
    ModeloTenant <|-- Categoria
    ModeloTenant <|-- Producto
    ModeloTenant <|-- MovimientoInventario
    ModeloTenant <|-- Cliente
    ModeloTenant <|-- Factura
    ModeloTenant <|-- DetalleFactura
    ModeloTenant <|-- TurnoCaja
    ModeloTenant <|-- Pedido
    ModeloTenant <|-- Pago

    Usuario "1" -- "*" Membresia : participa
    Empresa "1" -- "*" Membresia : agrupa
    Rol "1" -- "*" Membresia : asigna
    Rol "*" -- "*" Permiso : contiene

    Empresa "1" -- "1" Suscripcion : posee
    Plan "1" -- "*" Suscripcion : define
    Suscripcion "1" -- "*" HistorialSuscripcion : audita

    Categoria "0..1" -- "*" Producto : clasifica
    Producto "1" -- "*" MovimientoInventario : registra
    Cliente "1" -- "*" Factura : recibe
    Factura "1" *-- "1..*" DetalleFactura : compone
    Producto "1" -- "*" DetalleFactura : referencia
    TurnoCaja "0..1" -- "*" Factura : cobra_en_pos
    Pedido "1" -- "0..1" Factura : genera
    Factura "0..1" -- "*" Pago : cobra
    Pedido "0..1" -- "*" Pago : cobra
```
