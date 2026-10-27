"""
Servicios de Intersoft: aquí vive la LÓGICA DE NEGOCIO.

Las vistas reciben la petición y llaman a un servicio; el servicio hace el trabajo
y garantiza la integridad. Así la misma lógica sirve para la web, una API o un comando.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import DetalleFactura, Empresa, Factura, MovimientoInventario, Producto

CENTAVOS = Decimal("0.01")


class StockInsuficiente(Exception):
    """Se intenta vender más unidades de las que hay."""


@transaction.atomic
def crear_factura(*, empresa, usuario, cliente, items):
    """
    Crea una factura completa: encabezado, líneas, descuento de stock y kardex.

    items = [{"producto": <Producto>, "cantidad": 2}, ...]

    @transaction.atomic = TODO O NADA. Si algo falla a mitad de camino,
    PostgreSQL deshace todo lo hecho dentro de la función.
    """
    if cliente.empresa_id != empresa.id:
        raise ValueError("El cliente no pertenece a esta empresa.")
    if not items:
        raise ValueError("La factura necesita al menos un producto.")

    # 1. Bloquear los productos que se van a vender.
    #    select_for_update = "nadie más toca estas filas hasta que yo termine".
    #    order_by("id") evita bloqueos cruzados (deadlocks) entre dos ventas simultáneas.
    ids = [item["producto"].id for item in items]
    productos = {
        p.id: p
        for p in Producto.objects.select_for_update()
        .filter(empresa=empresa, id__in=ids, activo=True)
        .order_by("id")
    }

    # 2. Validar TODO antes de escribir nada.
    for item in items:
        producto = productos.get(item["producto"].id)
        cantidad = int(item["cantidad"])
        if producto is None:
            raise ValueError("Producto inexistente, inactivo o de otra empresa.")
        if cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        if producto.stock < cantidad:
            raise StockInsuficiente(
                f"Stock insuficiente de {producto.nombre}: hay {producto.stock}, se piden {cantidad}."
            )

    # 3. Consecutivo sin duplicados: bloqueamos la fila de la empresa mientras numeramos.
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    ultimo = Factura.objects.filter(empresa=empresa).aggregate(m=Max("numero"))["m"] or 0
    factura = Factura.objects.create(
        empresa=empresa, numero=ultimo + 1, cliente=cliente, creada_por=usuario
    )

    # 4. Líneas, descuento de stock y kardex.
    subtotal = Decimal("0")
    iva = Decimal("0")
    for item in items:
        producto = productos[item["producto"].id]
        cantidad = int(item["cantidad"])
        valor_linea = producto.precio * cantidad
        subtotal += valor_linea
        iva += (valor_linea * producto.iva_porcentaje / 100).quantize(CENTAVOS)

        DetalleFactura.objects.create(
            empresa=empresa,
            factura=factura,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,          # precio CONGELADO al vender
            iva_porcentaje=producto.iva_porcentaje,
        )
        # F() resta DENTRO de PostgreSQL, no en Python
        Producto.objects.filter(pk=producto.pk).update(stock=F("stock") - cantidad)
        MovimientoInventario.objects.create(
            empresa=empresa,
            producto=producto,
            tipo=MovimientoInventario.Tipo.SALIDA,
            cantidad=cantidad,
            referencia=f"Factura {factura.numero}",
            usuario=usuario,
        )

    # 5. Totales
    factura.subtotal = subtotal.quantize(CENTAVOS)
    factura.iva = iva
    factura.total = (subtotal + iva).quantize(CENTAVOS)
    factura.save(update_fields=["subtotal", "iva", "total"])
    return factura


@transaction.atomic
def anular_factura(*, factura, usuario):
    """Una factura NUNCA se borra: se anula y la mercancía vuelve al inventario."""
    factura = Factura.objects.select_for_update().get(pk=factura.pk)
    if factura.estado == Factura.Estado.ANULADA:
        raise ValueError("La factura ya está anulada.")

    for detalle in factura.detalles.all():
        Producto.objects.filter(pk=detalle.producto_id).update(stock=F("stock") + detalle.cantidad)
        MovimientoInventario.objects.create(
            empresa_id=factura.empresa_id,
            producto_id=detalle.producto_id,
            tipo=MovimientoInventario.Tipo.ENTRADA,
            cantidad=detalle.cantidad,
            referencia=f"Anulación factura {factura.numero}",
            usuario=usuario,
        )

    factura.estado = Factura.Estado.ANULADA
    factura.anulada_en = timezone.now()
    factura.save(update_fields=["estado", "anulada_en"])
    return factura

@transaction.atomic
def registrar_movimiento(*, empresa, producto, tipo, cantidad, usuario, referencia=""):
    """
    Único punto por el que cambia el stock (fuera de la facturación).

    - ENTRADA y SALIDA reciben cantidad positiva.
    - AJUSTE puede ser positivo (sobrante) o negativo (faltante, daño, pérdida).
    """
    cantidad = int(cantidad)
    Tipo = MovimientoInventario.Tipo

    if tipo in (Tipo.ENTRADA, Tipo.SALIDA) and cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    if tipo == Tipo.AJUSTE and cantidad == 0:
        raise ValueError("Un ajuste no puede ser cero.")

    variacion = -cantidad if tipo == Tipo.SALIDA else cantidad

    # Bloqueamos el producto: si alguien factura al mismo tiempo, espera su turno
    producto = Producto.objects.select_for_update().get(pk=producto.pk, empresa=empresa)
    if producto.stock + variacion < 0:
        raise StockInsuficiente(
            f"El movimiento dejaría el stock de {producto.nombre} en negativo (disponible: {producto.stock})."
        )

    Producto.objects.filter(pk=producto.pk).update(stock=F("stock") + variacion)
    return MovimientoInventario.objects.create(
        empresa=empresa,
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        referencia=referencia,
        usuario=usuario,
    )