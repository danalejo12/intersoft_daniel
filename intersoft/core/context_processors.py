from django.utils.translation import gettext
from django.db.models import F
from django.urls import reverse

from . import carrito as carrito_servicio
from .marketplace import categorias_publicas


def _notificaciones_panel(empresa, nav_permisos: dict) -> dict:
    """Resumen rápido de pendientes operativos para la campana de la barra superior."""
    from pqrs.models import PQRS
    from .models import Pedido, Producto

    items = []
    if nav_permisos.get("ver_pedidos"):
        por_despachar = Pedido.objects.filter(
            empresa=empresa,
            estado=Pedido.Estado.PAGADO,
            estado_envio__in=[Pedido.EstadoEnvio.PENDIENTE, Pedido.EstadoEnvio.PREPARANDO],
        ).count()
        if por_despachar:
            items.append({
                "titulo": gettext("{por_despachar} pedido(s) por despachar").format(por_despachar=por_despachar),
                "detalle": gettext("Pedidos pagados pendientes de envío."),
                "url": f"{reverse('pedidos_panel_lista')}?estado=pagado&envio=pendiente",
                "tipo": "info",
            })

    if nav_permisos.get("ver_productos"):
        stock_bajo = Producto.objects.filter(
            empresa=empresa,
            activo=True,
            stock_minimo__gt=0,
            stock__lte=F("stock_minimo"),
        ).count()
        if stock_bajo:
            items.append({
                "titulo": gettext("{stock_bajo} producto(s) en stock bajo").format(stock_bajo=stock_bajo),
                "detalle": gettext("Revisa existencias mínimas en catálogo."),
                "url": reverse("productos_lista"),
                "tipo": "alerta",
            })

    if nav_permisos.get("gestionar_pqrs"):
        pqrs_abiertas = PQRS.objects.filter(
            empresa=empresa,
            estado__in=[PQRS.Estado.RADICADA, PQRS.Estado.EN_TRAMITE, PQRS.Estado.ESCALADA],
        ).count()
        if pqrs_abiertas:
            items.append({
                "titulo": gettext("{pqrs_abiertas} PQRS por atender").format(pqrs_abiertas=pqrs_abiertas),
                "detalle": gettext("Solicitudes abiertas o escaladas."),
                "url": reverse("panel_pqrs_lista"),
                "tipo": "alerta",
            })

    return {"total": len(items), "items": items}


def carrito(request):
    """Cantidad para el ícono del carrito, negocios activos y permisos de navegación del panel."""
    from plataforma.models import AnuncioGlobal

    datos = {
        "carrito_cantidad": 0,
        "nav_permisos": {},
        "membresias_activas": getattr(request, "membresias_activas", []),
        # Se pasa la función, no la lista: la plantilla solo consulta si la usa
        "categorias_marketplace": categorias_publicas,
        "anuncios_globales": AnuncioGlobal.vigentes() if getattr(request, "empresa", None) else [],
        "notificaciones_panel": {"total": 0, "items": []},
    }
    if hasattr(request, "session"):
        datos["carrito_cantidad"] = carrito_servicio.cantidad_total(request)
    membresia = getattr(request, "membresia", None)
    if membresia is not None:
        datos["nav_permisos"] = {
            "ver_clientes": membresia.tiene_permiso("clientes.ver"),
            "ver_productos": membresia.tiene_permiso("inventario.ver"),
            "ver_facturas": membresia.tiene_permiso("ventas.ver"),
            "ver_pedidos": membresia.tiene_permiso("ventas.ver")
            or membresia.tiene_permiso("inventario.movimientos"),
            "ver_pos": membresia.tiene_permiso("ventas.crear"),
            "ver_erp": any(
                membresia.tiene_permiso(p)
                for p in (
                    "compras.ver",
                    "cartera.ver",
                    "tesoreria.ver",
                    "contabilidad.ver",
                    "nomina.ver",
                    "produccion.ver",
                    "agenda.ver",
                    "reportes.ver",
                )
            ),
            "configurar_pagos": membresia.tiene_permiso("pagos.configurar"),
            "editar_negocio": membresia.tiene_permiso("negocio.editar"),
            "gestionar_pqrs": membresia.tiene_permiso("pqrs.gestionar"),
            "ver_equipo": any(
                membresia.tiene_permiso(p)
                for p in ("equipo.ver", "equipo.gestionar", "negocio.editar")
            ),
        }
        if getattr(request, "empresa", None):
            datos["notificaciones_panel"] = _notificaciones_panel(request.empresa, datos["nav_permisos"])
    return datos
