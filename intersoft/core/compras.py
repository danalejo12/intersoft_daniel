"""Compra en el marketplace: el pedido reserva el stock y la factura nace al aprobarse el pago."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import bodegas, reservas
from .impuestos import CENTAVOS, calcular_iva
from .models import Comentario, CuponTienda, DetallePedido, Orden, Pago, Pedido, Producto
from .pagos import PagoNoPermitido, ResultadoWompi, revisar_en_wompi, sincronizar_pago
from .pasarelas import PasarelaNoDisponible, configuracion_activa, credenciales_negocio
from .services import StockInsuficiente, siguiente_consecutivo
from .tarifas import cargo_pasarela

Estado = Pedido.Estado
MINIMO_COBRABLE_WOMPI = Decimal("1500.00")


class OperacionNoPermitida(Exception):
    """El mensaje se le muestra al comprador."""


def _nuevo_vencimiento():
    return timezone.now() + timedelta(minutes=settings.PEDIDO_MINUTOS_RESERVA)


def calcular_costo_envio(*, negocio, total_productos, peso_total_gramos=0):
    """Calcula el costo de envío según tarifa base, peso total y umbral de envío gratis del negocio."""
    base = negocio.tarifa_envio_base or Decimal("0")
    por_kg = negocio.tarifa_envio_por_kg or Decimal("0")
    gratis_desde = negocio.envio_gratis_desde or Decimal("0")
    if base <= 0 and por_kg <= 0:
        return Decimal("0.00")
    if gratis_desde > 0 and total_productos >= gratis_desde:
        return Decimal("0.00")
    peso = max(int(peso_total_gramos or 0), 0)
    kilos = Decimal((peso + 999) // 1000) if peso > 0 else Decimal("0")
    return (base + por_kg * kilos).quantize(CENTAVOS)


def evaluar_cupon(*, negocio, codigo, total_productos):
    """Valida un código de cupón de tienda sin modificar usos; devuelve (cupon, descuento)."""
    limpio = (codigo or "").strip().upper()
    if not limpio:
        return None, Decimal("0.00")
    cupon = CuponTienda.objects.filter(empresa=negocio, codigo=limpio).first()
    if cupon is None:
        raise OperacionNoPermitida("El cupón ingresado no existe para este negocio.")
    try:
        cupon.validar_para(total_productos)
    except ValueError as error:
        raise OperacionNoPermitida(str(error)) from None
    descuento = cupon.calcular_descuento(total_productos)
    if total_productos - descuento < MINIMO_COBRABLE_WOMPI:
        raise OperacionNoPermitida(
            "El descuento deja el pedido por debajo del mínimo cobrable en Wompi ($ 1.500). "
            "Agrega más productos o usa otro cupón."
        )
    return cupon, descuento


@transaction.atomic
def crear_pedido(*, usuario, negocio, lineas, datos, codigo_cupon=""):
    """Crea el pedido con precios congelados y reserva el stock: todo o nada. No crea factura."""
    try:
        credenciales_negocio(negocio.pk)
    except PasarelaNoDisponible as error:
        raise PagoNoPermitido(str(error)) from None

    max_pendientes = getattr(settings, "PEDIDO_MAX_PENDIENTES_POR_COMPRADOR", 5)
    if max_pendientes > 0:
        pendientes_activos = Pedido.objects.filter(
            comprador=usuario,
            estado=Estado.PENDIENTE,
            expira_en__gt=timezone.now(),
        ).count()
        if pendientes_activos >= max_pendientes:
            raise OperacionNoPermitida(
                "Tienes varios pedidos pendientes de pago. Completa o cancela alguno antes de crear uno nuevo."
            )

    config = configuracion_activa(negocio.pk)
    # Productos primero y empresa después, el mismo orden de crear_factura, para evitar bloqueos cruzados
    cantidades = {linea["producto"].pk: linea["cantidad"] for linea in lineas}
    productos = list(
        Producto.objects.select_for_update()
        .filter(empresa=negocio, id__in=cantidades, activo=True)
        .order_by("id")
    )
    if len(productos) != len(cantidades):
        raise ValueError("Producto inexistente, inactivo o de otro negocio.")

    subtotal = iva = Decimal("0")
    peso_total_gramos = 0
    for producto in productos:  # misma fórmula de services.crear_factura
        cantidad = cantidades[producto.pk]
        valor = producto.precio * cantidad
        subtotal += valor
        iva += calcular_iva(valor, producto.iva_porcentaje)
        peso_total_gramos += (producto.peso_gramos or 0) * cantidad

    subtotal_redondeado = subtotal.quantize(CENTAVOS)
    total_productos = (subtotal_redondeado + iva).quantize(CENTAVOS)

    cupon_aplicado = None
    descuento = Decimal("0.00")
    codigo_limpio = (codigo_cupon or "").strip().upper()
    if codigo_limpio:
        cupon_aplicado = (
            CuponTienda.objects.select_for_update()
            .filter(empresa=negocio, codigo=codigo_limpio)
            .first()
        )
        if cupon_aplicado is None:
            raise OperacionNoPermitida("El cupón ingresado no existe para este negocio.")
        try:
            cupon_aplicado.validar_para(total_productos)
        except ValueError as error:
            raise OperacionNoPermitida(str(error)) from None
        descuento = cupon_aplicado.calcular_descuento(total_productos)

    total_productos_neto = max(total_productos - descuento, Decimal("0.00")).quantize(CENTAVOS)
    costo_envio = calcular_costo_envio(
        negocio=negocio,
        total_productos=total_productos_neto,
        peso_total_gramos=peso_total_gramos,
    )
    antes_de_pasarela = (total_productos_neto + costo_envio).quantize(CENTAVOS)
    if cupon_aplicado is not None and antes_de_pasarela < MINIMO_COBRABLE_WOMPI:
        raise OperacionNoPermitida(
            "El descuento deja el pedido por debajo del mínimo cobrable en Wompi ($ 1.500). "
            "Agrega más productos o usa otro cupón."
        )
    cargo = cargo_pasarela(antes_de_pasarela, config=config) if antes_de_pasarela > 0 else Decimal("0.00")
    total = (antes_de_pasarela + cargo).quantize(CENTAVOS)
    comision_porcentaje = Decimal("0.00")
    comision_valor = Decimal("0.00")
    # El cargo de la pasarela se lo queda Wompi, no el negocio
    neto_vendedor = (total - cargo - comision_valor).quantize(CENTAVOS)

    pedido = Pedido.objects.create(
        empresa=negocio,
        bodega=bodegas.bodega_en_linea(negocio),
        pago_directo=True,
        comprador=usuario,
        numero=siguiente_consecutivo(Pedido, negocio),
        expira_en=_nuevo_vencimiento(),
        subtotal=subtotal_redondeado,
        iva=iva,
        cupon=cupon_aplicado,
        cupon_codigo=cupon_aplicado.codigo if cupon_aplicado else "",
        descuento=descuento,
        costo_envio=costo_envio,
        cargo_pasarela=cargo,
        total=total,
        peso_total_gramos=peso_total_gramos,
        comision_porcentaje=comision_porcentaje,
        comision_valor=comision_valor,
        neto_vendedor=neto_vendedor,
        tipo_documento=datos["tipo_documento"],
        numero_documento=datos["numero_documento"],
        nombre=datos["nombre"],
        email=datos["email"],
        telefono=datos["telefono"],
        departamento=datos["departamento"],
        ciudad=datos["ciudad"],
        direccion=datos["direccion"],
        indicaciones=datos["indicaciones"],
    )
    if cupon_aplicado is not None:
        CuponTienda.objects.filter(pk=cupon_aplicado.pk).update(usos_actuales=F("usos_actuales") + 1)
    for producto in productos:
        DetallePedido.objects.create(
            empresa=negocio,
            pedido=pedido,
            producto=producto,
            cantidad=cantidades[producto.pk],
            precio_unitario=producto.precio,
            iva_porcentaje=producto.iva_porcentaje,
        )
    reservas.reservar_stock(pedido)
    return pedido


@transaction.atomic
def crear_orden(*, usuario, grupos, datos):
    """Un checkout para varios negocios: crea un pedido por negocio con los mismos datos de envío.
    Todo o nada: si un negocio no puede vender (stock, pasarela), no se crea ningún pedido.
    Los negocios se procesan por id para que dos compras simultáneas bloqueen filas en el mismo orden."""
    if not grupos:
        raise ValueError("No hay productos para comprar.")
    orden = Orden.objects.create(comprador=usuario)
    for grupo in sorted(grupos, key=lambda g: str(g["negocio"].pk)):
        pedido = crear_pedido(usuario=usuario, negocio=grupo["negocio"], lineas=grupo["lineas"], datos=datos)
        Pedido.objects.filter(pk=pedido.pk).update(orden=orden)
    return orden


def actualizar_pagos(pedido, transaccion_id="", forzar=False):
    """Le pregunta a Wompi por los intentos sin respuesta. El navegador nunca decide el estado.
    forzar=True salta la espera de 10 s: se usa justo antes de cobrar."""
    for pago in pedido.pagos.filter(estado=Pago.Estado.PENDIENTE):
        sincronizar_pago(pago=pago, transaccion_id=transaccion_id, forzar=forzar)
    pedido.refresh_from_db()  # aplicar_transaccion trabaja sobre su propia copia bloqueada


def cancelar_pedido(pedido):
    """Solo se cancela si Wompi confirma que ningún intento sigue vivo."""
    resultado = revisar_en_wompi(pedido)
    if resultado == ResultadoWompi.APROBADO:
        raise OperacionNoPermitida("Tu pago ya fue aprobado, así que este pedido no se puede cancelar.")
    if resultado == ResultadoWompi.EN_PROCESO:
        raise OperacionNoPermitida("Tu pago sigue en proceso en Wompi. Espera el resultado antes de cancelar.")
    if resultado == ResultadoWompi.SIN_RESPUESTA:
        raise OperacionNoPermitida("No pudimos confirmar tu pago con Wompi. Inténtalo de nuevo en un momento.")

    with transaction.atomic():
        bloqueado = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if bloqueado.estado != Estado.PENDIENTE:
            raise OperacionNoPermitida("Este pedido ya no se puede cancelar.")
        reservas.liberar_pedido(bloqueado, Estado.CANCELADO)


def vencer_pedido(pedido_id):
    """Vence un pedido si corresponde. Devuelve qué pasó: vencido, pagado, esperando u omitido."""
    ahora = timezone.now()
    pedido = Pedido.objects.get(pk=pedido_id)
    # Fuera de cualquier bloqueo: no se retiene una fila mientras se espera a Wompi
    resultado = revisar_en_wompi(pedido)
    if resultado == ResultadoWompi.APROBADO:
        return "pagado"
    espera = timedelta(minutes=settings.PEDIDO_MAX_ESPERA_PENDIENTE_MINUTOS)
    if resultado == ResultadoWompi.EN_PROCESO and ahora < pedido.expira_en + espera:
        return "esperando"
    # Si Wompi no responde también se vence: un pago que llegue después lo cubre el aprobado tardío
    with transaction.atomic():
        # skip_locked: si otra ejecución ya lo tomó, esta sigue con el siguiente
        bloqueado = (
            Pedido.objects.select_for_update(skip_locked=True)
            .filter(pk=pedido_id, estado=Estado.PENDIENTE, expira_en__lte=ahora)
            .first()
        )
        if bloqueado is None:
            return "omitido"
        reservas.liberar_pedido(bloqueado, Estado.VENCIDO)
    return "vencido"


@transaction.atomic
def renovar_reserva(pedido):
    """Amplía el plazo de un pedido pendiente o vencido (volviendo a reservar stock si hace falta),
    hasta PEDIDO_MAX_RENOVACIONES veces.
    """
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if not pedido.pago_directo:
        raise OperacionNoPermitida("Este pedido usa el cobro anterior. Crea un pedido nuevo.")
    if pedido.renovaciones >= settings.PEDIDO_MAX_RENOVACIONES:
        raise OperacionNoPermitida("Ya renovaste esta reserva las veces permitidas. Puedes hacer un pedido nuevo.")

    if pedido.estado == Estado.VENCIDO:
        # El stock se había liberado: hay que volver a reservarlo con lo que haya hoy
        try:
            with transaction.atomic():
                reservas.reservar_stock(pedido)
        except StockInsuficiente:
            raise OperacionNoPermitida("Lo sentimos, ya no hay unidades suficientes para este pedido.") from None
    elif pedido.estado == Estado.PENDIENTE:
        if not pedido.necesita_renovar:
            raise OperacionNoPermitida("Tu reserva sigue vigente, no hace falta renovarla.")
        if reservas.hay_productos_inactivos(pedido):
            raise OperacionNoPermitida("Lo sentimos, un producto de este pedido ya no está disponible.")
    else:
        raise OperacionNoPermitida("Este pedido ya no se puede renovar.")

    pedido.estado = Estado.PENDIENTE
    pedido.expira_en = _nuevo_vencimiento()
    pedido.renovaciones += 1
    pedido.save(update_fields=["estado", "expira_en", "renovaciones", "actualizado_en"])
    return pedido


def compro_el_producto(usuario, producto):
    return DetallePedido.objects.filter(
        producto=producto,
        pedido__comprador=usuario,
        pedido__estado=Estado.PAGADO,
    ).exists()


def guardar_comentario(*, usuario, producto, calificacion, texto):
    """Una opinión por persona y producto: si ya existe, se actualiza."""
    return Comentario.objects.update_or_create(
        producto=producto,
        autor=usuario,
        defaults={
            "empresa_id": producto.empresa_id,
            "calificacion": calificacion,
            "texto": texto,
            "compra_verificada": compro_el_producto(usuario, producto),
        },
    )[0]
