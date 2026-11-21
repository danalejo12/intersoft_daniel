"""Guía de primeros pasos para negocios nuevos: qué falta para vender en el marketplace."""
from django.utils.translation import gettext
from dataclasses import dataclass

from django.urls import reverse

from .models import Factura, Pedido, Producto


@dataclass(frozen=True)
class Paso:
    titulo: str
    ayuda: str
    hecho: bool
    url: str = ""
    accion: str = ""


def _cobros_activos(empresa) -> bool:
    return empresa.compra_en_linea


def pasos_del_negocio(empresa, usuario) -> list[Paso]:
    productos = Producto.objects.de_empresa(empresa).filter(activo=True)
    perfil_completo = all([empresa.nit, empresa.direccion, empresa.telefono, empresa.email])
    vendio = (
        Factura.objects.de_empresa(empresa).exclude(estado=Factura.Estado.ANULADA).exists()
        or Pedido.objects.de_empresa(empresa).filter(estado=Pedido.Estado.PAGADO).exists()
    )
    cobros = _cobros_activos(empresa)
    if cobros:
        ayuda_cobros = gettext("Tus clientes ya pueden pagar con tarjeta, PSE o Nequi por Wompi.")
    else:
        ayuda_cobros = gettext("Conecta, verifica y activa la cuenta de Wompi de tu negocio en Pagos.")
    return [
        Paso(
            gettext("Completa el perfil del negocio"),
            gettext("NIT, dirección, teléfono y correo. Sin ellos la ley no permite publicar tus productos."),
            perfil_completo, reverse("negocio_datos"), gettext("Completar perfil"),
        ),
        Paso(
            gettext("Crea tu primer producto"),
            gettext("Nombre, precio e inventario. Puedes empezar con uno solo."),
            productos.exists(), reverse("productos_crear"), gettext("Crear producto"),
        ),
        Paso(
            gettext("Publícalo con una buena foto"),
            gettext("Marca «Publicado» y sube una foto: los productos con foto se venden mucho más."),
            productos.filter(publicado=True).exclude(imagen="").exists(), reverse("productos_lista"), gettext("Ver productos"),
        ),
        Paso(gettext("Activa los cobros con Wompi"), ayuda_cobros, cobros, reverse("negocio_pagos"), gettext("Configurar pagos")),
        Paso(
            gettext("Haz tu primera venta"),
            gettext("Desde el punto de venta o cuando entre tu primer pedido pagado del marketplace."),
            vendio, reverse("pos"), gettext("Abrir punto de venta"),
        ),
    ]
