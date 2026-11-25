"""Carrito híbrido (sesión para invitados + base de datos para usuarios autenticados).

- Invitados: se guarda en la sesión como {id de producto: cantidad}.
- Usuarios autenticados: se persiste en `ItemCarrito` para sincronizarse entre dispositivos.
  Al iniciar sesión, cualquier producto agregado como invitado se fusiona automáticamente en BD.
El precio y la disponibilidad siempre se leen de la base de datos.
"""
from decimal import Decimal

from django.contrib.auth.signals import user_logged_in
from django.db.models import Sum
from django.dispatch import receiver

from .compras import calcular_costo_envio
from .http_utils import es_uuid_valido
from .impuestos import CENTAVOS, calcular_iva
from .marketplace import productos_publicos
from .models import ItemCarrito, Producto
from .tarifas import cargo_pasarela

CLAVE_SESION = "carrito"
CLAVE_FUSIONADO = "carrito_fusionado_usuario"
MAXIMO_POR_PRODUCTO = 99


def _usuario(request):
    """Devuelve el usuario autenticado del request, o None si es un visitante anónimo."""
    usuario = getattr(request, "user", None)
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        return usuario
    return None


def _mapa_bd(usuario):
    """Construye el diccionario {producto_id: cantidad} desde ItemCarrito para el usuario."""
    return {
        str(pid): cant
        for pid, cant in ItemCarrito.objects.filter(usuario=usuario).values_list("producto_id", "cantidad")
    }


def _reflejar_en_sesion(request, usuario, datos=None):
    """Mantiene request.session[CLAVE_SESION] como espejo del carrito en BD (compatibilidad)."""
    sesion = getattr(request, "session", None)
    if sesion is None:
        return
    sesion[CLAVE_SESION] = _mapa_bd(usuario) if datos is None else dict(datos)
    sesion[CLAVE_FUSIONADO] = str(usuario.pk)
    sesion.modified = True


def _absorber_sesion_en_bd(request, usuario):
    """Al autenticar una sesión que traía ítems de invitado, los fusiona una sola vez en BD."""
    sesion = getattr(request, "session", None)
    if sesion is None:
        return
    if sesion.get(CLAVE_FUSIONADO) == str(usuario.pk):
        return
    pendientes = sesion.get(CLAVE_SESION) or {}
    if pendientes:
        fusionar_en_bd(usuario, pendientes)
    _reflejar_en_sesion(request, usuario)


def fusionar_en_bd(usuario, items_por_id):
    """Fusiona un diccionario {producto_id: cantidad} en los ItemCarrito del usuario."""
    if not items_por_id:
        return
    ids_validos = [str(k).strip() for k in items_por_id.keys() if es_uuid_valido(k)]
    if not ids_validos:
        return
    existentes_prod = set(
        str(pk) for pk in Producto.objects.filter(pk__in=ids_validos).values_list("pk", flat=True)
    )
    actuales = {str(i.producto_id): i for i in ItemCarrito.objects.filter(usuario=usuario)}
    for clave, cantidad in items_por_id.items():
        clave_str = str(clave)
        if clave_str not in existentes_prod:
            continue
        try:
            qty = int(cantidad)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        item = actuales.get(clave_str)
        if item is not None:
            nueva = min(item.cantidad + qty, MAXIMO_POR_PRODUCTO)
            if nueva != item.cantidad:
                item.cantidad = nueva
                item.save(update_fields=["cantidad", "actualizado_en"])
        else:
            ItemCarrito.objects.create(
                usuario=usuario,
                producto_id=clave_str,
                cantidad=min(qty, MAXIMO_POR_PRODUCTO),
            )


@receiver(user_logged_in)
def fusionar_carrito_al_entrar(sender, request, user, **kwargs):
    """Al iniciar sesión o registrarse, fusiona el carrito de sesión con el persistido en BD."""
    if request is not None and user is not None:
        _absorber_sesion_en_bd(request, user)


