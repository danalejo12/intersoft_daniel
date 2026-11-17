"""Catálogo público: la ÚNICA consulta del proyecto que cruza empresas.

Ninguna vista del panel debe usar estas funciones: el panel siempre filtra por
request.empresa (TenantMixin). Aquí solo sale lo que cada negocio decidió publicar.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import (
    Avg, Case, Count, DecimalField, ExpressionWrapper, F, IntegerField, OuterRef, Subquery, Sum, Value, When,
)
from django.db.models.functions import Ceil, Coalesce, Round
from django.utils import timezone

from .models import Comentario, DetallePedido, Empresa, Pedido, Producto


def empresas_publicas():
    return Empresa.objects.filter(activa=True).select_related("pasarela")


def productos_publicos():
    return (
        Producto.objects
        .filter(activo=True, publicado=True, empresa__activa=True)
        # Sin datos legales del vendedor (Ley 1480, art. 53) sus productos no se publican
        .exclude(empresa__direccion="")
        .exclude(empresa__telefono="")
        .select_related("empresa__pasarela", "categoria")
        .order_by("nombre", "id")  # el id da un orden estable al paginar
    )


def negocios_con_productos():
    return empresas_publicas().filter(pk__in=productos_publicos().values("empresa"))


# ---------- Catálogo con filtros, orden y valoraciones ----------
# Etiqueta visible de cada orden; la clave viaja en la URL (?orden=...)
ORDENES = {
    "relevancia": "Más relevantes",
    "mas_vendidos": "Más vendidos",
    "precio_menor": "Precio: menor a mayor",
    "precio_mayor": "Precio: mayor a menor",
    "mejor_valorados": "Mejor valorados",
    "nuevos": "Más nuevos",
}
# Regla pública y verificable: el sello "Destacado" no se regala, se gana con opiniones reales
DESTACADO_PROMEDIO_MINIMO = Decimal("4.5")
DESTACADO_OPINIONES_MINIMAS = 3


# Ventana de "Más vendidos": solo cuentan pedidos pagados recientes, para que el ranking se renueve
DIAS_RANKING_VENTAS = 90
# En "Más relevantes" cada opinión pesa como estas unidades vendidas
PESO_OPINION_EN_RELEVANCIA = 2


def unidades_vendidas():
    """Subconsulta: unidades del producto en pedidos pagados de los últimos DIAS_RANKING_VENTAS días.
    Va en subconsulta (no en JOIN) para no multiplicar el conteo de opiniones."""
    desde = timezone.now() - timedelta(days=DIAS_RANKING_VENTAS)
    vendidas = (
        DetallePedido.objects
        .filter(producto=OuterRef("pk"), pedido__estado=Pedido.Estado.PAGADO, pedido__creado_en__gte=desde)
        .order_by()
        .values("producto")
        .annotate(total=Sum("cantidad"))
        .values("total")
    )
    return Coalesce(Subquery(vendidas, output_field=IntegerField()), Value(0))


def con_valoraciones(productos):
    return productos.annotate(
        promedio=Avg("comentarios__calificacion"),
        num_opiniones=Count("comentarios"),
        vendidos=unidades_vendidas(),
    )


def ordenar(productos, orden):
    """Compara el precio final de una unidad, incluidas las tarifas de cada negocio."""
    precio_con_iva = ExpressionWrapper(
        F("precio") + Round(F("precio") * F("iva_porcentaje") / 100, precision=2),
        output_field=DecimalField(max_digits=16, decimal_places=4),
    )
    if orden in ("precio_menor", "precio_mayor"):
        factor = 1 + Decimal(settings.WOMPI_TARIFA_IVA) / 100
        cobrado = (precio_con_iva + F("empresa__pasarela__tarifa_fija") * factor) / (
            1 - F("empresa__pasarela__tarifa_porcentaje") / 100 * factor)
        final = Case(
            When(precio__gt=0, empresa__pasarela__activa=True, empresa__pasarela__verificada_en__isnull=False,
                 empresa__pasarela__cobrar_tarifa_al_comprador=True,
                 then=precio_con_iva + Ceil(cobrado - precio_con_iva)),
            default=precio_con_iva, output_field=DecimalField(max_digits=16, decimal_places=4),
        )
        return productos.annotate(_p=final).order_by("_p" if orden == "precio_menor" else "-_p", "id")
    if orden == "mejor_valorados":
        return productos.order_by(F("promedio").desc(nulls_last=True), "-num_opiniones", "nombre", "id")
    if orden == "nuevos":
        return productos.order_by("-creado_en", "id")
    if orden == "mas_vendidos":
        return productos.order_by("-vendidos", F("promedio").desc(nulls_last=True), "nombre", "id")
    # Relevancia: ventas recientes + opiniones (cada opinión vale PESO_OPINION_EN_RELEVANCIA unidades);
    # a igual puntaje gana la mejor calificación; sin ventas ni opiniones, por nombre
    puntaje = F("vendidos") + F("num_opiniones") * PESO_OPINION_EN_RELEVANCIA
    return productos.annotate(_relevancia=puntaje).order_by(
        "-_relevancia", F("promedio").desc(nulls_last=True), "nombre", "id")


def categorias_publicas():
    """Nombres de categoría con al menos un producto publicado (las categorías son de cada negocio)."""
    return list(
        productos_publicos()
        .filter(categoria__isnull=False, categoria__activa=True)
        .order_by()
        .values_list("categoria__nombre", flat=True)
        .distinct()
        .order_by("categoria__nombre")
    )


def negocios_con_valoracion():
    """Negocios del catálogo con el promedio de las opiniones de sus productos."""
    datos = {
        fila["empresa"]: fila
        for fila in Comentario.objects.filter(producto__in=productos_publicos())
        .values("empresa")
        .annotate(promedio=Avg("calificacion"), total=Count("id"))
    }
    negocios = list(negocios_con_productos().order_by("nombre"))
    for negocio in negocios:
        fila = datos.get(negocio.pk, {})
        negocio.promedio = fila.get("promedio")
        negocio.num_opiniones = fila.get("total", 0)
        negocio.destacado = bool(
            negocio.promedio
            and Decimal(str(negocio.promedio)) >= DESTACADO_PROMEDIO_MINIMO
            and negocio.num_opiniones >= DESTACADO_OPINIONES_MINIMAS
        )
    return sorted(negocios, key=lambda n: (not n.destacado, -(n.promedio or 0), n.nombre.lower()))
