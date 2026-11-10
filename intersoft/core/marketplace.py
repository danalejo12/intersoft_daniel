"""Catálogo público: la ÚNICA consulta del proyecto que cruza empresas.

Ninguna vista del panel debe usar estas funciones: el panel siempre filtra por
request.empresa (TenantMixin). Aquí solo sale lo que cada negocio decidió publicar.
"""
from .models import Empresa, Producto


def empresas_publicas():
    return Empresa.objects.filter(activa=True)


def productos_publicos():
    return (
        Producto.objects
        .filter(activo=True, publicado=True, empresa__activa=True)
        # Sin datos legales del vendedor (Ley 1480, art. 53) sus productos no se publican
        .exclude(empresa__direccion="")
        .exclude(empresa__telefono="")
        .select_related("empresa", "categoria")
        .order_by("nombre", "id")  # el id da un orden estable al paginar
    )


def negocios_con_productos():
    return empresas_publicas().filter(pk__in=productos_publicos().values("empresa"))
