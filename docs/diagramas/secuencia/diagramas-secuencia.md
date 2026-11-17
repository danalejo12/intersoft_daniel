# Diagramas de Secuencia — InterSoft

Flujos detallados de interacción entre actores, vistas, servicios transaccionales y base de datos PostgreSQL.

## 1. Compra en Marketplace, Reserva de Stock y Pago Wompi

```mermaid
sequenceDiagram
    actor C as Comprador Web
    participant V as CheckoutView / Pagos
    participant R as Servicio Reservas
    participant DB as PostgreSQL (select_for_update)
    participant W as Pasarela Wompi
    participant S as Servicios Factura / Correo

    C->>V: Confirma carrito y datos de envío
    V->>R: crear_pedido() + reservar_stock()
    R->>DB: Bloquea filas Producto en orden por ID
    alt Stock suficiente
        DB-->>R: Descuenta stock temporalmente (30 min)
        R-->>V: Pedido en estado PENDIENTE
        V->>W: Redirige a Checkout con firma de integridad SHA-256
        C->>W: Completa el pago
        W-->>V: POST Webhook (transaction.updated)
        V->>V: Valida checksum HMAC y monto/moneda exactos
        alt Pago APPROVED y monto válido
            V->>S: crear_factura_desde_pedido()
            S->>DB: Crea Factura + DetalleFactura y marca Pedido PAGADO
            S-->>C: Envía correo de confirmación de pago
        else Monto o moneda alterados
            V->>DB: Libera stock y marca REQUIERE_REEMBOLSO
            V-->>C: Registra alerta CRITICAL para revisión
        end
    else Stock insuficiente
        DB-->>R: Rollback automático (@transaction.atomic)
        R-->>C: Informa producto sin unidades disponibles
    end
```

## 2. Cambio de Plan de Suscripción y Validación Multi-tenant

```mermaid
sequenceDiagram
    actor A as Administrador (Angular / Panel)
    participant MW as TenantMiddleware
    participant API as CambiarPlanAPIView / PanelView
    participant SRV as suscripciones.services
    participant DB as PostgreSQL

    A->>MW: POST /api/suscripcion/cambiar-plan/ (plan, ciclo)
    MW->>DB: Verifica Membresia activa del usuario
    MW-->>API: Inyecta request.empresa (aislamiento multi-tenant)
    API->>SRV: cambiar_plan(empresa, plan_destino, ciclo)
    SRV->>DB: Bloquea Suscripcion (select_for_update)
    SRV->>DB: Consulta uso_actual() (Productos activos + Membresías activas)

    alt Uso actual excede límites del plan destino (Downgrade inválido)
        SRV-->>API: Lanza DowngradeNoPermitido (excesos por recurso)
        API-->>A: HTTP 400 con detalle de qué recurso debe reducir
    else Uso dentro de límites
        SRV->>DB: Cuenta empresas con es_fundador=True
        opt Primeras 50 empresas con plan pago
            SRV->>SRV: Asigna es_fundador=True y descuento 50% de por vida
        end
        SRV->>DB: Actualiza Plan, Estado ACTIVA y vence_en (30 o 365 días)
        SRV->>DB: Inserta registro inmutable en HistorialSuscripcion
        SRV-->>API: Retorna suscripción actualizada
        API-->>A: HTTP 200 JSON con nuevo plan, vigencia y uso actual
    end
```

## 3. Punto de Venta (POS), Idempotencia y Traslado a Tesorería

```mermaid
sequenceDiagram
    actor CAJ as Cajero POS
    actor CON as Contador / Admin
    participant POS as VenderView / TurnoView
    participant CAJA as Servicio Caja (caja.py)
    participant FAC as Servicio Factura / Stock
    participant TES as Servicio Tesorería (erp_services)
    participant DB as PostgreSQL

    CAJ->>POS: Abre turno con base inicial
    POS->>CAJA: abrir_turno(empresa, usuario, base)
    CAJA->>DB: Crea TurnoCaja abierto (único por cajero)

    CAJ->>POS: Escanea productos, elige medios de pago y cobra (operacion_pos UUID)
    POS->>CAJA: registrar_venta(turno, items, pagos, operacion)
    CAJA->>DB: Bloquea TurnoCaja (select_for_update)

    alt operacion_pos ya existía (doble clic / reintento de red)
        DB-->>CAJA: Encuentra Factura previa
        CAJA-->>POS: Retorna Factura existente sin volver a descontar stock
    else Venta nueva
        CAJA->>FAC: crear_factura() (bloquea Productos, descuenta stock y crea Kardex)
        FAC->>DB: Guarda Factura + DetalleFactura + MovimientoInventario
        CAJA->>DB: Registra PagoCaja (Efectivo/Tarjeta/Transferencia) y calcula cambio
        CAJA-->>POS: Retorna Factura y enlace al Ticket
    end

    CAJ->>POS: Cierra caja contando efectivo (arqueo a ciegas)
    POS->>CAJA: cerrar_turno(contado)
    CAJA->>DB: Calcula efectivo_esperado y diferencia

    CON->>POS: Selecciona CuentaTesoreria y pulsa Trasladar efectivo
    POS->>TES: trasladar_turno_a_tesoreria(turno, cuenta)
    TES->>DB: Crea MovimientoTesoreria (ingreso) idempotente por turno.pk
```

## 4. Facturación Electrónica DIAN, Contabilidad PUC y Anulación (CUDE)

```mermaid
sequenceDiagram
    actor USU as Asesor / Contador
    participant FAC_V as FacturaDetailView
    participant DIAN as facturacion_electronica.py
    participant CONT as contabilidad_automatica.py
    participant SERV as services.anular_factura
    participant DB as PostgreSQL

    USU->>FAC_V: Solicita emitir factura electrónica DIAN
    FAC_V->>DIAN: emitir_factura_electronica(factura)
    DIAN->>DB: Bloquea Factura (select_for_update)
    DIAN->>DIAN: Calcula / solicita CUFE al proveedor DIAN
    DIAN->>DB: Guarda estado_dian=ACEPTADA, cufe, xml_url y pdf_url

    USU->>FAC_V: Pulsa Generar comprobante contable
    FAC_V->>CONT: contabilizar_factura(factura)
    CONT->>DB: Crea y confirma Asiento FACT-n (1305 Clientes vs 4135 Ingresos + 2408 IVA)
    opt Factura pagada (POS o Wompi)
        FAC_V->>CONT: contabilizar_recaudo_factura()
        CONT->>DB: Crea y confirma Asiento REC-FACT-n (1105 Caja/Bancos vs 1305 Clientes)
    end

    alt Anulación posterior de la factura
        USU->>FAC_V: Confirma anular factura
        FAC_V->>SERV: anular_factura(factura)
        SERV->>DB: Devuelve stock al Kardex y marca estado=ANULADA
        SERV->>CONT: reversar_asiento_factura()
        CONT->>DB: Genera Asiento inverso ANUL-FACT-n
        opt Factura tenía estado_dian=ACEPTADA
            SERV->>DIAN: emitir_nota_credito_electronica(factura)
            DIAN->>DB: Genera y guarda cude_nota_credito
        end
    end
```
