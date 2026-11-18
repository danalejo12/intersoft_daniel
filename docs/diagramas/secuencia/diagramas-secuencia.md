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

## 5. Compra Unificada en Varios Negocios (`Orden` + `Pedido`)

```mermaid
sequenceDiagram
    actor C as Comprador Web
    participant V as CheckoutTodoView (/comprar/)
    participant R as Servicio Reservas / Bodegas
    participant DB as PostgreSQL

    C->>V: Envía formulario único de envío para N negocios
    V->>DB: Inicia @transaction.atomic y crea Orden(comprador)
    loop Por cada negocio en el carrito
        V->>R: reservar_bodega_en_linea(empresa, items)
        R->>DB: Bloquea Existencia en Bodega(vende_en_linea=True)
        alt Stock suficiente en la bodega en línea
            R->>DB: Crea Pedido(orden=orden, bodega=bodega_linea, estado=PENDIENTE)
        else Sin stock
            R-->>V: Lanza StockInsuficiente (rollback total de Orden y Pedidos)
        end
    end
    V-->>C: Redirige a /compras/<orden_id>/ para pagar cada negocio por separado en Wompi
```

## 6. Pago de un Plan con Wompi (Retorno, Webhook y Conciliación)

```mermaid
sequenceDiagram
    actor A as Administrador
    participant PAN as SuscripcionPanelView / CobroSuscripcionView
    participant COB as suscripciones.cobros
    participant WH as WompiWebhookSuscripcionesView
    participant SRV as cambiar_plan()
    participant DB as PostgreSQL

    A->>PAN: Selecciona plan pago y ciclo
    PAN->>COB: iniciar_cobro() -> crea CobroSuscripcion(pendiente)
    PAN-->>A: Redirige a Checkout Wompi con firma SHA-256
    alt Camino 1: Retorno del navegador
        A->>PAN: GET /panel/suscripcion/cobros/<id>/?id=tx
        PAN->>COB: sincronizar_cobro(cobro, transaccion_id)
    else Camino 2: Webhook firmado Wompi
        WH->>WH: Valida checksum HMAC-SHA256
        WH->>COB: aplicar_transaccion(tx)
    else Camino 3: Tarea periódica
        COB->>COB: conciliar_cobros_suscripcion -> sincronizar_cobro(forzar=True)
    end
    COB->>DB: Bloquea CobroSuscripcion (select_for_update)
    alt APPROVED y monto/moneda coinciden
        COB->>SRV: cambiar_plan(empresa, plan, ciclo, forzar_fundador)
        SRV->>DB: Activa Suscripcion y registra HistorialSuscripcion
        COB->>DB: Marca CobroSuscripcion = aprobado
    else Discrepancia o DowngradeNoPermitido
        COB->>DB: Marca CobroSuscripcion = requiere_revision
    end
```

## 7. Traslado entre Bodegas

```mermaid
sequenceDiagram
    actor BOD as Bodega / Inventario
    participant V as TrasladoView
    participant S as core.bodegas.trasladar()
    participant DB as PostgreSQL

    BOD->>V: POST /panel/productos/<id>/trasladar/ (origen, destino, cantidad)
    V->>S: trasladar(empresa, producto, origen, destino, cantidad)
    S->>DB: Valida ambas bodegas activas de la empresa
    S->>DB: Bloquea Existencia origen y destino en orden por ID
    alt Existencia en origen >= cantidad
        S->>DB: Resta en origen y suma en destino (Producto.stock sin cambio)
        S->>DB: Registra MovimientoInventario(tipo=TRASLADO)
        S-->>BOD: Confirmación de traslado exitoso
    else Stock insuficiente en origen
        S-->>V: StockInsuficiente -> muestra error en formulario
    end
```

## 8. Venta POS desde una Bodega

```mermaid
sequenceDiagram
    actor CAJ as Cajero POS
    participant V as AbrirTurnoView / VenderView
    participant C as core.caja
    participant B as core.bodegas
    participant DB as PostgreSQL

    CAJ->>V: Abre turno eligiendo Bodega
    V->>DB: Crea TurnoCaja(empresa, cajero, bodega)
    CAJ->>V: Confirma venta POS (clave_operacion UUID)
    V->>C: vender_pos(turno, items, pagos)
    C->>B: mover(producto, bodega=turno.bodega, variacion=-qty)
    B->>DB: Descuenta Existencia de esa bodega y recalcula Producto.stock
    C->>DB: Crea Factura(bodega=turno.bodega), DetalleFactura y PagoCaja
    C-->>CAJ: Devuelve ticket POS
```

## 9. Tareas Periódicas (`core/tareas.py` + `EjecucionTarea`)

```mermaid
sequenceDiagram
    participant CRON as Scheduler / cron (tareas_periodicas)
    participant T as core.tareas.ejecutar_pendientes()
    participant DB as PostgreSQL (EjecucionTarea)
    participant CMD as Comando Django

    CRON->>T: Ejecuta pasada (cada 60s o 5 min)
    loop Por cada Tarea en TAREAS
        T->>DB: UPDATE condicional EjecucionTarea WHERE ultima_ejecucion <= ahora - cada
        alt Ganó el turno
            T->>CMD: call_command(tarea.comando)
            alt Éxito
                T->>DB: Actualiza ultimo_resultado, fallos_seguidos=0, ejecuciones+=1
            else Excepción
                T->>DB: Registra ultimo_error, fallos_seguidos+=1 (CRITICAL si == 3)
            end
        else Omitida (aún no le toca)
            T->>T: Continúa con la siguiente tarea
        end
    end
```