def _datos(request):
    """Devuelve el mapa {producto_id: cantidad} del carrito activo (BD si autenticado, sesión si invitado)."""
    usuario = _usuario(request)
    if usuario is not None:
        _absorber_sesion_en_bd(request, usuario)
        datos = _mapa_bd(usuario)
        _reflejar_en_sesion(request, usuario, datos)
        return datos
    return request.session.setdefault(CLAVE_SESION, {})


def cantidad_total(request):
    """Total de unidades en el carrito activo."""
    usuario = _usuario(request)
    if usuario is not None:
        _absorber_sesion_en_bd(request, usuario)
        return ItemCarrito.objects.filter(usuario=usuario).aggregate(total=Sum("cantidad"))["total"] or 0
    return sum(request.session.get(CLAVE_SESION, {}).values())


def agregar(request, producto, cantidad):
    """Suma unidades sin pasar de lo disponible. Devuelve cuántas se agregaron de verdad."""
    usuario = _usuario(request)
    if usuario is not None:
        _absorber_sesion_en_bd(request, usuario)
        item = ItemCarrito.objects.filter(usuario=usuario, producto_id=producto.pk).first()
        actual = item.cantidad if item else 0
        nueva = min(actual + cantidad, producto.disponible, MAXIMO_POR_PRODUCTO)
        if nueva <= actual:
            return 0
        if item is not None:
            item.cantidad = nueva
            item.save(update_fields=["cantidad", "actualizado_en"])
        else:
            ItemCarrito.objects.create(usuario=usuario, producto_id=producto.pk, cantidad=nueva)
        _reflejar_en_sesion(request, usuario)
        return nueva - actual

    datos = _datos(request)
    clave = str(producto.pk)
    actual = datos.get(clave, 0)
    nueva = min(actual + cantidad, producto.disponible, MAXIMO_POR_PRODUCTO)
    if nueva <= actual:
        return 0
    datos[clave] = nueva
    request.session.modified = True
    return nueva - actual


def actualizar(request, producto, cantidad):
    """Fija la cantidad de una línea; devuelve False si hubo que ajustarla a lo disponible."""
    limite = min(producto.disponible, MAXIMO_POR_PRODUCTO)
    final = min(cantidad, limite)
    usuario = _usuario(request)
    if usuario is not None:
        _absorber_sesion_en_bd(request, usuario)
        if final <= 0:
            ItemCarrito.objects.filter(usuario=usuario, producto_id=producto.pk).delete()
        else:
            ItemCarrito.objects.update_or_create(
                usuario=usuario,
                producto_id=producto.pk,
                defaults={"cantidad": final},
            )
        _reflejar_en_sesion(request, usuario)
        return final == cantidad

    if final <= 0:
        quitar(request, producto.pk)
    else:
        _datos(request)[str(producto.pk)] = final
        request.session.modified = True
    return final == cantidad


def quitar(request, producto_id):
    """Quita un producto del carrito (BD si autenticado, sesión si invitado)."""
    usuario = _usuario(request)
    if usuario is not None:
        _absorber_sesion_en_bd(request, usuario)
        ItemCarrito.objects.filter(usuario=usuario, producto_id=producto_id).delete()
        _reflejar_en_sesion(request, usuario)
        return
    if _datos(request).pop(str(producto_id), None) is not None:
        request.session.modified = True


def quitar_lineas(request, lineas):
    """Quita del carrito todos los productos de las líneas dadas (tras crear el pedido)."""
    usuario = _usuario(request)
    if usuario is not None:
        _absorber_sesion_en_bd(request, usuario)
        ids = [linea["producto"].pk for linea in lineas]
        if ids:
            ItemCarrito.objects.filter(usuario=usuario, producto_id__in=ids).delete()
        _reflejar_en_sesion(request, usuario)
        return
    for linea in lineas:
        quitar(request, linea["producto"].pk)


