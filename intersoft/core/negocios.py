"""Alta de un negocio nuevo a partir de una cuenta que ya existe."""
from django.db import transaction
from django.utils.text import slugify

from .models import Empresa, Membresia, Rol


def _slug_disponible(nombre):
    base = slugify(nombre)[:150] or "negocio"  # un nombre sin letras daría un slug vacío
    slug = base
    sufijo = 2
    while Empresa.objects.filter(slug=slug).exists():
        slug = f"{base}-{sufijo}"
        sufijo += 1
    return slug


@transaction.atomic
def registrar_negocio(*, usuario, datos):
    """Crea la empresa, su rol administrador y la membresía: las tres cosas o ninguna."""
    empresa = Empresa.objects.create(slug=_slug_disponible(datos["nombre"]), **datos)
    rol = Rol.objects.create(empresa=empresa, nombre="Administrador", es_admin=True)
    Membresia.objects.create(usuario=usuario, empresa=empresa, rol=rol)
    return empresa
