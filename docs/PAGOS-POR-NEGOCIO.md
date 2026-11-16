# Pagos directos a cada negocio

Las ventas del marketplace y el cobro de facturas usan exclusivamente la cuenta de Wompi del negocio. Los precios y los cobros de membresía quedan pendientes de definición; no se activa ninguna suscripción.

## Puesta en marcha

1. Instalar `requirements.txt`.
2. Configurar `PAGOS_CLAVES_CIFRADO` con una clave Fernet independiente y respaldarla de forma segura. Sin esta variable se usa una derivación de `SECRET_KEY`; `check --deploy` advierte de esta situación. No cambiar `SECRET_KEY` mientras existan datos cifrados con esa derivación.
3. Antes de migrar, conservar las llaves Wompi antiguas en el entorno para que la migración 0021 pueda guardar una instantánea cifrada de los cobros históricos. No se copian a la configuración de ningún negocio. Si faltan esas llaves, los intentos antiguos requieren conciliación manual.
4. Ejecutar `python intersoft/manage.py migrate` y `python intersoft/manage.py sincronizar_permisos`.
5. Cada administrador entra a **Panel → Negocio → Pagos**, guarda sus llaves, verifica y activa los cobros. El modo se identifica por los prefijos de las llaves y no permite mezclar pruebas y producción.
6. Configurar en el comercio de Wompi la URL HTTPS mostrada en esa pantalla: `/webhooks/wompi/<uuid-del-negocio>/`. Probar un pago en sandbox antes de usar producción.

La verificación consulta la llave pública y, si se proporcionó, la privada. Wompi no permite verificar los secretos de integridad y eventos mediante esas consultas; se valida su formato y su funcionamiento se comprueba con un pago de prueba. La llave privada es opcional, pero se recomienda para conciliar por referencia y permitir cancelaciones seguras de pedidos con intentos pendientes.

## Seguridad y conciliación

- Los secretos se guardan cifrados; los campos de edición no los devuelven y muestran solamente los últimos cuatro caracteres.
- Se exige `pagos.configurar`. Guardar, verificar, activar, pausar y eliminar dejan un registro en `AuditoriaPagos`, con actor y nombres de campos, sin valores secretos.
- Cambiar las llaves invalida la verificación y pausa los cobros. Una verificación en curso no puede validar llaves reemplazadas durante la consulta.
- Cada intento conserva una instantánea cifrada de sus credenciales. Cambiar, pausar o eliminar la configuración impide nuevos cobros, pero permite conciliar intentos anteriores.
- El webhook comprueba la firma con el secreto del intento, limita la búsqueda al negocio y obtiene la transacción desde la API antes de aplicarla. Monto, moneda e idempotencia se comprueban en el servicio de pagos. Si Wompi no responde se devuelve 503 para pedir un reintento.
- El retorno del comprador se concilia con la llave privada del comercio. El ID público de una transacción no demuestra quién recibió el dinero; sin llave privada se espera el webhook firmado.
- La URL antigua `/webhooks/wompi/` atiende exclusivamente intentos históricos con su instantánea. Nunca consulta las llaves actuales de `.env` para aprobar ventas nuevas. El simulador de facturas sigue limitado a `DEBUG=True`.
- Los pedidos antiguos no se vuelven a cobrar con una cuenta distinta: requieren crear un pedido nuevo. Sus comisiones y registros de dispersión siguen disponibles como historial.

## Tarifas

Por negocio se configura el porcentaje, el valor fijo y si se traslada el cargo al comprador. El mismo cálculo se usa en catálogo, carrito y pedido; el importe del pedido queda congelado. El IVA de la tarifa se toma de `WOMPI_TARIFA_IVA`.

Los pedidos nuevos tienen comisión de Intersoft en cero y no admiten registrar una dispersión. Si el negocio asume la tarifa, el valor mostrado antes de descuentos no representa su liquidación bancaria definitiva: Wompi puede descontar tarifas y retenciones.

## Rotación del cifrado

1. Agregar la nueva clave al inicio de `PAGOS_CLAVES_CIFRADO`, manteniendo la anterior separada por coma, y reiniciar todos los procesos que pueden crear cobros antes de ejecutar el recifrado.
2. Ejecutar `python intersoft/manage.py rotar_secretos_pago`. Recifra tanto configuraciones como instantáneas de pagos dentro de una transacción; ante una clave ilegible no guarda cambios parciales.
3. Retirar la clave anterior solamente después de completar el comando y verificar el respaldo.

Al pasar desde la derivación de `SECRET_KEY`, configurar primero la nueva clave maestra y ejecutar `python intersoft/manage.py rotar_secretos_pago --desde-secret-key`, conservando la misma `SECRET_KEY` hasta completar el comando. No retirar una clave necesaria para restaurar respaldos antiguos sin conservarla de forma segura.

Referencias: [Eventos de Wompi](https://docs.wompi.co/docs/colombia/eventos/), [Transacciones](https://docs.wompi.co/docs/colombia/transacciones/).
