"""Carrito en la sesión: funciona sin cuenta y sobrevive al iniciar sesión.

Solo guarda {id de producto: cantidad}. El precio y la disponibilidad siempre se leen
de la base de datos, para que nadie pueda alterarlos desde el navegador.
"""
from decimal import Decimal

from .marketplace import productos_publicos
from .impuestos import CENTAVOS, calcular_iva

CLAVE_SESION = "carrito"
MAXIMO_POR_PRODUCTO = 99


def _datos(request):
    return request.session.setdefault(CLAVE_SESION, {})


def cantidad_total(request):
    return sum(request.session.get(CLAVE_SESION, {}).values())


def agregar(request, producto, cantidad):
    """Suma unidades sin pasar de lo disponible. Devuelve cuántas se agregaron de verdad."""
    datos = _datos(request)
    clave = str(producto.pk)
    actual = datos.get(clave, 0)
    nueva = min(actual + cantidad, producto.stock, MAXIMO_POR_PRODUCTO)
    if nueva <= actual:
        return 0
    datos[clave] = nueva
    request.session.modified = True
    return nueva - actual


def actualizar(request, producto, cantidad):
    """Fija la cantidad de una línea; devuelve False si hubo que ajustarla a lo disponible."""
    limite = min(producto.stock, MAXIMO_POR_PRODUCTO)
    final = min(cantidad, limite)
    if final <= 0:
        quitar(request, producto.pk)
    else:
        _datos(request)[str(producto.pk)] = final
        request.session.modified = True
    return final == cantidad


def quitar(request, producto_id):
    if _datos(request).pop(str(producto_id), None) is not None:
        request.session.modified = True


def quitar_lineas(request, lineas):
    for linea in lineas:
        quitar(request, linea["producto"].pk)


def _linea(producto, cantidad):
    # Misma fórmula de services.crear_factura: lo que se muestra es exactamente lo que se cobra
    subtotal = producto.precio * cantidad
    iva = calcular_iva(subtotal, producto.iva_porcentaje)
    return {"producto": producto, "cantidad": cantidad, "subtotal": subtotal, "iva": iva, "total": subtotal + iva}


def grupos(request):
    """Devuelve (grupos por negocio, avisos). Corrige lo que cambió desde que se agregó."""
    datos = _datos(request)
    productos = {str(p.pk): p for p in productos_publicos().filter(pk__in=list(datos))}
    avisos = []
    por_negocio = {}

    for clave, cantidad in list(datos.items()):
        producto = productos.get(clave)
        if producto is None or producto.stock <= 0:
            del datos[clave]
            request.session.modified = True
            nombre = producto.nombre if producto else "Un producto de tu carrito"
            avisos.append(f"{nombre} ya no está disponible y lo quitamos de tu carrito.")
            continue
        if cantidad > producto.stock:
            cantidad = datos[clave] = producto.stock
            request.session.modified = True
            avisos.append(f"Ajustamos la cantidad de {producto.nombre} a las unidades disponibles.")
        por_negocio.setdefault(producto.empresa_id, []).append(_linea(producto, cantidad))

    resultado = []
    for lineas in por_negocio.values():
        lineas.sort(key=lambda linea: linea["producto"].nombre.lower())
        subtotal = sum((linea["subtotal"] for linea in lineas), Decimal("0"))
        iva = sum((linea["iva"] for linea in lineas), Decimal("0"))
        resultado.append({
            "negocio": lineas[0]["producto"].empresa,
            "lineas": lineas,
            "subtotal": subtotal.quantize(CENTAVOS),
            "iva": iva,
            "total": (subtotal + iva).quantize(CENTAVOS),
            "unidades": sum(linea["cantidad"] for linea in lineas),
        })
    resultado.sort(key=lambda grupo: grupo["negocio"].nombre.lower())
    return resultado, avisos


def grupo_de(request, negocio):
    grupos_actuales, avisos = grupos(request)
    grupo = next((g for g in grupos_actuales if g["negocio"].pk == negocio.pk), None)
    return grupo, avisos
