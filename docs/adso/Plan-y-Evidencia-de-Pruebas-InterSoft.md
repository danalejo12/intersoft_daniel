# Plan y Evidencia de Pruebas de Software — InterSoft
## Proyecto ADSO — SENA

---

## 1. Estrategia y Tipos de Pruebas Aplicados

| Tipo de Prueba | Alcance en InterSoft | Herramientas |
| :--- | :--- | :--- |
| **Pruebas Unitarias** | Servicios puros de IVA, comisiones, aportes de nómina colombiana, validaciones de formularios y límites de plan. | `django.test.TestCase` |
| **Pruebas de Integración** | Flujos completos: POS + stock + tesorería; Compra + kardex + cartera + asiento PUC; Factura + DIAN + Nota Crédito; Checkout + Webhook Wompi; Cambio de plan + historial. | `TestCase`, `APIClient` (DRF) |
| **Pruebas de Concurrencia** | Ventas simultáneas por última unidad y reintentos idempotentes con hilos paralelos (`threading.Barrier`). | `TransactionTestCase` |
| **Pruebas de Seguridad** | Aislamiento multi-tenant entre empresas, control RBAC (403), bloqueo `django-axes` (429), validación HMAC de webhooks y chequeo `check --deploy`. | `TestCase`, `django.core.checks` |

---

## 2. Matriz de Casos de Prueba (Caja Negra y Automatizados)

| ID | Módulo | Caso de Prueba | Entrada / Acción | Resultado Esperado | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CP-01** | Seguridad / Login | Bloqueo por fuerza bruta (`django-axes`) | 5 intentos fallidos con distinto uso de mayúsculas desde misma IP | Al 6.º intento responde HTTP `429` y no bloquea otros correos de la misma IP. | **APROBADO** |
| **CP-02** | Autenticación | Recuperación de contraseña | Solicitud en `/recuperar-contrasena/` + confirmación con token | Envía correo con token, valida nueva clave y actualiza hash en BD. | **APROBADO** |
| **CP-03** | Multi-tenant | Aislamiento entre Empresa A y Empresa B | Usuario A intenta editar/borrar cliente o cambiar suscripción de Empresa B | HTTP `404` en panel y aislamiento total al `empresa_id` propio en API. | **APROBADO** |
| **CP-04** | Inventario | Movimiento negativo prohibido | Ajuste de salida mayor al stock disponible | Lanza `StockInsuficiente`, revierte transacción y mantiene kardex intacto. | **APROBADO** |
| **CP-05** | POS | Doble clic / reintento concurrente | 2 hilos envían la misma venta con igual `operacion_pos` UUID | Crea una sola factura, descuenta stock una sola vez y retorna idempotente. | **APROBADO** |
| **CP-06** | POS → Tesorería | Traslado de cierre de caja | Trasladar turno cerrado con efectivo contado positivo | Crea un único `MovimientoTesoreria` de ingreso (`operacion=turno.pk`). | **APROBADO** |
| **CP-07** | DIAN + Contabilidad | Emisión, contabilización y anulación | Emitir factura → DIAN (`CUFE`) → contabilizar → anular | Genera asiento `ANUL-FACT-n`, Nota Crédito (`CUDE`) y saldo `1305 = 0.00`. | **APROBADO** |
| **CP-08** | Marketplace / Wompi | Pago con monto alterado en webhook | Webhook `APPROVED` con `amount_in_cents` distinto al pedido | Libera stock, pasa pedido a `REQUIERE_REEMBOLSO` y emite alerta `CRITICAL`. | **APROBADO** |
| **CP-09** | Suscripciones | Prueba gratis, comisión y límites | Crear empresa → verificar `TRIAL` 14 días → calcular comisión → exceder límite | Comisión `POS=0`, `MARKETPLACE` según plan; exceso devuelve HTTP `403` JSON estándar. | **APROBADO** |
| **CP-10** | Suscripciones | Downgrade con uso superior al límite | Empresa con 25 productos intenta bajar a plan `gratis` (máx 20) | Rechaza con `DowngradeNoPermitido` indicando reducir 5 productos. | **APROBADO** |
| **CP-11** | Cron / Comandos | Idempotencia de comandos | Ejecutar 2 veces `verificar_suscripciones` y `procesar_reservas_y_alertas` | 1.ª ejecución procesa vencidos; 2.ª ejecución procesa `0` sin duplicar historial. | **APROBADO** |
| **CP-12** | Despliegue | Chequeo de producción Django | `checks.run_checks(include_deployment_checks=True)` | `0` errores y `0` advertencias bloqueantes. | **APROBADO** |

---

## 3. Evidencia de Ejecución en Consola

```text
> C:\Python314\python.exe manage.py check
System check identified no issues (0 silenced).

> C:\Python314\python.exe manage.py test core suscripciones --noinput
Ran 433+ tests ... OK
```

Las suites se encuentran distribuidas por dominio en:
- `intersoft/core/tests.py`, `tests_cimientos.py`, `tests_compra.py`, `tests_equipo.py`, `tests_erp.py`, `tests_marketplace.py`, `tests_pagos_negocio.py`, `tests_pasarela_directa.py`, `tests_pedidos.py`, `tests_pos.py`, `tests_tarifas.py`, `tests_catalogo.py`, `tests_bienvenida.py`, `tests_mejoras.py`.
- `intersoft/suscripciones/tests.py`.
