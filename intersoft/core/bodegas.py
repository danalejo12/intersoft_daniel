"""Stock por bodega. ÚNICO lugar que cambia Existencia, y siempre junto con Producto.stock.

Invariante: Producto.stock == suma de sus existencias en todas las bodegas.

Orden de bloqueo (evita bloqueos cruzados): primero el Producto (select_for_update, lo hacen quienes
llaman), después su Existencia. Todas las rutas que mueven stock bloquean el producto primero.
"""
import logging

from django.db import IntegrityError, transaction
from django.db.models import F, Sum

from .models import Bodega, Existencia, Producto

logger = logging.getLogger(__name__)


def bodega_principal(empresa):
    """La Principal del negocio; se crea si falta (negocios registrados después de la migración)."""
    bodega = Bodega.objects.filter(empresa=empresa, es_principal=True).first()
    if bodega is not None:
        return bodega
    try:
        with transaction.atomic():
            return Bodega.objects.create(
                empresa=empresa, nombre="Principal", es_principal=True,
                vende_en_linea=not Bodega.objects.filter(empresa=empresa, vende_en_linea=True).exists(),
            )
    except IntegrityError:  # otra petición la creó al mismo tiempo
        return Bodega.objects.get(empresa=empresa, es_principal=True)


def bodega_en_linea(empresa):
    """De dónde reserva stock el marketplace."""
    return Bodega.objects.filter(empresa=empresa, vende_en_linea=True, activa=True).first() or bodega_principal(empresa)


def validar_bodega(empresa, bodega):
    if bodega is None:
        return bodega_principal(empresa)
    if bodega.empresa_id != empresa.pk:
        raise ValueError("La bodega no pertenece a este negocio.")
    if not bodega.activa:
        raise ValueError(f"La bodega {bodega.nombre} está inactiva.")
    return bodega


def cuadrar(producto):
    """Si Producto.stock no coincide con la suma de existencias (producto creado con stock inicial,
    o editado desde /admin/), asigna la diferencia a la Principal. El producto debe estar bloqueado."""
    total = Existencia.objects.filter(producto=producto).aggregate(t=Sum("cantidad"))["t"] or 0
    # De la base, no del objeto: otro movimiento de esta misma transacción pudo cambiarlo con F()
    stock = Producto.objects.filter(pk=producto.pk).values_list("stock", flat=True).get()
    diferencia = stock - total
    if diferencia == 0:
        return
    principal = bodega_principal(producto.empresa)
    if diferencia > 0:
        fila, _ = Existencia.objects.get_or_create(
            empresa_id=producto.empresa_id, bodega=principal, producto=producto, defaults={"cantidad": 0})
        Existencia.objects.filter(pk=fila.pk).update(cantidad=F("cantidad") + diferencia)
        return
    # Hay menos stock total que en las bodegas: se descuenta empezando por la Principal
    logger.warning("Stock de %s menor que sus existencias; se ajustan las bodegas (%s)", producto.pk, diferencia)
    faltante = -diferencia
    for fila in (Existencia.objects.select_for_update().filter(producto=producto, cantidad__gt=0)
                 .order_by("-bodega__es_principal", "bodega__nombre")):
        quitar = min(fila.cantidad, faltante)
        Existencia.objects.filter(pk=fila.pk).update(cantidad=F("cantidad") - quitar)
        faltante -= quitar
        if not faltante:
            break


def _sin_asignar(productos):
    """{producto_id: unidades del total que todavía no están en ninguna bodega} (se cuentan en la Principal)."""
    asignado = dict(
        Existencia.objects.filter(producto__in=productos).values("producto_id")
        .annotate(t=Sum("cantidad")).values_list("producto_id", "t")
    )
    return {p.pk: max(p.stock - asignado.get(p.pk, 0), 0) for p in productos}


def existencias_por_producto(bodega, productos):
    """{producto_id: unidades disponibles en la bodega}, sin escribir nada. Útil para mostrar."""
    productos = list(productos)
    datos = dict(
        Existencia.objects.filter(bodega=bodega, producto__in=productos).values_list("producto_id", "cantidad")
    )
    if bodega.es_principal:
        for pk, extra in _sin_asignar(productos).items():
            datos[pk] = datos.get(pk, 0) + extra
    return {p.pk: datos.get(p.pk, 0) for p in productos}


def existencia(producto, bodega) -> int:
    return existencias_por_producto(bodega, [producto])[producto.pk]


def mover(*, producto, bodega, variacion, error=None):
    """Suma (o resta) unidades del producto en la bodega y en su total.
    El producto ya debe estar bloqueado por quien llama. Lanza `error` si quedaría negativo."""
    from .services import StockInsuficiente

    if variacion == 0:
        return
    cuadrar(producto)
    fila, _ = Existencia.objects.get_or_create(
        empresa_id=producto.empresa_id, bodega=bodega, producto=producto, defaults={"cantidad": 0}
    )
    fila = Existencia.objects.select_for_update().get(pk=fila.pk)
    if fila.cantidad + variacion < 0:
        raise (error or StockInsuficiente)(
            f"Stock insuficiente de {producto.nombre} en {bodega.nombre}: hay {fila.cantidad}, "
            f"se piden {-variacion}."
        )
    Existencia.objects.filter(pk=fila.pk).update(cantidad=F("cantidad") + variacion)
    Producto.objects.filter(pk=producto.pk).update(stock=F("stock") + variacion)


