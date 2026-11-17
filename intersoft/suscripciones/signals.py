"""Señales de la aplicación suscripciones.

Por qué combinamos llamada explícita + señal post_save idempotente:
1. En el flujo de negocio (`core.negocios.registrar_negocio`) llamamos explícitamente a
   `crear_suscripcion_inicial(empresa)` para que la intención sea visible en el código.
2. Sin embargo, cuando se crea una empresa desde el Django Admin, shell o `Empresa.objects.create(...)`
   en tests, la señal `post_save` garantiza que toda empresa nueva nazca siempre con su
   suscripción `TRIAL` de 14 días en el plan Negocio. Como `crear_suscripcion_inicial` es
   idempotente, llamarla en ambos sitios jamás duplica registros.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import Empresa

from .services import crear_suscripcion_inicial


@receiver(post_save, sender=Empresa)
def asegurar_suscripcion_al_crear_empresa(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    crear_suscripcion_inicial(instance)