def _linea(producto, cantidad):
    # Misma fórmula de services.crear_factura: lo que se muestra es exactamente lo que se cobra
    """Calcula subtotal, IVA, total y peso de una línea con la misma fórmula de la factura."""
    subtotal = producto.precio * cantidad
    iva = calcular_iva(subtotal, producto.iva_porcentaje)
    peso_gramos = (producto.peso_gramos or 0) * cantidad
    return {
        "producto": producto,
        "cantidad": cantidad,
        "subtotal": subtotal,
        "iva": iva,
        "total": subtotal + iva,
        "peso_gramos": peso_gramos,
    }


def grupos(request):
    """Devuelve (grupos por negocio, avisos). Corrige lo que cambió desde que se agregó."""
    usuario = _usuario(request)
    datos = _datos(request)
    claves_validas = [clave for clave in list(datos) if es_uuid_valido(clave)]
    productos = {str(p.pk): p for p in productos_publicos().filter(pk__in=claves_validas)} if claves_validas else {}
    avisos = []
    por_negocio = {}

    for clave, cantidad in list(datos.items()):
        if not es_uuid_valido(clave):
            if usuario is None:
                del datos[clave]
                request.session.modified = True
            continue
        producto = productos.get(clave)
        if producto is None or producto.disponible <= 0:
            if usuario is not None:
                ItemCarrito.objects.filter(usuario=usuario, producto_id=clave).delete()
                datos.pop(clave, None)
                _reflejar_en_sesion(request, usuario, datos)
            else:
                del datos[clave]
                request.session.modified = True
            nombre = producto.nombre if producto else "Un producto de tu carrito"
            avisos.append(f"{nombre} ya no está disponible y lo quitamos de tu carrito.")
            continue
        if cantidad > producto.disponible:
            cantidad = producto.disponible
            if usuario is not None:
                ItemCarrito.objects.filter(usuario=usuario, producto_id=clave).update(cantidad=cantidad)
                datos[clave] = cantidad
                _reflejar_en_sesion(request, usuario, datos)
            else:
                datos[clave] = cantidad
                request.session.modified = True
            avisos.append(f"Ajustamos la cantidad de {producto.nombre} a las unidades disponibles.")
        por_negocio.setdefault(producto.empresa_id, []).append(_linea(producto, cantidad))

    resultado = []
    for lineas in por_negocio.values():
        lineas.sort(key=lambda linea: linea["producto"].nombre.lower())
        negocio = lineas[0]["producto"].empresa
        subtotal = sum((linea["subtotal"] for linea in lineas), Decimal("0")).quantize(CENTAVOS)
        iva = sum((linea["iva"] for linea in lineas), Decimal("0"))
        peso_total_gramos = sum(linea["peso_gramos"] for linea in lineas)
        total_productos = (subtotal + iva).quantize(CENTAVOS)
        costo_envio = calcular_costo_envio(
            negocio=negocio,
            total_productos=total_productos,
            peso_total_gramos=peso_total_gramos,
        )
        antes_de_pasarela = (total_productos + costo_envio).quantize(CENTAVOS)
        cargo = cargo_pasarela(antes_de_pasarela, config=negocio.configuracion_pagos)
        resultado.append({
            "negocio": negocio,
            "lineas": lineas,
            "subtotal": subtotal,
            "iva": iva,
            "costo_envio": costo_envio,
            "cargo_pasarela": cargo,
            "peso_total_gramos": peso_total_gramos,
            "total": (antes_de_pasarela + cargo).quantize(CENTAVOS),
            "unidades": sum(linea["cantidad"] for linea in lineas),
        })
    resultado.sort(key=lambda grupo: grupo["negocio"].nombre.lower())
    return resultado, avisos


def grupo_de(request, negocio):
    """Devuelve (grupo del carrito de ese negocio o None, avisos de cambios de stock)."""
    grupos_actuales, avisos = grupos(request)
    grupo = next((g for g in grupos_actuales if g["negocio"].pk == negocio.pk), None)
    return grupo, avisos
