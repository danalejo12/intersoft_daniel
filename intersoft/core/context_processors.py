from . import carrito as carrito_servicio


def carrito(request):
    """Cantidad para el ícono del carrito en la barra superior."""
    if not hasattr(request, "session"):
        return {"carrito_cantidad": 0}
    return {"carrito_cantidad": carrito_servicio.cantidad_total(request)}