@transaction.atomic
def trasladar(*, empresa, producto, origen, destino, cantidad, usuario):
    """Pasa unidades de una bodega a otra. El total del producto no cambia; el kardex registra
    la salida del origen y la entrada al destino con la misma referencia."""
    from .models import MovimientoInventario

    cantidad = int(cantidad)
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    origen = validar_bodega(empresa, origen)
    destino = validar_bodega(empresa, destino)
    if origen.pk == destino.pk:
        raise ValueError("El origen y el destino deben ser bodegas distintas.")
    producto = Producto.objects.select_for_update().get(pk=producto.pk, empresa=empresa)
    referencia = f"Traslado {origen.nombre} → {destino.nombre}"[:60]
    mover(producto=producto, bodega=origen, variacion=-cantidad)
    mover(producto=producto, bodega=destino, variacion=cantidad)
    for bodega, tipo in ((origen, MovimientoInventario.Tipo.SALIDA), (destino, MovimientoInventario.Tipo.ENTRADA)):
        MovimientoInventario.objects.create(
            empresa=empresa, producto=producto, bodega=bodega, tipo=tipo, cantidad=cantidad,
            referencia=referencia, usuario=usuario,
        )


# ---------- Administración de bodegas ----------
FUNCION_MULTISEDE = "multisede"


class OperacionBodega(Exception):
    """El mensaje se le muestra al usuario del panel."""


def permite_varias_bodegas(empresa) -> bool:
    from suscripciones.services import crear_suscripcion_inicial

    return crear_suscripcion_inicial(empresa).puede(FUNCION_MULTISEDE)


def _asignar_roles(bodega, *, es_principal, vende_en_linea):
    """Mueve las marcas Principal / Vende en línea a esta bodega (quitándolas de la otra)."""
    otras = Bodega.objects.filter(empresa_id=bodega.empresa_id).exclude(pk=bodega.pk)
    if es_principal:
        otras.filter(es_principal=True).update(es_principal=False)
        bodega.es_principal = True
    if vende_en_linea:
        otras.filter(vende_en_linea=True).update(vende_en_linea=False)
        bodega.vende_en_linea = True


@transaction.atomic
def guardar_bodega(*, empresa, bodega=None, nombre, direccion="", es_principal=False, vende_en_linea=False):
    """Crea o edita una bodega. Quitar una marca se hace asignándola a otra bodega, nunca dejándola sin dueña."""
    from .models import Empresa

    Empresa.objects.select_for_update().filter(pk=empresa.pk).first()  # serializa cambios de marcas
    nueva = bodega is None
    if nueva:
        if Bodega.objects.filter(empresa=empresa, activa=True).exists() and not permite_varias_bodegas(empresa):
            raise OperacionBodega("Tu plan permite una sola bodega. Cambia al plan Pro para gestionar varias sedes.")
        bodega = Bodega(empresa=empresa)
    elif bodega.empresa_id != empresa.pk:
        raise OperacionBodega("La bodega no pertenece a este negocio.")
    if Bodega.objects.filter(empresa=empresa, nombre__iexact=nombre.strip()).exclude(pk=bodega.pk).exists():
        raise OperacionBodega(f"Ya existe una bodega llamada {nombre.strip()}.")
    if not nueva and bodega.es_principal and not es_principal:
        raise OperacionBodega("Para cambiar la Principal, márcala en la bodega que la reemplaza.")
    if not nueva and bodega.vende_en_linea and not vende_en_linea:
        raise OperacionBodega("Para cambiar la bodega de venta en línea, márcala en la que la reemplaza.")
    bodega.nombre = nombre.strip()
    bodega.direccion = (direccion or "").strip()
    bodega.activa = True
    if nueva:
        bodega.save()
        # La primera bodega de un negocio siempre es la Principal y la de venta en línea
        es_principal = es_principal or not Bodega.objects.filter(empresa=empresa, es_principal=True).exists()
        vende_en_linea = vende_en_linea or not Bodega.objects.filter(empresa=empresa, vende_en_linea=True).exists()
    _asignar_roles(bodega, es_principal=es_principal, vende_en_linea=vende_en_linea)
    bodega.save()
    return bodega


@transaction.atomic
def desactivar_bodega(*, empresa, bodega):
    from .models import TurnoCaja

    bodega = Bodega.objects.select_for_update().get(pk=bodega.pk, empresa=empresa)
    if bodega.es_principal or bodega.vende_en_linea:
        raise OperacionBodega("La bodega Principal y la de venta en línea no se pueden desactivar.")
    if Existencia.objects.filter(bodega=bodega, cantidad__gt=0).exists():
        raise OperacionBodega(f"{bodega.nombre} todavía tiene mercancía. Trasládala antes de desactivarla.")
    if TurnoCaja.objects.filter(bodega=bodega, cerrado_en__isnull=True).exists():
        raise OperacionBodega(f"Hay una caja abierta vendiendo desde {bodega.nombre}.")
    bodega.activa = False
    bodega.save(update_fields=["activa", "actualizado_en"])
    return bodega
