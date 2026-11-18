from . import carrito as carrito_servicio
from .marketplace import categorias_publicas


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
    return datos
